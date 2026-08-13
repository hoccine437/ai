"""
Slice 8 — PulseStore (CognitivePulse persistence).

Persists everything the CognitivePulse needs to survive a restart without
duplicating already-completed work:

  - work queue (CognitiveWorkItem records with atomic status transitions)
  - cooldowns (last_run / next_allowed_run / trigger_reason)
  - event deduplication state (fingerprint -> occurrence_count, first/last seen)
  - budget counters (per-period spend for CPU/API/network/model-inference/etc.)
  - cycle history (what the pulse actually did, when, in which state)
  - failure history (bounded retries, TRANSIENT/PERMANENT/UNKNOWN classes)
  - per-task periodic last-run timestamps (each scheduled evaluation keeps its
    own cadence, recovered after restart)

Same SQLite-WAL + SHA-256 checksum pattern as Slices 1-7. Every mutation goes
through a lock so concurrent enqueue/execute paths cannot corrupt the queue
(no duplicate execution, no double status transitions).
"""

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class PulseIntegrityError(RuntimeError):
    """Raised when a stored pulse record fails its SHA-256 checksum."""


class WorkStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkType(str, Enum):
    GOAL_REVIEW = "GOAL_REVIEW"
    ATTENTION_REVIEW = "ATTENTION_REVIEW"
    QUESTION_GENERATION = "QUESTION_GENERATION"
    HYPOTHESIS_INVESTIGATION = "HYPOTHESIS_INVESTIGATION"
    EXPERIMENT = "EXPERIMENT"
    BELIEF_UPDATE = "BELIEF_UPDATE"
    EXPERIENCE_DISTILLATION = "EXPERIENCE_DISTILLATION"
    FAILURE_ANALYSIS = "FAILURE_ANALYSIS"
    CAPABILITY_HEALTH = "CAPABILITY_HEALTH"
    BOTTLENECK_ANALYSIS = "BOTTLENECK_ANALYSIS"
    IMPROVEMENT_EVALUATION = "IMPROVEMENT_EVALUATION"
    MEMORY_MAINTENANCE = "MEMORY_MAINTENANCE"
    DEEP_CYCLE = "DEEP_CYCLE"
    STALE_TASK_SCAN = "STALE_TASK_SCAN"
    ENVIRONMENT_HEALTH = "ENVIRONMENT_HEALTH"


class FailureKind(str, Enum):
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    UNKNOWN = "UNKNOWN"


@dataclass
class CognitiveWorkItem:
    """A unit of cognitive work scheduled through the priority queue."""

    work_type: WorkType
    priority: float = 0.5          # 0..1, CognitivePriority output when available
    source_event: str = ""         # event_type that created this work
    goal_ids: List[str] = field(default_factory=list)
    deadline: Optional[float] = None
    cost_estimate: float = 0.2     # abstract cognitive cost units
    risk: float = 0.2              # 0..1
    depth_required: str = "D1"     # Slice 6 CognitiveDepthScore level
    provider_required: bool = False  # execution chain needs a model provider
    status: WorkStatus = WorkStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    scheduled_at: float = field(default_factory=time.time)
    attempts: int = 0
    cooldown: float = 0.0          # seconds to wait after last attempt
    work_id: str = field(default_factory=lambda: "pulse_work_%d" % int(time.time() * 1000))
    payload: Dict[str, Any] = field(default_factory=dict)
    last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_id": self.work_id,
            "work_type": self.work_type.value if isinstance(self.work_type, WorkType) else str(self.work_type),
            "priority": self.priority,
            "source_event": self.source_event,
            "goal_ids": list(self.goal_ids),
            "deadline": self.deadline,
            "cost_estimate": self.cost_estimate,
            "risk": self.risk,
            "depth_required": self.depth_required,
            "provider_required": bool(self.provider_required),
            "status": self.status.value if isinstance(self.status, WorkStatus) else str(self.status),
            "created_at": self.created_at,
            "scheduled_at": self.scheduled_at,
            "attempts": self.attempts,
            "cooldown": self.cooldown,
            "payload": self.payload,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveWorkItem":
        return cls(
            work_id=data.get("work_id", cls._default_id()),
            work_type=WorkType(data.get("work_type", WorkType.ATTENTION_REVIEW.value)),
            priority=float(data.get("priority", 0.5)),
            source_event=data.get("source_event", ""),
            goal_ids=list(data.get("goal_ids", [])),
            deadline=data.get("deadline"),
            cost_estimate=float(data.get("cost_estimate", 0.2)),
            risk=float(data.get("risk", 0.2)),
            depth_required=data.get("depth_required", "D1"),
            provider_required=bool(data.get("provider_required", False)),
            status=WorkStatus(data.get("status", WorkStatus.QUEUED.value)),
            created_at=float(data.get("created_at", time.time())),
            scheduled_at=float(data.get("scheduled_at", time.time())),
            attempts=int(data.get("attempts", 0)),
            cooldown=float(data.get("cooldown", 0.0)),
            payload=dict(data.get("payload", {})),
            last_error=data.get("last_error", ""),
        )

    @staticmethod
    def _default_id() -> str:
        return "pulse_work_%d" % int(time.time() * 1000)


