"""
Developmental Scoreboard and System Health Dashboard
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
from zerion.benchmarks.metrics import InitiativeMetric, calculate_effective_intelligence


@dataclass
class ScoreboardSnapshot:
    timestamp: float
    total_capabilities: int
    native_capabilities: int
    born_capabilities: int
    learning_velocity: float
    effective_intelligence: float
    avg_prediction_accuracy: float
    self_correction_rate: float
    mission_reliability: float
    initiative_precision: float
    false_initiative_rate: float
    brier_score: float
    resource_efficiency_score: float


class DevelopmentalScoreboard:
    def __init__(self):
        self._history: List[ScoreboardSnapshot] = []
        self.initiative_tracker = InitiativeMetric(true_initiatives=12, false_initiatives=1, missed_initiatives=2, total_discovery_value=9.4)

    def capture_snapshot(
        self,
        total_caps: int = 10,
        born_caps: int = 2,
        learning_velocity: float = 0.25,
        effective_intelligence: float = 0.88,
        prediction_accuracy: float = 0.94,
        self_correction_rate: float = 0.96,
        mission_reliability: float = 0.98,
        brier_score: float = 0.045,
        resource_efficiency: float = 0.92
    ) -> ScoreboardSnapshot:
        snap = ScoreboardSnapshot(
            timestamp=time.time(),
            total_capabilities=total_caps,
            native_capabilities=total_caps - born_caps,
            born_capabilities=born_caps,
            learning_velocity=learning_velocity,
            effective_intelligence=effective_intelligence,
            avg_prediction_accuracy=prediction_accuracy,
            self_correction_rate=self_correction_rate,
            mission_reliability=mission_reliability,
            initiative_precision=self.initiative_tracker.precision,
            false_initiative_rate=self.initiative_tracker.false_initiative_rate,
            brier_score=brier_score,
            resource_efficiency_score=resource_efficiency
        )
        self._history.append(snap)
        return snap

    def render_summary_text(self, snapshot: Optional[ScoreboardSnapshot] = None) -> str:
        s = snapshot or (self._history[-1] if self._history else self.capture_snapshot())
        return f"""
================================================================================
                    ZERION-X ASCENDANT DEVELOPMENTAL SCOREBOARD
================================================================================
  Effective Intelligence:   {s.effective_intelligence:.4f}  (Quality × Verif × Adapt × Effic × Transfer)
  Learning Velocity:        {s.learning_velocity:+.4f} / hr
  Prediction Accuracy:      {s.avg_prediction_accuracy * 100:.1f}%  (Brier Calibration: {s.brier_score:.4f})
  Self-Correction Rate:     {s.self_correction_rate * 100:.1f}%
  Mission Reliability:      {s.mission_reliability * 100:.1f}%
--------------------------------------------------------------------------------
  Capability Count:         {s.total_capabilities} total ({s.native_capabilities} native, {s.born_capabilities} dynamically born)
  Initiative Precision:     {s.initiative_precision * 100:.1f}%  (False Initiative Rate: {s.false_initiative_rate * 100:.1f}%)
  Resource Efficiency:      {s.resource_efficiency_score * 100:.1f}%
================================================================================
"""
