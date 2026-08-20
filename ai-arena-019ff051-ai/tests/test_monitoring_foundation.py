"""
Slice 8 — Continuous monitoring & controlled self-improvement loop test suite.

Covers: TelemetryFeed (live routed-outcome -> real architecture telemetry,
INSUFFICIENT_DATA never invented), RuntimePolicy store (versioned promotion
target, parent deactivation, rollback, persistence), MonitorStore (cycle +
sighting persistence, persistent-bottleneck evidence requirement), and the
MonitorScheduler loop through the REAL CognitiveRuntime: cadence-driven
OBSERVE -> DETECT -> PERSISTENT -> PROPOSE (opt-in) -> REGRESSION ->
AUTO-ROLLBACK. Plus the gated policy promotion path (STRATEGY / PROMPT /
ROUTING / MEMORY_POLICY / CAPABILITY changes promote into the versioned
runtime policy store — never into source code — with explicit-approval
required for HIGH/CRITICAL) and regression auto-rollback restoring the
pre-promotion snapshot.

No LLM, no external APIs; all benchmark data is deterministic fixtures.

Run with:
    python3 -m unittest tests.test_monitoring_foundation -v
"""

import os
import sqlite3
import tempfile
import unittest

from zerion.runtime.events import EventType

from zerion.cognitive_os.telemetry import ArchitectureTelemetry
from zerion.cognitive_os.telemetry_feed import (
    ROUTER_COMPONENT,
    TelemetryFeed,
)
from zerion.cognitive_os.policy_store import (
    PolicyIntegrityError,
    PolicyStore,
    RuntimePolicies,
)
from zerion.cognitive_os.monitor import (
    MonitorConfig,
    MonitorIntegrityError,
    MonitorScheduler,
    MonitorStore,
)
from zerion.cognitive_os.improvement import (
    ModificationType,
    ProposalStatus,
    RiskLevel,
)
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime


class TestTelemetryFeed(unittest.TestCase):
    def test_feed_outcome_writes_real_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = ArchitectureTelemetry(db_path=os.path.join(tmp, "t.db"))
            feed = TelemetryFeed(t)
            for _ in range(10):
                feed.feed_outcome(provider="openai", model="gpt-4o-mini",
                                  latency_ms=42.0, success=True, verified=True)
            self.assertEqual(t.rate(ROUTER_COMPONENT, "routing_success"), 1.0)
            self.assertEqual(t.rate("model:openai", "model_success"), 1.0)
            self.assertEqual(t.rate("verifier", "verification_success"), 1.0)
            self.assertIsNotNone(t.avg_latency_ms(ROUTER_COMPONENT, "latency"))

    def test_feed_never_invents_rates_below_min_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = ArchitectureTelemetry(db_path=os.path.join(tmp, "t.db"))
            feed = TelemetryFeed(t)
            feed.feed_outcome(provider="gemini", model="gemini-pro",
                              latency_ms=10.0, success=True)
            # One sample is INSUFFICIENT_DATA, never a fabricated rate.
            self.assertIsNone(t.rate(ROUTER_COMPONENT, "routing_success"))
            self.assertIsNone(t.rate("model:gemini", "model_success"))

    def test_feed_verification_and_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = ArchitectureTelemetry(db_path=os.path.join(tmp, "t.db"))
            feed = TelemetryFeed(t)
            for _ in range(10):
                feed.feed_verification(success=False)
            self.assertEqual(t.rate("verifier", "verification_success"), 0.0)
            for _ in range(10):
                feed.feed_resource(usage=0.87)
            self.assertEqual(
                t.get(ROUTER_COMPONENT, "resource_usage").avg_value(), 0.87)

    def test_feed_requires_telemetry(self):
        with self.assertRaises(ValueError):
            TelemetryFeed(None)


