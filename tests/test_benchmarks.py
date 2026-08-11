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
        sb = DevelopmentalScoreboard()
        snap = sb.capture_snapshot()
        text = sb.render_summary_text(snap)
        self.assertIn("ZERION-X ASCENDANT DEVELOPMENTAL SCOREBOARD", text)
        self.assertIn("Effective Intelligence", text)


if __name__ == "__main__":
    unittest.main()