class PulseStore:
    """Corruption-safe, lock-protected persistence for the CognitivePulse."""

    def __init__(self, db_path: Optional[str] = "data/pulse_store.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._lock = threading.RLock()
        self._init_db()
        self.load()

    def _init_db(self):
        if not self.db_path:
            return
        p = Path(self.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS work_queue (
                work_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cooldowns (
                key TEXT PRIMARY KEY,
                last_run REAL,
                next_allowed_run REAL,
                trigger_reason TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dedup (
                fingerprint TEXT PRIMARY KEY,
                event_type TEXT,
                occurrence_count INTEGER,
                first_seen REAL,
                last_seen REAL,
                related_events TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                metric TEXT,
                period TEXT,
                amount REAL,
                PRIMARY KEY (metric, period)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS periodic (
                key TEXT PRIMARY KEY,
                last_run REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cycles (
                cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
                state TEXT NOT NULL,
                note TEXT,
                timestamp REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS failures (
                work_id TEXT,
                attempt INTEGER,
                kind TEXT,
                error TEXT,
                timestamp REAL,
                PRIMARY KEY (work_id, attempt)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pulse_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # -- work queue ---------------------------------------------------------

    def enqueue(self, item: CognitiveWorkItem) -> CognitiveWorkItem:
        with self._lock:
            payload = json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":"))
            if self.db_path:
                conn = sqlite3.connect(self.db_path)
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO work_queue VALUES (?, ?, ?)",
                        (item.work_id, payload, self._checksum(payload)))
                    conn.commit()
                finally:
                    conn.close()
            return item

    def get_work(self, work_id: str) -> Optional[CognitiveWorkItem]:
        with self._lock:
            if not self.db_path:
                return None
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT payload, checksum FROM work_queue WHERE work_id = ?",
                    (work_id,)).fetchone()
            finally:
                conn.close()
            if row is None:
                return None
            payload, checksum = row
            if self._checksum(payload) != checksum:
                if self.strict_load:
                    raise PulseIntegrityError(f"work item {work_id} failed checksum")
                self.load_errors.append(f"work item {work_id} failed checksum")
                return None
            return CognitiveWorkItem.from_dict(json.loads(payload))

    def list_work(self, status: Optional[WorkStatus] = None) -> List[CognitiveWorkItem]:
        with self._lock:
            if not self.db_path:
                return []
            conn = sqlite3.connect(self.db_path)
            try:
                rows = conn.execute("SELECT payload, checksum FROM work_queue").fetchall()
            finally:
                conn.close()
            out: List[CognitiveWorkItem] = []
            for payload, checksum in rows:
                if self._checksum(payload) != checksum:
                    if self.strict_load:
                        raise PulseIntegrityError("work item failed checksum")
                    self.load_errors.append("work item failed checksum")
                    continue
                item = CognitiveWorkItem.from_dict(json.loads(payload))
                if status is None or item.status == status:
                    out.append(item)
            return out

    def transition(self, work_id: str, from_status: WorkStatus,
                   to_status: WorkStatus) -> bool:
        """Atomic QUEUED -> RUNNING -> COMPLETED/FAILED/DEFERRED/CANCELLED.
        Returns False when the current status does not match from_status, which
        prevents double-execution and queue corruption."""
        with self._lock:
            item = self.get_work(work_id)
            if item is None or item.status != from_status:
                return False
            item.status = to_status
            if to_status in (WorkStatus.COMPLETED, WorkStatus.FAILED,
                             WorkStatus.CANCELLED):
                item.attempts += 1
            self.enqueue(item)
            return True

    def bump_attempt(self, work_id: str) -> None:
        with self._lock:
            item = self.get_work(work_id)
            if item is None:
                return
            item.attempts += 1
            self.enqueue(item)

    def requeue(self, work_id: str, *, cooldown_s: float = 0.0,
                backoff_s: float = 0.0, error: str = "") -> bool:
        """Return a failed/deferred item to QUEUED after a cooldown/backoff."""
        with self._lock:
            item = self.get_work(work_id)
            if item is None:
                return False
            item.status = WorkStatus.QUEUED
            item.cooldown = max(item.cooldown, cooldown_s, backoff_s)
            if error:
                item.last_error = error
            item.scheduled_at = time.time() + item.cooldown
            self.enqueue(item)
            return True

    # -- cooldowns ----------------------------------------------------------

    def set_cooldown(self, key: str, cooldown_s: float,
                     trigger_reason: str = "") -> None:
        now = time.time()
        with self._lock:
            if self.db_path:
                conn = sqlite3.connect(self.db_path)
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO cooldowns VALUES (?, ?, ?, ?)",
                        (key, now, now + cooldown_s, trigger_reason))
                    conn.commit()
                finally:
                    conn.close()

    # -- periodic last-run timestamps ----------------------------------------

    def mark_periodic_run(self, key: str) -> None:
        """Record that a periodic evaluation (goal health, telemetry scan, ...)
        last ran now. Each evaluation keeps its OWN cadence, so one activity
        never resets another's timer."""
        with self._lock:
            if not self.db_path:
                return
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO periodic VALUES (?, ?)",
                    (key, time.time()))
                conn.commit()
            finally:
                conn.close()

    def last_periodic_run(self, key: str,
                          default: Optional[float] = None) -> Optional[float]:
        """When this evaluation last ran (None when never run in this store)."""
        with self._lock:
            if not self.db_path:
                return default
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT last_run FROM periodic WHERE key = ?",
                    (key,)).fetchone()
            finally:
                conn.close()
            if row is None:
                return default
            return float(row[0])

    def cooldown_remaining(self, key: str) -> float:
        with self._lock:
            if not self.db_path:
                return 0.0
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT next_allowed_run FROM cooldowns WHERE key = ?",
                    (key,)).fetchone()
            finally:
                conn.close()
            if row is None:
                return 0.0
            return max(0.0, row[0] - time.time())

    def in_cooldown(self, key: str) -> bool:
        return self.cooldown_remaining(key) > 0.0

    # -- deduplication ------------------------------------------------------

    def dedup_register(self, fingerprint: str, event_type: str,
                       window_s: float, related_event: str = "") -> int:
        """Aggregate an event by fingerprint within the window. Returns the
        occurrence count (1 on first sighting). Related events are retained so
        deduplication never loses evidence."""
        now = time.time()
        with self._lock:
            if self.db_path:
                conn = sqlite3.connect(self.db_path)
                try:
                    row = conn.execute(
                        "SELECT occurrence_count, first_seen, last_seen, related_events "
                        "FROM dedup WHERE fingerprint = ?", (fingerprint,)).fetchone()
                    if row is None:
                        conn.execute(
                            "INSERT INTO dedup VALUES (?, ?, 1, ?, ?, ?)",
                            (fingerprint, event_type, now, now,
                             json.dumps([related_event]) if related_event else "[]"))
                        conn.commit()
                        return 1
                    count, first_seen, last_seen, related_json = row
                    if now - first_seen > window_s:
                        # window expired -> fresh aggregation bucket
                        conn.execute(
                            "UPDATE dedup SET occurrence_count = 1, first_seen = ?, "
                            "last_seen = ?, related_events = ? WHERE fingerprint = ?",
                            (now, now,
                             json.dumps([related_event]) if related_event else "[]",
                             fingerprint))
                        conn.commit()
                        return 1
                    count += 1
                    related = []
                    try:
                        related = json.loads(related_json or "[]")
                    except (ValueError, TypeError):
                        related = []
                    if related_event and related_event not in related:
                        related.append(related_event)
                    conn.execute(
                        "UPDATE dedup SET occurrence_count = ?, last_seen = ?, "
                        "related_events = ? WHERE fingerprint = ?",
                        (count, now, json.dumps(related[-50:]), fingerprint))
                    conn.commit()
                    return count
                finally:
                    conn.close()
            return 1

    # -- budgets ------------------------------------------------------------

    def spend_budget(self, metric: str, amount: float, period: str) -> float:
        """Add spend to a metric for the period; returns total spend for the
        period after the write."""
        key = f"{metric}:{period}"
        with self._lock:
            if self.db_path:
                conn = sqlite3.connect(self.db_path)
                try:
                    row = conn.execute(
                        "SELECT amount FROM budgets WHERE metric = ? AND period = ?",
                        (metric, period)).fetchone()
                    total = amount + (row[0] if row else 0.0)
                    conn.execute(
                        "INSERT OR REPLACE INTO budgets VALUES (?, ?, ?)",
                        (metric, period, total))
                    conn.commit()
                finally:
                    conn.close()
            return self.budget_usage(metric, period)

    def budget_usage(self, metric: str, period: str) -> float:
        with self._lock:
            if not self.db_path:
                return 0.0
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT amount FROM budgets WHERE metric = ? AND period = ?",
                    (metric, period)).fetchone()
            finally:
                conn.close()
            return float(row[0]) if row else 0.0

    # -- pulse lifecycle state (rule 2/31: persist enough state to recover) --

    def save_pulse_state(self, lifecycle: str, degraded_reason: str = "") -> None:
        """Persist the pulse lifecycle state + degraded reason so a restart can
        recover it: an explicitly PAUSED (or DEGRADED) pulse stays in that
        state instead of being silently resumed or declared healthy."""
        with self._lock:
            if not self.db_path:
                return
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO pulse_state VALUES ('lifecycle', ?)",
                    (lifecycle,))
                conn.execute(
                    "INSERT OR REPLACE INTO pulse_state VALUES ('degraded_reason', ?)",
                    (degraded_reason,))
                conn.commit()
            finally:
                conn.close()

    def load_pulse_state(self) -> tuple:
        """Return (lifecycle, degraded_reason), or (None, "") when nothing was
        ever persisted (a fresh pulse starts in its default state)."""
        with self._lock:
            if not self.db_path:
                return (None, "")
            conn = sqlite3.connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT key, value FROM pulse_state").fetchall()
            finally:
                conn.close()
            values = dict(rows)
            return (values.get("lifecycle"), values.get("degraded_reason", ""))

    # -- cycle history ------------------------------------------------------

    def cycle_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Most-recent cycle records (state, note, timestamp), newest first.
        Used by the deep-cycle review and diagnostics."""
        with self._lock:
            if not self.db_path:
                return []
            conn = sqlite3.connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT state, note, timestamp FROM cycles "
                    "ORDER BY cycle_id DESC LIMIT ?", (limit,)).fetchall()
            finally:
                conn.close()
            return [{"state": r[0], "note": r[1], "timestamp": r[2]}
                    for r in rows]

    def record_cycle(self, state: str, note: str = "") -> None:
        with self._lock:
            if self.db_path:
                conn = sqlite3.connect(self.db_path)
                try:
                    conn.execute(
                        "INSERT INTO cycles (state, note, timestamp) VALUES (?, ?, ?)",
                        (state, note, time.time()))
                    conn.commit()
                finally:
                    conn.close()

    def last_cycle(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self.db_path:
                return None
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT state, note, timestamp FROM cycles "
                    "ORDER BY cycle_id DESC LIMIT 1").fetchone()
            finally:
                conn.close()
            if row is None:
                return None
            return {"state": row[0], "note": row[1], "timestamp": row[2]}

    def cycle_count(self) -> int:
        with self._lock:
            if not self.db_path:
                return 0
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute("SELECT COUNT(*) FROM cycles").fetchone()
            finally:
                conn.close()
            return int(row[0]) if row else 0

    # -- failure history ----------------------------------------------------

    def record_failure(self, work_id: str, attempt: int, kind: str,
                       error: str = "") -> None:
        with self._lock:
            if self.db_path:
                conn = sqlite3.connect(self.db_path)
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO failures VALUES (?, ?, ?, ?, ?)",
                        (work_id, attempt, kind, error[:2000], time.time()))
                    conn.commit()
                finally:
                    conn.close()

    def failure_count(self, work_id: str) -> int:
        with self._lock:
            if not self.db_path:
                return 0
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM failures WHERE work_id = ?",
                    (work_id,)).fetchone()
            finally:
                conn.close()
            return int(row[0]) if row else 0

    # -- load ---------------------------------------------------------------

    def load(self) -> None:
        """Checksum-validate every persisted record on startup. Strict mode
        raises on corruption; lenient mode records load_errors and drops the
        bad records. Restart recovery simply re-reads the persisted queue."""
        if not self.db_path or not Path(self.db_path).exists():
            return
        for item in self.list_work():
            if item.status == WorkStatus.RUNNING:
                # A crash mid-execution leaves a RUNNING item. It is requeued
                # (bounded retry handles re-execution safety) rather than
                # silently completed or duplicated.
                self.transition(item.work_id, WorkStatus.RUNNING, WorkStatus.QUEUED)
