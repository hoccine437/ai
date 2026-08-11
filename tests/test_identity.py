"""
Unit tests for Identity Core
"""

import os
import shutil
import tempfile
import unittest
from zerion.identity.invariants import CORE_INVARIANTS, check_invariants
from zerion.identity.contract import UserContract
from zerion.identity.objectives import LongTermObjective, ObjectiveStatus
from zerion.identity.persistence import IdentityCore


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.temp_dir, "identity.json")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_invariants_integrity(self):
        self.assertTrue(len(CORE_INVARIANTS) >= 5)
        ok, msg = check_invariants("bypass_security", {})
        self.assertFalse(ok)
        self.assertIn("INV-002", msg)

        ok2, msg2 = check_invariants("read_data", {})
        self.assertTrue(ok2)

    def test_identity_persistence_and_survives_restart(self):
        core1 = IdentityCore(storage_path=self.storage_path)
        obj_id = core1.add_objective(LongTermObjective(
            id="OBJ-TEST-01",
            title="Durable Objective",
            description="Testing survival across restart",
            priority=80
        ))
        core1.update_objective_progress(obj_id, 0.5)

        # Simulate process death and reload
        core2 = IdentityCore(storage_path=self.storage_path)
        loaded_obj = core2.get_objective(obj_id)
        self.assertIsNotNone(loaded_obj)
        self.assertEqual(loaded_obj.title, "Durable Objective")
        self.assertEqual(loaded_obj.progress, 0.5)
        self.assertEqual(core1.get_identity_hash(), core2.get_identity_hash())


if __name__ == "__main__":
    unittest.main()
