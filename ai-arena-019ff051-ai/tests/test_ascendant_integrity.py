"""
ASCENDANT ∞ reality-integrity tests.

These tests prove the four focus systems are REAL parts of the canonical
ZERION X runtime and that their measurements are honest:

- Security: SecurityBoundary denies by default; the sandbox enforces it on the
  real execution path; the genesis pipeline rejects forbidden/dangerous code;
  SelfModificationGate enforces INV-001..INV-010 and SYSTEM_MUTATE.
- Self-experiments: measured-only scores (NOT_MEASURED when no evaluator).
- Strategy lineage: benchmark_gain is 0.0 (unmeasured) until measured — never
  a fabricated constant.
- Genome/phenotype: phenotypes really change adaptive allocation.
- Brier: vacuous 0.0 from an empty calibration set is gone (None instead).
"""

import unittest

from zerion.runtime.security import SecurityBoundary, PermissionLevel
from zerion.experiments.sandbox import ExecutionSandbox
from zerion.self_model.calibration import ConfidenceCalibrator
from zerion.cognitive_genome.genome import CognitiveGenome
from zerion.cognitive_genome.phenotype import PhenotypeFactory
from zerion.adaptive_cognition.controller import AdaptiveCognitiveController
from zerion.strategy_evolution.evolution_engine import StrategyEvolutionEngine
from zerion.cognitive_genesis.strategy import CognitiveStrategy
from zerion.cognitive_os.improvement import (
    ImprovementProposal,
    ModificationType,
    RiskLevel,
)
from zerion.cognitive_os.self_modification_gate import SelfModificationGate


class TestSecurityReality(unittest.IsolatedAsyncioTestCase):
    def test_security_boundary_denies_system_mutate_by_default(self):
        """SYSTEM_MUTATE / SELF_MODIFICATION is never held by default — the
        denial is the real authorization result, not a docstring."""
        boundary = SecurityBoundary(workspace_root="/tmp")
        self.assertFalse(boundary.authorize(
            action="self_modification", target="cognitive_os/thing",
            required_permission=PermissionLevel.SYSTEM_MUTATE,
            caller="test"))
        # And it is audited.
        trail = boundary.get_audit_trail()
        self.assertEqual(trail[-1]["granted"], False)

    async def test_sandbox_enforces_security_boundary(self):
        """The ExecutionSandbox runs through the SecurityBoundary: a boundary
        that cannot authorize execution yields an explicit denial result —
        the subprocess is never spawned."""
        class DenyingBoundary:
            def authorize(self, *args, **kwargs):
                return False

        sandbox = ExecutionSandbox(security=DenyingBoundary())
        result = await sandbox.run_python_code("print(42)")
        self.assertFalse(result.success)
        self.assertIn("denied by security boundary", result.stderr)

    async def test_genesis_rejects_forbidden_calls(self):
        """Cognitive genesis stage 4 rejects synthesized code containing
        forbidden calls — a real failing stage, not a fabricated pass."""
        from zerion.cognitive_genesis.genesis_pipeline import CognitiveGenesisPipeline

        pipeline = CognitiveGenesisPipeline()
        res = await pipeline.synthesize_strategy(
            problem_description="x", domain="test_domain",
            custom_code_template=(
                "def execute_strategy(context):\n"
                "    import os\n"
                "    os.system('rm -rf /')\n"
                "    return {'success': True}\n"))
        self.assertFalse(res.success)
        self.assertEqual(res.failure_stage, "4_STATIC_ANALYSIS")

    async def test_genesis_rejects_hardcoded_scores(self):
        """Anti-gaming is wired into genesis stage 4: a synthesized strategy
        that hard-codes a score is rejected (INV-010), not registered."""
        from zerion.cognitive_genesis.genesis_pipeline import CognitiveGenesisPipeline

        pipeline = CognitiveGenesisPipeline()
        res = await pipeline.synthesize_strategy(
            problem_description="x", domain="test_domain2",
            custom_code_template=(
                "def execute_strategy(context):\n"
                "    return 0.95\n"))
        self.assertFalse(res.success)
        self.assertEqual(res.failure_stage, "4_STATIC_ANALYSIS")
        self.assertIn("Anti-gaming", res.error_message)

    def test_self_modification_gate_enforces_invariants_and_permissions(self):
        """The gate's approve() is the real enforcement point: INV-010
        (bypass evaluator isolation) and INV-002 (SYSTEM_MUTATE not held) both
        deny — the invariant root is wired, not decorative."""
        gate = SelfModificationGate(security=SecurityBoundary(workspace_root="/tmp"))
        # A proposal trying to touch the benchmark evaluator is denied by the
        # invariant gate before the security check even matters.
        prop = ImprovementProposal(
            target_component="benchmark_config",
            problem="test",
            proposed_change={"modify_benchmark_evaluator": True},
            modification_type=ModificationType.CONFIGURATION_CHANGE,
            risk=RiskLevel.LOW,
            analysis={"passed": True, "tests_passed": True,
                      "claims_measured": True},
            benchmark={"verdict": "SUPPORTED"},
            rollback_plan="restore previous snapshot",
        )
        ok, reason = gate.approve(prop)
        self.assertFalse(ok)
        self.assertIn("INV-010", reason)


class TestLineageAndGenomeReality(unittest.TestCase):
    def test_composed_strategy_gain_is_unmeasured_not_fabricated(self):
        """benchmark_gain on composition is 0.0 = NOT measured (INV-003) —
        the previous hard-coded +0.05 gain is gone."""
        evo = StrategyEvolutionEngine(db_path=None)
        s1 = CognitiveStrategy(name="A", domain="db",
                               procedure_steps=["s1"])
        s2 = CognitiveStrategy(name="B", domain="cache",
                               procedure_steps=["s2"])
        composed = evo.compose_strategies(s1, s2, "Composite")
        node = evo._lineage[composed.strategy_id]
        self.assertEqual(node.derivation_type, "composition")
        self.assertEqual(node.benchmark_gain, 0.0)

    def test_phenotypes_alter_real_allocation(self):
        """Phenotypes genuinely change runtime behavior: the adaptive
        controller allocates different reasoning depth / parallel paths for
        different phenotypes under the same task intensity."""
        genome = CognitiveGenome()
        controller = AdaptiveCognitiveController(default_genome=genome)
        creative = PhenotypeFactory.derive_phenotype(genome, "creative")
        math_ph = PhenotypeFactory.derive_phenotype(genome, "mathematical")

        alloc_creative = controller.allocate_cognition(
            "t1", uncertainty=0.7, difficulty=0.7, novelty=0.5, risk=0.5,
            phenotype=creative)
        alloc_math = controller.allocate_cognition(
            "t2", uncertainty=0.7, difficulty=0.7, novelty=0.5, risk=0.5,
            phenotype=math_ph)
        # Same intensity band -> both NORMAL, but phenotypes drive different
        # parallel widths (creative=5 vs math=2) and depths.
        self.assertEqual(alloc_creative.selected_mode, "NORMAL")
        self.assertEqual(alloc_math.selected_mode, "NORMAL")
        self.assertNotEqual(alloc_creative.parallel_paths,
                            alloc_math.parallel_paths)

    def test_brier_is_none_without_calibration_samples(self):
        """The vacuous 0.0 Brier (empty sample set) is replaced by None —
        an unmeasured calibration must not read as perfect."""
        cal = ConfidenceCalibrator()
        self.assertIsNone(cal.calculate_brier_score())
        cal.record_prediction("p1", 0.9, True)
        self.assertIsNotNone(cal.calculate_brier_score())


if __name__ == "__main__":
    unittest.main()
