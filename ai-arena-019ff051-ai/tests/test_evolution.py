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

    async def test_ascension_cycle_inconclusive_when_unmeasured(self):
        """With the real (honest) benchmark runner the composite is
        NOT_MEASURED (transfer factor unwired), so the cycle must be
        INCONCLUSIVE — never a fabricated promotion with a base+0.04 gain."""
        asc_engine = AscensionEngine()
        report = await asc_engine.execute_ascension_cycle()
        self.assertFalse(report.promoted)
        self.assertFalse(report.rolled_back)
        self.assertEqual(report.details["verdict"], "INCONCLUSIVE")
        self.assertIsNone(report.post_cycle_intelligence)

    async def test_ascension_cycle_promotes_on_measured_gain(self):
        """When both benchmark runs return MEASURED intelligence, a real
        improvement is promoted and a regression is rolled back — the decision
        follows the measured comparison, never a hard-coded delta."""
        class FakeBenchmarks:
            def __init__(self):
                self.calls = 0

            async def run_all(self):
                self.calls += 1
                from zerion.benchmarks.runner import BenchmarkRunReport
                return BenchmarkRunReport(
                    run_id=f"fake_{self.calls}", timestamp=0.0,
                    total_tasks=1, measured_tasks=1,
                    avg_baseline_score=0.5,
                    avg_ascendant_score=0.55,
                    composite_improvement_ratio=1.1,
                    effective_intelligence_score=(
                        0.50 if self.calls == 1 else 0.55),
                    task_results=[],
                )

        asc_engine = AscensionEngine(benchmark_runner=FakeBenchmarks())
        report = await asc_engine.execute_ascension_cycle()
        self.assertTrue(report.promoted)
        self.assertAlmostEqual(report.post_cycle_intelligence, 0.55, places=4)
        self.assertEqual(report.details["verdict"], "PROMOTED")


if __name__ == "__main__":
    unittest.main()
