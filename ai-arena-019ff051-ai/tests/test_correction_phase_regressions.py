"""
Regression tests for the ZERION correction phase.

These tests target the specific fabrications found in ZERION_GROUND_TRUTH_REPORT.md
and prove the fixes described in ZERION_CORRECTION_REPORT.md. Each test documents
what the pre-fix behavior was, so a future contributor can see why the assertion
exists without re-reading the report.
"""

import asyncio
import os
import unittest

from zerion.runtime.evidence import (
    RuntimeEvidence, Metric, MeasurementStatus, ExecutionMode, collect_runtime_evidence,
)
from zerion.runtime.reality_audit import run_reality_audit
from zerion.self_model.maturity import CognitiveMaturityEvaluator, MaturityLevel
from zerion.benchmarks.scoreboard import DevelopmentalScoreboard
from zerion.model_providers.gemini_provider import GeminiProvider
from zerion.evolution.self_modification import ControlledSelfModificationEngine, ModificationProposal
from zerion.evolution.plasticity import CognitivePlasticityManager


class TestRealityAuditExecutesRealTests(unittest.TestCase):
    """
    Before: `--reality-audit` printed a literal hard-coded string
    ("Subsystems Verified: Real & Operational (67 automated tests passing).")
    without running anything.
    After: it actually invokes pytest and parses genuine results.
    """
    def test_reality_audit_does_not_fake_counts(self):
        result = run_reality_audit(target="tests/test_identity.py")
        self.assertTrue(result.ran_successfully)
        self.assertGreater(result.tests_executed, 0)
        # The old hard-coded claim was always exactly 67 regardless of target;
        # a targeted single-file run must not coincidentally reproduce that.
        self.assertNotEqual(result.tests_executed, 67)

    def test_reality_audit_reports_real_failures(self):
        # Deliberately point at a target with no tests to confirm honest reporting
        # of the "nothing executed" case rather than a fabricated pass count.
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            empty_test = pathlib.Path(d) / "test_empty_placeholder.py"
            empty_test.write_text("# no tests here\n")
            result = run_reality_audit(target=str(empty_test))
            self.assertEqual(result.passed, 0)
            self.assertEqual(result.failed, 0)


class TestMaturityUsesRealEvidence(unittest.TestCase):
    """
    Before: `evaluate()` was called with zero arguments at every user-facing
    reporting call site, silently using hard-coded defaults
    (episodes_count=1, born_capabilities_count=1, learning_acceleration=1.5, ...)
    that always satisfied every criterion up to L7, regardless of true state.
    After: `evaluate_from_evidence()` requires a live RuntimeEvidence snapshot.
    """
    def test_maturity_does_not_use_empirical_defaults_on_cold_state(self):
        evaluator = CognitiveMaturityEvaluator()
        cold_evidence = RuntimeEvidence(
            episodes_count=0, procedural_rules_count=0, born_capabilities_count=0,
            total_capabilities_count=8, synthesized_strategies_count=3,
            active_objectives_count=0, flywheel_cycles=0, brier_score=None,
            learning_acceleration=None, has_native_caps=True,
            has_adaptive_phenotypes=True, has_pressure_field=True,
        )
        result = evaluator.evaluate_from_evidence(cold_evidence)
        # A cold-start system with 0 episodes must NOT report L7.
        self.assertNotEqual(result.current_level, MaturityLevel.L7_COGNITIVE_GENERATIVE)
        self.assertEqual(result.current_level, MaturityLevel.L0_STATIC)

    def test_maturity_rises_with_real_state(self):
        evaluator = CognitiveMaturityEvaluator()
        warmer_evidence = RuntimeEvidence(
            episodes_count=1, procedural_rules_count=1, born_capabilities_count=0,
            total_capabilities_count=8, synthesized_strategies_count=3,
            active_objectives_count=0, flywheel_cycles=1, brier_score=0.04,
            learning_acceleration=None, has_native_caps=True,
            has_adaptive_phenotypes=True, has_pressure_field=True,
        )
        result = evaluator.evaluate_from_evidence(warmer_evidence)
        # L0-L4 criteria are all satisfied consecutively (native caps, episodes>0,
        # procedural rules>0, adaptive phenotypes, pressure field + good brier);
        # L5 breaks the ladder (born_capabilities_count=0), so this must land at L4,
        # not be inflated by unrelated later criteria.
        self.assertEqual(result.current_level, MaturityLevel.L4_SELF_DIAGNOSTIC)
        self.assertGreater(result.level_index,
                            CognitiveMaturityEvaluator().evaluate_from_evidence(
                                RuntimeEvidence(episodes_count=0, procedural_rules_count=0,
                                                 born_capabilities_count=0, total_capabilities_count=8,
                                                 synthesized_strategies_count=0, active_objectives_count=0,
                                                 flywheel_cycles=0, brier_score=None, learning_acceleration=None,
                                                 has_native_caps=True, has_adaptive_phenotypes=True,
                                                 has_pressure_field=True)).level_index)


