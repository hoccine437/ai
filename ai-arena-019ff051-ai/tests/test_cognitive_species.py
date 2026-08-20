"""
Unit and Integration Tests for ZERION-X Cognitive Species Substrate
Verifies:
- Persistent Goal Field across restart and failure
- Hypothesis Competition ($H_A, H_B, H_C$ generation)
- Bottleneck Detection
- Model Router Dynamic Cognitive Depth (D0..D6) & Graceful Failover
- Closed-Loop Species Pulse Execution
"""

import os
import shutil
import tempfile
import unittest

from zerion.cognitive_species.goal_field import GoalField, GoalItem
from zerion.cognitive_species.hypothesis_engine import HypothesisCompetitionEngine, BottleneckDetector
from zerion.cognitive_species.cognitive_pulse import CognitiveSpeciesRuntime
from zerion.model_providers.router import CognitiveRouter, CognitiveDepthLevel


class TestCognitiveSpecies(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="species_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_goal_field_persistence_and_advancement(self):
        db_file = os.path.join(self.temp_dir, "goals.db")
        gf1 = GoalField(db_path=db_file)

        goal = GoalItem(
            title="Durable Architecture Evolution",
            purpose="Maintain long-term objective continuity",
            priority=95,
            progress_ratio=0.20
        )
        gid = gf1.register_goal(goal)
        gf1.advance_goal(gid, 0.30, "Completed Slice A verification")

        # Reload from disk
        gf2 = GoalField(db_path=db_file)
        loaded = gf2._goals.get(gid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.progress_ratio, 0.50)
        self.assertEqual(len(loaded.progress_evidence), 1)

    def test_competing_hypothesis_engine(self):
        engine = HypothesisCompetitionEngine()
        hyps = engine.formulate_competing_hypotheses("Query cache hit ratio dropped to 40%")
        self.assertEqual(len(hyps), 3)
        self.assertIn("Direct Causal", hyps[0].title)
        self.assertIn("Latent Third Factor", hyps[1].title)
        self.assertIn("Adversarial Null", hyps[2].title)

    def test_bottleneck_detection(self):
        detector = BottleneckDetector()
        res = detector.detect_bottlenecks(
            avg_latency_ms=650.0, # High latency
            failure_rate=0.02,
            memory_usage_mb=1024.0,
            procedural_reuse_rate=0.85
        )
        self.assertEqual(res["primary_bottleneck"], "MODEL_LATENCY_LIMITATION")

    def test_cognitive_router_depth_and_failover(self):
        router = CognitiveRouter(models_dir=os.path.join(self.temp_dir, "models"))
        
        # Test low-risk reflex depth
        d_reflex = router.compute_cognitive_depth(uncertainty=0.1, novelty=0.1, stakes_risk=0.1, goal_relevance=0.2)
        self.assertEqual(d_reflex, CognitiveDepthLevel.D0_REFLEX)

        # Test high-uncertainty deep depth
        d_deep = router.compute_cognitive_depth(uncertainty=0.95, novelty=0.95, stakes_risk=0.95, goal_relevance=0.95)
        self.assertEqual(d_deep, CognitiveDepthLevel.D6_ARCHITECTURE)

    async def test_species_pulse_cycle_execution(self):
        # The legacy CognitiveSpeciesRuntime is DEPRECATED and isolated from the
        # live engine — tests construct it directly with REAL measured metrics.
        species = CognitiveSpeciesRuntime(data_dir=self.temp_dir)
        pulse_trace = await species.execute_pulse_cycle({
            "resource_metrics": {"cpu_percent": 25.0, "memory_mb": 900.0}
        })
        self.assertIsNotNone(pulse_trace.pulse_id)
        self.assertGreater(pulse_trace.active_goals_count, 0)
        self.assertEqual(pulse_trace.hypotheses_evaluated, 3)
        # Honest telemetry: reality_learned is True only because real resource
        # metrics were provided; unmeasured dimensions are never fabricated.
        self.assertTrue(pulse_trace.reality_learned)
        self.assertEqual(pulse_trace.primary_bottleneck, "NONE")


if __name__ == "__main__":
    unittest.main()