class TestPolicyStore(unittest.TestCase):
    def test_apply_versions_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PolicyStore(db_path=os.path.join(tmp, "p.db"))
            v1 = store.apply("router", {"strategy": "fast"}, applied_by="p1")
            self.assertEqual(v1.version, 1)
            v2 = store.apply("router", {"strategy": "deep"}, applied_by="p2",
                             snapshot_version=7)
            self.assertEqual(v2.version, 2)
            self.assertEqual(v2.parent_version, 1)
            self.assertEqual(v2.snapshot_version, 7)
            self.assertIsNone(store.current("other"))
            self.assertEqual(store.current("router").version, 2)
            # Rollback restores the parent as active; history is preserved.
            restored = store.rollback("router", reason="regression")
            self.assertEqual(restored.version, 1)
            self.assertEqual(store.current("router").version, 1)
            self.assertFalse(store.get("router", 2).active)

    def test_first_version_rollback_returns_to_no_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PolicyStore(db_path=os.path.join(tmp, "p.db"))
            store.apply("router", {"strategy": "fast"}, applied_by="p1")
            restored = store.rollback("router", reason="regression")
            # The pre-change state was "no policy", so rollback yields None.
            self.assertIsNone(restored)
            self.assertIsNone(store.current("router"))

    def test_persistence_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "p.db")
            store = PolicyStore(db_path=db)
            store.apply("router", {"strategy": "fast"}, applied_by="p1")
            store.apply("router", {"strategy": "deep"}, applied_by="p2")
            again = PolicyStore(db_path=db)
            self.assertEqual(again.current("router").version, 2)
            self.assertEqual(again.current("router").value["strategy"], "deep")
            self.assertEqual(again.get("router", 1).value["strategy"], "fast")
            policies = RuntimePolicies(again)
            self.assertEqual(policies.get("router")["strategy"], "deep")
            self.assertEqual(policies.get("missing", "default"), "default")

    def test_corruption_raises_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "p.db")
            store = PolicyStore(db_path=db)
            store.apply("router", {"strategy": "fast"}, applied_by="p1")
            conn = sqlite3.connect(db)
            conn.execute("UPDATE policies SET checksum='deadbeef' WHERE version=1")
            conn.commit()
            conn.close()
            with self.assertRaises(PolicyIntegrityError):
                PolicyStore(db_path=db, strict_load=True)
            loose = PolicyStore(db_path=db, strict_load=False)
            self.assertTrue(loose.load_errors)
            self.assertEqual(loose.count(), 0)


class TestMonitorStore(unittest.TestCase):
    def _cycle(self, seq, type_="VERIFICATION_LIMITATION", component="verifier"):
        from zerion.cognitive_os.monitor import MonitorCycle
        c = MonitorCycle(seq=seq)
        c.unresolved_bottlenecks = [{"type": type_, "component": component}]
        return c

    def test_cycles_persist_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "m.db")
            store = MonitorStore(db_path=db)
            store.put_cycle(self._cycle(1))
            store.put_cycle(self._cycle(2))
            again = MonitorStore(db_path=db)
            self.assertEqual(again.count(), 2)
            self.assertEqual(again.max_cycle_seq(), 2)

    def test_persistent_requires_repeated_sightings(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MonitorStore(db_path=os.path.join(tmp, "m.db"))
            # Real cycles first (max cycle seq drives the evidence window).
            store.put_cycle(self._cycle(0))   # assigns seq 1
            store.put_cycle(self._cycle(0))   # assigns seq 2
            # Single sighting: never persistent.
            store.record_sighting("VERIFICATION_LIMITATION", "verifier", 1)
            self.assertEqual(store.list_persistent(2), [])
            store.record_sighting("VERIFICATION_LIMITATION", "verifier", 2)
            persistent = store.list_persistent(2)
            self.assertEqual(len(persistent), 1)
            self.assertEqual(persistent[0]["type"], "VERIFICATION_LIMITATION")
            self.assertEqual(persistent[0]["component"], "verifier")

    def test_corruption_raises_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "m.db")
            store = MonitorStore(db_path=db)
            store.put_cycle(self._cycle(1))
            conn = sqlite3.connect(db)
            conn.execute("UPDATE cycles SET checksum='deadbeef' WHERE seq=1")
            conn.commit()
            conn.close()
            with self.assertRaises(MonitorIntegrityError):
                MonitorStore(db_path=db, strict_load=True)


class TestMonitorSchedulerRuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    def _make_runtime(self):
        return CognitiveRuntime(data_dir=tempfile.mkdtemp())

    async def test_cycle_completes_and_publishes_event(self):
        rt = self._make_runtime()
        cycle = await rt.monitor.run_once()
        self.assertIsNotNone(cycle.cycle_id)
        self.assertIsNotNone(cycle.finished_at)
        replayed = await rt.event_bus.replay_events(limit=500)
        self.assertTrue(any(e.event_type == EventType.MONITOR_CYCLE_COMPLETED
                            for e in replayed))
        await rt.monitor.stop()

    async def test_bottleneck_persistent_only_after_cycles(self):
        rt = self._make_runtime()
        rt.monitor.config.persistent_cycles = 2
        for _ in range(10):
            rt.record_telemetry("verifier", "verification_success", success=False)
        # Cycle 1: detected + sighted but NOT yet persistent.
        c1 = await rt.monitor.run_once()
        self.assertTrue(c1.unresolved_bottlenecks)
        self.assertEqual(c1.persistent_bottlenecks, [])
        # Cycle 2: the same (type, component) has real repeated evidence.
        c2 = await rt.monitor.run_once()
        self.assertTrue(any(p["type"] == "VERIFICATION_LIMITATION"
                            and p["component"] == "verifier"
                            for p in c2.persistent_bottlenecks))
        await rt.monitor.stop()

    async def test_auto_propose_is_opt_in(self):
        rt = self._make_runtime()
        rt.monitor.config.persistent_cycles = 2
        seen = []

        def factory(pb):
            seen.append(pb)
            return rt.propose_improvement(
                target_component=pb["component"], problem="persistent bottleneck",
                hypothesis="dedicated verifier capability",
                proposed_change={"verification": {"dedicated": True}},
                modification_type=ModificationType.CAPABILITY_CHANGE,
                risk=RiskLevel.LOW, scope=["verifier"],
                rollback_plan="restore previous snapshot")

        # Default: auto_propose=False -> no proposals even with a factory.
        rt.monitor.proposal_factory = factory
        for _ in range(10):
            rt.record_telemetry("verifier", "verification_success", success=False)
        await rt.monitor.run_once()
        await rt.monitor.run_once()
        self.assertEqual(rt.proposal_store.list(), [])
        # Opt-in: the factory's proposal is created and persisted.
        rt.monitor.config.auto_propose = True
        c3 = await rt.monitor.run_once()
        self.assertTrue(c3.proposals_created)
        self.assertTrue(rt.proposal_store.list())
        await rt.monitor.stop()

    async def _promote_policy_proposal(self, rt, *, risk=RiskLevel.LOW,
                                       approval=None):
        p = rt.propose_improvement(
            target_component="router", problem="latency",
            hypothesis="fast-path routing strategy wins",
            proposed_change={"strategy": "fast_path", "depth": 2},
            modification_type=ModificationType.STRATEGY_CHANGE,
            risk=risk, scope=["router"],
            rollback_plan="restore previous snapshot",
            test_plan=[{"name": "strategy", "kind": "config",
                        "config_path": ["strategy"],
                        "expected_value": "fast_path"}])
        p = await rt.analyze_modification(p, {"strategy": "baseline"},
                                          {"strategy": "candidate"})
        p = await rt.sandbox_modification(p)
        p = await rt.test_modification(p)
        p = await rt.benchmark_modification(
            p,
            baseline_runner=lambda cfg: [
                {"correct": False, "latency_ms": 10.0} for _ in range(10)],
            candidate_runner=lambda cfg: [
                {"correct": True, "latency_ms": 10.0} for _ in range(10)])
        ok, _ = await rt.approve_modification(p, approval=approval)
        self.assertTrue(ok)
        result = await rt.promote_modification(p)
        self.assertTrue(result.ok)
        self.assertTrue(result.applied)
        return p, result

    async def test_policy_promotion_applies_then_rolls_back(self):
        rt = self._make_runtime()
        p, result = await self._promote_policy_proposal(rt)
        # Real promotion into the versioned runtime policy store.
        self.assertEqual(rt.runtime_policies.get("router")["strategy"], "fast_path")
        self.assertEqual(p.policy_version, 1)
        self.assertEqual(p.status, ProposalStatus.APPROVED)
        # Post-promotion regression (real telemetry) -> auto-rollback.
        for _ in range(10):
            rt.record_telemetry("router", "routing_success", success=False)
        cycle = await rt.monitor.run_once()
        self.assertIn(p.proposal_id, cycle.regressions)
        self.assertTrue(cycle.rolled_back)
        self.assertEqual(cycle.rolled_back[0]["ok"], True)
        self.assertEqual(rt.runtime_policies.get("router", "absent"), "absent")
        self.assertEqual(p.status, ProposalStatus.ROLLED_BACK)
        replayed = await rt.event_bus.replay_events(limit=500)
        self.assertTrue(any(e.event_type == EventType.REGRESSION_DETECTED
                            for e in replayed))
        self.assertTrue(any(e.event_type == EventType.MODIFICATION_ROLLED_BACK
                            for e in replayed))
        await rt.monitor.stop()

    async def test_high_risk_requires_explicit_approval(self):
        rt = self._make_runtime()
        p = rt.propose_improvement(
            target_component="router", problem="p", hypothesis="h",
            proposed_change={"strategy": "deep"},
            modification_type=ModificationType.ROUTING_CHANGE,
            risk=RiskLevel.HIGH, scope=["router"],
            rollback_plan="restore previous snapshot")
        p = await rt.analyze_modification(p, {"v": 1}, {"v": 2})
        p = await rt.sandbox_modification(p)
        p = await rt.test_modification(p, tests=[
            {"name": "t", "kind": "config", "config_path": ["strategy"],
             "expected_value": "deep"}])
        p = await rt.benchmark_modification(
            p,
            baseline_runner=lambda cfg: [
                {"correct": False, "latency_ms": 10.0} for _ in range(10)],
            candidate_runner=lambda cfg: [
                {"correct": True, "latency_ms": 10.0} for _ in range(10)])
        # HIGH is NEVER auto-approved.
        ok, _ = await rt.approve_modification(p)
        self.assertFalse(ok)
        self.assertEqual(p.status, ProposalStatus.REJECTED)
        # Explicit operator approval unlocks it (still gated, still real).
        p2, result = await self._promote_policy_proposal(
            rt, risk=RiskLevel.HIGH, approval={"explicit": True})
        self.assertTrue(result.applied)
        self.assertEqual(rt.runtime_policies.get("router")["strategy"], "fast_path")
        await rt.monitor.stop()

    async def test_critical_requires_named_approver(self):
        rt = self._make_runtime()
        p = rt.propose_improvement(
            target_component="router", problem="p", hypothesis="h",
            proposed_change={"strategy": "deep"},
            modification_type=ModificationType.MEMORY_POLICY_CHANGE,
            risk=RiskLevel.CRITICAL, scope=["router"],
            rollback_plan="restore previous snapshot")
        p = await rt.analyze_modification(p, {"v": 1}, {"v": 2})
        p = await rt.sandbox_modification(p)
        p = await rt.test_modification(p, tests=[
            {"name": "t", "kind": "config", "config_path": ["strategy"],
             "expected_value": "deep"}])
        p = await rt.benchmark_modification(
            p,
            baseline_runner=lambda cfg: [
                {"correct": False, "latency_ms": 10.0} for _ in range(10)],
            candidate_runner=lambda cfg: [
                {"correct": True, "latency_ms": 10.0} for _ in range(10)])
        # Explicit approval without a named approver is still rejected.
        ok, _ = await rt.approve_modification(p, approval={"explicit": True})
        self.assertFalse(ok)
        self.assertEqual(p.status, ProposalStatus.REJECTED)
        # Named approver + explicit unlocks the gated path.
        ok, _ = await rt.approve_modification(
            p, approval={"explicit": True, "approver": "operator-1"})
        self.assertTrue(ok)
        await rt.monitor.stop()

    async def test_source_code_never_auto_applied(self):
        rt = self._make_runtime()
        p = rt.propose_improvement(
            target_component="router", problem="p", hypothesis="h",
            proposed_change="def helper():\n    return 42\n",
            modification_type=ModificationType.CODE_CHANGE,
            risk=RiskLevel.LOW, scope=["router"],
            rollback_plan="restore previous snapshot")
        p = await rt.analyze_modification(p, {"v": 1}, {"v": 2})
        p = await rt.sandbox_modification(p)
        p = await rt.test_modification(p, tests=[
            {"name": "t", "kind": "unit",
             "check": lambda change: "return 42" in change}])
        p = await rt.benchmark_modification(
            p,
            baseline_runner=lambda cfg: [
                {"correct": False, "latency_ms": 10.0} for _ in range(10)],
            candidate_runner=lambda cfg: [
                {"correct": True, "latency_ms": 10.0} for _ in range(10)])
        # CODE_CHANGE is HIGH base risk: never auto-approved; an explicit
        # operator approval unlocks approval-with-evidence — but the change is
        # still never applied to source code (no unrestricted self-modification).
        result = await rt.promote_modification(p, approval={"explicit": True})
        self.assertTrue(result.ok)
        self.assertFalse(result.applied)
        self.assertEqual(rt.runtime_policies.get("router", "absent"), "absent")
        await rt.monitor.stop()


if __name__ == "__main__":
    unittest.main()
