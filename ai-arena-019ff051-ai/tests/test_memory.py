"""
Unit tests for 7-Domain Developmental Memory & Experience Distillation
"""

import os
import shutil
import tempfile
import unittest
from zerion.memory.episodic import Episode
from zerion.memory.procedural import ProceduralRule
from zerion.memory.semantic import SemanticConcept, FailureMemoryRecord
from zerion.memory.distillation import ExperienceDistiller
from zerion.memory.developmental_store import DevelopmentalMemoryStore


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "memory.db")
        self.store = DevelopmentalMemoryStore(db_path=self.db_path, data_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_experience_distillation_into_procedural_rules(self):
        # Record 3 identical successful episodes
        for i in range(3):
            self.store.record_episode(Episode(
                goal="optimize database query index",
                actions_taken=["explain_query", "add_btree_index", "verify_latency"],
                outcome_status="SUCCESS",
                reward=0.95
            ))

        new_rules = self.store.trigger_distillation()
        self.assertTrue(len(new_rules) >= 1)
        rule = new_rules[0]
        self.assertEqual(rule.success_count, 3)
        self.assertEqual(rule.reliability, 1.0)
        self.assertEqual(rule.action_procedure, "explain_query -> add_btree_index -> verify_latency")

        # Query procedural rule
        found = self.store.find_procedural_rule("optimize database query")
        self.assertIsNotNone(found)

    def test_failure_memory_recording(self):
        fail_id = self.store.record_failure(FailureMemoryRecord(
            task_goal="execute unsafe bash script",
            failure_type="execution_limitation",
            root_cause="Permission denied by sandbox security",
            preventive_rule="Check permission before running"
        ))
        failures = self.store.list_failures(failure_type="execution_limitation")
        self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
