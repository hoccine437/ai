"""
Pressure Signal Definitions and Types
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict
import uuid


class SignalType(str, Enum):
    PREDICTION_ERROR = "PREDICTION_ERROR"
    ANOMALY = "ANOMALY"
    UNFINISHED_GOAL = "UNFINISHED_GOAL"
    PERFORMANCE_DEGRADATION = "PERFORMANCE_DEGRADATION"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    CONTRADICTION = "CONTRADICTION"
    RISK = "RISK"
    INEFFICIENCY = "INEFFICIENCY"
    OPPORTUNITY = "OPPORTUNITY"
    DRIFT = "DRIFT"


@dataclass
class PressureSignal:
    signal_type: SignalType
    magnitude: float  # 0.0 to 1.0
    source: str
    description: str
    id: str = field(default_factory=lambda: f"sig_{uuid.uuid4().hex[:8]}")
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "signal_type": self.signal_type.value if isinstance(self.signal_type, SignalType) else str(self.signal_type),
            "magnitude": round(self.magnitude, 4),
            "source": self.source,
            "description": self.description,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PressureSignal":
        st_str = data.get("signal_type", SignalType.ANOMALY.value)
        try:
            st = SignalType(st_str)
        except ValueError:
            st = SignalType.ANOMALY
        return cls(
            id=data.get("id", f"sig_{uuid.uuid4().hex[:8]}"),
            signal_type=st,
            magnitude=data.get("magnitude", 0.5),
            source=data.get("source", "unknown"),
            description=data.get("description", ""),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {})
        )
