"""
Unit tests for Benchmarks, Metrics, and Scoreboard
"""

import unittest
from zerion.benchmarks.metrics import (
    calculate_effective_intelligence,
    calculate_improvement_ratio,
    calculate_learning_velocity,
    InitiativeMetric
)
from zerion.benchmarks.suite import build_default_benchmark_suite
from zerion.benchmarks.runner import BenchmarkRunner
from zerion.benchmarks.scoreboard import DevelopmentalScoreboard


class TestBenchmarks(unittest.IsolatedAsyncioTestCase):
    def test_metrics_calculations(self):
        # Effective Intelligence Composite
        eff = calculate_effective_intelligence(
            quality=0.95,
            verification=0.98,
            adaptability=0.90,
            efficiency=0.92,
            transfer=0.88
        )
        self.assertAlmostEqual(eff, 0.6784, places=2)

        # Improvement Ratio
        ratio = calculate_improvement_ratio(ascendant_score=0.95, baseline_score=0.19)
        self.assertEqual(ratio, 5.0)

        # Initiative Metric
        im = InitiativeMetric(true_initiatives=8, false_initiatives=2, missed_initiatives=1, total_discovery_value=7.5)
        self.assertEqual(im.precision, 0.8)
        self.assertEqual(im.false_initiative_rate, 0.2)

    async def test_14_category_benchmark_run(self):
        suite = build_default_benchmark_suite()
        self.assertEqual(len(suite), 14)

        runner = BenchmarkRunner(tasks=suite)
        report = await runner.run_all()
        self.assertEqual(report.total_tasks, 14)
        self.assertGreater(report.composite_improvement_ratio, 1.0)
        self.assertGreater(report.effective_intelligence_score, 0.0)

    def test_scoreboard_rendering(self):
        # Regression test for the ZERION correction phase: the scoreboard must be
        # built from a real RuntimeEvidence snapshot, and must never silently
        # fabricate a default snapshot. See test_scoreboard_does_not_report_default_metrics_as_observed
        # in test_evidence_integrity.py for the provenance-specific assertions.
        from zerion.runtime.evidence import RuntimeEvidence
        sb = DevelopmentalScoreboard()
        evidence = RuntimeEvidence(
            episodes_count=1, procedural_rules_count=0, born_capabilities_count=2,
            total_capabilities_count=10, synthesized_strategies_count=3,
            active_objectives_count=0, flywheel_cycles=1, brier_score=0.04,
            learning_acceleration=None, has_native_caps=True,
            has_adaptive_phenotypes=True, has_pressure_field=True,
        )
        snap = sb.capture_snapshot_from_evidence(evidence, cycles_run=1)
        text = sb.render_summary_text(snap)
        self.assertIn("ZERION-X ASCENDANT DEVELOPMENTAL SCOREBOARD", text)
        self.assertIn("Effective Intelligence", text)
        # Metrics with no real measurement pipeline must say so, not show a fake number.
        self.assertIn("UNAVAILABLE", text)

    def test_scoreboard_has_no_default_snapshot(self):
        """A fresh scoreboard must not fabricate a snapshot before any real capture."""
        sb = DevelopmentalScoreboard()
        text = sb.render_summary_text()
        self.assertIn("No snapshot captured yet", text)


if __name__ == "__main__":
    unittest.main()
