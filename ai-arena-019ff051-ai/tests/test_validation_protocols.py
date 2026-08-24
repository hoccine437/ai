"""
Automated Test Suite for Genesis Validation Protocols
Verifies Adversarial Evaluator, A/B Experiment, Ablation Matrix, and Long Horizon Trajectory.
"""

import unittest
from zerion.benchmarks.adversarial_evaluator import AdversarialEvaluator
from zerion.experiments.developmental_ab_test import DevelopmentalABExperiment
from zerion.experiments.ablation_study import AblationStudyRunner
from zerion.experiments.long_horizon_100 import LongHorizonDevelopmentExperiment


class TestGenesisValidationProtocols(unittest.IsolatedAsyncioTestCase):
    async def test_adversarial_evaluator_against_real_baselines(self):
        """The comparative evaluation is honest: Full ASCENDANT is only scored
        on categories with a real executable harness (MEASURED, 0.0/1.0 from
        actual sandbox pass/fail); every other category is NOT_MEASURED. The
        comparison is restricted to that measured subset, so heuristic scores
        for unwired categories never contaminate the ratios."""
        evaluator = AdversarialEvaluator()
        report = await evaluator.run_evaluation(count_per_category=1)
        self.assertEqual(report.total_blind_tasks, 14)

        full = report.comparative_scores["FullAscendant"]
        # Only the 3 executable categories are measured for Full ASCENDANT.
        self.assertEqual(full.measured_tasks, 3)
        self.assertEqual(sorted(full.score_by_category.keys()),
                         ["coding", "debugging", "tool_use"])
        # Measured scores are REAL pass/fail (0.0 or 1.0) — never 0.96/0.94.
        for v in full.score_by_category.values():
            self.assertIn(v, (0.0, 1.0))
        # Baselines are summarized over the same measured subset.
        self.assertEqual(report.comparative_scores["ScriptedBaseline"].measured_tasks, 3)
        # Ratios and learning contribution exist only when both sides measured.
        self.assertGreater(report.improvement_ratio_vs_scripted, 1.5)
        self.assertGreater(report.improvement_ratio_vs_react, 1.1)
        self.assertGreater(report.learning_contribution_score, 0.0)

    async def test_developmental_ab_experiment(self):
        exp = DevelopmentalABExperiment()
        report = await exp.run_experiment()
        self.assertGreater(report.seen_tasks_score_a, report.seen_tasks_score_b)
        self.assertGreater(report.similar_unseen_tasks_score_a, report.similar_unseen_tasks_score_b)
        self.assertGreater(report.strategy_reuse_count_a, 0)
        self.assertEqual(report.strategy_reuse_count_b, 0)

    async def test_ablation_matrix(self):
        runner = AblationStudyRunner()
        report = await runner.run_ablation_matrix()
        self.assertEqual(len(report.ablation_results), 8)
        self.assertGreater(len(report.most_critical_component), 0)
        self.assertIn("World Model", report.most_critical_component)

    async def test_long_horizon_trajectory(self):
        """The trajectory executes real cycles and reports MEASURED (or
        NOT_MEASURED) values — the synthetic curve formulas (97%/0.0200/2.0x)
        are gone. Prediction accuracy is None until the calibration pipeline
        records real predictions, and no fabricated gain is claimed."""
        exp = LongHorizonDevelopmentExperiment(target_cycles=15)  # Fast test run
        report = await exp.run_trajectory()
        self.assertEqual(report.total_cycles_executed, 15)
        # Snapshots at cycle 1, 10 and 15.
        self.assertEqual([s.cycle_index for s in report.cycle_snapshots],
                         [1, 10, 15])
        for s in report.cycle_snapshots:
            # Honest values: measured floats in [0,1] or explicit None.
            self.assertTrue(s.prediction_accuracy is None
                            or 0.0 <= s.prediction_accuracy <= 1.0)
            self.assertTrue(s.brier_score is None or 0.0 <= s.brier_score <= 1.0)
            self.assertIsNone(s.discovery_rate)
            self.assertIsNone(s.resource_efficiency)
        # Real cycle execution grew real capability/store state.
        self.assertGreaterEqual(report.final_capabilities,
                                report.initial_capabilities)
        # No fabricated synthetic constants anywhere in the summary.
        self.assertNotIn("97.0%", report.what_changed_summary)
        self.assertNotIn("0.0200", report.what_changed_summary)
        self.assertIn("NOT MEASURED", report.what_changed_summary)
        # With only 15 cycles no capability birth happens -> no claimed gain.
        self.assertIsNone(report.second_order_learning_gain)


if __name__ == "__main__":
    unittest.main()
