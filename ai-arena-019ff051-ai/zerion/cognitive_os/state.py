"""
Cognitive State — the single authoritative representation of the runtime's current
cognitive state (Slice 1 foundation).

The state is:
- typed (dataclasses, enums) — no LLM-generated prose as a substitute for structure
- serializable / deserializable with strict schema-version validation
- persisted to SQLite WAL with a SHA-256 checksum so partial/corrupted writes are
  detected and never silently become empty state

It represents perception, attention, active goals, current focus, pending cognitive
events, resource/budget state, runtime status, and schema version.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import time
from typing import Any, Dict, Optional
import uuid


class RuntimeStatus(str, Enum):
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    RECOVERING = "RECOVERING"


class StateVersionError(ValueError):
    """Raised when a serialized state's schema version does not match the expected version."""


class StateIntegrityError(RuntimeError):
    """Raised when persisted state is corrupt (checksum mismatch, malformed payload)."""


@dataclass
class PerceptionSnapshot:
    """Typed perception state (resource telemetry)."""

    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    compute_tier: str = "UNKNOWN"
    source: str = "runtime"
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_percent": round(self.cpu_percent, 4),
            "memory_mb": round(self.memory_mb, 4),
            "compute_tier": self.compute_tier,
            "source": self.source,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PerceptionSnapshot":
        return cls(
            cpu_percent=float(data.get("cpu_percent", 0.0)),
            memory_mb=float(data.get("memory_mb", 0.0)),
            compute_tier=data.get("compute_tier", "UNKNOWN"),
            source=data.get("source", "runtime"),
            observed_at=float(data.get("observed_at", time.time())),
        )


@dataclass
class ResourceBudgetView:
    """Snapshot of the resource/budget state the runtime is operating under."""

    compute_units: float = 1.0
    api_calls: float = 10.0
    latency_ms: float = 1000.0
    concurrent_workload: int = 0
    max_concurrent: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compute_units": self.compute_units,
            "api_calls": self.api_calls,
            "latency_ms": self.latency_ms,
            "concurrent_workload": self.concurrent_workload,
            "max_concurrent": self.max_concurrent,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceBudgetView":
        return cls(
            compute_units=float(data.get("compute_units", 1.0)),
            api_calls=float(data.get("api_calls", 10.0)),
            latency_ms=float(data.get("latency_ms", 1000.0)),
            concurrent_workload=int(data.get("concurrent_workload", 0)),
            max_concurrent=int(data.get("max_concurrent", 3)),
        )


@dataclass
class AttentionStateView:
    """Attention economy counters and the current focus."""

    current_focus_id: Optional[str] = None
    current_focus: str = ""
    selected_count: int = 0
    deferred_count: int = 0
    discarded_count: int = 0
    pending_candidates: int = 0
    deferred_candidates: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_focus_id": self.current_focus_id,
            "current_focus": self.current_focus,
            "selected_count": self.selected_count,
            "deferred_count": self.deferred_count,
            "discarded_count": self.discarded_count,
            "pending_candidates": self.pending_candidates,
            "deferred_candidates": self.deferred_candidates,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttentionStateView":
        return cls(
            current_focus_id=data.get("current_focus_id"),
            current_focus=data.get("current_focus", ""),
            selected_count=int(data.get("selected_count", 0)),
            deferred_count=int(data.get("deferred_count", 0)),
            discarded_count=int(data.get("discarded_count", 0)),
            pending_candidates=int(data.get("pending_candidates", 0)),
            deferred_candidates=int(data.get("deferred_candidates", 0)),
        )


@dataclass
class GoalStateView:
    """Goal field summary counts (the Goal Field store remains the source of truth)."""

    total: int = 0
    proposed: int = 0
    active: int = 0
    blocked: int = 0
    paused: int = 0
    completed: int = 0
    abandoned: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "proposed": self.proposed,
            "active": self.active,
            "blocked": self.blocked,
            "paused": self.paused,
            "completed": self.completed,
            "abandoned": self.abandoned,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoalStateView":
        return cls(
            total=int(data.get("total", 0)),
            proposed=int(data.get("proposed", 0)),
            active=int(data.get("active", 0)),
            blocked=int(data.get("blocked", 0)),
            paused=int(data.get("paused", 0)),
            completed=int(data.get("completed", 0)),
            abandoned=int(data.get("abandoned", 0)),
        )


@dataclass
class LastEventView:
    """The most recent cognitive event observed by the runtime."""

    event_id: str = ""
    event_type: str = ""
    sequence: Optional[int] = None
    timestamp: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LastEventView":
        return cls(
            event_id=data.get("event_id", ""),
            event_type=data.get("event_type", ""),
            sequence=data.get("sequence"),
            timestamp=data.get("timestamp", ""),
            source=data.get("source", ""),
        )


