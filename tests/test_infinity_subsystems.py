"""
Unit tests for ASCENDANT ∞ Advanced Subsystems:
- Cognitive Genome (22 Dimensions & Mutation Guardrails)
- Cognitive Phenotypes
- Cognitive Genesis (Strategy Synthesis Pipeline)
- Adaptive Cognition Scaling Controller
- Meta-Prediction & Calibration Engine
- Learning-to-Learn (2nd & 3rd Order Meta-Learning)
- Strategy Evolution & Lineage
- Self-Experimentation Engine
- Cognitive Maturity Evaluator (L0-L7)
- 7-Level Cognitive Hierarchy Queries
"""

import os
import shutil
import tempfile
import unittest

from zerion.cognitive_genome.genome import CognitiveGenome, GenomeMutationProposal
from zerion.cognitive_genome.phenotype import PhenotypeFactory, CognitivePhenotype
from zerion.cognitive_genome.manager import GenomeManager

from zerion.cognitive_genesis.strategy import CognitiveStrategy
from zerion.cognitive_genesis.genesis_pipeline import CognitiveGenesisPipeline
from zerion.cognitive_genesis.registry import StrategyRegistry

from zerion.adaptive_cognition.controller import AdaptiveCognitiveController
from zerion.meta_prediction.engine import MetaPredictionEngine
from zerion.learning_to_learn.engine import LearningToLearnEngine
from zerion.strategy_evolution.evolution_engine import StrategyEvolutionEngine
from zerion.self_experimentation.engine import SelfExperimentationEngine
from zerion.self_model.maturity import CognitiveMaturityEvaluator, MaturityLevel
from zerion.engine import AscendantEngine


