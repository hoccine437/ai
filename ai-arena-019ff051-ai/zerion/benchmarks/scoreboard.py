"""
Developmental Scoreboard and System Health Dashboard

Every reported metric carries explicit provenance (see zerion.runtime.evidence.Metric).
Metrics that cannot currently be measured from live engine state are reported as
UNAVAILABLE rather than filled in with a plausible-looking default. Previously this
module unconditionally fabricated values (effective_intelligence=0.88, prediction
accuracy=94%, etc. as constructor defaults that were never overridden by any caller).
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
from zerion.benchmarks.metrics import InitiativeMetric, calculate_effective_intelligence
from zerion.runtime.evidence import Metric, MeasurementStatus


@dataclass
class ScoreboardSnapshot:
    timestamp: float
    total_capabilities: Metric
    native_capabilities: Metric
    born_capabilities: Metric
    learning_velocity: Metric
    effective_intelligence: Metric
    avg_prediction_accuracy: Metric
    self_correction_rate: Metric
    mission_reliability: Metric
    initiative_precision: Metric
    false_initiative_rate: Metric
    brier_score: Metric
    resource_efficiency_score: Metric

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_capabilities": self.total_capabilities.to_dict(),
            "native_capabilities": self.native_capabilities.to_dict(),
            "born_capabilities": self.born_capabilities.to_dict(),
            "learning_velocity": self.learning_velocity.to_dict(),
            "effective_intelligence": self.effective_intelligence.to_dict(),
            "avg_prediction_accuracy": self.avg_prediction_accuracy.to_dict(),
            "self_correction_rate": self.self_correction_rate.to_dict(),
            "mission_reliability": self.mission_reliability.to_dict(),
            "initiative_precision": self.initiative_precision.to_dict(),
            "false_initiative_rate": self.false_initiative_rate.to_dict(),
            "brier_score": self.brier_score.to_dict(),
            "resource_efficiency_score": self.resource_efficiency_score.to_dict(),
        }


class DevelopmentalScoreboard:
    def __init__(self):
        self._history: List[ScoreboardSnapshot] = []
        # NOTE: this tracker's own seed numbers (12/1/2/9.4) are themselves configured
        # defaults, not observed initiative outcomes. Surfaced as CONFIGURED_DEFAULT below
        # rather than silently presented as measured precision.
        self.initiative_tracker = InitiativeMetric(true_initiatives=12, false_initiatives=1, missed_initiatives=2, total_discovery_value=9.4)
        self._initiative_tracker_is_seeded = True

    def capture_snapshot_from_evidence(self, evidence: "Any", cycles_run: int) -> ScoreboardSnapshot:
        """
        Builds a scoreboard snapshot strictly from measured RuntimeEvidence.
        Metrics with no real measurement pathway yet are UNAVAILABLE, not guessed.
        """
        total_caps = evidence.total_capabilities_count
        born_caps = evidence.born_capabilities_count

        cap_metric = Metric(
            name="total_capabilities", value=float(total_caps),
            status=MeasurementStatus.OBSERVED, sample_count=1,
            evidence=["engine.self_model._capabilities length"],
        )
        native_metric = Metric(
            name="native_capabilities", value=float(total_caps - born_caps),
            status=MeasurementStatus.CALCULATED_FROM_OBSERVED_DATA, sample_count=1,
            evidence=["total_capabilities - born_capabilities"],
        )
        born_metric = Metric(
            name="born_capabilities", value=float(born_caps),
            status=MeasurementStatus.OBSERVED, sample_count=1,
            evidence=["engine.capability_registry.list_born_capabilities() length"],
        )

        if evidence.learning_acceleration is not None and cycles_run > 1:
            velocity = Metric(
                name="learning_velocity", value=evidence.learning_acceleration,
                status=MeasurementStatus.CALCULATED_FROM_OBSERVED_DATA, sample_count=cycles_run,
                evidence=["learning_to_learn.calculate_learning_acceleration()"],
            )
        else:
            velocity = Metric.unavailable("learning_velocity", "requires >1 completed cycle")

        # Effective intelligence, prediction accuracy, self-correction rate, and mission
        # reliability have no real measurement pipeline in the current codebase (no
        # ground-truth task benchmark, no calibration corpus). Reporting UNAVAILABLE
        # rather than a hard-coded plausible number.
        eff_intel = Metric.unavailable("effective_intelligence", "no benchmark pipeline wired to real task outcomes yet")
        pred_acc = Metric.unavailable("avg_prediction_accuracy", "no calibration corpus with resolved outcomes yet")
        self_corr = Metric.unavailable("self_correction_rate", "not yet instrumented")
        mission_rel = Metric.unavailable("mission_reliability", "not yet instrumented")

        if evidence.brier_score is not None:
            brier = Metric(
                name="brier_score", value=evidence.brier_score,
                status=MeasurementStatus.CALCULATED_FROM_OBSERVED_DATA,
                sample_count=max(1, evidence.brier_samples),
                evidence=["self_model.calibrator.calculate_brier_score() "
                          f"over {evidence.brier_samples} recorded predictions"],
            )
        else:
            brier = Metric.unavailable("brier_score", "calibrator has no recorded predictions yet")

        if self._initiative_tracker_is_seeded:
            init_prec = Metric(
                name="initiative_precision", value=self.initiative_tracker.precision,
                status=MeasurementStatus.CONFIGURED_DEFAULT, sample_count=0,
                evidence=["InitiativeMetric constructed with seed/example counts, not observed initiatives"],
            )
            false_init = Metric(
                name="false_initiative_rate", value=self.initiative_tracker.false_initiative_rate,
                status=MeasurementStatus.CONFIGURED_DEFAULT, sample_count=0,
                evidence=["InitiativeMetric constructed with seed/example counts, not observed initiatives"],
            )
        else:
            init_prec = Metric.unavailable("initiative_precision")
            false_init = Metric.unavailable("false_initiative_rate")

        resource_eff = Metric.unavailable("resource_efficiency_score", "not yet instrumented")

        snap = ScoreboardSnapshot(
            timestamp=time.time(),
            total_capabilities=cap_metric,
            native_capabilities=native_metric,
            born_capabilities=born_metric,
            learning_velocity=velocity,
            effective_intelligence=eff_intel,
            avg_prediction_accuracy=pred_acc,
            self_correction_rate=self_corr,
            mission_reliability=mission_rel,
            initiative_precision=init_prec,
            false_initiative_rate=false_init,
            brier_score=brier,
            resource_efficiency_score=resource_eff,
        )
        self._history.append(snap)
        return snap

    @staticmethod
    def _fmt(m: Metric, as_pct: bool = False, decimals: int = 4) -> str:
        if m.status == MeasurementStatus.UNAVAILABLE or m.value is None:
            return f"UNAVAILABLE ({m.evidence[0] if m.evidence else 'not measured'})"
        val = m.value * 100 if as_pct else m.value
        suffix = "%" if as_pct else ""
        tag = "" if m.status == MeasurementStatus.OBSERVED else f" [{m.status.value}]"
        return f"{val:.{1 if as_pct else decimals}f}{suffix}{tag}"

    def render_summary_text(self, snapshot: Optional[ScoreboardSnapshot] = None) -> str:
        if snapshot is None:
            if not self._history:
                return (
                    "\n=== ZERION-X ASCENDANT DEVELOPMENTAL SCOREBOARD ===\n"
                    "No snapshot captured yet. Run capture_snapshot_from_evidence() with a\n"
                    "live RuntimeEvidence object -- this scoreboard no longer fabricates a\n"
                    "default snapshot on first render.\n"
                )
            snapshot = self._history[-1]
        s = snapshot
        return f"""
