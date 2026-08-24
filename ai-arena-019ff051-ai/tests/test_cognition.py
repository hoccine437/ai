"""
Unit tests for Cognition, Compiler, Multi-Path, and Adversarial Engine
"""

import unittest
from zerion.cognition.cells import CognitiveCell, CellType, CellInput
from zerion.cognition.compiler import CognitiveCompiler
from zerion.cognition.program import CognitiveProgram
from zerion.cognition.multi_path import MultiPathReasoner
from zerion.cognition.adversarial import AdversarialEngine
from zerion.cognition.adaptive_compute import resolve_compute_profile, ComputeMode


class TestCognition(unittest.IsolatedAsyncioTestCase):
    async def test_cognitive_compiler_and_execution(self):
        compiler = CognitiveCompiler()
        # Compile debugging topology
        prog = compiler.compile(goal="Debug memory leak in worker process")
        self.assertGreater(len(prog.steps), 4)

        result = await prog.execute()
        self.assertTrue(result["completed"])
        self.assertEqual(len(result["execution_log"]), len(prog.steps))

    async def test_multi_path_reasoning(self):
        mpr = MultiPathReasoner()
        res = await mpr.execute_multi_path("Why did cache invalidation stall?", {}, paths_to_run=3)
        self.assertEqual(res["paths_evaluated"], 3)
        self.assertGreater(res["consensus_score"], 0.7)

    def test_adversarial_attack_engine(self):
        adv = AdversarialEngine()
        # Test claim with overconfidence
        res = adv.attack_conclusion("This function 100% never fails under any condition", [])
        self.assertTrue(len(res.hidden_assumptions) > 0)
        self.assertGreater(res.confidence_reduction, 0.0)

    def test_adaptive_compute_profiles(self):
        prof_reflex = resolve_compute_profile(urgency=0.95, uncertainty=0.1, impact=0.1)
        self.assertEqual(prof_reflex.mode, ComputeMode.REFLEX)

        prof_extreme = resolve_compute_profile(urgency=0.5, uncertainty=0.9, impact=0.9)
        self.assertEqual(prof_extreme.mode, ComputeMode.EXPERIMENTAL)



if __name__ == "__main__":
    unittest.main()
