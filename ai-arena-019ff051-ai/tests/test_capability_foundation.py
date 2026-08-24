"""
Slice 5 — Capability Genesis test suite.

Covers: Capability model + registry (versioning, dedup, dependencies),
CapabilitySandbox security tests (os.system / subprocess / filesystem escape /
secret access / network / privilege escalation / destructive / infinite loop),
CapabilityGenesis lifecycle (gap -> design -> generate -> sandbox -> test ->
validate -> register), permissions, monitoring (DEGRADED -> DEPRECATED),
versioning + rollback, the required E2E (Slice 4 evidence -> registered usable
capability that survives restart), and adversarial cases. No LLM involved.

Run with:
    python3 -m unittest tests.test_capability_foundation -v
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.capability import (
    Capability,
    CapabilityHealth,
    CapabilityRegistry,
    CapabilityStatus,
    CapabilityStoreIntegrityError,
    CapabilityType,
    CapabilityValidationError,
    LEAST_PRIVILEGE,
    Permission,
    PermissionPolicy,
)
from zerion.cognitive_os.capability_sandbox import CapabilitySandbox
from zerion.cognitive_os.capability_genesis import CapabilityGenesis
from zerion.cognitive_os.distilled import (
    DistilledExperience,
    DistilledExperienceStore,
    DistilledType,
    ValidationStatus,
)
from zerion.cognitive_os.failure_learning import (
    FailureClassification,
    FailureStore,
)
from zerion.cognitive_os.episode import EpisodeMode, EpisodeStore
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.engine import AscendantEngine


AUTH_FAIL = {
    "action": "execute_tool",
    "error": "tool returned authentication error",
    "classification": FailureClassification.TOOL_FAILURE,
    "signals": ["authentication expired"],
    "recovery_attempt": "retry",
    "recovery_result": "failed",
}


def _validated_prevention_rule(store, episodes=None, signals=None):
    rule = DistilledExperience(
        type=DistilledType.FAILURE_PREVENTION_RULE,
        statement="'execute_tool' fails when authentication expired.",
        conditions="deploy pipeline",
        action="check authentication before executing",
        expected_outcome="execute_tool succeeds when conditions hold",
        confidence=0.85,
        source_episodes=episodes or ["ep_1", "ep_2", "ep_3", "ep_4"],
        validation_status=ValidationStatus.VALIDATED,
        provenance={"source": "experience_distillation",
                    "failure_id": "fail_1",
                    "signals": signals or ["authentication expired"],
                    "repeat_count_at_distillation": 4},
        revision_history=[{"event": "validated"}],
    )
    store.put(rule)
    return rule


# ---------------------------------------------------------------------------
# 1. CAPABILITY MODEL & REGISTRY
# ---------------------------------------------------------------------------

class TestCapabilityModel(unittest.TestCase):
    def test_create_structured_capability(self):
        cap = Capability(name="auth_expiration_detector",
                         description="detects auth expiration",
                         type=CapabilityType.VALIDATOR,
                         required_permissions=list(LEAST_PRIVILEGE))
        self.assertEqual(cap.status, CapabilityStatus.NEEDED)
        self.assertEqual(cap.version, 1)
        self.assertEqual(cap.health, CapabilityHealth.HEALTHY)
        self.assertEqual(set(cap.required_permissions), set(LEAST_PRIVILEGE))
        self.assertTrue(cap.capability_id.startswith("cap_"))

    def test_least_privilege_is_default(self):
        cap = Capability(name="x")
        self.assertEqual(set(cap.required_permissions), set(LEAST_PRIVILEGE))

    def test_empty_name_rejected(self):
        with self.assertRaises(CapabilityValidationError):
            Capability(name="   ")

    def test_serialization_roundtrip(self):
        cap = Capability(name="x", version=2, status=CapabilityStatus.VALIDATED,
                         implementation="def run(p):\n    return {}",
                         required_permissions=[Permission.READ])
        cap2 = Capability.from_dict(cap.to_dict())
        self.assertEqual(cap2.name, "x")
        self.assertEqual(cap2.version, 2)
        self.assertEqual(cap2.status, CapabilityStatus.VALIDATED)
        self.assertEqual(cap2.required_permissions, [Permission.READ])


class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice5_registry_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reg(self):
        return CapabilityRegistry(db_path=os.path.join(self.tmp, "caps.db"),
                                  strict_load=True)

    def test_persistence_restart(self):
        reg1 = self._reg()
        cap = Capability(name="detector", status=CapabilityStatus.REGISTERED,
                         version=1)
        reg1.put(cap)
        reg2 = self._reg()
        loaded = reg2.get(cap.capability_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, CapabilityStatus.REGISTERED)
        self.assertEqual(reg2.active_version("detector").capability_id, cap.capability_id)

    def test_duplicate_active_rejected(self):
        reg = self._reg()
        v1 = Capability(name="cap", status=CapabilityStatus.REGISTERED,
                        implementation="def run(p):\n    return 1")
        reg.put(v1)
        dup = Capability(name="cap", status=CapabilityStatus.VALIDATED,
                         implementation="def run(p):\n    return 2")
        self.assertIsNotNone(reg.find_duplicate_active(dup.name, dup.version,
                                                       dup.fingerprint))

    def test_dependency_inspection(self):
        reg = self._reg()
        base = Capability(name="base", status=CapabilityStatus.REGISTERED)
        reg.put(base)
        ok, missing = reg.resolve_dependencies(
            Capability(name="consumer", dependencies=["base"]))
        self.assertTrue(ok)
        ok2, missing2 = reg.resolve_dependencies(
            Capability(name="consumer2", dependencies=["ghost"]))
        self.assertFalse(ok2)
        self.assertEqual(missing2, ["ghost"])

    def test_corrupt_row_strict_raises(self):
        reg1 = self._reg()
        reg1.put(Capability(name="x"))
        conn = sqlite3.connect(os.path.join(self.tmp, "caps.db"))
        conn.execute("UPDATE capabilities SET payload = ?", ("{broken",))
        conn.commit()
        conn.close()
        with self.assertRaises(CapabilityStoreIntegrityError):
            self._reg()


# ---------------------------------------------------------------------------
# 2. SANDBOX SECURITY TESTS
# ---------------------------------------------------------------------------

class TestCapabilitySandboxSecurity(unittest.TestCase):
    def setUp(self):
        self.sb = CapabilitySandbox(default_timeout_s=2.0)

    def _run(self, code, payload=None):
        return self.sb.run_artifact(code, payload or {})

    def test_benign_artifact_runs(self):
        r = self._run("def run(p):\n    return {'success': True, 'detected': 'x' in str(p.get('m', ''))}",
                      {"m": "x"})
        self.assertTrue(r["success"])
        self.assertEqual(r["result"]["detected"], True)

    def test_os_system_blocked(self):
        r = self._run("def run(p):\n    import os\n    os.system('rm -rf /')\n    return {'success': True}")
        self.assertFalse(r["success"])
        self.assertTrue(r["blocked"])
        self.assertIn("import", r["violation"])

    def test_unrestricted_subprocess_blocked(self):
        r = self._run("def run(p):\n    import subprocess\n    subprocess.Popen(['ls'])\n    return {'success': True}")
        self.assertTrue(r["blocked"])

    def test_filesystem_escape_blocked(self):
        r = self._run("def run(p):\n    open('/etc/x')\n    return {'success': True}")
        self.assertTrue(r["blocked"])
        self.assertIn("forbidden call", r["violation"])

    def test_secret_access_blocked(self):
        r = self._run("def run(p):\n    import os\n    return os.environ")
        self.assertTrue(r["blocked"])

    def test_network_access_blocked(self):
        r = self._run("def run(p):\n    import socket\n    return {'success': True}")
        self.assertTrue(r["blocked"])

    def test_privilege_escalation_blocked(self):
        r = self._run("def run(p):\n    import os\n    os.setuid(0)\n    return {'success': True}")
        self.assertTrue(r["blocked"])

    def test_destructive_command_string_blocked(self):
        r = self._run("def run(p):\n    return {'success': True, 'cmd': 'rm -rf /tmp'}")
        self.assertTrue(r["blocked"])
        self.assertIn("dangerous command", r["violation"])

    def test_introspection_escape_blocked(self):
        r = self._run("def run(p):\n    return ().__class__.__bases__[0].__subclasses__()")
        self.assertTrue(r["blocked"])

    def test_infinite_loop_times_out(self):
        r = self._run("def run(p):\n    while True:\n        pass", {})
        self.assertFalse(r["success"])
        self.assertTrue(r["blocked"])
        self.assertIn("timed out", r["violation"])

    def test_looks_valid_but_crashes(self):
        r = self._run("def run(p):\n    raise RuntimeError('boom')")
        self.assertFalse(r["success"])
        self.assertTrue(r["blocked"])


# ---------------------------------------------------------------------------
# 3. CAPABILITY GENESIS LIFECYCLE
# ---------------------------------------------------------------------------

class _GenesisHarness:
    def __init__(self, tmp, policy=None):
        self.tmp = tmp
        self.registry = CapabilityRegistry(db_path=os.path.join(tmp, "caps.db"),
                                           strict_load=True)
        self.distilled = DistilledExperienceStore(
            db_path=os.path.join(tmp, "distilled.db"), strict_load=True)
        self.failures = FailureStore(db_path=os.path.join(tmp, "f.db"),
                                     strict_load=True)
        self.episodes = EpisodeStore(db_path=os.path.join(tmp, "ep.db"),
                                     strict_load=True)
        self.genesis = CapabilityGenesis(
            registry=self.registry, sandbox=CapabilitySandbox(default_timeout_s=2.0),
            distilled_store=self.distilled, failure_store=self.failures,
            permission_policy=policy or PermissionPolicy())


class TestGapDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice5_gap_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gap_from_validated_prevention_rule(self):
        h = _GenesisHarness(self.tmp)
        _validated_prevention_rule(h.distilled)
        gaps = h.genesis.detect_gaps()
        self.assertGreaterEqual(len(gaps), 1)
        validator = next(g for g in gaps if g.type == CapabilityType.VALIDATOR)
        self.assertEqual(validator.status, CapabilityStatus.NEEDED)
        self.assertEqual(validator.metadata["signals"], ["authentication expired"])
        self.assertEqual(validator.source_rules,
                         [h.distilled.list()[0].id])
        # Experience -> candidate capability, never auto-trusted: still NEEDED.
        self.assertNotEqual(validator.status, CapabilityStatus.REGISTERED)
        self.assertEqual(validator.implementation, "")

    def test_gap_from_repeated_failure(self):
        from zerion.cognitive_os.failure_learning import FailureLearning
        h = _GenesisHarness(self.tmp)
        fl = FailureLearning(h.failures)
        for i in range(4):
            fl.record_failure(episode_id=f"ep_{i}", action="run_deploy",
                              error="boom", signals=["disk full"])
        gaps = h.genesis.detect_gaps()
        heuristic = next((g for g in gaps if g.type == CapabilityType.HEURISTIC), None)
        self.assertIsNotNone(heuristic)
        self.assertIn("run_deploy", heuristic.name)
        self.assertEqual(heuristic.metadata["gap"]["frequency"], 4)

    def test_gap_detection_is_deterministic_and_deduped(self):
        h = _GenesisHarness(self.tmp)
        _validated_prevention_rule(h.distilled)
        first = h.genesis.detect_gaps()
        second = h.genesis.detect_gaps()
        # A second call finds the capability already covered — no duplicates.
        self.assertEqual(second, [])
        self.assertEqual(h.registry.count(), len(first))

    def test_no_auto_generation(self):
        h = _GenesisHarness(self.tmp)
        _validated_prevention_rule(h.distilled)
        h.genesis.detect_gaps()
        for cap in h.registry.list():
            self.assertEqual(cap.implementation, "")


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice5_life_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _capability_through_sandbox(self, h, implementation=None):
        _validated_prevention_rule(h.distilled)
        cap = h.genesis.detect_gaps()[0]
        cap = h.genesis.design(cap)
        cap = h.genesis.generate(cap, implementation=implementation)
        cap = h.genesis.sandbox(cap)
        return cap

    def test_design_fills_contract(self):
        h = _GenesisHarness(self.tmp)
        _validated_prevention_rule(h.distilled)
        cap = h.genesis.detect_gaps()[0]
        cap = h.genesis.design(cap)
        self.assertEqual(cap.status, CapabilityStatus.DESIGNED)
        design = cap.metadata["design"]
        for key in ("purpose", "inputs", "outputs", "dependencies", "procedure",
                    "permissions", "success_criteria", "failure_criteria",
                    "test_strategy", "rollback_strategy", "resource_requirements"):
            self.assertIn(key, design)
        self.assertEqual(set(cap.required_permissions), set(LEAST_PRIVILEGE))

    def test_generate_marks_untrusted(self):
        h = _GenesisHarness(self.tmp)
        _validated_prevention_rule(h.distilled)
        cap = h.genesis.detect_gaps()[0]
        cap = h.genesis.design(cap)
        cap = h.genesis.generate(cap)
        self.assertEqual(cap.status, CapabilityStatus.GENERATED)
        self.assertIn("def run(payload)", cap.implementation)
        self.assertIn("authentication expired", cap.implementation)

    def test_sandbox_rejects_malicious_implementation(self):
        h = _GenesisHarness(self.tmp)
        cap = self._capability_through_sandbox(
            h, implementation="def run(p):\n    import os\n    os.system('rm -rf /')\n    return {'success': True}")
        self.assertEqual(cap.status, CapabilityStatus.REJECTED)
        self.assertTrue(any("sandbox" in str(e.get("reason", ""))
                            for e in cap.validation_evidence))

    def test_sandbox_rejects_excessive_permissions(self):
        h = _GenesisHarness(self.tmp)  # policy approves nothing high-risk
        _validated_prevention_rule(h.distilled)
        cap = h.genesis.detect_gaps()[0]
        cap = h.genesis.design(cap)
        cap.required_permissions = [Permission.READ, Permission.FINANCIAL]
        cap = h.genesis.generate(cap)
        cap = h.genesis.sandbox(cap)
        self.assertEqual(cap.status, CapabilityStatus.REJECTED)
        self.assertIn("permission policy denied", cap.validation_evidence[-1]["reason"])

    def test_sandbox_allows_policy_approved_high_risk(self):
        h = _GenesisHarness(self.tmp, policy=PermissionPolicy(approved={Permission.FINANCIAL}))
        _validated_prevention_rule(h.distilled)
        cap = h.genesis.detect_gaps()[0]
        cap = h.genesis.design(cap)
        cap.required_permissions = [Permission.READ, Permission.FINANCIAL]
        cap = h.genesis.generate(cap)
        cap = h.genesis.sandbox(cap)
        self.assertEqual(cap.status, CapabilityStatus.SANDBOXED)

    def test_full_lifecycle_to_registered(self):
        h = _GenesisHarness(self.tmp)
        cap = self._capability_through_sandbox(h)
        self.assertEqual(cap.status, CapabilityStatus.SANDBOXED)
        cap = h.genesis.test(cap)
        self.assertEqual(cap.status, CapabilityStatus.TESTED)
        self.assertEqual(len(cap.test_results), 4)
        self.assertEqual(cap.success_rate, 1.0)
        cap = h.genesis.validate(cap)
        self.assertEqual(cap.status, CapabilityStatus.VALIDATED)
        cap = h.genesis.register(cap)
        self.assertEqual(cap.status, CapabilityStatus.REGISTERED)
        # Executed on a controlled case; the tests determined success.
        outcome = h.genesis.execute(cap, {"message": "error: authentication expired"})
        self.assertTrue(outcome["success"])
        self.assertTrue(outcome["result"]["detected"])
        outcome2 = h.genesis.execute(cap, {"message": "all good"})
        self.assertFalse(outcome2["result"]["detected"])

    def test_validate_requires_actual_test_results(self):
        """'generated successfully' is never validation."""
        h = _GenesisHarness(self.tmp)
        cap = self._capability_through_sandbox(h)
        cap = h.genesis.test(cap)
        # Strip the real test results, leaving only the claim.
        cap.test_results = []
        cap.validation_evidence.append({"type": "claim", "claim": "generated successfully"})
        h.registry.put(cap)
        cap = h.genesis.validate(cap)
        self.assertEqual(cap.status, CapabilityStatus.REJECTED)
        self.assertIn("actual test results", cap.validation_evidence[-1]["reason"])

    def test_validate_rejects_failing_tests(self):
        h = _GenesisHarness(self.tmp)
        bad = "def run(payload):\n    return {'success': False, 'detected': False}"
        cap = self._capability_through_sandbox(h, implementation=bad)
        cap = h.genesis.test(cap)
        cap = h.genesis.validate(cap)
        self.assertEqual(cap.status, CapabilityStatus.REJECTED)

    def test_register_never_duplicates_active_definition(self):
        h = _GenesisHarness(self.tmp)
        cap = self._capability_through_sandbox(h)
        cap = h.genesis.test(cap)
        cap = h.genesis.validate(cap)
        cap = h.genesis.register(cap)
        self.assertEqual(cap.status, CapabilityStatus.REGISTERED)
        # A conflicting definition becomes a pending NEW VERSION — it never
        # replaces or duplicates the active capability (v1 stays active alone).
        dup = Capability(name=cap.name, implementation="def run(p):\n    return 2",
                         status=CapabilityStatus.VALIDATED)
        h.registry.put(dup)
        dup = h.genesis.register(dup)
        self.assertEqual(dup.version, 2)
        self.assertEqual(dup.status, CapabilityStatus.VALIDATED)  # pending, not active
        active = h.registry.active_version(cap.name)
        self.assertEqual(active.capability_id, cap.capability_id)  # v1 still active
        actives = [c for c in h.registry.versions(cap.name) if c.is_active]
        self.assertEqual(len(actives), 1)

    def test_false_validation_evidence_not_accepted(self):
        h = _GenesisHarness(self.tmp)
        cap = self._capability_through_sandbox(h)
        cap = h.genesis.test(cap)
        # Fake evidence claiming success without any real test run.
        cap.test_results = []
        cap.validation_evidence = [{"type": "test_summary", "tests": 0,
                                    "passed": 0, "success_rate": 1.0}]
        h.registry.put(cap)
        cap = h.genesis.validate(cap)
        self.assertEqual(cap.status, CapabilityStatus.REJECTED)


# ---------------------------------------------------------------------------
# 4. MONITORING, VERSIONING, ROLLBACK
# ---------------------------------------------------------------------------

class TestMonitoringVersioning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice5_mon_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _registered(self, h, name="detector"):
        _validated_prevention_rule(h.distilled)
        cap = h.genesis.detect_gaps()[0]
        cap = h.genesis.design(cap)
        cap = h.genesis.generate(cap)
        cap = h.genesis.sandbox(cap)
        cap = h.genesis.test(cap)
        cap = h.genesis.validate(cap)
        return h.genesis.register(cap)

    def test_repeated_failure_degrades_then_deprecates(self):
        h = _GenesisHarness(self.tmp)
        cap = self._registered(h)
        # 3 consecutive failures -> health DEGRADED (flagged, not silently active)
        for _ in range(3):
            cap = h.genesis.record_usage(cap, success=False)
        self.assertEqual(cap.health, CapabilityHealth.DEGRADED)
        self.assertEqual(cap.consecutive_failures, 3)
        # 5 total -> DEPRECATED — never silently kept active
        for _ in range(2):
            cap = h.genesis.record_usage(cap, success=False)
        self.assertEqual(cap.status, CapabilityStatus.DEPRECATED)
        self.assertEqual(cap.health, CapabilityHealth.FAILING)
        self.assertFalse(cap.is_active)

    def test_recovery_after_degradation(self):
        h = _GenesisHarness(self.tmp)
        cap = self._registered(h)
        for _ in range(3):
            cap = h.genesis.record_usage(cap, success=False)
        self.assertEqual(cap.health, CapabilityHealth.DEGRADED)
        cap = h.genesis.record_usage(cap, success=True)
        self.assertEqual(cap.health, CapabilityHealth.HEALTHY)
        self.assertEqual(cap.consecutive_failures, 0)

    def test_usage_metrics_tracked(self):
        h = _GenesisHarness(self.tmp)
        cap = self._registered(h)
        cap = h.genesis.record_usage(cap, success=True, latency_ms=12.5,
                                     resource_cost=1.0)
        cap = h.genesis.record_usage(cap, success=False, latency_ms=99.0)
        self.assertEqual(cap.usage_count, 2)
        self.assertEqual(cap.success_rate, 0.5)
        self.assertIsNotNone(cap.last_used)

    def test_new_version_does_not_auto_replace(self):
        h = _GenesisHarness(self.tmp)
        v1 = self._registered(h)
        self.assertEqual(v1.version, 1)
        # A newer implementation registers as a pending version, not active.
        v2 = Capability(
            name=v1.name, description="v2",
            type=CapabilityType.VALIDATOR,
            implementation="def run(payload):\n    return {'success': True, 'detected': True}",
            status=CapabilityStatus.VALIDATED,
            success_rate=0.9, failure_rate=0.0)
        h.registry.put(v2)
        v2 = h.genesis.register(v2)
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.status, CapabilityStatus.VALIDATED)  # pending, not active
        self.assertEqual(h.registry.active_version(v1.name).version, 1)

    def test_promote_requires_evidence(self):
        h = _GenesisHarness(self.tmp)
        v1 = self._registered(h)
        v1.success_rate = 0.9
        h.registry.put(v1)
        weak_v2 = Capability(
            name=v1.name, description="weaker v2",
            type=CapabilityType.VALIDATOR,
            implementation="def run(payload):\n    return {'success': False}",
            status=CapabilityStatus.VALIDATED,
            success_rate=0.3, failure_rate=0.7)
        h.registry.put(weak_v2)
        weak_v2 = h.genesis.register(weak_v2)
        result = h.genesis.promote(v1.name, weak_v2.version)
        self.assertFalse(result["ok"])
        self.assertIn("evidence", result["reason"])

    def test_promote_with_evidence(self):
        h = _GenesisHarness(self.tmp)
        v1 = self._registered(h)
        v1.success_rate = 0.9
        h.registry.put(v1)
        strong_v2 = Capability(
            name=v1.name, description="stronger v2",
            type=CapabilityType.VALIDATOR,
            implementation="def run(payload):\n    return {'success': True, 'detected': True}",
            status=CapabilityStatus.VALIDATED,
            success_rate=0.95, failure_rate=0.0)
        h.registry.put(strong_v2)
        strong_v2 = h.genesis.register(strong_v2)
        result = h.genesis.promote(v1.name, strong_v2.version)
        self.assertTrue(result["ok"])
        self.assertEqual(h.registry.active_version(v1.name).version, strong_v2.version)

    def test_rollback_restores_previous_version(self):
        h = _GenesisHarness(self.tmp)
        v1 = self._registered(h)
        v1.success_rate = 0.9
        h.registry.put(v1)
        v2 = Capability(
            name=v1.name, type=CapabilityType.VALIDATOR,
            implementation="def run(payload):\n    return {'success': True, 'detected': True}",
            status=CapabilityStatus.VALIDATED, success_rate=0.95, failure_rate=0.0)
        h.registry.put(v2)
        v2 = h.genesis.register(v2)
        h.genesis.promote(v1.name, v2.version)
        self.assertEqual(h.registry.active_version(v1.name).version, 2)
        result = h.genesis.rollback(v1.name, "regression in v2")
        self.assertTrue(result["ok"])
        self.assertEqual(result["restored_version"], 1)
        active = h.registry.active_version(v1.name)
        self.assertEqual(active.version, 1)
        self.assertEqual(active.status, CapabilityStatus.REGISTERED)
        # The rolled-back version is deprecated, evidence preserved in history.
        v2_dep = h.registry.get_by_name_version(v1.name, 2)
        self.assertEqual(v2_dep.status, CapabilityStatus.DEPRECATED)
        self.assertTrue(any(e["event"] == "rollback" for e in v2_dep.history))

    def test_rollback_failure_recorded_not_silent(self):
        h = _GenesisHarness(self.tmp)
        v1 = self._registered(h)
        result = h.genesis.rollback(v1.name, "no prior version")
        self.assertFalse(result["ok"])
        # The capability stays intact and active.
        self.assertEqual(h.registry.active_version(v1.name).version, 1)
        self.assertTrue(any(e["event"] == "rollback_failed" for e in v1.history))

    def test_incompatible_version_missing_dependency_rejected(self):
        h = _GenesisHarness(self.tmp)
        cap = self._registered(h)
        v2 = Capability(
            name=cap.name, type=CapabilityType.VALIDATOR,
            dependencies=["ghost_capability"],
            implementation="def run(payload):\n    return {'success': True, 'detected': True}",
            status=CapabilityStatus.TESTED, success_rate=1.0,
            test_results=[{"name": "t", "passed": True}])
        h.registry.put(v2)
        v2 = h.genesis.validate(v2)
        self.assertEqual(v2.status, CapabilityStatus.REJECTED)
        self.assertIn("dependencies", v2.validation_evidence[-1]["reason"])


# ---------------------------------------------------------------------------
# 5. RUNTIME INTEGRATION + REQUIRED E2E
# ---------------------------------------------------------------------------

class TestSlice5RuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice5_rt_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def _seed_validated_rule(self, rt):
        """Full Slice 4 path: repeated auth-expiration failures -> validated
        prevention rule (evidence the E2E starts from)."""
        for _ in range(4):
            ep = await rt.start_episode("execute tool for deployment",
                                        mode=EpisodeMode.TEST)
            await rt.complete_episode(ep.episode_id, success=False, failures=[AUTH_FAIL])
        rules = [i for i in rt.distilled_store.list()
                 if i.type == DistilledType.FAILURE_PREVENTION_RULE]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].validation_status, ValidationStatus.VALIDATED)
        return rules[0]

    async def test_required_e2e_experience_to_registered_usable_capability(self):
        """Slice 4 evidence (repeated auth-expiration failure, validated rule) ->
        NEED -> DESIGN -> GENERATE -> SANDBOX -> TEST -> VALIDATE -> REGISTER ->
        controlled execution -> measure -> persist -> restart -> retrieve -> still
        registered and usable. The tests determine success — nothing is hard-coded."""
        dir1 = os.path.join(self.tmp, "data")
        rt = CognitiveRuntime(data_dir=dir1)
        await rt.start()
        rule = await self._seed_validated_rule(rt)

        # 1. Detect the capability gap (no auto-generation).
        gaps = await rt.detect_capability_gaps()
        validator = next(g for g in gaps if g.type == CapabilityType.VALIDATOR)
        self.assertEqual(validator.status, CapabilityStatus.NEEDED)
        self.assertEqual(validator.implementation, "")
        self.assertEqual(validator.source_rules, [rule.id])
        # Gap -> question -> Slice 1 attention (verified INVESTIGATING later).
        gap_qs = [q for q in rt.question_store.list() if q.source == "CAPABILITY_GAP"]
        self.assertGreaterEqual(len(gap_qs), 1)

        # 2-8. Pipeline with explicit stages.
        cap = await rt.design_capability(validator.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.DESIGNED)
        cap = await rt.generate_capability(cap.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.GENERATED)
        self.assertIn("authentication expired", cap.implementation)
        cap = await rt.sandbox_capability(cap.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.SANDBOXED)
        cap = await rt.test_capability(cap.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.TESTED)
        self.assertEqual(len(cap.test_results), 4)
        cap = await rt.validate_capability(cap.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.VALIDATED)
        cap = await rt.register_capability(cap.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.REGISTERED)

        # 8-9. Execute on a controlled test case and measure.
        out = rt.execute_capability(cap.capability_id,
                                    {"message": "error: authentication expired"})
        self.assertTrue(out["success"])
        self.assertTrue(out["result"]["detected"])
        self.assertGreaterEqual(out["latency_ms"], 0.0)
        self.assertEqual(out["capability"].usage_count, 1)
        out2 = rt.execute_capability(cap.capability_id, {"message": "all good"})
        self.assertFalse(out2["result"]["detected"])
        # Gap question was attended to (investigation happened).
        for q in gap_qs:
            self.assertEqual(q.status.value, "INVESTIGATING")

        # 10. Persisted (each stage persists).
        self.assertEqual(rt.capability_registry.get(cap.capability_id).status,
                         CapabilityStatus.REGISTERED)
        await rt.stop()

        # 11-13. Restart, retrieve, verify registered and usable.
        rt2 = CognitiveRuntime(data_dir=dir1)
        await rt2.start()
        loaded = rt2.get_capability(cap.capability_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, CapabilityStatus.REGISTERED)
        self.assertEqual(loaded.version, 1)
        active = rt2.capability_registry.active_version(cap.name)
        self.assertEqual(active.capability_id, cap.capability_id)
        out3 = rt2.execute_capability(cap.capability_id,
                                      {"message": "error: authentication expired"})
        self.assertTrue(out3["result"]["detected"])
        self.assertEqual(out3["capability"].usage_count, 3)
        await rt2.stop()

    async def test_capability_gap_attention_and_events(self):
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()
        await self._seed_validated_rule(rt)
        await rt.detect_capability_gaps()
        replayed = await rt.event_bus.replay_events(limit=500)
        types = [e.event_type for e in replayed]
        self.assertIn(EventType.CAPABILITY_GAP, types)
        gap_qs = [q for q in rt.question_store.list() if q.source == "CAPABILITY_GAP"]
        self.assertGreaterEqual(len(gap_qs), 1)
        self.assertEqual(gap_qs[0].status.value, "INVESTIGATING")
        await rt.stop()

    async def test_full_pipeline_events_on_bus(self):
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()
        await self._seed_validated_rule(rt)
        gaps = await rt.detect_capability_gaps()
        cap = await rt.design_capability(gaps[0].capability_id)
        cap = await rt.generate_capability(cap.capability_id)
        cap = await rt.sandbox_capability(cap.capability_id)
        cap = await rt.test_capability(cap.capability_id)
        cap = await rt.validate_capability(cap.capability_id)
        await rt.register_capability(cap.capability_id)
        replayed = await rt.event_bus.replay_events(limit=500)
        types = [e.event_type for e in replayed]
        for expected in (EventType.CAPABILITY_DESIGNED, EventType.CAPABILITY_GENERATED,
                         EventType.CAPABILITY_SANDBOXED, EventType.CAPABILITY_TESTED,
                         EventType.CAPABILITY_VALIDATED, EventType.CAPABILITY_REGISTERED):
            self.assertIn(expected, types)
        await rt.stop()

    async def test_malicious_generated_capability_never_registers(self):
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()
        await self._seed_validated_rule(rt)
        gaps = await rt.detect_capability_gaps()
        cap = await rt.design_capability(gaps[0].capability_id)
        evil = "def run(p):\n    import os\n    os.system('rm -rf /')\n    return {'success': True}"
        cap = await rt.generate_capability(cap.capability_id, implementation=evil)
        cap = await rt.sandbox_capability(cap.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.REJECTED)
        self.assertNotEqual(cap.status, CapabilityStatus.REGISTERED)
        # Only the NEEDED proposals exist — nothing was generated/registered.
        self.assertFalse(any(c.status == CapabilityStatus.REGISTERED
                             for c in rt.capability_registry.list()))
        self.assertIn(cap.capability_id, [c.capability_id for c in rt.capability_registry.list()])
        await rt.stop()

    async def test_monitoring_deprecates_broken_capability_in_runtime(self):
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()
        await self._seed_validated_rule(rt)
        gaps = await rt.detect_capability_gaps()
        cap = await rt.design_capability(gaps[0].capability_id)
        cap = await rt.generate_capability(cap.capability_id)
        cap = await rt.sandbox_capability(cap.capability_id)
        cap = await rt.test_capability(cap.capability_id)
        cap = await rt.validate_capability(cap.capability_id)
        cap = await rt.register_capability(cap.capability_id)
        for _ in range(5):
            await rt.record_capability_usage(cap.capability_id, success=False)
        cap = rt.get_capability(cap.capability_id)
        self.assertEqual(cap.status, CapabilityStatus.DEPRECATED)
        self.assertEqual(cap.health, CapabilityHealth.FAILING)
        replayed = await rt.event_bus.replay_events(limit=500)
        types = [e.event_type for e in replayed]
        self.assertIn(EventType.CAPABILITY_DEGRADED, types)
        self.assertIn(EventType.CAPABILITY_DEPRECATED, types)
        await rt.stop()


class TestSlice5EngineIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice5_engine_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_engine_wires_capability_layer(self):
        engine = AscendantEngine(data_dir=self.tmp)
        await engine.start()
        rt = engine.cognitive_runtime
        self.assertIsNotNone(rt.capability_registry)
        self.assertIsNotNone(rt.capability_genesis)
        self.assertIsNotNone(rt.capability_sandbox)
        await rt.start_episode("x", mode=EpisodeMode.TEST)
        self.assertEqual(rt.episode_store.count(), 1)
        await engine.stop()


if __name__ == "__main__":
    unittest.main()