class TestScoreboardProvenance(unittest.TestCase):
    """
    Before: capture_snapshot() was never called with real arguments anywhere in
    the codebase, so every rendered scoreboard showed hard-coded defaults
    (effective_intelligence=0.88, avg_prediction_accuracy=0.94, ...) presented
    as if they were measured system performance.
    After: every metric carries an explicit MeasurementStatus; unmeasured
    metrics report UNAVAILABLE instead of a plausible-looking number.
    """
    def test_scoreboard_does_not_report_default_metrics_as_observed(self):
        sb = DevelopmentalScoreboard()
        evidence = RuntimeEvidence(
            episodes_count=0, procedural_rules_count=0, born_capabilities_count=0,
            total_capabilities_count=8, synthesized_strategies_count=0,
            active_objectives_count=0, flywheel_cycles=0, brier_score=None,
            learning_acceleration=None, has_native_caps=True,
            has_adaptive_phenotypes=True, has_pressure_field=True,
        )
        snap = sb.capture_snapshot_from_evidence(evidence, cycles_run=0)
        self.assertEqual(snap.effective_intelligence.status, MeasurementStatus.UNAVAILABLE)
        self.assertEqual(snap.avg_prediction_accuracy.status, MeasurementStatus.UNAVAILABLE)
        self.assertEqual(snap.self_correction_rate.status, MeasurementStatus.UNAVAILABLE)
        self.assertEqual(snap.mission_reliability.status, MeasurementStatus.UNAVAILABLE)
        # Capability counts ARE genuinely measured and must be OBSERVED.
        self.assertEqual(snap.total_capabilities.status, MeasurementStatus.OBSERVED)
        self.assertEqual(snap.total_capabilities.value, 8.0)

    def test_scoreboard_never_auto_fabricates_first_snapshot(self):
        sb = DevelopmentalScoreboard()
        text = sb.render_summary_text()
        self.assertIn("No snapshot captured yet", text)
        self.assertNotIn("0.8800", text)


class TestProviderFallbackHonesty(unittest.TestCase):
    """
    Gemini is the ONLY provider (OpenAI/local-GGUF providers were removed).
    With no API key configured, GeminiProvider returns an honestly-marked
    FALLBACK response — never fabricated telemetry, never another brain.
    """
    def test_gemini_fallback_is_marked_and_does_not_fake_telemetry(self):
        os.environ.pop("GEMINI_API_KEY", None)
        provider = GeminiProvider()
        self.assertFalse(provider.is_available())
        response = asyncio.run(provider.generate_response("test prompt"))
        self.assertEqual(response.execution_mode, ExecutionMode.FALLBACK_RESPONSE)
        self.assertTrue(response.is_fallback)
        self.assertIsNone(response.cost_cents)
        self.assertIn("FALLBACK", response.content)

    def test_no_other_provider_exists(self):
        import zerion.model_providers as mp
        import zerion.model_providers.provider as mpp
        for banned in ("OpenAIProvider", "DeterministicFallbackProvider",
                       "LocalGGUFProvider"):
            self.assertFalse(any(banned == n for n in dir(mp)),
                             f"{banned} must not exist in model_providers")
            self.assertFalse(any(banned == n for n in dir(mpp)),
                             f"{banned} must not exist in provider interface")


class TestSelfModificationBypassResistance(unittest.TestCase):
    """
    Before: the static-analysis stage matched a textual blocklist
    (["os.system", "shutil.rmtree", "subprocess.Popen", ...]) against
    ast.unparse(node.func). Adversarial testing found 5/7 realistic bypass
    techniques were promoted (getattr indirection, subprocess.run, os.popen,
    eval-built calls, runtime-built __import__ strings).
    After: an allowlist-based static validator rejects any import, identifier,
    attribute, or string-literal reference to a name outside a small safe set.
    """
    def _run(self, code: str):
        engine = ControlledSelfModificationEngine()
        proposal = ModificationProposal(hypothesis="adversarial test", target_module="x", proposed_code=code)
        return asyncio.run(engine.execute_modification_pipeline(proposal))

    def test_rejects_original_direct_os_system(self):
        result = self._run("""
def bad_module():
    import os
    os.system('echo dangerous')
    return True
""")
        self.assertFalse(result.promoted)

    def test_rejects_getattr_indirection_bypass(self):
        result = self._run("""
import os
fn = getattr(os, 'sy' + 'stem')
fn('echo pwned')
""")
        self.assertFalse(result.promoted)

    def test_rejects_subprocess_run_not_on_old_blocklist(self):
        result = self._run("""
import subprocess
subprocess.run(['echo', 'pwned'])
""")
        self.assertFalse(result.promoted)

    def test_rejects_os_popen_bypass(self):
        result = self._run("""
import os
os.popen('echo pwned').read()
""")
        self.assertFalse(result.promoted)

    def test_rejects_eval_built_call_bypass(self):
        result = self._run("""
eval(compile("__import__('os').system('echo pwned')", '<s>', 'exec'))
""")
        self.assertFalse(result.promoted)

    def test_rejects_runtime_built_import_string_bypass(self):
        result = self._run("""
m = __import__('o' + 's')
getattr(m, 'system')('echo pwned')
""")
        self.assertFalse(result.promoted)

    def test_still_promotes_legitimate_safe_code(self):
        result = self._run("""
def fast_add(a, b):
    return a + b
""")
        self.assertTrue(result.promoted)


