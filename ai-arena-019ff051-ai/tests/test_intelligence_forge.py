"""
Unit tests for ZERION-X Ω Intelligence Foundry Substrates:
- Significance Engine (SignificanceSignal, Scoring, SignificanceOutput)
- Cognitive Episode & Store (Lifecycle transitions, CognitiveBudget, SQLite persistence)
- Cognitive Credit Assignment (CreditContributionNode, Empirical Attribution)
- Developmental Compiler (DevelopmentProposal, Sandbox validation, Promotion)
- Model Economy (ModelProfile, GGUF discovery, Fallbacks)
- Master Intelligence Foundry Runtime Cycle
"""

import os
import shutil
import tempfile
import unittest

from zerion.intelligence_forge.significance.significance_engine import (
    SignificanceEngine,
    SignificanceSignal,
    SignificanceOutput,
)
from zerion.intelligence_forge.cognitive_episode.episode import (
    CognitiveEpisode,
    EpisodeLifecycleState,
    CognitiveBudget,
)
from zerion.intelligence_forge.cognitive_episode.store import CognitiveEpisodeStore
from zerion.intelligence_forge.cognitive_credit.credit_graph import (
    CognitiveCreditAssigner,
    CreditRelation,
)
from zerion.intelligence_forge.developmental_compiler.compiler import DevelopmentalCompiler
from zerion.intelligence_forge.model_economy.economy import ModelEconomy
from zerion.intelligence_forge.organism_runtime.foundry import IntelligenceFoundry


class TestIntelligenceForge(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="forge_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_significance_engine_evaluation(self):
        engine = SignificanceEngine()
        sig_prob = SignificanceSignal(
            source="latency_monitor",
            importance=0.85,
            uncertainty=0.70,
            novelty=0.60,
            objective_relevance=0.90,
            expected_information_gain=0.80,
            description="Severe latency anomaly detected on query gateway"
        )
        assessment = engine.evaluate_signal(sig_prob)
        self.assertTrue(assessment.requires_cognitive_episode)
        self.assertEqual(assessment.decision, SignificanceOutput.PROBLEM)
        self.assertGreater(assessment.significance_score, 10.0)

    def test_cognitive_episode_lifecycle_and_persistence(self):
        db_file = os.path.join(self.temp_dir, "episodes.db")
        store1 = CognitiveEpisodeStore(db_path=db_file)

        ep = CognitiveEpisode(
            objective="Resolve latency bottleneck in distributed lock manager",
            problem_statement="Lock contention exceeds 500ms threshold"
        )
        ep.transition(EpisodeLifecycleState.SCOPING)
        ep.transition(EpisodeLifecycleState.EXECUTING)
        ep.results = {"latency_reduction": 0.35}
        ep.transition(EpisodeLifecycleState.COMPLETED)
        store1.save_episode(ep)

        # Reload from disk (simulating restart)
        store2 = CognitiveEpisodeStore(db_path=db_file)
        loaded = store2.get_episode(ep.episode_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, EpisodeLifecycleState.COMPLETED)
        self.assertEqual(loaded.results["latency_reduction"], 0.35)

    def test_cognitive_credit_assignment(self):
        credit_assigner = CognitiveCreditAssigner(db_path=os.path.join(self.temp_dir, "credit.db"))
        rep = credit_assigner.assign_credit(
            episode_id="ep_test_001",
            is_success=True,
            had_experiment=True,
            had_procedural_memory=True,
            strategy_used="IntervalBisection",
            model_used="openai_gpt4o_mini"
        )
        self.assertEqual(rep.overall_outcome, "SUCCESS")
        self.assertEqual(rep.primary_catalyst, "strategy")
        self.assertIn("strategy", rep.node_contributions)
        self.assertGreater(rep.node_contributions["strategy"].contribution_delta_percent, 10.0)

    async def test_developmental_compiler(self):
        compiler = DevelopmentalCompiler(db_path=os.path.join(self.temp_dir, "dev.db"))
        prop = compiler.synthesize_proposal(
            bottleneck="Elevated search latency in strategy selection",
            target_subsystem="strategy_selector"
        )
        self.assertEqual(prop.target_subsystem, "strategy_selector")
        
        promoted = await compiler.validate_and_promote(prop)
        self.assertTrue(promoted)
        self.assertTrue(prop.is_validated)

    def test_model_economy_selection_and_discovery(self):
        models_dir = os.path.join(self.temp_dir, "models")
        os.makedirs(models_dir, exist_ok=True)
        # Create a mock .gguf file
        with open(os.path.join(models_dir, "qwen2.5_coder_q4_k_m.gguf"), "w") as f:
            f.write("mock_gguf_binary")

        economy = ModelEconomy(models_dir=models_dir)
        discovered = economy.discover_gguf_models()
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].quantization, "Q4_K_M")

        # Select optimal model for reasoning
        best = economy.select_optimal_model(required_capability="reasoning")
        self.assertIsNotNone(best)
        self.assertEqual(best.provider, "openai")

    async def test_intelligence_foundry_master_cycle(self):
        foundry = IntelligenceFoundry(data_dir=self.temp_dir)
        telemetry = await foundry.execute_foundry_cycle(
            signal_source="host_governor",
            signal_description="Continuous Epistemic Exploration",
            importance=0.80,
            uncertainty=0.50
        )
        self.assertIsNotNone(telemetry.foundry_cycle_id)
        self.assertIsNotNone(telemetry.active_episode_id)
        self.assertEqual(telemetry.selected_strategy, "IntervalBisection")
        self.assertGreater(telemetry.duration_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
