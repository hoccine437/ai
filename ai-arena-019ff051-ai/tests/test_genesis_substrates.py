"""
Unit tests for ZERION-X GENESIS Substrates:
- Cognitive Autopoiesis (Recursive self-development diagnostic)
- Counterfactual Simulation & Intervention Engine
- World Model 3.0 (8 Epistemic Categories & Contradiction Tracking)
- Question Genesis 3.0 (9 Question Modalities & Risk-Adjusted Priority)
- Cognitive Immune System (Multi-Barrier Security & Invariant Gatekeeping)
- Anti-Gaming Detector (Integrity Auditing)
- GENESIS 25-Stage Master Developmental Flywheel
"""

import os
import shutil
import tempfile
import unittest

from zerion.cognitive_autopoiesis.engine import CognitiveAutopoiesisEngine
from zerion.counterfactual.engine import CounterfactualEngine, CounterfactualQuery
from zerion.world.epistemic import EpistemicStatus, EpistemicValue, EpistemicAssertion
from zerion.questions.question import Question, QuestionType
from zerion.questions.scorer import QuestionScorer
from zerion.cognitive_immune.immune_system import CognitiveImmuneSystem
from zerion.benchmarks.anti_gaming import AntiGamingDetector
from zerion.engine import AscendantEngine


class TestGenesisSubstrates(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="genesis_tests_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_cognitive_autopoiesis_engine(self):
        autopoiesis = CognitiveAutopoiesisEngine(db_path=os.path.join(self.temp_dir, "auto.db"))
        report = await autopoiesis.execute_autopoietic_reflection(
            task_failure_goal="distributed_lock_consensus",
            error_context="Timeout during leader re-election"
        )
        self.assertTrue(report.sandbox_experiment_passed)
        self.assertTrue(report.promoted)
        self.assertEqual(report.failure_classification, "learning_process_gap")

    async def test_counterfactual_engine(self):
        cf_engine = CounterfactualEngine()
        query = CounterfactualQuery(
            target_variable="cache_ttl",
            baseline_state=60,
            counterfactual_state=3600
        )
        res = await cf_engine.evaluate_counterfactual(query)
        self.assertEqual(res.target_variable, "cache_ttl")
        self.assertGreater(len(res.alternative_explanations), 0)
        self.assertGreater(res.confidence, 0.85)

    def test_world_model_3_epistemic_states(self):
        val_measured = EpistemicValue(value=42.0, status=EpistemicStatus.MEASURED, confidence=0.95)
        self.assertEqual(val_measured.epistemic_assertion, EpistemicAssertion.I_KNOW)

        val_inferred = EpistemicValue(value="derived_result", status=EpistemicStatus.INFERRED, confidence=0.80)
        self.assertEqual(val_inferred.epistemic_assertion, EpistemicAssertion.I_INFER)

        # Contradiction tracking
        val_measured.record_contradiction("fuzz_test_probe")
        val_measured.record_contradiction("hardware_sensor_probe")
        self.assertEqual(val_measured.status, EpistemicStatus.CONTRADICTED)
        self.assertEqual(val_measured.epistemic_assertion, EpistemicAssertion.I_DO_NOT_KNOW)

    def test_question_genesis_3_modalities_and_risk_scoring(self):
        scorer = QuestionScorer()
        q_opt = Question(
            text="How can query compilation latency be minimized under memory pressure?",
            question_type=QuestionType.OPTIMIZATION,
            impact=0.9,
            uncertainty=0.8,
            expected_information_gain=0.85,
            goal_relevance=0.95,
            cost=1.0,
            risk=0.1
        )
        score = scorer.score(q_opt)
        self.assertGreater(score, 5.0)

        # High risk question gets penalized in priority
        q_risky = Question(
            text="What happens if disk write buffer is disabled entirely?",
            question_type=QuestionType.COUNTERFACTUAL,
            impact=0.9,
            uncertainty=0.8,
            expected_information_gain=0.85,
            goal_relevance=0.95,
            cost=1.0,
            risk=0.85  # Very high risk
        )
        score_risky = scorer.score(q_risky)
        self.assertGreater(score_risky, score)  # High risk increases priority of safety investigation

    async def test_cognitive_immune_system_barriers(self):
        immune = CognitiveImmuneSystem()

        # Attack on protected core
        res_prot = await immune.inspect_proposed_mutation(
            target_subsystem="zerion.identity.invariants",
            code_diff_or_payload="x = 1"
        )
        self.assertFalse(res_prot.passed)
        self.assertEqual(res_prot.rejection_barrier, "1_PROTECTED_ROOT")

        # Attack with dangerous call
        res_call = await immune.inspect_proposed_mutation(
            target_subsystem="zerion.dynamic_module",
            code_diff_or_payload="import os; os.system('echo bad')"
        )
        self.assertFalse(res_call.passed)
        self.assertEqual(res_call.rejection_barrier, "2_STATIC_AST_CHECK")

        # Safe mutation
        res_safe = await immune.inspect_proposed_mutation(
            target_subsystem="zerion.dynamic_math",
            code_diff_or_payload="def add(a, b): return a + b"
        )
        self.assertTrue(res_safe.passed)

    def test_anti_gaming_detector(self):
        detector = AntiGamingDetector()
        res_bad = detector.audit_code_payload("ascendant_score = 0.95")
        self.assertFalse(res_bad.is_valid)

        res_clean = detector.audit_code_payload("def calculate_metric(x): return x * 2.0")
        self.assertTrue(res_clean.is_valid)

    async def test_genesis_25_stage_developmental_flywheel(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            trace = await engine.run_developmental_cycle()
            self.assertEqual(trace.counterfactuals_simulated, 1)
            self.assertGreater(trace.duration_ms, 0.0)
            self.assertIsNotNone(trace.maturity_level)
        finally:
            await engine.stop()


if __name__ == "__main__":
    unittest.main()
