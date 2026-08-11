"""
Long-Term Objectives and Invariant Management
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid


class ObjectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class LongTermObjective:
    id: str = field(default_factory=lambda: f"obj_{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    priority: int = 50
    status: ObjectiveStatus = ObjectiveStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    parent_objective_id: Optional[str] = None
    success_criteria: List[str] = field(default_factory=list)
    progress: float = 0.0  # 0.0 to 1.0
    evidence_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status.value if isinstance(self.status, ObjectiveStatus) else str(self.status),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "parent_objective_id": self.parent_objective_id,
            "success_criteria": self.success_criteria,
            "progress": self.progress,
            "evidence_ids": self.evidence_ids,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LongTermObjective":
        status_str = data.get("status", ObjectiveStatus.ACTIVE.value)
        try:
            status = ObjectiveStatus(status_str)
        except ValueError:
            status = ObjectiveStatus.ACTIVE
        return cls(
            id=data.get("id", f"obj_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            priority=data.get("priority", 50),
            status=status,
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            parent_objective_id=data.get("parent_objective_id"),
            success_criteria=data.get("success_criteria", []),
            progress=data.get("progress", 0.0),
            evidence_ids=data.get("evidence_ids", []),
            metadata=data.get("metadata", {})
        )
