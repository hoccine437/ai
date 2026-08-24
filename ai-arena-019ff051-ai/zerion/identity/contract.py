"""
User Contract and Core Commitments
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class Commitment:
    id: str
    statement: str
    priority: int  # 1 (highest) to 10
    active: bool = True


@dataclass
class UserContract:
    owner_id: str = "default_user"
    commitments: List[Commitment] = field(default_factory=lambda: [
        Commitment("COM-01", "Preserve user data privacy and local isolation", 1),
        Commitment("COM-02", "Provide rigorous, verifiable evidence for all substantive claims", 2),
        Commitment("COM-03", "Proactively discover latent system anomalies and inefficiencies", 3),
        Commitment("COM-04", "Continuously improve execution efficiency through empirical learning", 4)
    ])
    operational_boundaries: List[str] = field(default_factory=lambda: [
        "No unapproved destructive filesystem modifications",
        "Strict budget compliance on external model calls",
        "Graceful offline degradation when disconnected"
    ])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "commitments": [{"id": c.id, "statement": c.statement, "priority": c.priority, "active": c.active} for c in self.commitments],
            "operational_boundaries": self.operational_boundaries
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserContract":
        commitments = [
            Commitment(c["id"], c["statement"], c["priority"], c.get("active", True))
            for c in data.get("commitments", [])
        ]
        return cls(
            owner_id=data.get("owner_id", "default_user"),
            commitments=commitments,
            operational_boundaries=data.get("operational_boundaries", [])
        )
