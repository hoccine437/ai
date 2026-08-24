"""
Durable Long-Horizon Mission Definitions
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid


class MissionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"


@dataclass
class MissionStep:
    step_id: str
    name: str
    action_type: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    status: str = "PENDING"  # "PENDING", "RUNNING", "COMPLETED", "FAILED"
    result_data: Any = None
    error_message: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "action_type": self.action_type,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "status": self.status,
            "result_data": self.result_data,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MissionStep":
        return cls(
            step_id=data["step_id"],
            name=data.get("name", data["step_id"]),
            action_type=data.get("action_type", "execute"),
            parameters=data.get("parameters", {}),
            dependencies=data.get("dependencies", []),
            status=data.get("status", "PENDING"),
            result_data=data.get("result_data"),
            error_message=data.get("error_message"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at")
        )


@dataclass
class MissionCheckpoint:
    checkpoint_id: str = field(default_factory=lambda: f"chk_{uuid.uuid4().hex[:8]}")
    mission_id: str = ""
    completed_step_ids: List[str] = field(default_factory=list)
    state_snapshot: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "mission_id": self.mission_id,
            "completed_step_ids": self.completed_step_ids,
            "state_snapshot": self.state_snapshot,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MissionCheckpoint":
        return cls(
            checkpoint_id=data.get("checkpoint_id", f"chk_{uuid.uuid4().hex[:8]}"),
            mission_id=data.get("mission_id", ""),
            completed_step_ids=data.get("completed_step_ids", []),
            state_snapshot=data.get("state_snapshot", {}),
            timestamp=data.get("timestamp", time.time())
        )


@dataclass
class Mission:
    goal: str
    id: str = field(default_factory=lambda: f"mis_{uuid.uuid4().hex[:8]}")
    objective_id: Optional[str] = None
    subgoals: List[str] = field(default_factory=list)
    steps: Dict[str, MissionStep] = field(default_factory=dict)
    status: MissionStatus = MissionStatus.PENDING
    evidence_ids: List[str] = field(default_factory=list)
    checkpoints: List[MissionCheckpoint] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    recovery_strategy: str = "resume_from_last_checkpoint"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: MissionStep):
        self.steps[step.step_id] = step
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "objective_id": self.objective_id,
            "subgoals": self.subgoals,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "status": self.status.value if isinstance(self.status, MissionStatus) else str(self.status),
            "evidence_ids": self.evidence_ids,
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "failures": self.failures,
            "recovery_strategy": self.recovery_strategy,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Mission":
        st_str = data.get("status", MissionStatus.PENDING.value)
        try:
            status = MissionStatus(st_str)
        except ValueError:
            status = MissionStatus.PENDING

        steps = {k: MissionStep.from_dict(v) for k, v in data.get("steps", {}).items()}
        checkpoints = [MissionCheckpoint.from_dict(c) for c in data.get("checkpoints", [])]

        return cls(
            id=data.get("id", f"mis_{uuid.uuid4().hex[:8]}"),
            goal=data.get("goal", ""),
            objective_id=data.get("objective_id"),
            subgoals=data.get("subgoals", []),
            steps=steps,
            status=status,
            evidence_ids=data.get("evidence_ids", []),
            checkpoints=checkpoints,
            failures=data.get("failures", []),
            recovery_strategy=data.get("recovery_strategy", "resume_from_last_checkpoint"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {})
        )
