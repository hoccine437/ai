"""
Episodic Memory - Chronological Experience Log
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class Episode:
    id: str = field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:8]}")
    goal: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    actions_taken: List[str] = field(default_factory=list)
    outcome_status: str = "SUCCESS"  # "SUCCESS", "FAILURE", "ABORTED"
    reward: float = 1.0              # -1.0 to 1.0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "context": self.context,
            "actions_taken": self.actions_taken,
            "outcome_status": self.outcome_status,
            "reward": round(self.reward, 3),
            "duration_ms": round(self.duration_ms, 2),
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Episode":
        return cls(
            id=data.get("id", f"ep_{uuid.uuid4().hex[:8]}"),
            goal=data.get("goal", ""),
            context=data.get("context", {}),
            actions_taken=data.get("actions_taken", []),
            outcome_status=data.get("outcome_status", "SUCCESS"),
            reward=data.get("reward", 1.0),
            duration_ms=data.get("duration_ms", 0.0),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {})
        )
