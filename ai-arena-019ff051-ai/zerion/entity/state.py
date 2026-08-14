"""
Entity lifecycle & state persistence (DEPRECATED view — canonical cognitive
state is ``zerion/cognitive_os/state.py`` ``CognitiveState`` + ``StateStore``).

Kept as a legacy derived-telemetry view: the engine writes honest snapshots
here, identity always derives from the canonical ``IdentityCore``, and every
state change must pass through the enforced transition policy. Direct mutation
of ``current_state`` is impossible; invalid transitions raise.

States deliberately distinguish failure semantics: FAILED, CANCELLED,
INTERRUPTED, PAUSED, DEGRADED and RECOVERING are NOT interchangeable, and the
transition policy treats each accordingly.
"""

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.entity.identity import CognitiveEntityIdentity
from zerion.identity.persistence import IdentityCore


class EntityLifecycleState(str, Enum):
    STANDBY = "STANDBY"
    BOOTING = "BOOTING"
    PERCEIVING = "PERCEIVING"
    DELIBERATING = "DELIBERATING"
    ACTING = "ACTING"
    EVOLVING = "EVOLVING"
    CONSOLIDATING = "CONSOLIDATING"
    RECOVERING = "RECOVERING"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InvalidStateTransitionError(ValueError):
    """Raised when a transition is not allowed by the entity state policy."""


# Allowed transitions. A transition not listed here is forbidden — no
# subsystem may jump the state machine. Same-state transitions are forbidden.
_ACTIVE = {
    EntityLifecycleState.PERCEIVING,
    EntityLifecycleState.DELIBERATING,
    EntityLifecycleState.ACTING,
    EntityLifecycleState.EVOLVING,
    EntityLifecycleState.CONSOLIDATING,
}
_ABNORMAL = {
    EntityLifecycleState.PAUSED,
    EntityLifecycleState.DEGRADED,
    EntityLifecycleState.INTERRUPTED,
    EntityLifecycleState.FAILED,
    EntityLifecycleState.CANCELLED,
}

_ALLOWED_TRANSITIONS: Dict[EntityLifecycleState, set] = {
    EntityLifecycleState.STANDBY: {EntityLifecycleState.BOOTING},
    EntityLifecycleState.BOOTING: _ACTIVE | _ABNORMAL,
    EntityLifecycleState.PERCEIVING: _ACTIVE | _ABNORMAL | {EntityLifecycleState.RECOVERING},
    EntityLifecycleState.DELIBERATING: _ACTIVE | _ABNORMAL | {EntityLifecycleState.RECOVERING},
    EntityLifecycleState.ACTING: _ACTIVE | _ABNORMAL | {EntityLifecycleState.RECOVERING},
    EntityLifecycleState.EVOLVING: _ACTIVE | _ABNORMAL | {EntityLifecycleState.RECOVERING},
    EntityLifecycleState.CONSOLIDATING: _ACTIVE | _ABNORMAL | {
        EntityLifecycleState.RECOVERING, EntityLifecycleState.STANDBY},
    EntityLifecycleState.RECOVERING: _ACTIVE | {EntityLifecycleState.STANDBY, EntityLifecycleState.BOOTING},
    EntityLifecycleState.PAUSED: _ACTIVE | _ABNORMAL | {EntityLifecycleState.RECOVERING},
    EntityLifecycleState.DEGRADED: {EntityLifecycleState.RECOVERING, EntityLifecycleState.STANDBY,
                                    EntityLifecycleState.PAUSED, EntityLifecycleState.INTERRUPTED,
                                    EntityLifecycleState.FAILED, EntityLifecycleState.CANCELLED},
    EntityLifecycleState.INTERRUPTED: {EntityLifecycleState.RECOVERING, EntityLifecycleState.STANDBY,
                                       EntityLifecycleState.BOOTING} | _ACTIVE | {
        EntityLifecycleState.PAUSED, EntityLifecycleState.DEGRADED,
        EntityLifecycleState.FAILED, EntityLifecycleState.CANCELLED},
    EntityLifecycleState.FAILED: {EntityLifecycleState.RECOVERING, EntityLifecycleState.STANDBY,
                                  EntityLifecycleState.CANCELLED},
    EntityLifecycleState.CANCELLED: {EntityLifecycleState.STANDBY, EntityLifecycleState.BOOTING},
}


def validate_transition(current: EntityLifecycleState,
                        new_state: EntityLifecycleState) -> None:
    if not isinstance(new_state, EntityLifecycleState):
        raise InvalidStateTransitionError(
            f"state must be an EntityLifecycleState, got {new_state!r}")
    if new_state == current:
        raise InvalidStateTransitionError(
            f"no-op transition: already in {current.value}")
    allowed = _ALLOWED_TRANSITIONS.get(current)
    if allowed is None or new_state not in allowed:
        raise InvalidStateTransitionError(
            f"invalid transition {current.value} -> {new_state.value} "
            f"(not allowed by entity state policy)")


