"""
Core Typed Events for ASCENDANT Runtime
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class EventType(str, Enum):
    # System Lifecycle
    SYSTEM_STARTUP = "SYSTEM_STARTUP"
    SYSTEM_SHUTDOWN = "SYSTEM_SHUTDOWN"
    RESOURCE_ALERT = "RESOURCE_ALERT"
    WATCHDOG_HEARTBEAT = "WATCHDOG_HEARTBEAT"
    
    # User Interaction
    USER_GOAL_CREATED = "USER_GOAL_CREATED"
    USER_INTERACTION = "USER_INTERACTION"
    SCREEN_CHANGED = "SCREEN_CHANGED"
    
    # Perception & Pressure
    OBSERVATION_RECORDED = "OBSERVATION_RECORDED"
    PREDICTION_MADE = "PREDICTION_MADE"
    PREDICTION_ERROR = "PREDICTION_ERROR"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    PRESSURE_SURGE = "PRESSURE_SURGE"
    
    # Question & Cognition
    QUESTION_CREATED = "QUESTION_CREATED"
    QUESTION_ANSWERED = "QUESTION_ANSWERED"
    COGNITIVE_PROGRAM_COMPILED = "COGNITIVE_PROGRAM_COMPILED"
    COGNITIVE_STEP_STARTED = "COGNITIVE_STEP_STARTED"
    COGNITIVE_STEP_COMPLETED = "COGNITIVE_STEP_COMPLETED"
    
    # Evidence & Belief
    EVIDENCE_ACQUIRED = "EVIDENCE_ACQUIRED"
    BELIEF_UPDATED = "BELIEF_UPDATED"
    CONTRADICTION_FOUND = "CONTRADICTION_FOUND"
    
    # Experimentation
    EXPERIMENT_STARTED = "EXPERIMENT_STARTED"
    EXPERIMENT_COMPLETED = "EXPERIMENT_COMPLETED"
    EXPERIMENT_FAILED = "EXPERIMENT_FAILED"
    
    # Capabilities & Learning
    CAPABILITY_GAP = "CAPABILITY_GAP"
    CAPABILITY_BORN = "CAPABILITY_BORN"
    CAPABILITY_VALIDATED = "CAPABILITY_VALIDATED"
    SKILL_DISTILLED = "SKILL_DISTILLED"
    TRANSFER_EVALUATED = "TRANSFER_EVALUATED"
    
    # Missions
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_CHECKPOINT = "MISSION_CHECKPOINT"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_FAILED = "MISSION_FAILED"
    
    # Evolution & Self-Improvement
    STRATEGY_MUTATED = "STRATEGY_MUTATED"
    ASCENSION_ATTEMPTED = "ASCENSION_ATTEMPTED"
    ASCENSION_PROMOTED = "ASCENSION_PROMOTED"
    ASCENSION_ROLLED_BACK = "ASCENSION_ROLLED_BACK"


@dataclass
class Event:
    event_type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "runtime"
    priority: int = 50  # 0 (lowest) to 100 (highest/critical)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type),
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "priority": self.priority
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        event_type_str = data.get("event_type", EventType.OBSERVATION_RECORDED.value)
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            event_type = EventType.OBSERVATION_RECORDED
        return cls(
            event_type=event_type,
            payload=data.get("payload", {}),
            event_id=data.get("event_id", str(uuid.uuid4())),
            correlation_id=data.get("correlation_id"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            source=data.get("source", "runtime"),
            priority=data.get("priority", 50)
        )
