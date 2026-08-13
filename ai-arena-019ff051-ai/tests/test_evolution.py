"""
Unit tests for Ascension Engine and Controlled Self-Modification
"""

import unittest
from zerion.evolution.plasticity import CognitivePlasticityManager
from zerion.evolution.self_modification import (
    ControlledSelfModificationEngine,
    ModificationProposal
)
from zerion.evolution.ascension import AscensionEngine


class TestEvolution(unittest.IsolatedAsyncioTestCase):
    def test_plasticity_mutation_and_rollback(self):
        cpm = CognitivePlasticityManager()
        self.assertEqual(cpm.current.version, 1)

        cpm.apply_mutation({"reasoning_depth": 5})
        self.assertEqual(cpm.current.version, 2)
        self.assertEqual(cpm.current.reasoning_depth, 5)

        # Rollback
        rolled = cpm.rollback_to_previous()
        self.assertIsNotNone(rolled)
        self.assertEqual(rolled.version, 1)
        self.assertEqual(rolled.reasoning_depth, 3)

    async def test_self_modification_safety_guardrails_and_rejection(self):
        mod_engine = ControlledSelfModificationEngine()

        # Malicious / forbidden modification attempting os.system
        dangerous_prop = ModificationProposal(
            hypothesis="Direct OS execution improves latency",
            target_module="bad_module",
            proposed_code="""
def bad_module():
    import os
    os.system('echo dangerous')
    return True
"""
        )
        res = await mod_engine.execute_modification_pipeline(dangerous_prop)
        self.assertFalse(res.promoted)
        self.assertTrue(res.rolled_back)
        self.assertIn("Invariant violation", res.reason)

        # Safe modification
        safe_prop = ModificationProposal(
            hypothesis="Pure math helper speedup",
            target_module="fast_add",
            proposed_code="""
def fast_add(a, b):
    return a + b
"""
        )
        res_safe = await mod_engine.execute_modification_pipeline(safe_prop, baseline_score=0.8)
        self.assertTrue(res_safe.promoted)
        self.assertFalse(res_safe.rolled_back)

    async def test_ascension_cycle(self):
        asc_engine = AscensionEngine()
        report = await asc_engine.execute_ascension_cycle()
        self.assertTrue(report.promoted)
        self.assertGreater(report.post_cycle_intelligence, 0.0)


if __name__ == "__main__":
    unittest.main()
