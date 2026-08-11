"""
Autonomous Problem Discovery Subsystem for Cognitive OS
Monitors environmental drift, prediction errors, resource bottlenecks, and objective gaps.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class DiscoveredProblem:
    problem_id: str = field(default_factory=lambda: f"prob_{uuid.uuid4().hex[:8]}")
    title: str = ""
    signal_source: str = ""
    evidence_data: Dict[str, Any] = field(default_factory=dict)
    impact: float = 0.5
    urgency: float = 0.5
    uncertainty: float = 0.5
    expected_value: float = 0.5
    recommended_action: str = ""
    is_autonomous: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "title": self.title,
            "signal_source": self.signal_source,
            "evidence_data": self.evidence_data,
            "impact": round(self.impact, 3),
            "urgency": round(self.urgency, 3),
            "uncertainty": round(self.uncertainty, 3),
            "expected_value": round(self.expected_value, 3),
            "recommended_action": self.recommended_action,
            "is_autonomous": self.is_autonomous,
            "created_at": self.created_at
        }


class AutonomousProblemDiscovery:
    def __init__(self, urgency_threshold: float = 0.4):
        self.urgency_threshold = urgency_threshold
        self._problem_history: List[DiscoveredProblem] = []

    def evaluate_pressure_signals(self, pressure_signals: List[Any]) -> List[DiscoveredProblem]:
        problems = []
        for sig in pressure_signals:
            mag = getattr(sig, "magnitude", 0.5)
            if mag >= self.urgency_threshold:
                prob = DiscoveredProblem(
                    title=f"Autonomous Discovery: {getattr(sig, 'description', 'Unidentified pressure signal')}",
                    signal_source=getattr(sig, "source", "pressure_sensor"),
                    evidence_data=getattr(sig, "metadata", {}),
                    impact=min(1.0, mag * 1.1),
                    urgency=mag,
                    uncertainty=0.6,
                    expected_value=round(mag * 1.2, 3),
                    recommended_action="Initiate Question Genesis and formulate causal investigation hypothesis.",
                    is_autonomous=True
                )
                problems.append(prob)

        self._problem_history.extend(problems)
        return sorted(problems, key=lambda p: p.expected_value, reverse=True)

    def get_recent_problems(self, limit: int = 10) -> List[DiscoveredProblem]:
        return self._problem_history[-limit:]
