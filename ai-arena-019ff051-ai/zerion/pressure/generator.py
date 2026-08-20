"""
Autonomous Problem Candidate Generator
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid
from zerion.pressure.signals import PressureSignal, SignalType
from zerion.pressure.field import PressureField


@dataclass
class ProblemCandidate:
    id: str = field(default_factory=lambda: f"prob_{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    trigger_signal: Optional[PressureSignal] = None
    urgency: float = 0.5   # 0.0 to 1.0
    impact: float = 0.5    # 0.0 to 1.0
    source: str = "pressure_field"
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "trigger_signal": self.trigger_signal.to_dict() if self.trigger_signal else None,
            "urgency": round(self.urgency, 4),
            "impact": round(self.impact, 4),
            "source": self.source,
            "created_at": self.created_at,
            "metadata": self.metadata
        }


class ProblemCandidateGenerator:
    def __init__(self, pressure_threshold: float = 0.4):
        self.pressure_threshold = pressure_threshold

    def generate_candidates(self, pressure_field: PressureField) -> List[ProblemCandidate]:
        candidates: List[ProblemCandidate] = []
        signals = pressure_field.sample_field()

        for sig in signals:
            if sig.magnitude >= self.pressure_threshold:
                cand = self._convert_signal_to_problem(sig)
                candidates.append(cand)

        return candidates

    def _convert_signal_to_problem(self, sig: PressureSignal) -> ProblemCandidate:
        if sig.signal_type == SignalType.INEFFICIENCY:
            title = f"Resolve Inefficiency: {sig.description}"
            impact = 0.7
        elif sig.signal_type == SignalType.PREDICTION_ERROR:
            title = f"Reconcile Prediction Error in {sig.source}"
            impact = 0.8
        elif sig.signal_type == SignalType.CAPABILITY_GAP:
            title = f"Develop Missing or Degraded Capability: {sig.source}"
            impact = 0.85
        elif sig.signal_type == SignalType.KNOWLEDGE_GAP:
            title = f"Investigate Epistemic Void: {sig.description}"
            impact = 0.6
        elif sig.signal_type == SignalType.ANOMALY:
            title = f"Diagnose Anomaly: {sig.description}"
            impact = 0.75
        else:
            title = f"Investigate Pressure: {sig.description}"
            impact = 0.5

        return ProblemCandidate(
            title=title,
            description=sig.description,
            trigger_signal=sig,
            urgency=sig.magnitude,
            impact=impact,
            source=sig.source,
            metadata=sig.metadata
        )