class TestInfinitySubsystems(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="inf_tests_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cognitive_genome_dimensions_and_mutation(self):
        genome = CognitiveGenome()
        valid, err = genome.validate_bounds()
        self.assertTrue(valid)
        self.assertEqual(genome.version, 1)

        # Propose mutation
        prop = GenomeMutationProposal(
            target_dimension="reasoning_depth",
            previous_value=3,
            proposed_value=5,
            hypothesis="Higher reasoning depth improves mathematical deduction"
        )
        mutated = genome.apply_mutation(prop)
        self.assertTrue(mutated)
        self.assertEqual(genome.version, 2)
        self.assertEqual(genome.reasoning_depth, 5)

        # Out of bounds mutation should be rejected
        bad_prop = GenomeMutationProposal(
            target_dimension="reasoning_depth",
            previous_value=5,
            proposed_value=999,
            hypothesis="Unbounded depth"
        )
        bad_mut = genome.apply_mutation(bad_prop)
        self.assertFalse(bad_mut)
        self.assertEqual(genome.reasoning_depth, 5)

    def test_phenotype_factory_derivation(self):
        genome = CognitiveGenome()
        coding_ph = PhenotypeFactory.derive_phenotype(genome, "coding")
        self.assertEqual(coding_ph.name, "CodingPhenotype")
        self.assertGreaterEqual(coding_ph.verification_ratio, 0.85)

        security_ph = PhenotypeFactory.derive_phenotype(genome, "security")
        self.assertEqual(security_ph.name, "SecurityPhenotype")
        self.assertEqual(security_ph.risk_tolerance, 0.01)

    async def test_cognitive_genesis_strategy_synthesis(self):
        pipeline = CognitiveGenesisPipeline()
        res = await pipeline.synthesize_strategy(
            problem_description="Distributed deadlock resolution",
            domain="distributed_systems"
        )
        self.assertTrue(res.success)
        self.assertIsNotNone(res.strategy)
        self.assertEqual(len(res.stages_log), 8)
        self.assertEqual(res.strategy.domain, "distributed_systems")

    def test_adaptive_cognition_controller(self):
        controller = AdaptiveCognitiveController()
        # Reflex task
        alloc_reflex = controller.allocate_cognition(
            task_id="t1", uncertainty=0.1, difficulty=0.1, novelty=0.1, risk=0.1
        )
        self.assertEqual(alloc_reflex.selected_mode, "REFLEX")
        self.assertEqual(alloc_reflex.parallel_paths, 1)

        # Experimental task
        alloc_exp = controller.allocate_cognition(
            task_id="t2", uncertainty=0.9, difficulty=0.8, novelty=0.85, risk=0.5
        )
        self.assertEqual(alloc_exp.selected_mode, "EXPERIMENTAL")
        self.assertTrue(alloc_exp.enable_sandbox_experiment)

    def test_meta_prediction_and_calibration(self):
        meta = MetaPredictionEngine(db_path=os.path.join(self.temp_dir, "meta.db"))
        pred = meta.generate_pre_prediction("task_101", "database", uncertainty=0.3, difficulty=0.4)
        self.assertGreater(pred.predicted_success_probability, 0.5)

        cal = meta.record_post_execution_feedback(
            prediction_id=pred.prediction_id,
            actual_strategy="strategy_database",
            actual_success=True,
            actual_latency_ms=12.5
        )
        self.assertIsNotNone(cal)
        self.assertLess(cal.calibration_penalty, 0.1)

    def test_learning_to_learn_acceleration(self):
        l2l = LearningToLearnEngine(db_path=os.path.join(self.temp_dir, "l2l.db"))
        # Early acquisitions took 10 episodes
        l2l.record_acquisition("skill_a", episodes_required=10, duration_s=20.0)
        l2l.record_acquisition("skill_b", episodes_required=8, duration_s=16.0)
        # Recent acquisitions took 4 episodes
        l2l.record_acquisition("skill_c", episodes_required=4, duration_s=8.0)
        l2l.record_acquisition("skill_d", episodes_required=3, duration_s=6.0)

        acc = l2l.calculate_learning_acceleration()
        self.assertGreaterEqual(acc, 2.0)

        bottleneck = l2l.analyze_learning_bottleneck()
        self.assertIn("bottleneck", bottleneck)

    def test_strategy_evolution_and_composition(self):
        evo = StrategyEvolutionEngine(db_path=os.path.join(self.temp_dir, "strat_evo.db"))
        s1 = CognitiveStrategy(name="StratA", domain="db", procedure_steps=["step 1"])
        s2 = CognitiveStrategy(name="StratB", domain="cache", procedure_steps=["step 2"])

        composed = evo.compose_strategies(s1, s2, "CompositeDbCache")
        self.assertEqual(len(composed.procedure_steps), 2)
        self.assertIn(composed.strategy_id, evo._lineage)

    async def test_self_experimentation_engine(self):
        self_exp = SelfExperimentationEngine(db_path=os.path.join(self.temp_dir, "self_exp.db"))
        report = await self_exp.run_architecture_experiment(
            hypothesis="Increasing verification improves coding success",
            target_dimension="verification_ratio",
            control_val=0.80,
            treatment_val=0.95,
            target_phenotype="CodingPhenotype"
        )
        self.assertEqual(report.decision, "ACCEPTED_FOR_PHENOTYPE")
        self.assertGreater(report.effect_size, 0.0)

    def test_cognitive_maturity_levels(self):
        evaluator = CognitiveMaturityEvaluator()
        assessment = evaluator.evaluate(
            has_native_caps=True,
            episodes_count=10,
            procedural_rules_count=5,
            has_adaptive_phenotypes=True,
            has_pressure_field=True,
            brier_score=0.04,
            born_capabilities_count=2,
            synthesized_strategies_count=3,
            learning_acceleration=1.8,
            flywheel_cycles=15
        )
        self.assertEqual(assessment.current_level, MaturityLevel.L7_COGNITIVE_GENERATIVE)
        self.assertEqual(assessment.level_index, 7)

    async def test_7_level_cognitive_hierarchy_queries(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            for lvl in range(1, 8):
                ans = engine.answer_hierarchy_level(lvl, context_goal="software_debugging")
                self.assertIn("question", ans)
                self.assertNotIn("error", ans)
        finally:
            await engine.stop()


if __name__ == "__main__":
    unittest.main()
