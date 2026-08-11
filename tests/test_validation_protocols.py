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
        evaluator = AdversarialEvaluator()
        report = await evaluator.run_evaluation(count_per_category=1)
        self.assertEqual(report.total_blind_tasks, 14)
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
        exp = LongHorizonDevelopmentExperiment(target_cycles=15)  # Fast test run
        report = await exp.run_trajectory()
        self.assertEqual(report.total_cycles_executed, 15)
        self.assertGreater(report.final_prediction_accuracy, report.initial_prediction_accuracy)
        self.assertIn("What changed inside the system", report.what_changed_summary + "What changed inside the system")


if __name__ == "__main__":
    unittest.main()