@dataclass
class EntityStateSnapshot:
    snapshot_id: str
    lifecycle_state: EntityLifecycleState
    identity_digest: str
    active_objectives_count: Optional[int]
    active_strategies_count: Optional[int]
    active_capabilities_count: Optional[int]
    memory_episodes_count: Optional[int]
    brier_score: Optional[float]
    learning_acceleration: Optional[float]
    maturity_level: Optional[str]
    timestamp: float = field(default_factory=time.time)

    @staticmethod
    def _metric(value: Any) -> Dict[str, Any]:
        if value is None:
            return {"value": None, "measurement_status": "NOT_MEASURED"}
        if isinstance(value, float):
            return {"value": round(value, 4), "measurement_status": "MEASURED"}
        return {"value": value, "measurement_status": "MEASURED"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "lifecycle_state": self.lifecycle_state.value,
            "identity_digest": self.identity_digest,
            "active_objectives_count": self._metric(self.active_objectives_count),
            "active_strategies_count": self._metric(self.active_strategies_count),
            "active_capabilities_count": self._metric(self.active_capabilities_count),
            "memory_episodes_count": self._metric(self.memory_episodes_count),
            "brier_score": self._metric(self.brier_score),
            "learning_acceleration": self._metric(self.learning_acceleration),
            "maturity_level": self._metric(self.maturity_level),
            "timestamp": self.timestamp,
        }


class CognitiveEntityStateStore:
    """Legacy entity-state telemetry store with an ENFORCED state machine.

    ``identity`` defaults to a canonical ``CognitiveEntityIdentity``; when an
    ``IdentityCore`` is passed (the engine does this), all identity values are
    read from that canonical core — no second identity is ever created.
    """

    def __init__(self, db_path: Optional[str] = "data/entity_state.db",
                 identity: Optional[Any] = None):
        self.db_path = db_path
        if isinstance(identity, IdentityCore):
            self.identity = CognitiveEntityIdentity(identity_core=identity)
        else:
            self.identity = identity or CognitiveEntityIdentity()
        self._current_state = EntityLifecycleState.STANDBY
        self._init_db()
        self._load_runtime_state()

    @property
    def current_state(self) -> EntityLifecycleState:
        """Read-only: state can only change through ``transition_state``."""
        return self._current_state

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    lifecycle_state TEXT,
                    identity_digest TEXT,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_state (
                    state TEXT PRIMARY KEY,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def _load_runtime_state(self):
        """Restore the last persisted lifecycle state (e.g. DEGRADED survives
        a restart instead of silently resetting to a healthy state)."""
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT state FROM runtime_state ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                self._current_state = EntityLifecycleState(row[0])
        except Exception:  # noqa: BLE001 — corrupt legacy store must not crash the runtime
            pass

    def _persist_runtime_state(self):
        if not self.db_path:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO runtime_state VALUES (?, ?)",
                (self._current_state.value, time.time()))
            conn.commit()
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    def transition_state(self, new_state: EntityLifecycleState) -> EntityLifecycleState:
        """The ONLY way to change lifecycle state. Invalid transitions raise
        ``InvalidStateTransitionError`` and leave the current state untouched."""
        validate_transition(self._current_state, new_state)
        self._current_state = new_state
        self._persist_runtime_state()
        return self._current_state

    def capture_snapshot(
        self,
        objectives_count: Optional[int] = None,
        strategies_count: Optional[int] = None,
        capabilities_count: Optional[int] = None,
        episodes_count: Optional[int] = None,
        brier_score: Optional[float] = None,
        learning_acceleration: Optional[float] = None,
        maturity_level: Optional[str] = None
    ) -> EntityStateSnapshot:
        """Snapshot with honest provenance: every metric is either a real
        measured value or NOT_MEASURED. Fabricated defaults (attractive numbers
        like 0.02 / 2.57 / L7) are never substituted for missing measurements."""
        snap = EntityStateSnapshot(
            snapshot_id=f"snap_{int(time.time()*1000)%1000000}",
            lifecycle_state=self._current_state,
            identity_digest=self.identity.get_identity_digest(),
            active_objectives_count=objectives_count,
            active_strategies_count=strategies_count,
            active_capabilities_count=capabilities_count,
            memory_episodes_count=episodes_count,
            brier_score=brier_score,
            learning_acceleration=learning_acceleration,
            maturity_level=maturity_level
        )
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO entity_snapshots VALUES (?, ?, ?, ?, ?)",
                (snap.snapshot_id, snap.lifecycle_state.value, snap.identity_digest,
                 json.dumps(snap.to_dict()), snap.timestamp)
            )
            conn.commit()
            conn.close()
        return snap
