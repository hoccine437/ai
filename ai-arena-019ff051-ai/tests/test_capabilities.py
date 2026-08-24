"""
Unit tests for Capability Gap Detection, Birth Pipeline, and Learning
"""

import os
import shutil
import tempfile
import unittest
from zerion.capabilities.detector import CapabilityGapDetector, GapType
from zerion.capabilities.birth import CapabilityBirthPipeline
from zerion.capabilities.registry import DynamicCapabilityRegistry
from zerion.learning.curriculum import SelfCurriculumGenerator
from zerion.learning.transfer import TransferEngine


class TestCapabilitiesAndLearning(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "caps.db")
        self.registry = DynamicCapabilityRegistry(db_path=self.db_path)
        self.detector = CapabilityGapDetector()
        self.pipeline = CapabilityBirthPipeline()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_capability_birth_lifecycle(self):
        gap = self.detector.classify_failure(
            task_goal="compress json payloads using gzip",
            error_message="tool not found: gzip_compressor"
        )
        self.assertEqual(gap.gap_type, GapType.TOOL_GAP)

        born = await self.pipeline.birth_capability(
            gap=gap,
            custom_prototype_code="""
def compress_json(payload):
    return {"success": True, "compressed": True, "size": 42}
"""
        )
        self.assertTrue(born.is_validated)
        self.assertGreaterEqual(born.benchmark_score, 0.8)

        registered = self.registry.register_born_capability(born)
        self.assertTrue(registered)

    def test_self_curriculum_and_transfer_engine(self):
        cur_gen = SelfCurriculumGenerator()
        gap = self.detector.classify_failure("distributed mutex coordination", "concurrency timeout")
        track = cur_gen.build_curriculum_for_gap(gap)
        self.assertEqual(len(track.steps), 5)
        self.assertEqual(track.progress, 0.0)

        transfer = TransferEngine()
        res = transfer.evaluate_strategy_transfer(
            strategy_name="binary_search_debugging",
            source_domain="python",
            target_domain="linux_c",
            source_score=0.95,
            target_score=0.90
        )
        self.assertTrue(res.is_valid_transfer)
        self.assertGreaterEqual(res.transfer_efficiency, 0.90)


if __name__ == "__main__":
    unittest.main()
