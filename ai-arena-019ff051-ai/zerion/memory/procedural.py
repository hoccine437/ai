"""
Procedural Memory and Reusable Action Primitives
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class ProceduralRule:
    id: str = field(default_factory=lambda: f"P_{uuid.uuid4().hex[:6].upper()}")
    name: str = ""
    trigger_conditions: List[str] = field(default_factory=list)
    action_procedure: str = ""
    success_count: int = 0
    attempt_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_episodes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def reliability(self) -> float:
        if self.attempt_count == 0:
            return 0.5
        return round(self.success_count / self.attempt_count, 4)

    def record_attempt(self, success: bool, episode_id: Optional[str] = None):
        self.attempt_count += 1
        if success:
            self.success_count += 1
        if episode_id and episode_id not in self.source_episodes:
            self.source_episodes.append(episode_id)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger_conditions": self.trigger_conditions,
            "action_procedure": self.action_procedure,
            "success_count": self.success_count,
            "attempt_count": self.attempt_count,
            "reliability": self.reliability,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_episodes": self.source_episodes,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProceduralRule":
        return cls(
            id=data.get("id", f"P_{uuid.uuid4().hex[:6].upper()}"),
            name=data.get("name", ""),
            trigger_conditions=data.get("trigger_conditions", []),
            action_procedure=data.get("action_procedure", ""),
            success_count=data.get("success_count", 0),
            attempt_count=data.get("attempt_count", 0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            source_episodes=data.get("source_episodes", []),
            metadata=data.get("metadata", {})
        )
