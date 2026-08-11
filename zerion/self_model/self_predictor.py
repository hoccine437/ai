"""
Predictive Self-Model & Introspection Substrate
Maintains live empirical self-calibration, forecasts task execution parameters,
and computes self-prediction errors to eliminate cognitive overconfidence.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional


@dataclass
class SelfTaskPrediction:
    task_id: str
    predicted_strategy: str
    predicted_success_prob: float
    predicted_latency_ms: float
    predicted_failure_mode: Optional[str]
    predicted_compute_cost: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class SelfCalibrationDelta:
    task_id: str
    probability_error: float
    latency_error_ms: float
    strategy_matched: bool
    brier_penalty: float
    recalibrated_confidence: float


class SelfPredictor:
    def __init__(self):
        self._prediction_history: List[SelfTaskPrediction] = []
        self._calibration_deltas: List[SelfCalibrationDelta] = []

    def predict_task_execution(
        self,
        task_id: str,
        task_domain: str,
        task_difficulty: float = 0.5,
        historical_strategy_reliability: float = 0.90
    ) -> SelfTaskPrediction:
        """Forecasts self-performance prior to task deliberation."""
        prob = max(0.20, min(0.98, historical_strategy_reliability - (task_difficulty * 0.15)))
        latency = 12.0 if task_difficulty < 0.4 else (45.0 if task_difficulty < 0.7 else 180.0)
        failure_mode = "timeout_risk" if task_difficulty > 0.8 else None
        
        pred = SelfTaskPrediction(
            task_id=task_id,
            predicted_strategy=f"strategy_{task_domain}",
            predicted_success_prob=round(prob, 3),
            predicted_latency_ms=latency,
            predicted_failure_mode=failure_mode,
            predicted_compute_cost=0.01 * (latency / 10.0)
        )
        self._prediction_history.append(pred)
        return pred

    def record_actual_outcome(
        self,
        prediction: SelfTaskPrediction,
        actual_strategy: str,
        actual_success: bool,
        actual_latency_ms: float
    ) -> SelfCalibrationDelta:
        actual_binary = 1.0 if actual_success else 0.0
        prob_err = abs(prediction.predicted_success_prob - actual_binary)
        lat_err = abs(prediction.predicted_latency_ms - actual_latency_ms)
        penalty = (prediction.predicted_success_prob - actual_binary) ** 2
        recal_conf = round(max(0.20, min(0.99, prediction.predicted_success_prob * (1.0 - prob_err * 0.2))), 3)

        delta = SelfCalibrationDelta(
            task_id=prediction.task_id,
            probability_error=round(prob_err, 4),
            latency_error_ms=round(lat_err, 2),
            strategy_matched=(actual_strategy == prediction.predicted_strategy),
            brier_penalty=round(penalty, 4),
            recalibrated_confidence=recal_conf
        )
        self._calibration_deltas.append(delta)
        return delta
