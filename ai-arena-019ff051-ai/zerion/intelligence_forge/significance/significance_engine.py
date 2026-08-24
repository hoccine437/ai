"""
Significance Engine Substrate for ZERION-X Ω Intelligence Foundry
Determines what signals and state changes deserve computational intelligence.
Evaluates incoming environmental, objective, anomaly, and user signals to produce:
IGNORE, MONITOR, PROBLEM, OPPORTUNITY, RISK, UNKNOWN, OBJECTIVE_DRIFT, or CAPABILITY_GAP.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid


class SignificanceOutput(str, Enum):
    IGNORE = "IGNORE"
    MONITOR = "MONITOR"
    PROBLEM = "PROBLEM"
    OPPORTUNITY = "OPPORTUNITY"
    RISK = "RISK"
    UNKNOWN = "UNKNOWN"
    OBJECTIVE_DRIFT = "OBJECTIVE_DRIFT"
    CAPABILITY_GAP = "CAPABILITY_GAP"


@dataclass
class SignificanceSignal:
    source: str
    signal_id: str = field(default_factory=lambda: f"sig_{uuid.uuid4().hex[:8]}")
    importance: float = 0.5            # [0.0, 1.0]
    uncertainty: float = 0.5           # [0.0, 1.0]
    novelty: float = 0.5               # [0.0, 1.0]
    objective_relevance: float = 0.5   # [0.0, 1.0]
    expected_information_gain: float = 0.5 # [0.0, 1.0]
    cost: float = 1.0                  # Estimated compute cost >= 0.1
    risk: float = 0.1                  # Action risk [0.0, 1.0]
    payload: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def significance_score(self) -> float:
        """
        Computes composite significance value:
        (importance * uncertainty * novelty * objective_relevance * expected_information_gain) / (max(0.1, cost) * max(0.1, 1.0 - risk)) * 10
        """
        numerator = (
            max(0.01, self.importance) *
            max(0.01, self.uncertainty) *
            max(0.01, self.novelty) *
            max(0.01, self.objective_relevance) *
            max(0.01, self.expected_information_gain)
        )
        denominator = max(0.1, self.cost) * max(0.1, 1.0 - self.risk)
        return round((numerator / denominator) * 1000.0, 4)


@dataclass
class SignificanceAssessment:
    assessment_id: str
    decision: SignificanceOutput
    significance_score: float
    trigger_signal: SignificanceSignal
    requires_cognitive_episode: bool
    rationale: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "decision": self.decision.value,
            "significance_score": round(self.significance_score, 4),
            "source": self.trigger_signal.source,
            "description": self.trigger_signal.description,
            "requires_cognitive_episode": self.requires_cognitive_episode,
            "rationale": self.rationale,
            "timestamp": self.timestamp
        }


class SignificanceEngine:
    def __init__(self, episode_threshold: float = 0.50):
        self.episode_threshold = episode_threshold
        self._history: List[SignificanceAssessment] = []

    def evaluate_signal(self, signal: SignificanceSignal) -> SignificanceAssessment:
        score = signal.significance_score
        sig_id = f"eval_{uuid.uuid4().hex[:8]}"

        # Classify output
        desc_lower = signal.description.lower()
        if "gap" in desc_lower or "missing" in desc_lower:
            decision = SignificanceOutput.CAPABILITY_GAP
        elif "drift" in desc_lower or "deviation" in desc_lower:
            decision = SignificanceOutput.OBJECTIVE_DRIFT
        elif "risk" in desc_lower or signal.risk > 0.6:
            decision = SignificanceOutput.RISK
        elif "surplus" in desc_lower or "opportunity" in desc_lower:
            decision = SignificanceOutput.OPPORTUNITY
        elif "unknown" in desc_lower or signal.uncertainty > 0.75:
            decision = SignificanceOutput.UNKNOWN
        elif signal.importance > 0.6 or "anomaly" in desc_lower or "failure" in desc_lower:
            decision = SignificanceOutput.PROBLEM
        elif score > 0.20:
            decision = SignificanceOutput.MONITOR
        else:
            decision = SignificanceOutput.IGNORE

        requires_episode = (decision in (
            SignificanceOutput.PROBLEM,
            SignificanceOutput.OPPORTUNITY,
            SignificanceOutput.CAPABILITY_GAP,
            SignificanceOutput.UNKNOWN,
            SignificanceOutput.OBJECTIVE_DRIFT
        )) and (signal.importance >= 0.35)

        rationale = f"Evaluated signal from '{signal.source}' with composite score {score:.2f} -> {decision.value}."

        assessment = SignificanceAssessment(
            assessment_id=sig_id,
            decision=decision,
            significance_score=score,
            trigger_signal=signal,
            requires_cognitive_episode=requires_episode,
            rationale=rationale
        )
        self._history.append(assessment)
        return assessment

    def get_recent_assessments(self, limit: int = 20) -> List[SignificanceAssessment]:
        return self._history[-limit:]
