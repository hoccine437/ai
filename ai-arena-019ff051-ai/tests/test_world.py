"""
Unit tests for World Model & Tracker
"""

import os
import shutil
import tempfile
import unittest
from zerion.world.epistemic import EpistemicStatus, EpistemicValue
from zerion.world.causal import CausalHypothesis
from zerion.world.graph import WorldNode, WorldEdge, WorldModel
from zerion.world.tracker import WorldTracker


class TestWorld(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "world.db")
        self.world = WorldModel(db_path=self.db_path)
        self.tracker = WorldTracker(self.world)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_epistemic_distinctions(self):
        node = WorldNode(id="node_db", node_type="resource", name="Database")
        node.set_attribute("latency_ms", 12.5, EpistemicStatus.OBSERVED)
        node.set_attribute("max_connections", 100, EpistemicStatus.ASSUMED)
        node.set_attribute("failure_probability", 0.01, EpistemicStatus.PREDICTED)
        node.set_attribute("internal_buffer_size", None, EpistemicStatus.UNKNOWN)

        self.world.upsert_node(node)

        loaded = self.world.get_node("node_db")
        self.assertEqual(loaded.get_attribute("latency_ms").status, EpistemicStatus.OBSERVED)
        self.assertEqual(loaded.get_attribute("max_connections").status, EpistemicStatus.ASSUMED)
        self.assertEqual(loaded.get_attribute("failure_probability").status, EpistemicStatus.PREDICTED)
        self.assertEqual(loaded.get_attribute("internal_buffer_size").status, EpistemicStatus.UNKNOWN)

    def test_drift_detection(self):
        node = WorldNode(id="server_1", node_type="server", name="Server 1")
        node.set_attribute("response_time", 2.0, EpistemicStatus.PREDICTED)
        self.world.upsert_node(node)

        # Real observation is 8.0s -> drift anomaly
        anomaly = self.tracker.record_observation(
            node_id="server_1",
            attr_key="response_time",
            observed_val=8.0
        )
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.expected_value, 2.0)
        self.assertEqual(anomaly.observed_value, 8.0)
        self.assertGreater(anomaly.delta_magnitude, 1.0)

    def test_causal_hypothesis_falsification(self):
        hyp = CausalHypothesis(
            cause="high_concurrency",
            effect="high_latency",
            mechanism="thread pool saturation",
            strength=0.5
        )
        hyp_id = self.world.add_causal_hypothesis(hyp)

        # Record successful falsification
        hyp.record_falsification_result(falsified=False)
        hyp.record_falsification_result(falsified=False)
        self.assertTrue(hyp.verified)
        self.assertGreaterEqual(hyp.strength, 0.8)


if __name__ == "__main__":
    unittest.main()
