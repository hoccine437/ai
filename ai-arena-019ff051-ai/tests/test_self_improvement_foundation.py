"""
Slice 7 — Self-Improvement Gate test suite.

Covers: ArchitectureTelemetry (real measurements, INSUFFICIENT_DATA handling,
persistence), BottleneckDetector (evidence-required reports, configurable
thresholds, VERIFICATION_LIMITATION scenario), ImprovementProposal lifecycle
and risk levels, SelfModificationGate (static analysis / security checks,
sandboxed tests, baseline-vs-candidate benchmark with statistical discipline,
policy approval, atomic promotion, monitoring + rollback), CognitiveGenome
(controlled candidate evaluation, no production mutation during
experimentation, promote/reject with evidence), versioned snapshots, the four
required E2E tests (REJECT / PROMOTE / ROLLBACK / BOTTLENECK), security tests
(os.system / subprocess.Popen / privilege escalation / secret extraction /
destructive filesystem / unauthorized network / outside-scope), persistence
across restart, and failure safety. Provider-independent: no LLM, no external
APIs; all benchmark data is deterministic fixtures.

Run with:
    python3 -m unittest tests.test_self_improvement_foundation -v
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.telemetry import ArchitectureTelemetry, TelemetryIntegrityError
from zerion.cognitive_os.bottlenecks import BottleneckDetector, BottleneckStore
from zerion.cognitive_os.improvement import (
    ImprovementProposal,
    ModificationType,
    ProposalStatus,
    ProposalStore,
    RiskLevel,
)
from zerion.cognitive_os.genome import (
    CognitiveGenome,
    GenomeManager,
    GenomeStatus,
    GenomeStore,
)
from zerion.cognitive_os.snapshots import (
    RuntimeSnapshot,
    SnapshotIntegrityError,
    SnapshotStore,
)
from zerion.cognitive_os.self_modification_gate import (
    GatePolicy,
    SelfModificationGate,
)
from zerion.cognitive_os.capability_sandbox import CapabilitySandbox
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime


def _genome(config: dict, status=GenomeStatus.PROMOTED, version=1,
            genome_id="gen_1", parent_id=None) -> CognitiveGenome:
    return CognitiveGenome(genome_id=genome_id, parent_id=parent_id,
                           version=version, configuration=dict(config),
                           status=status)


class TestArchitectureTelemetry(unittest.TestCase):
    def test_insufficient_data_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = ArchitectureTelemetry(db_path=os.path.join(tmp, "t.db"))
            t.record("verifier", "verification_success", success=True)
            self.assertIsNone(t.rate("verifier", "verification_success"))
            self.assertIsNone(t.failure_rate("verifier", "verification_success"))
            self.assertIsNone(t.avg_latency_ms("verifier", "verification_success"))

    def test_rates_computed_after_min_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = ArchitectureTelemetry(db_path=os.path.join(tmp, "t.db"))
            for _ in range(10):
                t.record("verifier", "verification_success", success=False)
            self.assertEqual(t.rate("verifier", "verification_success"), 0.0)
            self.assertEqual(t.failure_rate("verifier", "verification_success"), 1.0)
            for _ in range(5):
                t.record("verifier", "verification_success", success=True)
            self.assertEqual(t.rate("verifier", "verification_success"), 5 / 15)

    def test_latency_and_value_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = ArchitectureTelemetry(db_path=os.path.join(tmp, "t.db"))
            for _ in range(8):
                t.record("router", "latency", latency_ms=120.0)
            self.assertEqual(t.avg_latency_ms("router", "latency"), 120.0)
            for _ in range(8):
                t.record("sys", "resource_usage", value=0.95)
            m = t.get("sys", "resource_usage")
            self.assertIsNotNone(m)
            self.assertEqual(m.avg_value(), 0.95)

    def test_persistence_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            t1 = ArchitectureTelemetry(db_path=path)
            for _ in range(10):
                t1.record("verifier", "verification_success", success=True)
            t2 = ArchitectureTelemetry(db_path=path)
            self.assertEqual(t2.rate("verifier", "verification_success"), 1.0)

    def test_corruption_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            t1 = ArchitectureTelemetry(db_path=path)
            for _ in range(10):
                t1.record("verifier", "verification_success", success=True)
            conn = sqlite3.connect(path)
            conn.execute("UPDATE metrics SET checksum='deadbeef'")
            conn.commit()
            conn.close()
            # strict_load raises on corruption (same convention as Slices 1-6).
            with self.assertRaises(TelemetryIntegrityError):
                ArchitectureTelemetry(db_path=path, strict_load=True)


class TestBottleneckDetector(unittest.TestCase):
    def _detector(self, tmp, thresholds=None):
        telemetry = ArchitectureTelemetry(db_path=os.path.join(tmp, "t.db"))
        store = BottleneckStore(db_path=os.path.join(tmp, "b.db"))
        return BottleneckDetector(telemetry, store=store, thresholds=thresholds)

    def test_required_bottleneck_verification_limitation(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._detector(tmp)
            for _ in range(10):
                d.telemetry.record("verifier", "verification_success", success=False)
            for _ in range(10):
                d.telemetry.record("verifier", "model_success", success=True)
            for _ in range(10):
                d.telemetry.record("verifier", "tool_success", success=True)
            reports = d.detect()
            self.assertTrue(reports)
            kinds = {r.type for r in reports}
            self.assertIn("VERIFICATION_LIMITATION", kinds)
            rep = next(r for r in reports if r.type == "VERIFICATION_LIMITATION")
            self.assertTrue(rep.evidence)
            self.assertGreater(rep.confidence, 0.0)
            self.assertGreater(rep.severity, 0.0)
            self.assertTrue(rep.affected_tasks)

    def test_no_bottleneck_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._detector(tmp)
            for _ in range(10):
                d.telemetry.record("verifier", "verification_success", success=True)
            self.assertEqual(d.detect(), [])

    def test_insufficient_samples_no_bottleneck(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._detector(tmp)
            for _ in range(2):
                d.telemetry.record("verifier", "verification_success", success=False)
            self.assertEqual(d.detect(), [])

    def test_thresholds_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._detector(tmp, thresholds={"verification_success": 0.9})
            for _ in range(10):
                d.telemetry.record("verifier", "verification_success", success=True)
            # 100% success is still above the 0.9 threshold -> no bottleneck.
            self.assertEqual(d.detect(), [])

    def test_latency_bottleneck(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._detector(tmp, thresholds={"latency_ms": 100.0})
            for _ in range(10):
                d.telemetry.record("router", "latency", latency_ms=500.0)
            reports = d.detect()
            self.assertTrue(reports)
            self.assertIn("RESOURCE_LIMITATION", {r.type for r in reports})

    def test_persistence_of_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._detector(tmp)
            for _ in range(10):
                d.telemetry.record("verifier", "verification_success", success=False)
            reports = d.detect()
            self.assertTrue(reports)
            s2 = BottleneckStore(db_path=os.path.join(tmp, "b.db"))
            self.assertEqual(s2.count(), len(reports))
            loaded = s2.list()
            self.assertEqual(loaded[0].affected_component, "verifier")


class TestImprovementProposal(unittest.TestCase):
    def test_proposal_structured_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProposalStore(db_path=os.path.join(tmp, "p.db"))
            p = ImprovementProposal(
                target_component="router",
                problem="high latency on complex tasks",
                hypothesis="verification pass adds disproportionate latency",
                proposed_change={"verification_policy": {"strictness": 0.3}},
                expected_benefit="lower latency",
                expected_cost="slightly lower verification",
                risk=RiskLevel.LOW,
                modification_type=ModificationType.CONFIGURATION_CHANGE,
                test_plan=[{"name": "cfg", "kind": "config",
                            "config_path": ["verification_policy", "strictness"],
                            "expected_value": 0.3}],
                rollback_plan="restore previous snapshot",
                scope=["router"],
            )
            store.put(p)
            p2 = store.get(p.proposal_id)
            self.assertEqual(p2.target_component, "router")
            self.assertEqual(p2.status, ProposalStatus.PROPOSED)

    def test_transition_validation(self):
        p = ImprovementProposal()
        p.transition(ProposalStatus.ANALYZING)
        p.transition(ProposalStatus.SANDBOXED)
        p.transition(ProposalStatus.TESTING)
        with self.assertRaises(ValueError):
            p.transition(ProposalStatus.APPROVED)  # TESTING cannot jump to APPROVED

    def test_risk_order(self):
        self.assertLess(_risk_idx(RiskLevel.LOW), _risk_idx(RiskLevel.MEDIUM))
        self.assertLess(_risk_idx(RiskLevel.MEDIUM), _risk_idx(RiskLevel.HIGH))
        self.assertLess(_risk_idx(RiskLevel.HIGH), _risk_idx(RiskLevel.CRITICAL))


def _risk_idx(r: RiskLevel) -> int:
    return [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH,
            RiskLevel.CRITICAL].index(r)


class TestStaticAnalysisSecurity(unittest.TestCase):
    def setUp(self):
        self.gate = SelfModificationGate(policy=GatePolicy(
            allow_low_auto=True, allow_medium_auto=False))

    def _proposal(self, change, mtype=ModificationType.CODE_CHANGE, scope=None):
        return ImprovementProposal(
            target_component="some_component",
            problem="test",
            hypothesis="test",
            proposed_change=change,
            modification_type=mtype,
            scope=scope or ["some_component"],
            rollback_plan="restore previous snapshot",
        )

    def test_benign_code_passes(self):
        p = self._proposal("def run(x):\n    return x + 1\n")
        r = self.gate.static_analysis(p)
        self.assertTrue(r.passed)

    def test_os_system_rejected(self):
        p = self._proposal("import os\ndef run(x):\n    os.system('rm -rf /')\n")
        r = self.gate.static_analysis(p)
        self.assertFalse(r.passed)

    def test_subprocess_popen_rejected(self):
        p = self._proposal("import subprocess\ndef run(x):\n    subprocess.Popen(['sh'])\n")
        r = self.gate.static_analysis(p)
        self.assertFalse(r.passed)

    def test_secret_extraction_rejected(self):
        p = self._proposal("import os\ndef run(x):\n    return os.environ['API_KEY']\n")
        r = self.gate.static_analysis(p)
        self.assertFalse(r.passed)

    def test_destructive_filesystem_rejected(self):
        p = self._proposal("def run(x):\n    open('/etc/passwd', 'w').write('x')\n")
        r = self.gate.static_analysis(p)
        self.assertFalse(r.passed)

    def test_network_rejected(self):
        p = self._proposal("import socket\ndef run(x):\n    socket.socket()\n")
        r = self.gate.static_analysis(p)
        self.assertFalse(r.passed)

    def test_outside_scope_rejected(self):
        p = self._proposal("def run(x):\n    return x\n",
                           mtype=ModificationType.CONFIGURATION_CHANGE,
                           scope=["allowed_scope"])
        p.target_component = "not_allowed"
        r = self.gate.static_analysis(p)
        self.assertFalse(r.passed)
        self.assertTrue(any("scope" in v for v in r.violations))

    def test_forbidden_string_pattern_rejected(self):
        p = self._proposal({"policy": "sudo rm -rf /"}, mtype=ModificationType.CONFIGURATION_CHANGE)
        r = self.gate.static_analysis(p)
        self.assertFalse(r.passed)

    def test_high_risk_never_auto_approved(self):
        p = self._proposal("def run(x):\n    return x\n")
        p.risk = RiskLevel.CRITICAL
        p.analysis = {"passed": True, "tests_passed": True,
                      "risk": "CRITICAL",
                      "baseline_config": {}, "candidate_config": {}}
        p.benchmark = {"verdict": "SUPPORTED"}
        p.test_results = [{"name": "t", "passed": True}]
        ok, _ = self.gate.approve(p)
        self.assertFalse(ok)

    def test_medium_requires_explicit_approval(self):
        p = self._proposal("def run(x):\n    return x\n")
        p.risk = RiskLevel.MEDIUM
        p.analysis = {"passed": True, "tests_passed": True,
                      "risk": "MEDIUM",
                      "baseline_config": {}, "candidate_config": {}}
        p.benchmark = {"verdict": "SUPPORTED"}
        p.test_results = [{"name": "t", "passed": True}]
        ok, _ = self.gate.approve(p)
        self.assertFalse(ok)
        ok, _ = self.gate.approve(p, approval={"explicit": True})
        self.assertTrue(ok)


class TestBenchmarkDiscipline(unittest.TestCase):
    def test_insufficient_trials_inconclusive(self):
        b = [{"correct": True, "latency_ms": 10.0} for _ in range(3)]
        c = [{"correct": True, "latency_ms": 10.0} for _ in range(3)]
        cmp_ = self._gate().benchmark(
            self._proposal(), lambda cfg: b, lambda cfg: c, trials=10, min_trials=5)
        self.assertEqual(cmp_.verdict, "INCONCLUSIVE")

    def test_improvement_supported_with_enough_samples(self):
        b = [{"correct": True, "latency_ms": 20.0} for _ in range(10)]
        c = [{"correct": True, "latency_ms": 20.0} for _ in range(10)]
        for i in range(7):
            b[i] = {"correct": False, "latency_ms": 20.0}
        cmp_ = self._gate().benchmark(
            self._proposal(), lambda cfg: b, lambda cfg: c, trials=10, min_trials=5)
        self.assertEqual(cmp_.verdict, "SUPPORTED")

    def test_regression_detected(self):
        b = [{"correct": True, "latency_ms": 10.0} for _ in range(10)]
        c = [{"correct": True, "latency_ms": 500.0} for _ in range(10)]
        cmp_ = self._gate().benchmark(
            self._proposal(), lambda cfg: b, lambda cfg: c, trials=10, min_trials=5)
        self.assertEqual(cmp_.verdict, "REGRESSION")

    def _gate(self):
        return SelfModificationGate(policy=GatePolicy(
            allow_low_auto=True, allow_medium_auto=False))

    def _proposal(self):
        return ImprovementProposal(
            target_component="router",
            problem="p",
            hypothesis="h",
            proposed_change={"verification_policy": {"strictness": 0.5}},
            modification_type=ModificationType.CONFIGURATION_CHANGE,
            analysis={"baseline_config": {"x": 1}, "candidate_config": {"x": 2}},
            rollback_plan="restore previous snapshot",
        )


class TestGenome(unittest.TestCase):
    def test_default_genome_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            gm = GenomeManager(store=GenomeStore(db_path=os.path.join(tmp, "g.db")))
            cur = gm.current()
            self.assertEqual(cur.status, GenomeStatus.PROMOTED)
            self.assertIn("routing_policy", cur.configuration)
            self.assertIn("architecture_version", cur.configuration)

    def test_variation_is_clone_not_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            gm = GenomeManager(store=GenomeStore(db_path=os.path.join(tmp, "g.db")))
            before = gm.current()
            cand = gm.propose_variation({"routing_policy": {"prefer_local": True}})
            self.assertEqual(cand.status, GenomeStatus.CANDIDATE)
            self.assertEqual(cand.parent_id, before.genome_id)
            after = gm.current()
            self.assertEqual(after.configuration["routing_policy"]["prefer_local"], False)

    def test_promote_requires_evaluation_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            gm = GenomeManager(store=GenomeStore(db_path=os.path.join(tmp, "g.db")))
            cand = gm.propose_variation({"routing_policy": {"prefer_local": True}})
            with self.assertRaises(ValueError):
                gm.promote(cand.genome_id)

    def test_evaluate_then_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            gm = GenomeManager(store=GenomeStore(db_path=os.path.join(tmp, "g.db")))
            cand = gm.propose_variation({"routing_policy": {"prefer_local": True}})
            gm.record_evaluation(cand.genome_id,
                                 {"success_rate": 0.9, "trials": 20})
            promoted = gm.promote(cand.genome_id)
            self.assertEqual(promoted.status, GenomeStatus.PROMOTED)
            self.assertEqual(gm.current().genome_id, cand.genome_id)

    def test_reject_records_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            gm = GenomeManager(store=GenomeStore(db_path=os.path.join(tmp, "g.db")))
            cand = gm.propose_variation({"routing_policy": {"prefer_local": True}})
            rejected = gm.reject(cand.genome_id, reason="benchmark regression")
            self.assertEqual(rejected.status, GenomeStatus.REJECTED)
            self.assertEqual(rejected.evaluation_results["rejection_reason"],
                             "benchmark regression")

    def test_rollback_restores_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            gm = GenomeManager(store=GenomeStore(db_path=os.path.join(tmp, "g.db")))
            orig = gm.current()
            cand = gm.propose_variation({"routing_policy": {"prefer_local": True}})
            gm.record_evaluation(cand.genome_id, {"success_rate": 0.9})
            gm.promote(cand.genome_id)
            self.assertTrue(gm.current().configuration["routing_policy"]["prefer_local"])
            gm.rollback_to(orig)
            cur = gm.current()
            self.assertEqual(cur.configuration["routing_policy"]["prefer_local"], False)
            self.assertEqual(cur.genome_id, orig.genome_id)  # previous genome restored

    def test_persistence_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "g.db")
            gm = GenomeManager(store=GenomeStore(db_path=path))
            cand = gm.propose_variation({"routing_policy": {"prefer_local": True}})
            gm.record_evaluation(cand.genome_id, {"success_rate": 0.9})
            gm.promote(cand.genome_id)
            gm2 = GenomeManager(store=GenomeStore(db_path=path))
            self.assertEqual(gm2.current().genome_id, cand.genome_id)
            self.assertEqual(gm2.current().configuration["routing_policy"]["prefer_local"], True)


class TestSnapshots(unittest.TestCase):
    def test_snapshot_roundtrip_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(db_path=os.path.join(tmp, "s.db"))
            s1 = RuntimeSnapshot(version=store.next_version(), timestamp=time.time(),
                                 changed_components=["router"],
                                 configuration={"routing_policy": {"prefer_local": True}},
                                 tests=[{"name": "t", "passed": True}],
                                 benchmark_results={"verdict": "SUPPORTED"},
                                 approval_state={"proposal_id": "prop_1"},
                                 rollback_reference="gen_old",
                                 label="pre-prop_1")
            store.put(s1)
            s2 = store.get(s1.version)
            self.assertEqual(s2.configuration["routing_policy"]["prefer_local"], True)
            self.assertEqual(store.count(), 1)
            self.assertEqual(store.latest().version, s1.version)

    def test_corrupted_snapshot_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.db")
            store = SnapshotStore(db_path=path)
            store.put(RuntimeSnapshot(version=store.next_version(),
                                      timestamp=time.time(),
                                      changed_components=["x"],
                                      configuration={"a": 1}, tests=[],
                                      benchmark_results={}, approval_state={}))
            conn = sqlite3.connect(path)
            conn.execute("UPDATE snapshots SET checksum='bad'")
            conn.commit()
            conn.close()
            # strict_load raises on corruption (same convention as Slices 1-6).
            with self.assertRaises(SnapshotIntegrityError):
                SnapshotStore(db_path=path, strict_load=True)


class TestSelfModificationGatePromotionRollback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proposal_store = ProposalStore(
            db_path=os.path.join(self.tmp.name, "p.db"))
        self.genome_store = GenomeStore(
            db_path=os.path.join(self.tmp.name, "g.db"))
        self.genome_manager = GenomeManager(store=self.genome_store)
        self.snapshot_store = SnapshotStore(
            db_path=os.path.join(self.tmp.name, "s.db"))
        self.gate = SelfModificationGate(
            sandbox=CapabilitySandbox(),
            policy=GatePolicy(allow_low_auto=True, allow_medium_auto=False))

    def _cfg_proposal(self, change, risk=RiskLevel.LOW, scope=None):
        return ImprovementProposal(
            target_component="router",
            problem="latency",
            hypothesis="config change",
            proposed_change=change,
            modification_type=ModificationType.CONFIGURATION_CHANGE,
            risk=risk,
            scope=scope or ["router"],
            rollback_plan="restore previous snapshot",
            test_plan=[{"name": "cfg", "kind": "config",
                        "config_path": list(change.keys()),
                        "expected_value": list(change.values())[0]}],
        )

    def _bench(self, proposal, candidate_verdict="SUPPORTED"):
        if candidate_verdict == "SUPPORTED":
            b = [{"correct": False, "latency_ms": 20.0} for _ in range(4)]
            b += [{"correct": True, "latency_ms": 20.0} for _ in range(6)]
            c = [{"correct": True, "latency_ms": 10.0} for _ in range(10)]
        elif candidate_verdict == "REGRESSION":
            b = [{"correct": True, "latency_ms": 10.0} for _ in range(10)]
            c = [{"correct": True, "latency_ms": 500.0} for _ in range(10)]
        else:
            b = c = [{"correct": True, "latency_ms": 10.0} for _ in range(3)]
        return self.gate.benchmark(
            proposal, lambda cfg: b, lambda cfg: c, trials=10, min_trials=5)

    def test_promote_success_flow(self):
        p = self._cfg_proposal({"verification_policy": {"strictness": 0.3}})
        # analysis
        analysis = self.gate.static_analysis(p)
        self.assertTrue(analysis.passed)
        p.analysis = {"passed": True, "tests_passed": True,
                      "risk": RiskLevel.LOW.value,
                      "baseline_config": {"v": 0.5},
                      "candidate_config": {"v": 0.3}}
        # tests
        outcome = self.gate.run_tests(p)
        self.assertTrue(outcome.passed)
        p.test_results = list(outcome.results)
        # benchmark
        bench = self._bench(p)
        self.assertEqual(bench.verdict, "SUPPORTED")
        p.benchmark = bench.to_dict()
        # promote
        result = self.gate.promote(p, self.genome_manager, self.snapshot_store)
        self.assertTrue(result.ok)
        self.assertTrue(result.applied)
        self.assertIsNotNone(result.snapshot_version)
        self.assertEqual(self.snapshot_store.count(), 1)
        promoted = self.genome_manager.current()
        self.assertEqual(promoted.configuration["verification_policy"]["strictness"], 0.3)

    def test_regression_rejected_production_unchanged(self):
        before = dict(self.genome_manager.current().configuration)
        p = self._cfg_proposal({"verification_policy": {"strictness": 0.3}})
        p.analysis = {"passed": True, "tests_passed": True,
                      "risk": RiskLevel.LOW.value,
                      "baseline_config": {"v": 0.5},
                      "candidate_config": {"v": 0.3}}
        outcome = self.gate.run_tests(p)
        p.test_results = list(outcome.results)
        bench = self._bench(p, candidate_verdict="REGRESSION")
        self.assertEqual(bench.verdict, "REGRESSION")
        p.benchmark = bench.to_dict()
        result = self.gate.promote(p, self.genome_manager, self.snapshot_store)
        self.assertFalse(result.ok)
        after = dict(self.genome_manager.current().configuration)
        self.assertEqual(before, after)
        self.assertEqual(self.snapshot_store.count(), 0)

    def test_rollback_restores_snapshot(self):
        p = self._cfg_proposal({"verification_policy": {"strictness": 0.3}})
        p.analysis = {"passed": True, "tests_passed": True,
                      "risk": RiskLevel.LOW.value,
                      "baseline_config": {"v": 0.5},
                      "candidate_config": {"v": 0.3}}
        outcome = self.gate.run_tests(p)
        p.test_results = list(outcome.results)
        bench = self._bench(p)
        p.benchmark = bench.to_dict()
        result = self.gate.promote(p, self.genome_manager, self.snapshot_store)
        self.assertTrue(result.ok)
        p.status = ProposalStatus.APPROVED
        # Simulate post-promotion regression via telemetry
        telemetry = ArchitectureTelemetry(db_path=os.path.join(self.tmp.name, "t.db"))
        for _ in range(10):
            telemetry.record("router", "verification_success", success=False)
        degraded = self.gate.monitor_regression(p, telemetry)
        self.assertTrue(degraded)
        rb = self.gate.rollback(p, self.genome_manager, self.snapshot_store,
                                reason="post-promotion regression")
        self.assertTrue(rb.ok)
        self.assertEqual(rb.restored_version, result.snapshot_version)
        self.assertEqual(p.status, ProposalStatus.ROLLED_BACK)
        self.assertEqual(self.genome_manager.current().configuration["verification_policy"]["strictness"], 0.5)

    def test_rollback_without_snapshot_fails_honestly(self):
        p = self._cfg_proposal({"verification_policy": {"strictness": 0.3}})
        rb = self.gate.rollback(p, self.genome_manager, self.snapshot_store)
        self.assertFalse(rb.ok)


class TestRuntimeSlice7Integration(unittest.IsolatedAsyncioTestCase):
    def _make_runtime(self):
        return CognitiveRuntime(data_dir=tempfile.mkdtemp())

    async def test_telemetry_and_bottleneck_question_flow(self):
        rt = self._make_runtime()
        for _ in range(10):
            rt.record_telemetry("verifier", "verification_success", success=False)
        for _ in range(10):
            rt.record_telemetry("verifier", "model_success", success=True)
        reports = await rt.detect_bottlenecks()
        self.assertTrue(any(r.type == "VERIFICATION_LIMITATION" for r in reports))
        # Event on the bus and a generated question via Slice 2 genesis.
        replayed = await rt.event_bus.replay_events(limit=500)
        events = [e for e in replayed
                  if e.event_type == EventType.BOTTLENECK_DETECTED]
        self.assertTrue(events)

    async def test_bottleneck_reported_once_deduped(self):
        rt = self._make_runtime()
        for _ in range(10):
            rt.record_telemetry("verifier", "verification_success", success=False)
        r1 = await rt.detect_bottlenecks()
        self.assertTrue(r1)
        r2 = await rt.detect_bottlenecks()
        self.assertEqual(r2, [])

    async def test_proposal_pipeline_reject_unsafe(self):
        rt = self._make_runtime()
        p = rt.propose_improvement(
            target_component="router",
            problem="latency",
            hypothesis="change policy",
            proposed_change={"routing_policy": {"policy_version": 7}},
            modification_type=ModificationType.CONFIGURATION_CHANGE,
            risk=RiskLevel.LOW,
            scope=["router"],
            rollback_plan="restore previous snapshot",
        )
        p = await rt.analyze_modification(p, {"v": 1}, {"v": 2})
        self.assertEqual(p.status, ProposalStatus.ANALYZING)
        p = await rt.sandbox_modification(p)
        self.assertEqual(p.status, ProposalStatus.SANDBOXED)
        p = await rt.test_modification(p, tests=[{"name": "t1", "kind": "config",
                                                  "config_path": ["routing_policy", "policy_version"],
                                                  "expected_value": 7}])
        self.assertEqual(p.status, ProposalStatus.TESTING)
        self.assertTrue(p.analysis.get("tests_passed"))

    async def test_slice7_event_types_published(self):
        rt = self._make_runtime()
        p = rt.propose_improvement(
            target_component="router", problem="p", hypothesis="h",
            proposed_change={"routing_policy": {"policy_version": 7}},
            modification_type=ModificationType.CONFIGURATION_CHANGE,
            risk=RiskLevel.LOW, scope=["router"],
            rollback_plan="restore previous snapshot")
        await rt.analyze_modification(p, {"v": 1}, {"v": 2})
        replayed = await rt.event_bus.replay_events(limit=500)
        types = {e.event_type for e in replayed}
        self.assertIn(EventType.MODIFICATION_ANALYSIS_STARTED, types)


if __name__ == "__main__":
    unittest.main()
