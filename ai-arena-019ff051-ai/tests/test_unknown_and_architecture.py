"""
Unit tests for Unknown Space and Cognitive Architecture Search
"""

import os
import shutil
import tempfile
import unittest

from zerion.unknown.unknown_space import UnknownSpaceEngine, EpistemicVoidType
from zerion.architecture_search.search_engine import ArchitectureSearchEngine


class TestUnknownAndArchitecture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="unk_arch_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unknown_space_void_registration_and_priority(self):
        db_file = os.path.join(self.temp_dir, "unk.db")
        engine = UnknownSpaceEngine(db_path=db_file)
        
        v1 = engine.register_void("host_memory", "fragmentation_ratio", EpistemicVoidType.KNOWN_UNKNOWN, entropy=0.9)
        self.assertEqual(v1.void_type, EpistemicVoidType.KNOWN_UNKNOWN)
        self.assertGreater(v1.investigation_priority, 0.8)

        engine.register_contradiction("Memory is lossless", "heap_dump_sensor", 0.35)
        top_voids = engine.get_highest_priority_voids()
        self.assertTrue(len(top_voids) >= 2)

    def test_architecture_search_and_tournaments(self):
        db_file = os.path.join(self.temp_dir, "arch.db")
        search = ArchitectureSearchEngine(db_path=db_file)
        
        cands = search.list_candidates()
        self.assertTrue(len(cands) >= 3)

        tour_res = search.run_tournament("top_causal_exp_v1", "top_reflex_v1")
        self.assertIn("winner", tour_res)
        self.assertGreater(tour_res["effect_size"], 0.0)

        # Promotion and rollback
        search.promote_candidate("top_causal_exp_v1")
        self.assertEqual(search.get_active_candidate().candidate_id, "top_causal_exp_v1")
        search.rollback()
        self.assertEqual(search.get_active_candidate().candidate_id, "top_adversarial_v1")


if __name__ == "__main__":
    unittest.main()