================================================================================
                    ZERION-X ASCENDANT DEVELOPMENTAL SCOREBOARD
================================================================================
  Effective Intelligence:   {self._fmt(s.effective_intelligence)}
  Learning Velocity:        {self._fmt(s.learning_velocity)}
  Prediction Accuracy:      {self._fmt(s.avg_prediction_accuracy, as_pct=True)}  (Brier: {self._fmt(s.brier_score)})
  Self-Correction Rate:     {self._fmt(s.self_correction_rate, as_pct=True)}
  Mission Reliability:      {self._fmt(s.mission_reliability, as_pct=True)}
--------------------------------------------------------------------------------
  Capability Count:         {int(s.total_capabilities.value)} total ({int(s.native_capabilities.value)} native, {int(s.born_capabilities.value)} dynamically born)
  Initiative Precision:     {self._fmt(s.initiative_precision, as_pct=True)}  (False Initiative Rate: {self._fmt(s.false_initiative_rate, as_pct=True)})
  Resource Efficiency:      {self._fmt(s.resource_efficiency_score, as_pct=True)}
================================================================================
  Tags in brackets mark non-observed values (CONFIGURED_DEFAULT = seed data, not
  measured behavior). UNAVAILABLE means no measurement pipeline exists yet for that
  metric -- this is reported honestly rather than replaced with a plausible number.
================================================================================
"""
