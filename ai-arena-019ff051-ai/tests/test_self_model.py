"""
Unit tests for Self Model & Calibration
"""

import os
import shutil
import tempfile
import unittest
from zerion.self_model.capabilities import CapabilityRecord
from zerion.self_model.calibration import ConfidenceCalibrator
from zerion.self_model.introspector import SelfModel


class TestSelfModel(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "self.db")
        self.self_model = SelfModel(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_introspection_queries(self):
        can_do = self.self_model.what_can_i_do()
        self.assertTrue(len(can_do) >= 5)

        rel = self.self_model.how_reliable_am_i_at("observe_reality")
        self.assertTrue(rel["known"])
        self.assertEqual(rel["capability"], "observe_reality")

        cannot_do = self.self_model.what_can_i_not_do()
        self.assertTrue(len(cannot_do) >= 1)

    def test_calibration_and_brier_score(self):
        cal = ConfidenceCalibrator()
        cal.record_prediction("p1", 0.9, True)
        cal.record_prediction("p2", 0.8, True)
        cal.record_prediction("p3", 0.2, False)

        brier = cal.calculate_brier_score()
        self.assertLess(brier, 0.1)  # Well calibrated predictions have low Brier score


if __name__ == "__main__":
    unittest.main()
