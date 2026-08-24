"""
Durable Long-Term Objective Manager for Cognitive OS
Guarantees objective continuity across crashes, restarts, reboots, and network losses.

Slice 1 additions (backward compatible):
- ``ObjectiveLifecycle``: PROPOSED / ACTIVE / BLOCKED / PAUSED / COMPLETED / ABANDONED
  with a validated transition matrix (impossible transitions raise GoalTransitionError).
- Rich goal fields: ``purpose``, ``progress_evidence`` (structured), ``abandonment_criteria``,
  ``blockers`` (structured), ``trajectory`` (structured historical record).
- New API: ``create_goal``, ``set_status``, ``activate``, ``block``, ``unblock``, ``pause``,
  ``resume``, ``complete``, ``abandon``, ``set_progress``, ``set_next_action``, ``list_goals``.
- Corruption-safe loading: ``strict_load=True`` raises ObjectiveStoreIntegrityError instead of
  silently returning empty state; load errors are always recorded in ``load_errors``.
"""

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


class ObjectiveLifecycle(str, Enum):
    """Lifecycle of a goal in the Goal Field."""

    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


# Valid lifecycle transitions. Terminal states (COMPLETED / ABANDONED) are final.
GOAL_TRANSITIONS: Dict[ObjectiveLifecycle, set] = {
    ObjectiveLifecycle.PROPOSED: {ObjectiveLifecycle.ACTIVE, ObjectiveLifecycle.BLOCKED, ObjectiveLifecycle.ABANDONED},
    ObjectiveLifecycle.ACTIVE: {ObjectiveLifecycle.BLOCKED, ObjectiveLifecycle.PAUSED, ObjectiveLifecycle.COMPLETED, ObjectiveLifecycle.ABANDONED},
    ObjectiveLifecycle.BLOCKED: {ObjectiveLifecycle.ACTIVE, ObjectiveLifecycle.PAUSED, ObjectiveLifecycle.ABANDONED},
    ObjectiveLifecycle.PAUSED: {ObjectiveLifecycle.ACTIVE, ObjectiveLifecycle.BLOCKED, ObjectiveLifecycle.ABANDONED},
    ObjectiveLifecycle.COMPLETED: set(),
    ObjectiveLifecycle.ABANDONED: set(),
}

TERMINAL_LIFECYCLE = {ObjectiveLifecycle.COMPLETED, ObjectiveLifecycle.ABANDONED}


class GoalTransitionError(ValueError):
    """Raised when a goal lifecycle transition is not permitted."""


class GoalDependencyError(ValueError):
    """Raised when a goal cannot be activated because dependencies are unmet."""


class ObjectiveStoreIntegrityError(RuntimeError):
    """Raised when persisted goal data is corrupt and strict loading is enabled."""


def _coerce_lifecycle(value: Any) -> ObjectiveLifecycle:
    if isinstance(value, ObjectiveLifecycle):
        return value
    try:
        return ObjectiveLifecycle(str(value))
    except ValueError:
        return ObjectiveLifecycle.ACTIVE


def _validate_priority(priority: int):
    if not isinstance(priority, int) or isinstance(priority, bool) or not (0 <= priority <= 100):
        raise ValueError(f"Goal priority must be an int in [0, 100], got {priority!r}")


