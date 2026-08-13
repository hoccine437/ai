"""
Unit tests for Missions, Checkpoints, and Crash Recovery
"""

import os
import shutil
import tempfile
import unittest
from zerion.missions.mission import Mission, MissionStep, MissionStatus
from zerion.missions.lifecycle import MissionLifecycleManager


class TestMissions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "missions.db")
        self.mgr = MissionLifecycleManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_durable_mission_execution_and_checkpoint_resume(self):
        mission = self.mgr.create_mission("Deploy and verify cache cluster")
        s1 = MissionStep(step_id="step_1", name="Initialize nodes", action_type="init")
        s2 = MissionStep(step_id="step_2", name="Run cluster test", action_type="test", dependencies=["step_1"])
        mission.add_step(s1)
        mission.add_step(s2)

        # Execute
        success = await self.mgr.execute_mission(mission.id)
        self.assertTrue(success)
        self.assertEqual(mission.status, MissionStatus.COMPLETED)
        self.assertEqual(len(mission.checkpoints), 2)

        # Simulate reload from disk
        mgr2 = MissionLifecycleManager(db_path=self.db_path)
        loaded = mgr2.get_mission(mission.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, MissionStatus.COMPLETED)
        self.assertEqual(len(loaded.checkpoints), 2)


if __name__ == "__main__":
    unittest.main()
