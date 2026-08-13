"""
Cross-Domain Strategy & Pattern Transfer Evaluation Engine
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class TransferEvaluationResult:
    id: str = field(default_factory=lambda: f"trans_{uuid.uuid4().hex[:8]}")
    strategy_name: str = ""
    source_domain: str = "python"
    target_domain: str = "linux"
    source_performance: float = 0.95
    target_performance: float = 0.90
    transfer_efficiency: float = 0.947  # target / source
    is_valid_transfer: bool = True
    tested_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "strategy_name": self.strategy_name,
            "source_domain": self.source_domain,
            "target_domain": self.target_domain,
            "source_performance": round(self.source_performance, 4),
            "target_performance": round(self.target_performance, 4),
            "transfer_efficiency": round(self.transfer_efficiency, 4),
            "is_valid_transfer": self.is_valid_transfer,
            "tested_at": self.tested_at
        }


class TransferEngine:
    def __init__(self, min_transfer_threshold: float = 0.75):
        self.min_transfer_threshold = min_transfer_threshold
        self._history: List[TransferEvaluationResult] = []

    def evaluate_strategy_transfer(
        self,
        strategy_name: str,
        source_domain: str,
        target_domain: str,
        source_score: float,
        target_score: float
    ) -> TransferEvaluationResult:
        """
        Tests whether a procedural/cognitive strategy generalizes to a different target domain.
        Transfer Efficiency = target_score / max(1e-5, source_score)
        """
        efficiency = min(1.5, target_score / max(0.01, source_score))
        is_valid = target_score >= 0.70 and efficiency >= self.min_transfer_threshold

        res = TransferEvaluationResult(
            strategy_name=strategy_name,
            source_domain=source_domain,
            target_domain=target_domain,
            source_performance=source_score,
            target_performance=target_score,
            transfer_efficiency=efficiency,
            is_valid_transfer=is_valid
        )
        self._history.append(res)
        return res

    def get_transfer_matrix(self) -> Dict[str, Dict[str, float]]:
        matrix: Dict[str, Dict[str, float]] = {}
        for r in self._history:
            if r.source_domain not in matrix:
                matrix[r.source_domain] = {}
            matrix[r.source_domain][r.target_domain] = r.transfer_efficiency
        return matrix
