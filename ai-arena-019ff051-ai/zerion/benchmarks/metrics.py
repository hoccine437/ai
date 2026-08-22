"""
Scientific Metrics Engine for Developmental Intelligence
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class InitiativeMetric:
    true_initiatives: int = 0
    false_initiatives: int = 0
    missed_initiatives: int = 0
    total_discovery_value: float = 0.0

    @property
    def precision(self) -> float:
        total = self.true_initiatives + self.false_initiatives
        return round(self.true_initiatives / total, 4) if total > 0 else 0.0

    @property
    def recall(self) -> float:
        total = self.true_initiatives + self.missed_initiatives
        return round(self.true_initiatives / total, 4) if total > 0 else 0.0

    @property
    def false_initiative_rate(self) -> float:
        total = self.true_initiatives + self.false_initiatives
        return round(self.false_initiatives / total, 4) if total > 0 else 0.0

    @property
    def avg_discovery_value(self) -> float:
        return round(self.total_discovery_value / self.true_initiatives, 4) if self.true_initiatives > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "true_initiatives": self.true_initiatives,
            "false_initiatives": self.false_initiatives,
            "missed_initiatives": self.missed_initiatives,
            "precision": self.precision,
            "recall": self.recall,
            "false_initiative_rate": self.false_initiative_rate,
            "avg_discovery_value": self.avg_discovery_value
        }


def calculate_effective_intelligence(
    quality: float,
    verification: float,
    adaptability: float,
    efficiency: float,
    transfer: float
) -> float:
    """
    Composite Intelligence Score = Quality * Verification * Adaptability * Efficiency * Transfer
    All parameters normalized to [0.0, 1.0]. Output in [0.0, 1.0].
    """
    q = max(0.0, min(1.0, quality))
    v = max(0.0, min(1.0, verification))
    a = max(0.0, min(1.0, adaptability))
    e = max(0.0, min(1.0, efficiency))
    t = max(0.0, min(1.0, transfer))
    return round(q * v * a * e * t, 4)


def calculate_learning_velocity(score_before: float, score_after: float, time_delta_hours: float = 1.0) -> float:
    """
    Learning Velocity = (performance_after - performance_before) / max(0.1, time_delta_hours)
    """
    delta = score_after - score_before
    return round(delta / max(0.1, time_delta_hours), 4)


def calculate_improvement_ratio(ascendant_score: float, baseline_score: float) -> float:
    """
    Improvement Ratio = ascendant_score / baseline_score
    Target: >= 5.0x
    """
    base = max(0.001, baseline_score)
    return round(ascendant_score / base, 3)
