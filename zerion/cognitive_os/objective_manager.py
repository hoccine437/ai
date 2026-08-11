"""
Durable Long-Term Objective Manager for Cognitive OS
Guarantees objective continuity across crashes, restarts, reboots, and network losses.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class ContinuousObjective:
    objective_id: str
    title: str
    priority: int = 80             # [1, 100]
    deadline_ts: Optional[float] = None
    progress: float = 0.0          # [0.0, 1.0]
    dependencies: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    success_condition: str = "All milestones verified with empirical evidence"
    failure_condition: str = "Unrecoverable invariant violation"
    history: List[str] = field(default_factory=list)
    next_action: str = "Sample environmental state"
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "title": self.title,
            "priority": self.priority,
            "deadline_ts": self.deadline_ts,
            "progress": round(self.progress, 3),
            "dependencies": self.dependencies,
            "blocked_reason": self.blocked_reason,
            "success_condition": self.success_condition,
            "failure_condition": self.failure_condition,
            "history": self.history,
            "next_action": self.next_action,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class ObjectiveContinuityManager:
    def __init__(self, db_path: Optional[str] = "data/continuous_objectives.db"):
        self.db_path = db_path
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
        self._objectives[obj.objective_id] = obj
        self._persist(obj)
        return obj.objective_id

    def update_progress(self, objective_id: str, delta_progress: float, action_note: str):
        if objective_id in self._objectives:
            obj = self._objectives[objective_id]
            obj.progress = min(1.0, max(0.0, obj.progress + delta_progress))
            obj.history.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {action_note} (+{delta_progress*100:.1f}%)")
            obj.updated_at = time.time()
            if obj.progress >= 1.0:
                obj.is_active = False
                obj.next_action = "Objective completed and verified"
            self._persist(obj)

    def list_active_objectives(self) -> List[ContinuousObjective]:
        return sorted(
            [o for o in self._objectives.values() if o.is_active],
            key=lambda x: x.priority,
            reverse=True
        )

    def _persist(self, obj: ContinuousObjective):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO continuous_objectives VALUES (?, ?, ?, ?, ?, ?, ?)",
            (obj.objective_id, obj.title, obj.priority, obj.progress, json.dumps(obj.to_dict()), 1 if obj.is_active else 0, obj.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM continuous_objectives").fetchall():
                d = json.loads(row[0])
                obj = ContinuousObjective(
                    objective_id=d["objective_id"],
                    title=d["title"],
                    priority=d.get("priority", 80),
                    deadline_ts=d.get("deadline_ts"),
                    progress=d.get("progress", 0.0),
                    dependencies=d.get("dependencies", []),
                    blocked_reason=d.get("blocked_reason"),
                    success_condition=d.get("success_condition", ""),
                    failure_condition=d.get("failure_condition", ""),
                    history=d.get("history", []),
                    next_action=d.get("next_action", ""),
                    is_active=bool(d.get("is_active", True)),
                    created_at=d.get("created_at", time.time()),
                    updated_at=d.get("updated_at", time.time())
                )
                self._objectives[obj.objective_id] = obj
            conn.close()
        except Exception:
            pass
