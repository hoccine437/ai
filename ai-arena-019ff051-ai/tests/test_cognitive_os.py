"""
Unit tests for Cognitive OS & Autonomous Organism Subsystems
Verifies Attention Economy, Opportunity Discovery, Intention Manager,
Continuous Objectives, and Organism Cycle execution.
"""

import os
import shutil
import tempfile
import unittest

from zerion.cognitive_os.attention import AttentionEconomy, AttentionItem
from zerion.cognitive_os.intention import IntentionManager
from zerion.cognitive_os.opportunity_detector import OpportunityDetector
from zerion.cognitive_os.objective_manager import ObjectiveContinuityManager, ContinuousObjective
from zerion.cognitive_os.organism import CognitiveOrganism
from zerion.engine import AscendantEngine


class TestCognitiveOS(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="cog_os_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_attention_economy_and_priority_calculation(self):
        economy = AttentionEconomy(capacity_slots=2)
        item_high = AttentionItem(
            topic="Critical Security Drift",
            urgency=0.9,
            importance=0.9,
            uncertainty=0.8,
            novelty=0.7,
            objective_relevance=0.95,
            expected_information_gain=0.9,
            resource_cost=0.5
        )
        item_low = AttentionItem(
            topic="Background Log Rotation",
            urgency=0.1,
            importance=0.2,
            uncertainty=0.1,
            novelty=0.1,
            objective_relevance=0.2,
            expected_information_gain=0.1,
            resource_cost=2.0
        )
        p_high = economy.submit_candidate(item_high)
        p_low = economy.submit_candidate(item_low)

        self.assertGreater(p_high, p_low)
        focused = economy.get_focused_attention()
        self.assertEqual(len(focused), 2)
        self.assertEqual(focused[0].topic, "Critical Security Drift")

    def test_opportunity_detector(self):
        detector = OpportunityDetector()
        opps = detector.scan_for_opportunities(
            resource_snapshot={"cpu_percent": 10.0, "memory_mb": 2048.0},
            active_objectives=[{"title": "Optimize partition index"}],
            available_capabilities=["bloom_filter_indexer"]
        )
        self.assertTrue(len(opps) >= 1)
        best = detector.get_highest_value_opportunity()
        self.assertIsNotNone(best)
        self.assertGreater(best.value_to_effort_ratio, 1.0)

    def test_continuous_objective_continuity_across_restarts(self):
        db_file = os.path.join(self.temp_dir, "objs.db")
        mgr1 = ObjectiveContinuityManager(db_path=db_file)
        mgr1.register_objective(ContinuousObjective(
            objective_id="OBJ_LONG_01",
            title="Durable Multi-Week Architecture Ascension",
            priority=95,
            progress=0.25
        ))
        mgr1.update_progress("OBJ_LONG_01", 0.25, "Completed Phase 1 milestone")

        # Simulate restart
        mgr2 = ObjectiveContinuityManager(db_path=db_file)
        objs = mgr2.list_active_objectives()
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].progress, 0.50)
        self.assertEqual(len(objs[0].history), 1)

    async def test_cognitive_organism_cycle_execution(self):
        organism = CognitiveOrganism(data_dir=self.temp_dir)
        res = await organism.execute_organism_cycle({
            "resource_metrics": {"cpu_percent": 20.0, "memory_mb": 1024.0},
            "pressure_signals": []
        })
        self.assertIsNotNone(res.cycle_id)
        self.assertGreater(len(res.selected_strategy), 0)
        self.assertGreater(len(res.selected_architecture), 0)


if __name__ == "__main__":
    unittest.main()