class TestPlasticityRollbackRestoresState(unittest.TestCase):
    """
    Genuine apply-then-revert test for the ONE component in this codebase that
    actually performs a live apply/rollback cycle on state
    (CognitivePlasticityManager). ControlledSelfModificationEngine does NOT
    apply proposals to live state at all -- see the note on
    ModificationResult.rolled_back in zerion/evolution/self_modification.py.
    """
    def test_rollback_restores_exact_previous_state(self):
        mgr = CognitivePlasticityManager()
        original = mgr.current
        self.assertEqual(original.version, 1)
        self.assertEqual(original.reasoning_depth, 3)

        mgr.apply_mutation({"reasoning_depth": 9})
        self.assertEqual(mgr.current.version, 2)
        self.assertEqual(mgr.current.reasoning_depth, 9)

        restored = mgr.rollback_to_previous()
        self.assertEqual(restored.version, original.version)
        self.assertEqual(restored.reasoning_depth, original.reasoning_depth)
        self.assertEqual(mgr.current.reasoning_depth, 3)

    def test_rollback_with_no_history_returns_none(self):
        mgr = CognitivePlasticityManager()
        # Nothing to roll back to from the initial state.
        result = mgr.rollback_to_previous()
        self.assertIsNone(result)


class TestSecurityBoundaryPathMatching(unittest.TestCase):
    """
    Found via real-world Termux/Android testing: SecurityBoundary.authorize()
    compared str(Path(target).resolve()).startswith(str(forbidden_path)) to
    decide whether a path was forbidden. This has two problems:
      1. It is a bare string-prefix check, so "/etc/shadowbackup" would
         incorrectly match "/etc/shadow" as forbidden (over-blocking a
         legitimate path).
      2. Path.resolve() behavior for a non-existent absolute path is
         platform-dependent. On Termux/Android (where /etc/shadow does not
         exist as a real file), this caused the comparison to silently fail
         to match, so authorize("write_file", "/etc/shadow", WORKSPACE_WRITE)
         incorrectly returned True -- a genuine security gate failure,
         reproduced live: `1 failed, 120 passed` with
         `AssertionError: True is not false` on
         test_security_boundary_authorization.
    Fixed to use existence-independent path-component comparison with a
    correctly-anchored string fallback (checks for an exact match or a
    path-separator-bounded prefix, never a bare substring).
    """
    def test_forbidden_path_blocked_regardless_of_resolve_behavior(self):
        import tempfile
        from zerion.runtime.security import SecurityBoundary, PermissionLevel
        with tempfile.TemporaryDirectory() as d:
            sb = SecurityBoundary(workspace_root=d)
            self.assertFalse(sb.authorize("write_file", "/etc/shadow", PermissionLevel.WORKSPACE_WRITE))
            self.assertFalse(sb.authorize("write_file", "/root", PermissionLevel.WORKSPACE_WRITE))
            self.assertFalse(sb.authorize("write_file", "/root/anything", PermissionLevel.WORKSPACE_WRITE))

    def test_similarly_named_path_is_not_falsely_blocked(self):
        import tempfile
        from zerion.runtime.security import SecurityBoundary, PermissionLevel
        with tempfile.TemporaryDirectory() as d:
            sb = SecurityBoundary(workspace_root=d)
            # A bare string-prefix check would incorrectly forbid this.
            self.assertTrue(sb.authorize("write_file", "/etc/shadowbackup", PermissionLevel.WORKSPACE_WRITE))

    def test_legitimate_relative_path_still_permitted(self):
        import tempfile
        from zerion.runtime.security import SecurityBoundary, PermissionLevel
        with tempfile.TemporaryDirectory() as d:
            sb = SecurityBoundary(workspace_root=d)
            self.assertTrue(sb.authorize("read_file", "notes.txt", PermissionLevel.READ_ONLY))


if __name__ == "__main__":
    unittest.main()
