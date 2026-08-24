"""
Learning-to-Learn (Meta-Learning) Substrate - 2nd & 3rd Order Learning Engine
Measures learning efficiency, tracks learning acceleration trajectories,
and optimizes curriculum construction to reduce episodes required for capability mastery.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class LearningAcquisitionRecord:
    target_skill_or_capability: str
    order_level: int                  # 1: First-Order, 2: Second-Order, 3: Third-Order
    episodes_required: int
    time_to_mastery_seconds: float
    generalization_score: float
    retention_score: float
    transfer_efficiency: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_skill_or_capability": self.target_skill_or_capability,
            "order_level": self.order_level,
            "episodes_required": self.episodes_required,
            "time_to_mastery_seconds": round(self.time_to_mastery_seconds, 2),
            "generalization_score": round(self.generalization_score, 3),
            "retention_score": round(self.retention_score, 3),
            "transfer_efficiency": round(self.transfer_efficiency, 3),
            "timestamp": self.timestamp
        }


class LearningToLearnEngine:
    def __init__(self, db_path: Optional[str] = "data/learning_to_learn.db"):
        self.db_path = db_path
        self._history: List[LearningAcquisitionRecord] = []
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learning_acquisitions (
                    id TEXT PRIMARY KEY,
                    target TEXT,
                    order_level INTEGER,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.commit()
            conn.close()

    def record_acquisition(
        self,
        target: str,
        episodes_required: int,
        duration_s: float,
        generalization: float = 0.92,
        retention: float = 0.98,
        transfer: float = 0.90,
        order_level: int = 2
    ) -> LearningAcquisitionRecord:
        record = LearningAcquisitionRecord(
            target_skill_or_capability=target,
            order_level=order_level,
            episodes_required=episodes_required,
            time_to_mastery_seconds=duration_s,
            generalization_score=generalization,
            retention_score=retention,
            transfer_efficiency=transfer
        )
        self._history.append(record)
        self._persist(record)
        return record

    def calculate_learning_acceleration(self) -> float:
        """
        Calculates second-order learning acceleration ratio:
        Ratio of episodes required for early capabilities vs. recent capabilities.
        > 1.0 means learning is becoming faster over time.
        """
        if len(self._history) < 2:
            return 1.0
        
        first_half = self._history[:len(self._history)//2]
        second_half = self._history[len(self._history)//2:]

        avg_early = sum(r.episodes_required for r in first_half) / len(first_half)
        avg_recent = sum(r.episodes_required for r in second_half) / len(second_half)

        if avg_recent == 0:
            return 2.0
        return round(avg_early / avg_recent, 3)

    def analyze_learning_bottleneck(self) -> Dict[str, Any]:
        """Third-Order: Analyzes failure points in learning trajectories and recommends curriculum changes."""
        if not self._history:
            return {"bottleneck": "Insufficient historical acquisition data", "recommendation": "Execute baseline trials"}

        avg_episodes = sum(r.episodes_required for r in self._history) / len(self._history)
        avg_gen = sum(r.generalization_score for r in self._history) / len(self._history)

        if avg_gen < 0.80:
            return {
                "bottleneck": "Low generalization after training",
                "root_cause": "Overfitting to narrow task parameters",
                "recommended_curriculum_mutation": "Increase variance and noise injection in sandbox practice steps."
            }
        elif avg_episodes > 8:
            return {
                "bottleneck": "High episode requirement for mastery",
                "root_cause": "Insufficient abstraction in procedural rule extraction",
                "recommended_curriculum_mutation": "Lower minimum pattern support threshold to 2 episodes and enable multi-path distillation."
            }
        else:
            return {
                "bottleneck": "None detected",
                "status": "Optimal developmental velocity",
                "recommended_curriculum_mutation": "Maintain current curriculum configuration."
            }

    def _persist(self, r: LearningAcquisitionRecord):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT OR REPLACE INTO learning_acquisitions VALUES (?, ?, ?, ?, ?)", (str(uuid.uuid4()), r.target_skill_or_capability, r.order_level, json.dumps(r.to_dict()), r.timestamp))
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM learning_acquisitions ORDER BY timestamp ASC").fetchall():
                d = json.loads(row[0])
                self._history.append(LearningAcquisitionRecord(
                    target_skill_or_capability=d["target_skill_or_capability"],
                    order_level=d.get("order_level", 2),
                    episodes_required=d.get("episodes_required", 5),
                    time_to_mastery_seconds=d.get("time_to_mastery_seconds", 10.0),
                    generalization_score=d.get("generalization_score", 0.9),
                    retention_score=d.get("retention_score", 0.98),
                    transfer_efficiency=d.get("transfer_efficiency", 0.9),
                    timestamp=d.get("timestamp", time.time())
                ))
            conn.close()
        except Exception:
            pass
