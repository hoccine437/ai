"""
Persistent Goal Field Substrate for ZERION-X
Manages living objective structures surviving process restarts, model replacements, and hardware reboots.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class GoalItem:
    goal_id: str = field(default_factory=lambda: f"goal_{uuid.uuid4().hex[:8]}")
    title: str = ""
    purpose: str = ""
    priority: int = 80             # [1, 100]
    deadline_ts: Optional[float] = None
    current_state: str = "ACTIVE"  # "ACTIVE", "PAUSED", "COMPLETED", "BLOCKED", "ABANDONED"
    dependencies: List[str] = field(default_factory=list)
    progress_evidence: List[str] = field(default_factory=list)
    progress_ratio: float = 0.0    # [0.0, 1.0]
    blockers: List[str] = field(default_factory=list)
    next_action: str = "Scan environment"
    abandonment_criteria: str = "Unresolvable invariant contradiction or zero marginal utility"
    success_criteria: str = "Empirical verification in sandbox"
    historical_trajectory: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "purpose": self.purpose,
            "priority": self.priority,
            "deadline_ts": self.deadline_ts,
            "current_state": self.current_state,
            "dependencies": self.dependencies,
            "progress_evidence": self.progress_evidence,
            "progress_ratio": round(self.progress_ratio, 3),
            "blockers": self.blockers,
            "next_action": self.next_action,
            "abandonment_criteria": self.abandonment_criteria,
            "success_criteria": self.success_criteria,
            "historical_trajectory": self.historical_trajectory,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class GoalField:
    def __init__(self, db_path: Optional[str] = "data/goal_field.db"):
        self.db_path = db_path
        self._goals: Dict[str, GoalItem] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goal_items (
                    goal_id TEXT PRIMARY KEY,
                    title TEXT,
                    priority INTEGER,
                    current_state TEXT,
                    progress_ratio REAL,
                    data_json TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def register_goal(self, goal: GoalItem) -> str:
        self._goals[goal.goal_id] = goal
        self._persist(goal)
        return goal.goal_id

    def advance_goal(self, goal_id: str, delta_progress: float, evidence_note: str):
        if goal_id in self._goals:
            g = self._goals[goal_id]
            g.progress_ratio = min(1.0, max(0.0, g.progress_ratio + delta_progress))
            g.progress_evidence.append(f"[{time.strftime('%H:%M:%S')}] {evidence_note}")
            g.historical_trajectory.append(f"+{delta_progress*100:.1f}% -> {g.progress_ratio*100:.1f}%")
            g.updated_at = time.time()
            if g.progress_ratio >= 1.0:
                g.current_state = "COMPLETED"
                g.next_action = "Goal completed and verified"
            self._persist(g)

    def list_active_goals(self) -> List[GoalItem]:
        return sorted(
            [g for g in self._goals.values() if g.current_state == "ACTIVE"],
            key=lambda x: x.priority,
            reverse=True
        )

    def _persist(self, g: GoalItem):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO goal_items VALUES (?, ?, ?, ?, ?, ?, ?)",
            (g.goal_id, g.title, g.priority, g.current_state, g.progress_ratio, json.dumps(g.to_dict()), g.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM goal_items").fetchall():
                d = json.loads(row[0])
                g = GoalItem(
                    goal_id=d["goal_id"],
                    title=d["title"],
                    purpose=d.get("purpose", ""),
                    priority=d.get("priority", 80),
                    deadline_ts=d.get("deadline_ts"),
                    current_state=d.get("current_state", "ACTIVE"),
                    dependencies=d.get("dependencies", []),
                    progress_evidence=d.get("progress_evidence", []),
                    progress_ratio=d.get("progress_ratio", 0.0),
                    blockers=d.get("blockers", []),
                    next_action=d.get("next_action", ""),
                    abandonment_criteria=d.get("abandonment_criteria", ""),
                    success_criteria=d.get("success_criteria", ""),
                    historical_trajectory=d.get("historical_trajectory", []),
                    created_at=d.get("created_at", time.time()),
                    updated_at=d.get("updated_at", time.time())
                )
                self._goals[g.goal_id] = g
            conn.close()
        except Exception:
            pass
