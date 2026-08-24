"""
Confidence Calibration and Brier Score Tracker
"""

from dataclasses import dataclass, field
import math
import time
from typing import Any, Dict, List, Optional


@dataclass
class CalibrationSample:
    prediction_id: str
    stated_confidence: float  # 0.0 to 1.0
    actual_outcome: bool      # True for success/correct, False for failure
    timestamp: float = field(default_factory=time.time)


class ConfidenceCalibrator:
    def __init__(self):
        self._samples: List[CalibrationSample] = []

    def record_prediction(self, prediction_id: str, stated_confidence: float, actual_outcome: bool):
        self._samples.append(CalibrationSample(
            prediction_id=prediction_id,
            stated_confidence=max(0.0, min(1.0, stated_confidence)),
            actual_outcome=actual_outcome,
            timestamp=time.time()
        ))

    def calculate_brier_score(self) -> Optional[float]:
        """
        Brier Score: Mean squared difference between stated confidence and binary outcome.
        0.0 = perfect calibration, 1.0 = completely inverted.

        Honesty contract (INV-001): with ZERO recorded predictions the score
        is ``None`` (NOT_MEASURED) — not a vacuous 0.0. A "perfect" 0.0 with
        no samples would fabricate calibration (and previously inflated
        cognitive maturity to L7).
        """
        if not self._samples:
            return None
        total_sq_err = sum(
            (s.stated_confidence - (1.0 if s.actual_outcome else 0.0)) ** 2
            for s in self._samples
        )
        return round(total_sq_err / len(self._samples), 4)

    def get_calibration_curve(self, num_bins: int = 5) -> List[Dict[str, Any]]:
        """Generates reliability diagram bins."""
        if not self._samples:
            return []
        bins = []
        bin_width = 1.0 / num_bins
        for i in range(num_bins):
            bin_min = i * bin_width
            bin_max = (i + 1) * bin_width
            bin_samples = [
                s for s in self._samples
                if (bin_min <= s.stated_confidence < bin_max) or (i == num_bins - 1 and s.stated_confidence == 1.0)
            ]
            if bin_samples:
                avg_conf = sum(s.stated_confidence for s in bin_samples) / len(bin_samples)
                accuracy = sum(1.0 for s in bin_samples if s.actual_outcome) / len(bin_samples)
                bins.append({
                    "bin_range": f"{bin_min:.1f}-{bin_max:.1f}",
                    "count": len(bin_samples),
                    "mean_confidence": round(avg_conf, 3),
                    "empirical_accuracy": round(accuracy, 3),
                    "calibration_gap": round(abs(avg_conf - accuracy), 3)
                })
        return bins