@dataclass
class CognitiveState:
    """The authoritative, versioned cognitive state document."""

    STATE_SCHEMA_VERSION: int = 1

    schema_version: int = 1
    state_id: str = field(default_factory=lambda: f"cs_{uuid.uuid4().hex[:12]}")
    runtime_status: RuntimeStatus = RuntimeStatus.INITIALIZING
    perception: PerceptionSnapshot = field(default_factory=PerceptionSnapshot)
    attention: AttentionStateView = field(default_factory=AttentionStateView)
    goals: GoalStateView = field(default_factory=GoalStateView)
    pending_events: int = 0
    resources: ResourceBudgetView = field(default_factory=ResourceBudgetView)
    current_focus: str = ""
    last_event: Optional[LastEventView] = None
    recovery_error: Optional[str] = None
    stale_events_discarded: int = 0
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> "CognitiveState":
        self.updated_at = time.time()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "runtime_status": self.runtime_status.value if isinstance(self.runtime_status, RuntimeStatus) else str(self.runtime_status),
            "perception": self.perception.to_dict(),
            "attention": self.attention.to_dict(),
            "goals": self.goals.to_dict(),
            "pending_events": self.pending_events,
            "resources": self.resources.to_dict(),
            "current_focus": self.current_focus,
            "last_event": self.last_event.to_dict() if self.last_event else None,
            "recovery_error": self.recovery_error,
            "stale_events_discarded": self.stale_events_discarded,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveState":
        version = data.get("schema_version")
        if version != cls.STATE_SCHEMA_VERSION:
            raise StateVersionError(
                f"State schema version mismatch: expected {cls.STATE_SCHEMA_VERSION}, got {version!r}"
            )
        status_str = data.get("runtime_status", RuntimeStatus.INITIALIZING.value)
        try:
            status = RuntimeStatus(status_str)
        except ValueError:
            status = RuntimeStatus.ERROR
        return cls(
            schema_version=version,
            state_id=data.get("state_id", f"cs_{uuid.uuid4().hex[:12]}"),
            runtime_status=status,
            perception=PerceptionSnapshot.from_dict(data.get("perception", {})),
            attention=AttentionStateView.from_dict(data.get("attention", {})),
            goals=GoalStateView.from_dict(data.get("goals", {})),
            pending_events=int(data.get("pending_events", 0)),
            resources=ResourceBudgetView.from_dict(data.get("resources", {})),
            current_focus=data.get("current_focus", ""),
            last_event=LastEventView.from_dict(data["last_event"]) if data.get("last_event") else None,
            recovery_error=data.get("recovery_error"),
            stale_events_discarded=int(data.get("stale_events_discarded", 0)),
            updated_at=float(data.get("updated_at", time.time())),
        )


class StateStore:
    """SQLite WAL-backed store for the CognitiveState document.

    Each write is a single atomic transaction; each read verifies the SHA-256 checksum
    of the payload. Corruption is raised (StateIntegrityError), never silently ignored.
    """

    def __init__(self, db_path: str = "data/cognitive_state.db"):
        self.db_path = str(db_path)
        p = Path(self.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cognitive_state (
                schema_version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (schema_version)
            )
        """)
        self._conn.commit()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def exists(self) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM cognitive_state WHERE schema_version = ?",
            (CognitiveState.STATE_SCHEMA_VERSION,),
        ).fetchone()
        return row is not None

    def put(self, state: CognitiveState) -> None:
        state.touch()
        payload = json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":"))
        checksum = self._checksum(payload)
        self._conn.execute(
            "INSERT OR REPLACE INTO cognitive_state (schema_version, payload, checksum, updated_at) VALUES (?, ?, ?, ?)",
            (state.schema_version, payload, checksum, state.updated_at),
        )
        self._conn.commit()

    def load(self) -> Optional[CognitiveState]:
        row = self._conn.execute(
            "SELECT payload, checksum FROM cognitive_state WHERE schema_version = ?",
            (CognitiveState.STATE_SCHEMA_VERSION,),
        ).fetchone()
        if row is None:
            return None
        payload, stored_checksum = row
        if self._checksum(payload) != stored_checksum:
            raise StateIntegrityError(
                f"Persisted cognitive state checksum mismatch (corrupt or partial write) in {self.db_path}"
            )
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise StateIntegrityError(f"Persisted cognitive state is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise StateIntegrityError("Persisted cognitive state payload is not a JSON object")
        return CognitiveState.from_dict(data)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