@dataclass
class ContinuousObjective:
    """A durable goal. A goal is never merely a name — it carries purpose, criteria,
    dependencies, blockers, evidence, and a full historical trajectory."""

    objective_id: str
    title: str
    priority: int = 80             # [0, 100]
    deadline_ts: Optional[float] = None
    progress: float = 0.0          # [0.0, 1.0]
    dependencies: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    success_condition: str = "All milestones verified with empirical evidence"
    failure_condition: str = "Unrecoverable invariant violation"
    abandonment_criteria: List[str] = field(default_factory=list)
    history: List[str] = field(default_factory=list)          # legacy string log (kept)
    trajectory: List[Dict[str, Any]] = field(default_factory=list)  # structured history
    progress_evidence: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[Dict[str, Any]] = field(default_factory=list)
    next_action: str = "Sample environmental state"
    purpose: str = ""
    status: ObjectiveLifecycle = ObjectiveLifecycle.ACTIVE
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.status = _coerce_lifecycle(self.status)
        self.is_active = self.status not in TERMINAL_LIFECYCLE
        _validate_priority(self.priority)

    def _append_trajectory(self, field_name: str, from_value: Any, to_value: Any, note: str = ""):
        self.trajectory.append({
            "timestamp": time.time(),
            "field": field_name,
            "from": from_value,
            "to": to_value,
            "note": note,
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "title": self.title,
            "priority": self.priority,
            "deadline_ts": self.deadline_ts,
            "progress": round(self.progress, 6),
            "dependencies": self.dependencies,
            "blocked_reason": self.blocked_reason,
            "success_condition": self.success_condition,
            "failure_condition": self.failure_condition,
            "abandonment_criteria": self.abandonment_criteria,
            "history": self.history,
            "trajectory": self.trajectory,
            "progress_evidence": self.progress_evidence,
            "blockers": self.blockers,
            "next_action": self.next_action,
            "purpose": self.purpose,
            "status": self.status.value,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContinuousObjective":
        status = _coerce_lifecycle(data.get("status", ObjectiveLifecycle.ACTIVE.value))
        return cls(
            objective_id=data["objective_id"],
            title=data.get("title", ""),
            priority=data.get("priority", 80),
            deadline_ts=data.get("deadline_ts"),
            progress=float(data.get("progress", 0.0)),
            dependencies=list(data.get("dependencies", [])),
            blocked_reason=data.get("blocked_reason"),
            success_condition=data.get("success_condition", ""),
            failure_condition=data.get("failure_condition", ""),
            abandonment_criteria=list(data.get("abandonment_criteria", [])),
            history=list(data.get("history", [])),
            trajectory=list(data.get("trajectory", [])),
            progress_evidence=list(data.get("progress_evidence", [])),
            blockers=list(data.get("blockers", [])),
            next_action=data.get("next_action", ""),
            purpose=data.get("purpose", ""),
            status=status,
            is_active=bool(data.get("is_active", status not in TERMINAL_LIFECYCLE)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


class ObjectiveContinuityManager:
    """Persistent Goal Field backed by SQLite WAL (atomic commits)."""

    def __init__(self, db_path: Optional[str] = "data/continuous_objectives.db",
                 strict_load: bool = False):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._objectives: Dict[str, ContinuousObjective] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS continuous_objectives (
                    objective_id TEXT PRIMARY KEY,
                    title TEXT,
                    priority INTEGER,
                    progress REAL,
                    data_json TEXT,
                    is_active INTEGER,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def register_objective(self, obj: ContinuousObjective) -> str:
        """Legacy API: register (or overwrite) a goal and persist immediately."""
        _validate_priority(obj.priority)
        self._objectives[obj.objective_id] = obj
        self._persist(obj)
        return obj.objective_id

    def create_goal(self, objective: str, purpose: str = "",
                    priority: int = 80, deadline_ts: Optional[float] = None,
                    dependencies: Optional[List[str]] = None,
                    success_criteria: Optional[List[str]] = None,
                    failure_criteria: Optional[List[str]] = None,
                    abandonment_criteria: Optional[List[str]] = None,
                    next_action: str = "",
                    goal_id: Optional[str] = None) -> ContinuousObjective:
        """Create a goal in the PROPOSED lifecycle state, persisted immediately."""
        _validate_priority(priority)
        obj = ContinuousObjective(
            objective_id=goal_id or f"goal_{uuid.uuid4().hex[:10]}",
            title=objective,
            purpose=purpose,
            priority=priority,
            deadline_ts=deadline_ts,
            dependencies=list(dependencies or []),
            success_condition="; ".join(success_criteria) if success_criteria else "All milestones verified with empirical evidence",
            failure_condition="; ".join(failure_criteria) if failure_criteria else "Unrecoverable invariant violation",
            abandonment_criteria=list(abandonment_criteria or []),
            next_action=next_action,
            status=ObjectiveLifecycle.PROPOSED,
            is_active=True,
        )
        obj._append_trajectory("status", None, ObjectiveLifecycle.PROPOSED.value, "goal created")
        self._objectives[obj.objective_id] = obj
        self._persist(obj)
        return obj

    def get_goal(self, objective_id: str) -> Optional[ContinuousObjective]:
        return self._objectives.get(objective_id)

    def get_objective(self, objective_id: str) -> Optional[ContinuousObjective]:
        return self.get_goal(objective_id)

    def list_goals(self, status: Optional[ObjectiveLifecycle] = None) -> List[ContinuousObjective]:
        objs = list(self._objectives.values())
        if status is not None:
            status = _coerce_lifecycle(status)
            objs = [o for o in objs if o.status == status]
        return sorted(objs, key=lambda x: (x.priority, x.created_at), reverse=True)

    def list_active_objectives(self) -> List[ContinuousObjective]:
        return sorted(
            [o for o in self._objectives.values() if o.is_active],
            key=lambda x: (x.priority, x.created_at),
            reverse=True
        )

    # --- Lifecycle state machine -------------------------------------------------

    def _transition(self, objective_id: str, new_status: ObjectiveLifecycle,
                    note: str = "") -> ContinuousObjective:
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        new_status = _coerce_lifecycle(new_status)
        allowed = GOAL_TRANSITIONS[obj.status]
        if new_status not in allowed:
            raise GoalTransitionError(
                f"Impossible goal transition {obj.status.value} -> {new_status.value} for {objective_id}"
            )
        old_status = obj.status
        obj.status = new_status
        obj.is_active = new_status not in TERMINAL_LIFECYCLE
        obj.updated_at = time.time()
        obj._append_trajectory("status", old_status.value, new_status.value, note)
        if note:
            obj.history.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {note}")
        self._persist(obj)
        return obj

    def set_status(self, objective_id: str, new_status: ObjectiveLifecycle,
                   note: str = "") -> ContinuousObjective:
        return self._transition(objective_id, new_status, note=note)

    def activate(self, objective_id: str) -> ContinuousObjective:
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        unmet = [dep for dep in obj.dependencies
                 if self.get_goal(dep) is None or self.get_goal(dep).status != ObjectiveLifecycle.COMPLETED]
        if unmet:
            raise GoalDependencyError(
                f"Cannot activate goal {objective_id}: unmet dependencies {unmet}"
            )
        if obj.status == ObjectiveLifecycle.PROPOSED:
            return self._transition(objective_id, ObjectiveLifecycle.ACTIVE, "goal activated")
        if obj.status == ObjectiveLifecycle.BLOCKED:
            obj.blockers = []
            obj.blocked_reason = None
            return self._transition(objective_id, ObjectiveLifecycle.ACTIVE, "goal unblocked")
        return obj

    def block(self, objective_id: str, reason: str) -> ContinuousObjective:
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        obj.blockers.append({"reason": reason, "since": time.time()})
        obj.blocked_reason = reason
        if obj.status in (ObjectiveLifecycle.ACTIVE, ObjectiveLifecycle.PROPOSED):
            obj = self._transition(objective_id, ObjectiveLifecycle.BLOCKED, f"blocked: {reason}")
        else:
            obj.updated_at = time.time()
            obj._append_trajectory("blocker", None, reason, "blocker added")
            self._persist(obj)
        return obj

    def unblock(self, objective_id: str) -> ContinuousObjective:
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        obj.blockers = []
        obj.blocked_reason = None
        if obj.status == ObjectiveLifecycle.BLOCKED:
            return self._transition(objective_id, ObjectiveLifecycle.ACTIVE, "blocker resolved")
        obj.updated_at = time.time()
        self._persist(obj)
        return obj

    def pause(self, objective_id: str) -> ContinuousObjective:
        return self._transition(objective_id, ObjectiveLifecycle.PAUSED, "goal paused")

    def resume(self, objective_id: str) -> ContinuousObjective:
        return self._transition(objective_id, ObjectiveLifecycle.ACTIVE, "goal resumed")

    def complete(self, objective_id: str, note: str = "goal completed") -> ContinuousObjective:
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        if obj.progress < 1.0:
            obj.progress = 1.0
            obj._append_trajectory("progress", round(obj.progress, 6), 1.0, note)
            obj.progress_evidence.append({"timestamp": time.time(), "progress": 1.0, "note": note})
        return self._transition(objective_id, ObjectiveLifecycle.COMPLETED, note)

    def abandon(self, objective_id: str, reason: str = "") -> ContinuousObjective:
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        return self._transition(objective_id, ObjectiveLifecycle.ABANDONED,
                                f"abandoned: {reason}" if reason else "goal abandoned")

    def set_next_action(self, objective_id: str, next_action: str) -> ContinuousObjective:
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        obj.next_action = next_action
        obj.updated_at = time.time()
        obj._append_trajectory("next_action", None, next_action, "next action updated")
        self._persist(obj)
        return obj

    # --- Progress ---------------------------------------------------------------

    def update_progress(self, objective_id: str, delta_progress: float, action_note: str):
        """Legacy API: delta-based progress update with a string history note."""
        if objective_id in self._objectives:
            obj = self._objectives[objective_id]
            obj.progress = min(1.0, max(0.0, obj.progress + delta_progress))
            obj.history.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {action_note} (+{delta_progress*100:.1f}%)")
            obj.progress_evidence.append({
                "timestamp": time.time(),
                "progress": round(obj.progress, 6),
                "note": action_note,
            })
            obj.updated_at = time.time()
            if obj.progress >= 1.0:
                obj.is_active = False
                obj.next_action = "Objective completed and verified"
                if obj.status != ObjectiveLifecycle.COMPLETED:
                    obj.status = ObjectiveLifecycle.COMPLETED
                    obj._append_trajectory("status", None, ObjectiveLifecycle.COMPLETED.value,
                                           "completed via progress")
            self._persist(obj)

    def set_progress(self, objective_id: str, progress: float, note: str = "",
                     evidence: Optional[str] = None) -> ContinuousObjective:
        """Absolute progress update with structured evidence. Auto-completes at >= 1.0."""
        progress = float(progress)
        if not (0.0 <= progress <= 1.0):
            raise ValueError(f"Goal progress must be in [0.0, 1.0], got {progress!r}")
        obj = self.get_goal(objective_id)
        if obj is None:
            raise KeyError(f"Unknown goal: {objective_id}")
        old = obj.progress
        obj.progress = progress
        obj.updated_at = time.time()
        obj.progress_evidence.append({
            "timestamp": time.time(),
            "progress": round(progress, 6),
            "note": note,
            "evidence": evidence,
        })
        obj._append_trajectory("progress", round(old, 6), round(progress, 6), note)
        if progress >= 1.0:
            obj.is_active = False
            obj.next_action = "Goal completed and verified"
            if obj.status == ObjectiveLifecycle.PROPOSED:
                # Dependencies must be met before a proposed goal can complete.
                self.activate(objective_id)
            if obj.status != ObjectiveLifecycle.COMPLETED:
                return self._transition(objective_id, ObjectiveLifecycle.COMPLETED, "completed via progress")
        else:
            obj.is_active = obj.status not in TERMINAL_LIFECYCLE
        self._persist(obj)
        return obj

    def count_goals(self) -> Dict[str, int]:
        counts = {status.value: 0 for status in ObjectiveLifecycle}
        for obj in self._objectives.values():
            counts[obj.status.value] += 1
        counts["total"] = len(self._objectives)
        return counts

    # --- Persistence ------------------------------------------------------------

    def _persist(self, obj: ContinuousObjective):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO continuous_objectives VALUES (?, ?, ?, ?, ?, ?, ?)",
                (obj.objective_id, obj.title, obj.priority, obj.progress,
                 json.dumps(obj.to_dict()), 1 if obj.is_active else 0, obj.updated_at)
            )
            conn.commit()
        finally:
            conn.close()

    def load(self):
        """Load all goals. Never silently returns empty state: load errors are recorded
        in ``load_errors`` and, with ``strict_load=True``, raised as
        ObjectiveStoreIntegrityError."""
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT data_json FROM continuous_objectives").fetchall()
            conn.close()
            for row in rows:
                d = json.loads(row[0])
                self._objectives[d["objective_id"]] = ContinuousObjective.from_dict(d)
        except Exception as e:
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise ObjectiveStoreIntegrityError(
                    f"Failed to load persisted goals from {self.db_path}: {e}"
                ) from e
