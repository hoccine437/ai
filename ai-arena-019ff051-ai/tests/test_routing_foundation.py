"""
Slice 6 — Cognitive Router test suite.

Covers: provider interface (model independence), honest provider adapters,
local GGUF discovery (only .gguf, corrupted/duplicate/oversize/path-escape),
resource-aware load manager, CognitiveDepthScore determinism + FAST/DEEP
fields, deterministic model selection + capability matching, offline-only
mode, provider failover/timeout/unavailable, provider health, historical
performance (cold start INSUFFICIENT_DATA + persistence + weight learning),
verification integration (MODEL_OUTPUT -> OBSERVED_RESULT -> VERIFIED_RESULT),
secret redaction, retry/resource budgets, event-bus integration, the required
E2E scenarios 1-5 and the local model discovery test. No external APIs; all
providers are deterministic stubs or honest adapters.

Run with:
    python3 -m unittest tests.test_routing_foundation -v
"""

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from zerion.runtime.event_bus import AsyncEventBus
from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.router_types import (
    CognitiveDepthLevel,
    CognitiveDepthScore,
    CognitiveField,
    CognitiveResult,
    DepthWeights,
    ModelSelection,
    ProviderStatus,
    ResultStatus,
    RoutingMode,
    Task,
    TaskType,
    VerificationStatus,
    redact_secrets,
)
from zerion.cognitive_os.provider_interface import (
    ModelInfo,
    ProviderCall,
    ProviderFailureKind,
    RawProviderResponse,
)
from zerion.cognitive_os.provider_health import ProviderHealthTracker
from zerion.cognitive_os.performance_ledger import (
    PerformanceLedger,
    PerformanceLedgerIntegrityError,
)
import unittest.mock

from zerion.cognitive_os.cognitive_router import CognitiveRouter, ModelSelector
from zerion.cognitive_os.provider_adapters import LegacyGeminiAdapter
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.engine import AscendantEngine


# ---------------------------------------------------------------------------
# Deterministic stub providers (implement the Slice 6 protocol only)
# ---------------------------------------------------------------------------

class StubProvider:
    def __init__(self, name, models, *, fail_kind=None, timeout=False,
                 local=False, caps=("text", "reasoning"),
                 field_profile=None, latency_ms=5.0, output="stub answer",
                 error="stub failure"):
        self.provider_name = name
        self.is_local = local
        self.field_profile = field_profile
        self.models = list(models)
        self.fail_kind = fail_kind
        self.timeout = timeout
        self.caps = set(caps)
        self.latency_ms = latency_ms
        self.output = output
        self.error = error
        self.calls = 0

    async def generate(self, call: ProviderCall) -> RawProviderResponse:
        self.calls += 1
        if self.timeout:
            await asyncio.sleep(60)
        if self.fail_kind is not None:
            return RawProviderResponse(output=None, success=False,
                                       failure_kind=self.fail_kind,
                                       error=self.error)
        return RawProviderResponse(output=self.output,
                                   latency_ms=self.latency_ms, success=True)

    async def stream(self, call):
        yield RawProviderResponse(output=self.output, success=True)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.AVAILABLE

    def capabilities(self):
        return self.caps

    def list_models(self):
        return [ModelInfo(model_id=m, provider=self.provider_name,
                          capabilities=self.caps,
                          status=ProviderStatus.AVAILABLE, format="api")
                for m in self.models]

    def model_info(self, model_id):
        for m in self.list_models():
            if m.model_id == model_id:
                return m
        return None


def deep_task(**kw):
    base = dict(type=TaskType.REASONING, description="complex reasoning",
                uncertainty=0.8, novelty=0.7, stakes=0.9, goal_relevance=0.9,
                metadata={"contradiction": 0.5, "expected_value": 0.8})
    base.update(kw)
    return Task(**base)


def fast_task(**kw):
    base = dict(type=TaskType.RETRIEVAL, description="routine operation",
                uncertainty=0.1, novelty=0.1, stakes=0.1, goal_relevance=0.3)
    base.update(kw)
    return Task(**base)


def make_router(tmp, models_dir=None, **kw):
    # No local models exist anywhere in Zerion: Gemini-only routing.
    return CognitiveRouter(
        health=ProviderHealthTracker(),
        ledger=PerformanceLedger(db_path=f"{tmp}/ledger.db"),
        **kw)


def make_models_dir(tmp, *names, magic=b"GGUF", size=0):
    mdir = Path(tmp) / "models"
    mdir.mkdir(exist_ok=True)
    for name in names:
        (mdir / name).write_bytes(magic + b"\x00" * size)
    return mdir


# ---------------------------------------------------------------------------
# 1. PROVIDER INTERFACE & MODEL INDEPENDENCE
# ---------------------------------------------------------------------------

class TestProviderInterface(unittest.TestCase):
    def test_router_core_has_no_provider_sdk_imports(self):
        """The cognitive core must not depend on openai / google / llama.cpp.
        Only adapters may. Check for actual import statements (the docstring
        mentions the packages by name; imports are what matter)."""
        for mod in ("zerion/cognitive_os/cognitive_router.py",
                    "zerion/cognitive_os/router_types.py",
                    "zerion/cognitive_os/provider_health.py",
                    "zerion/cognitive_os/performance_ledger.py",
                    "zerion/cognitive_os/provider_interface.py"):
            src = Path(mod).read_text()
            lines = [ln for ln in src.splitlines()
                     if ln.strip().startswith(("import ", "from "))]
            joined = "\n".join(lines)
            self.assertNotIn("openai", joined, mod)
            self.assertNotIn("google", joined, mod)
            self.assertNotIn("llama_cpp", joined, mod)

    def test_router_accepts_any_protocol_implementor(self):
        rt = make_router(tempfile.mkdtemp())
        stub = StubProvider("stub_a", ["m1"])
        rt.register_provider(stub, configured=True)
        sel = rt.route(fast_task())
        self.assertEqual(sel.provider, "stub_a")
        self.assertEqual(sel.model, "m1")


# ---------------------------------------------------------------------------
# 2. HONEST PROVIDER ADAPTERS
# ---------------------------------------------------------------------------

class TestProviderAdapters(unittest.TestCase):
    """Gemini is the only provider: the OpenAI and GGUF legacy adapters were
    REMOVED from provider_adapters. These tests pin the Gemini-only surface."""

    def test_only_gemini_adapter_exists(self):
        import zerion.cognitive_os.provider_adapters as pa
        for banned in ("LegacyOpenAIAdapter", "LegacyGGUFAdapter",
                       "OpenAIProvider", "LocalGGUFProvider"):
            self.assertFalse(hasattr(pa, banned), f"{banned} must be removed")
        self.assertTrue(hasattr(pa, "LegacyGeminiAdapter"))

    def test_gemini_adapter_is_honest_about_missing_integration(self):
        adapter = LegacyGeminiAdapter()
        models = adapter.list_models()
        self.assertEqual(models[0].status, ProviderStatus.NOT_CONFIGURED)
        resp = asyncio.run(adapter.generate(ProviderCall(
            task=fast_task(), prompt="hi", model_id="gemini-2.5-flash")))
        self.assertFalse(resp.success)
        self.assertIsNone(resp.output)  # never canned text
        self.assertEqual(resp.failure_kind, ProviderFailureKind.PROVIDER_UNAVAILABLE)


# ---------------------------------------------------------------------------
# 3. LOCAL GGUF DISCOVERY (required test)
# ---------------------------------------------------------------------------

class NoLocalModelArchitecture(unittest.TestCase):
    """The local GGUF model architecture has been REMOVED from Zerion.
    Gemini is the only provider. These tests pin the removal in place."""

    def test_local_model_discovery_is_gone(self):
        import zerion.cognitive_os.cognitive_router as cr
        self.assertFalse(hasattr(cr, "LocalModelDiscovery"))
        self.assertFalse(hasattr(cr, "ModelLoadManager"))
        import zerion.cognitive_os.provider_adapters as pa
        for banned in ("LocalGGUFProvider", "OpenAIProvider"):
            self.assertFalse(any(banned in n for n in dir(pa)),
                             f"{banned} must not exist")

    def test_router_has_no_local_models_parameter(self):
        import inspect
        from zerion.cognitive_os.cognitive_router import CognitiveRouter
        params = inspect.signature(CognitiveRouter.__init__).parameters
        self.assertNotIn("local_models", params)


# ---------------------------------------------------------------------------
# 4. COGNITIVE DEPTH SCORE
# ---------------------------------------------------------------------------

class TestCognitiveDepth(unittest.TestCase):
    def test_deterministic_identical_inputs(self):
        ds = CognitiveDepthScore()
        t = deep_task()
        self.assertEqual(ds.score(t), ds.score(t))
        self.assertEqual(ds.level(t), ds.level(t))
        self.assertEqual(ds.field(t), ds.field(t))

    def test_level_boundaries(self):
        ds = CognitiveDepthScore()
        def task(score):
            # Every weighted input set to the same value -> depth = 0.9 * score
            # (the six weighted inputs sum to 0.9; failure rate defaults to 0).
            return Task(type=TaskType.REASONING, uncertainty=score,
                        novelty=score, stakes=score, goal_relevance=score,
                        metadata={"contradiction": score, "expected_value": score})
        self.assertEqual(ds.score(task(0.10)), 0.09)
        self.assertEqual(ds.level(task(0.10)), CognitiveDepthLevel.D0_REFLEX)
        self.assertEqual(ds.level(task(0.30)), CognitiveDepthLevel.D1_DIRECT_REASONING)
        self.assertEqual(ds.level(task(0.45)), CognitiveDepthLevel.D2_VERIFICATION)
        self.assertEqual(ds.level(task(0.60)), CognitiveDepthLevel.D3_MULTI_HYPOTHESIS)
        self.assertEqual(ds.level(task(0.75)), CognitiveDepthLevel.D4_EXPERIMENTATION)
        self.assertEqual(ds.level(task(0.85)), CognitiveDepthLevel.D5_ADVERSARIAL_CHALLENGE)
        self.assertEqual(ds.level(task(0.95)), CognitiveDepthLevel.D6_ARCHITECTURE_INVESTIGATION)

    def test_inputs_move_score(self):
        ds = CognitiveDepthScore()
        base = Task(type=TaskType.REASONING, uncertainty=0.0, novelty=0.0,
                    stakes=0.0, goal_relevance=0.0,
                    metadata={"expected_value": 0.0})
        self.assertEqual(ds.score(base), 0.0)
        higher = Task(type=TaskType.REASONING, uncertainty=0.5, novelty=0.0,
                      stakes=0.0, goal_relevance=0.0,
                      metadata={"expected_value": 0.0})
        self.assertGreater(ds.score(higher), 0.0)
        contra = Task(type=TaskType.REASONING, uncertainty=0.0, novelty=0.0,
                      stakes=0.0, goal_relevance=0.0,
                      metadata={"contradiction": 1.0, "expected_value": 0.0})
        self.assertGreater(ds.score(contra), 0.0)
        failure = Task(type=TaskType.REASONING, uncertainty=0.0, novelty=0.0,
                       stakes=0.0, goal_relevance=0.0,
                       metadata={"expected_value": 0.0})
        self.assertGreater(ds.score(failure, historical_failure_rate=0.9), 0.0)

    def test_configurable_weights_and_thresholds(self):
        t = fast_task()
        ds1 = CognitiveDepthScore(weights=DepthWeights(stakes=1.0))
        ds2 = CognitiveDepthScore(weights=DepthWeights(stakes=0.0))
        self.assertGreater(ds1.score(t), ds2.score(t))
        ds3 = CognitiveDepthScore(thresholds=[0.99] * 6)
        self.assertEqual(ds3.level(t), CognitiveDepthLevel.D0_REFLEX)

    def test_fast_and_deep_fields(self):
        ds = CognitiveDepthScore()
        self.assertEqual(ds.field(fast_task()), CognitiveField.FAST_FIELD)
        self.assertEqual(ds.field(deep_task()), CognitiveField.DEEP_FIELD)


# ---------------------------------------------------------------------------
# 5. SELECTION
# ---------------------------------------------------------------------------

class TestSelection(unittest.TestCase):
    def test_capability_matching_excludes_incapable_providers(self):
        rt = make_router(tempfile.mkdtemp())
        vision = StubProvider("vision_p", ["v1"], caps=("text", "vision"))
        text = StubProvider("text_p", ["t1"], caps=("text", "reasoning"))
        rt.register_provider(vision, configured=True)
        rt.register_provider(text, configured=True)
        task = deep_task(required_capabilities={"vision"})
        sel = rt.route(task)
        self.assertEqual(sel.provider, "vision_p")
        self.assertIn("vision", sel.capabilities)

    def test_selection_explains_reason_structurally(self):
        rt = make_router(tempfile.mkdtemp())
        rt.register_provider(StubProvider("p1", ["m1"], field_profile="FAST_FIELD"),
                             configured=True)
        rt.register_provider(StubProvider("p2", ["m2"], field_profile="DEEP_FIELD"),
                             configured=True)
        sel = rt.route(deep_task())
        self.assertGreaterEqual(len(sel.reason), 4)
        joined = " ".join(sel.reason)
        self.assertIn("field=DEEP_FIELD", joined)
        self.assertIn("health=", joined)
        self.assertIn("fallback chain", joined)
        self.assertIsNotNone(sel.field)
        self.assertIsNotNone(sel.depth_level)
        self.assertEqual(sel.routing_policy_version, 6)

    def test_selection_is_deterministic(self):
        rt = make_router(tempfile.mkdtemp())
        for i in range(4):
            rt.register_provider(StubProvider(f"p{i}", [f"m{i}"],
                                              field_profile="FAST_FIELD"),
                                 configured=True)
        a = rt.route(deep_task())
        b = rt.route(deep_task())
        self.assertEqual(a.provider, b.provider)
        self.assertEqual(a.model, b.model)
        self.assertEqual(a.confidence, b.confidence)
        self.assertEqual(a.fallback_chain, b.fallback_chain)

    def test_fallback_chain_ordered(self):
        rt = make_router(tempfile.mkdtemp())
        rt.register_provider(StubProvider("b", ["m"]), configured=True)
        rt.register_provider(StubProvider("a", ["m"]), configured=True)
        sel = rt.route(fast_task())
        self.assertEqual(sel.provider, "a")
        self.assertEqual([c["provider"] for c in sel.fallback_chain], ["b"])

    def test_field_profile_guides_fast_vs_deep_selection(self):
        rt = make_router(tempfile.mkdtemp())
        rt.register_provider(StubProvider("fast_provider", ["fast-1"],
                                          field_profile="FAST_FIELD"), configured=True)
        rt.register_provider(StubProvider("deep_provider", ["deep-1"],
                                          field_profile="DEEP_FIELD"), configured=True)
        self.assertEqual(rt.route(deep_task()).provider, "deep_provider")
        self.assertEqual(rt.route(fast_task()).provider, "fast_provider")


# ---------------------------------------------------------------------------
# 6. OFFLINE-ONLY MODE
# ---------------------------------------------------------------------------

class NoOfflineModeRouting(unittest.IsolatedAsyncioTestCase):
    """OFFLINE_ONLY mode is REMOVED: Gemini is the ONLY provider and an
    unconfigured/unavailable Gemini yields an honest structured failure —
    never a local-model fallback, never fabricated output."""

    async def test_offline_only_mode_is_gone(self):
        self.assertFalse(any(m.value == "OFFLINE_ONLY" for m in RoutingMode))

    async def test_no_providers_yields_structured_failure_not_fake_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            res = await rt.execute(deep_task(), "q")
            self.assertEqual(res.status, ResultStatus.ROUTING_FAILED)
            self.assertIsNone(res.output)  # NO fabricated answer
            self.assertTrue(res.errors)


# ---------------------------------------------------------------------------
# 7. FAILOVER & FAILURE HANDLING
# ---------------------------------------------------------------------------

class TestFailover(unittest.IsolatedAsyncioTestCase):
    async def test_primary_failure_falls_back_to_compatible_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            primary = StubProvider("aaa_primary", ["p1"],
                                   fail_kind=ProviderFailureKind.QUOTA_FAILURE)
            backup = StubProvider("zzz_backup", ["b1"])
            rt.register_provider(primary, configured=True)
            rt.register_provider(backup, configured=True)
            res = await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.SUCCESS)
            self.assertEqual(res.provider, "zzz_backup")
            self.assertEqual(res.output, "stub answer")
            self.assertEqual(primary.calls, 1)  # failover actually happened
            self.assertEqual(backup.calls, 1)

    async def test_timeout_triggers_failover(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp, max_attempts=2)
            slow = StubProvider("aaa_slow", ["s1"], timeout=True)
            backup = StubProvider("zzz_backup", ["b1"], latency_ms=2.0)
            rt.register_provider(slow, configured=True)
            rt.register_provider(backup, configured=True)
            task = fast_task(latency_budget_ms=150)
            res = await rt.execute(task, "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.SUCCESS)
            self.assertEqual(res.provider, "zzz_backup")
            self.assertEqual(rt.health.get("aaa_slow").timeouts, 1)

    async def test_retry_budget_respected_no_endless_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp, max_attempts=1)
            f1 = StubProvider("p1", ["m1"],
                              fail_kind=ProviderFailureKind.TIMEOUT)
            f2 = StubProvider("p2", ["m2"],
                              fail_kind=ProviderFailureKind.TIMEOUT)
            rt.register_provider(f1, configured=True)
            rt.register_provider(f2, configured=True)
            res = await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.TIMEOUT)
            self.assertEqual(f1.calls + f2.calls, 1)  # budget: 1 attempt only

    async def test_non_retriable_failure_does_not_failover(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            bad = StubProvider("bad", ["m1"],
                               fail_kind=ProviderFailureKind.MALFORMED_OUTPUT)
            good = StubProvider("good", ["m2"])
            rt.register_provider(bad, configured=True)
            rt.register_provider(good, configured=True)
            res = await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.MALFORMED_OUTPUT)
            self.assertEqual(good.calls, 0)  # never retried — retry won't fix it

    async def test_all_providers_fail_is_structured_not_system_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            for name in ("p1", "p2"):
                rt.register_provider(StubProvider(
                    name, [f"{name}-m"],
                    fail_kind=ProviderFailureKind.PROVIDER_UNAVAILABLE),
                    configured=True)
            res = await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.PROVIDER_UNAVAILABLE)
            self.assertIsNone(res.output)
            self.assertGreaterEqual(len(res.errors), 1)

    async def test_provider_unavailable_single(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            rt.register_provider(StubProvider(
                "gone", ["g1"],
                fail_kind=ProviderFailureKind.NETWORK_UNAVAILABLE), configured=True)
            res = await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.NETWORK_UNAVAILABLE)
            self.assertIsNone(res.output)


# ---------------------------------------------------------------------------
# 8. PROVIDER HEALTH
# ---------------------------------------------------------------------------

class TestProviderHealth(unittest.TestCase):
    def test_fresh_provider_is_unknown_not_ready_from_config(self):
        tracker = ProviderHealthTracker()
        tracker.register("p", configured=True, integration_implemented=True)
        self.assertEqual(tracker.status("p"), ProviderStatus.UNKNOWN)
        # never READY merely because configuration exists

    def test_unconfigured_is_not_config_implemented_missing_is_unavailable(self):
        tracker = ProviderHealthTracker()
        tracker.register("p", configured=False)
        self.assertEqual(tracker.status("p"), ProviderStatus.NOT_CONFIGURED)
        tracker.register("p2", configured=True, integration_implemented=False)
        self.assertEqual(tracker.status("p2"), ProviderStatus.UNAVAILABLE)

    def test_failures_degrade_then_unavailable(self):
        tracker = ProviderHealthTracker()
        tracker.register("p", configured=True)
        tracker.record_success("p", 10.0)
        self.assertEqual(tracker.status("p"), ProviderStatus.AVAILABLE)
        tracker.record_failure("p", error="boom")
        tracker.record_failure("p", error="boom")
        self.assertEqual(tracker.status("p"), ProviderStatus.DEGRADED)
        for _ in range(4):
            tracker.record_failure("p", error="boom")
        self.assertEqual(tracker.status("p"), ProviderStatus.UNAVAILABLE)

    def test_timeout_tracked(self):
        tracker = ProviderHealthTracker()
        tracker.register("p", configured=True)
        tracker.record_failure("p", error="timeout", timeout=True)
        h = tracker.get("p")
        self.assertEqual(h.timeouts, 1)
        self.assertEqual(h.timeout_rate(), 1.0)

    def test_success_records_latency_and_resets_failures(self):
        tracker = ProviderHealthTracker()
        tracker.register("p", configured=True)
        tracker.record_failure("p", error="x")
        tracker.record_success("p", 20.0)
        h = tracker.get("p")
        self.assertEqual(h.consecutive_failures, 0)
        self.assertEqual(h.latency_ema_ms, 20.0)
        self.assertIsNotNone(h.last_successful_request)

    def test_health_scoring_order(self):
        """Health must affect selection: available > unknown > degraded >
        unavailable. Health is proven by outcomes, never by config."""
        sel = ModelSelector()
        t = fast_task()
        def score(status):
            return sel.score_candidate(
                provider="p", model="m", capabilities={"text"},
                is_local=False, task=t, mode=RoutingMode.ONLINE_ALLOWED,
                health_status=status, ledger=None, cost_estimate=None,
                latency_estimate=None)
        self.assertGreater(score(ProviderStatus.AVAILABLE),
                           score(ProviderStatus.UNKNOWN))
        self.assertGreater(score(ProviderStatus.UNKNOWN),
                           score(ProviderStatus.DEGRADED))
        self.assertGreater(score(ProviderStatus.DEGRADED),
                           score(ProviderStatus.UNAVAILABLE))

    def test_health_used_in_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            good = StubProvider("a_good", ["m1"], field_profile="FAST_FIELD")
            bad = StubProvider("zz_bad", ["m2"], field_profile="FAST_FIELD")
            rt.register_provider(good, configured=True)
            rt.register_provider(bad, configured=True)
            # Before any calls both are UNKNOWN -> "a_good" wins the tie.
            self.assertEqual(rt.route(fast_task()).provider, "a_good")
            # Degrade "a_good" with real failures; routing prefers "zz_bad".
            for _ in range(3):
                rt.health.record_failure("a_good", error="boom")
            self.assertEqual(rt.route(fast_task()).provider, "zz_bad")


# ---------------------------------------------------------------------------
# 9. HISTORICAL PERFORMANCE
# ---------------------------------------------------------------------------

class TestHistoricalPerformance(unittest.TestCase):
    def test_cold_start_is_insufficient_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = PerformanceLedger(db_path=f"{tmp}/l.db")
            s = ledger.stats(task_type="REASONING", provider="p", model="m")
            self.assertTrue(s.insufficient_data)
            self.assertIsNone(s.success_rate)
            self.assertEqual(s.samples, 0)
            self.assertEqual(ledger.routing_weight(
                task_type="REASONING", provider="p", model="m"), 0.5)

    def test_insufficient_data_until_min_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = PerformanceLedger(db_path=f"{tmp}/l.db")
            task = deep_task()
            for _ in range(ledger.min_samples - 1):
                ledger.record_outcome(task=task, provider="p", model="m",
                                      success=True, latency_ms=10.0, cost_cents=1.0)
            s = ledger.stats(task_type="REASONING", provider="p", model="m")
            self.assertTrue(s.insufficient_data)

    def test_stats_after_real_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = PerformanceLedger(db_path=f"{tmp}/l.db")
            task = deep_task()
            for i in range(4):
                ledger.record_outcome(task=task, provider="p", model="m",
                                      success=(i % 2 == 0), latency_ms=10.0,
                                      cost_cents=2.0, verified=(i == 0))
            s = ledger.stats(task_type="REASONING", provider="p", model="m")
            self.assertFalse(s.insufficient_data)
            self.assertEqual(s.samples, 4)
            self.assertEqual(s.success_rate, 0.5)
            self.assertEqual(s.avg_latency_ms, 10.0)
            self.assertEqual(s.avg_cost_cents, 2.0)

    def test_persistence_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/l.db"
            ledger1 = PerformanceLedger(db_path=db)
            task = fast_task()
            for _ in range(5):
                ledger1.record_outcome(task=task, provider="p", model="m",
                                       success=True, latency_ms=5.0, cost_cents=None)
            ledger2 = PerformanceLedger(db_path=db)
            s = ledger2.stats(task_type="RETRIEVAL", provider="p", model="m")
            self.assertEqual(s.samples, 5)
            self.assertEqual(s.success_rate, 1.0)

    def test_corrupted_ledger_row_raises_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/l.db"
            ledger = PerformanceLedger(db_path=db)
            task = fast_task()
            ledger.record_outcome(task=task, provider="p", model="m",
                                  success=True, latency_ms=1.0, cost_cents=None)
            conn = sqlite3.connect(db)
            row = conn.execute("SELECT payload, checksum FROM outcomes").fetchone()
            conn.execute("UPDATE outcomes SET payload=? WHERE checksum=?",
                         ("corrupted-json", row[1]))
            conn.commit()
            conn.close()
            with self.assertRaises(PerformanceLedgerIntegrityError):
                PerformanceLedger(db_path=db, strict_load=True)

    def test_weights_only_shift_after_min_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = PerformanceLedger(db_path=f"{tmp}/l.db")
            task = fast_task()
            # One success must NOT move the weight (no overfitting from tiny samples).
            ledger.record_outcome(task=task, provider="p", model="m",
                                  success=True, latency_ms=1.0, cost_cents=None)
            self.assertEqual(ledger.routing_weight(
                task_type="RETRIEVAL", provider="p", model="m"), 0.5)
            # Five successes -> weight rises.
            for _ in range(4):
                ledger.record_outcome(task=task, provider="p", model="m",
                                      success=True, latency_ms=1.0, cost_cents=None)
            w = ledger.routing_weight(task_type="RETRIEVAL", provider="p", model="m")
            self.assertGreater(w, 0.5)

    def test_repeated_failure_reduces_router_preference(self):
        """A model that repeatedly fails a task category must become less
        likely for that category (evidence-driven, not opinion)."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = PerformanceLedger(db_path=f"{tmp}/l.db")
            task = fast_task()
            for _ in range(5):
                ledger.record_outcome(task=task, provider="loser", model="m1",
                                      success=False, latency_ms=1.0, cost_cents=None)
            for _ in range(5):
                ledger.record_outcome(task=task, provider="winner", model="m2",
                                      success=True, latency_ms=1.0, cost_cents=None)
            w_loser = ledger.routing_weight(task_type="RETRIEVAL",
                                            provider="loser", model="m1")
            w_winner = ledger.routing_weight(task_type="RETRIEVAL",
                                             provider="winner", model="m2")
            self.assertLess(w_loser, 0.5)
            self.assertGreater(w_winner, 0.5)
            # And routing prefers the winner for that task category.
            rt = make_router(tmp, models_dir=f"{tmp}/models")
            loser = StubProvider("loser", ["m1"], field_profile="FAST_FIELD")
            winner = StubProvider("winner", ["m2"], field_profile="FAST_FIELD")
            rt.register_provider(loser, configured=True)
            rt.register_provider(winner, configured=True)
            rt.ledger = ledger
            sel = rt.route(task)
            self.assertEqual(sel.provider, "winner")


# ---------------------------------------------------------------------------
# 10. VERIFICATION INTEGRATION
# ---------------------------------------------------------------------------

class TestVerificationIntegration(unittest.IsolatedAsyncioTestCase):
    async def _rt(self, tmp):
        rt = CognitiveRuntime(data_dir=tmp)
        await rt.start()
        return rt

    async def test_high_risk_output_starts_as_model_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = await self._rt(tmp)
            try:
                # Detach all providers so this test never touches the network.
                router = rt.cognitive_router
                router._providers.clear()
                router._provider_order.clear()
                router._models.clear()
                res = await rt.execute_task(
                    deep_task(verification_required=True), "q")
                # No eligible provider -> structured failure, but verification
                # semantics are still explicit.
                self.assertEqual(res.verification_status,
                                 VerificationStatus.MODEL_OUTPUT)
            finally:
                await rt.stop()

    async def test_model_output_observed_then_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = await self._rt(tmp)
            try:
                res = CognitiveResult(task_id="t1", provider="stub",
                                      model="m", output="x",
                                      status=ResultStatus.SUCCESS,
                                      verification_required=True)
                res2 = rt.record_observed_result(
                    res, observation={"reality": "matches"},
                    source="test_observation")
                self.assertEqual(res2.verification_status,
                                 VerificationStatus.OBSERVED_RESULT)
                ev_ids = res2.metadata["evidence_ids"]
                ev = rt.evidence_store.get(ev_ids[0])
                self.assertEqual(ev.provenance.mode.value, "OBSERVED")
                res3 = rt.confirm_verified(res2, evidence_ids=ev_ids)
                self.assertEqual(res3.verification_status,
                                 VerificationStatus.VERIFIED_RESULT)
            finally:
                await rt.stop()

    async def test_fabricated_evidence_cannot_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = await self._rt(tmp)
            try:
                res = CognitiveResult(task_id="t1", provider="stub",
                                      model="m", output="x",
                                      status=ResultStatus.SUCCESS,
                                      verification_required=True)
                res2 = rt.record_observed_result(
                    res, observation={"reality": "matches"}, source="s")
                # Fake evidence id -> rejected.
                with self.assertRaises(ValueError):
                    rt.confirm_verified(res2, evidence_ids=["ev_nonexistent"])
            finally:
                await rt.stop()

    async def test_observing_twice_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = await self._rt(tmp)
            try:
                res = CognitiveResult(task_id="t1", provider="stub",
                                      model="m", output="x",
                                      status=ResultStatus.SUCCESS,
                                      verification_required=True)
                rt.record_observed_result(res, observation={"a": 1}, source="s")
                with self.assertRaises(ValueError):
                    rt.record_observed_result(res, observation={"a": 2},
                                              source="s2")
            finally:
                await rt.stop()


# ---------------------------------------------------------------------------
# 11. SECURITY (secret redaction)
# ---------------------------------------------------------------------------

class TestSecretRedaction(unittest.TestCase):
    def test_secret_keys_redacted_recursively(self):
        payload = {"api_key": "sk-123", "model": "m",
                   "nested": {"token": "abc", "ok": 1},
                   "list": [{"password": "x"}, {"name": "fine"}]}
        out = redact_secrets(payload)
        self.assertEqual(out["api_key"], "[REDACTED]")
        self.assertEqual(out["nested"]["token"], "[REDACTED]")
        self.assertEqual(out["list"][0]["password"], "[REDACTED]")
        self.assertEqual(out["nested"]["ok"], 1)
        self.assertEqual(out["list"][1]["name"], "fine")

    def test_selection_and_result_dicts_redact(self):
        sel = ModelSelection(provider="p", model="m",
                             reason=["api_key=sk-123 in config"],
                             estimated_cost_cents=1.0)
        d = sel.to_dict(redact=True)
        self.assertNotIn("sk-123", json.dumps(d))
        res = CognitiveResult(task_id="t", output="x", metadata={"api_key": "k"})
        rd = res.to_dict(redact=True)
        self.assertEqual(rd["metadata"]["api_key"], "[REDACTED]")

    def test_event_payloads_never_leak_secrets(self):
        captured = {}

        async def emit(event_type, payload):
            captured[event_type] = payload

        async def run():
            rt = CognitiveRouter(health=ProviderHealthTracker(),
                                 ledger=None,
                                 emit=emit)
            leaky = StubProvider("leaky", ["m1"])
            rt.register_provider(leaky, configured=True)
            await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            # Defense in depth: even a payload carrying a raw key is scrubbed
            # before it reaches the bus/UI/logs.
            await rt._emit("MODEL_SELECTED", {
                "api_key": "sk-secret-abc",
                "reason": "config token Bearer tok12345xyz",
            })

        asyncio.run(run())
        blob = json.dumps(captured)
        self.assertNotIn("sk-secret", blob)
        self.assertNotIn("tok12345xyz", blob)


# ---------------------------------------------------------------------------
# 12. RESOURCE LIMITS
# ---------------------------------------------------------------------------

class TestResourceLimits(unittest.IsolatedAsyncioTestCase):
    async def test_latency_budget_enforced_as_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp, max_attempts=1)
            slow = StubProvider("slow", ["s1"], timeout=True)
            rt.register_provider(slow, configured=True)
            task = fast_task(latency_budget_ms=100)
            res = await rt.execute(task, "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.TIMEOUT)
            self.assertIsNone(res.output)

    async def test_retry_budget_caps_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp, max_attempts=3)
            f1 = StubProvider("p1", ["m1"], fail_kind=ProviderFailureKind.QUOTA_FAILURE)
            f2 = StubProvider("p2", ["m2"], fail_kind=ProviderFailureKind.QUOTA_FAILURE)
            f3 = StubProvider("p3", ["m3"], fail_kind=ProviderFailureKind.QUOTA_FAILURE)
            for p in (f1, f2, f3):
                rt.register_provider(p, configured=True)
            res = await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(f1.calls + f2.calls + f3.calls, 3)
            self.assertEqual(res.status, ResultStatus.QUOTA_FAILURE)
            self.assertIsNone(res.output)


# ---------------------------------------------------------------------------
# 13. EVENT BUS INTEGRATION
# ---------------------------------------------------------------------------

class TestEventBusIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_routing_event_trail_on_single_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = AsyncEventBus(db_path=f"{tmp}/events.db")
            seen = []

            async def emit(event_type, payload):
                seen.append(event_type)
                await bus.publish(Event(
                    event_type=EventType(event_type), payload=payload,
                    source="cognitive_router"), dispatch_immediately=True)

            rt = CognitiveRouter(health=ProviderHealthTracker(), ledger=None,
                                 emit=emit)
            rt.register_provider(StubProvider("p1", ["m1"]), configured=True)
            rt.register_provider(StubProvider("p2", ["m2"]), configured=True)
            await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertIn("ROUTING_STARTED", seen)
            self.assertIn("MODEL_SELECTED", seen)
            self.assertIn("PROVIDER_CALLED", seen)
            self.assertIn("PROVIDER_SUCCEEDED", seen)
            self.assertIn("ROUTING_COMPLETED", seen)

    async def test_failover_events_on_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = AsyncEventBus(db_path=f"{tmp}/events.db")
            seen = []

            async def emit(event_type, payload):
                seen.append(event_type)
                await bus.publish(Event(
                    event_type=EventType(event_type), payload=payload,
                    source="cognitive_router"), dispatch_immediately=True)

            rt = CognitiveRouter(health=ProviderHealthTracker(), ledger=None,
                                 emit=emit)
            rt.register_provider(StubProvider(
                "p1", ["m1"], fail_kind=ProviderFailureKind.QUOTA_FAILURE),
                configured=True)
            rt.register_provider(StubProvider("p2", ["m2"]), configured=True)
            await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertIn("PROVIDER_FAILED", seen)
            self.assertIn("FAILOVER_STARTED", seen)
            self.assertIn("PROVIDER_SUCCEEDED", seen)

    async def test_routing_failed_event_on_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = AsyncEventBus(db_path=f"{tmp}/events.db")
            seen = []

            async def emit(event_type, payload):
                seen.append(event_type)
                await bus.publish(Event(
                    event_type=EventType(event_type), payload=payload,
                    source="cognitive_router"), dispatch_immediately=True)

            rt = CognitiveRouter(health=ProviderHealthTracker(), ledger=None,
                                 emit=emit)
            await rt.execute(deep_task(), "q")
            self.assertIn("ROUTING_STARTED", seen)
            self.assertIn("MODEL_SELECTED", seen)
            self.assertIn("ROUTING_FAILED", seen)


# ---------------------------------------------------------------------------
# 14. REQUIRED E2E SCENARIOS
# ---------------------------------------------------------------------------

class TestRequiredE2E(unittest.IsolatedAsyncioTestCase):
    async def test_e2e_scenarios_1_2_fast_and_deep_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            rt.register_provider(StubProvider("fast_provider", ["fast-1"],
                                              field_profile="FAST_FIELD"),
                                 configured=True)
            rt.register_provider(StubProvider("deep_provider", ["deep-1"],
                                              field_profile="DEEP_FIELD"),
                                 configured=True)
            # Scenario 1: complex reasoning, high uncertainty, high stakes.
            s1 = rt.route(deep_task())
            self.assertEqual(s1.field, CognitiveField.DEEP_FIELD)
            self.assertEqual(s1.provider, "deep_provider")
            # Scenario 2: simple routine operation.
            s2 = rt.route(fast_task())
            self.assertEqual(s2.field, CognitiveField.FAST_FIELD)
            self.assertEqual(s2.provider, "fast_provider")

    async def test_e2e_scenario_3_gemini_only_routing(self):
        """Scenario 3 rewritten for the Gemini-only architecture: there are
        no local models and no OFFLINE_ONLY mode; the single configured
        provider serves every task."""
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            gemini = StubProvider("gemini", ["gemini-flash"], local=False)
            rt.register_provider(gemini, configured=True)
            sel = rt.route(fast_task())
            self.assertEqual(sel.provider, "gemini")
            res = await rt.execute(fast_task(), "q")
            self.assertEqual(res.status, ResultStatus.SUCCESS)
            self.assertEqual(res.output, "stub answer")

    async def test_e2e_scenario_4_selected_provider_fails_fallback_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            failing = StubProvider("aaa_failing", ["m1"],
                                   fail_kind=ProviderFailureKind.QUOTA_FAILURE)
            backup = StubProvider("zzz_backup", ["m2"])
            rt.register_provider(failing, configured=True)
            rt.register_provider(backup, configured=True)
            sel = rt.route(fast_task())
            self.assertEqual(sel.provider, "aaa_failing")  # selected first
            res = await rt.execute(fast_task(), "q", mode=RoutingMode.ONLINE_ALLOWED)
            self.assertEqual(res.status, ResultStatus.SUCCESS)
            self.assertEqual(res.provider, "zzz_backup")
            self.assertEqual(failing.calls, 1)
            # Provider failure recorded — not hidden.
            h = rt.health.get("aaa_failing")
            self.assertGreaterEqual(h.failures, 1)

    async def test_e2e_scenario_5_no_provider_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = make_router(tmp)
            res = await rt.execute(deep_task(), "q")
            self.assertEqual(res.status, ResultStatus.ROUTING_FAILED)
            self.assertIsNone(res.output)  # NO fabricated answer
            self.assertTrue(res.errors)



# ---------------------------------------------------------------------------
# 15. RUNTIME WIRING (engine level)
# ---------------------------------------------------------------------------

class TestRuntimeWiring(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_routes_and_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = CognitiveRuntime(data_dir=tmp)
            await rt.start()
            try:
                # Detach all providers so this test never touches the network;
                # routing must fail honestly and structurally.
                router = rt.cognitive_router
                router._providers.clear()
                router._provider_order.clear()
                router._models.clear()
                sel = rt.route_task(fast_task())
                self.assertEqual(sel.provider, "")
                res = await rt.execute_task(fast_task(), "q")
                self.assertEqual(res.status, ResultStatus.ROUTING_FAILED)
                self.assertIsNone(res.output)
                # Events landed on the runtime's single bus.
                replayed = await rt.event_bus.replay_events(limit=100)
                types = [e.event_type for e in replayed]
                self.assertIn(EventType.ROUTING_STARTED, types)
                self.assertIn(EventType.ROUTING_FAILED, types)
            finally:
                await rt.stop()

    async def test_engine_exposes_cognitive_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = AscendantEngine(data_dir=tmp)
            self.assertIsNotNone(engine.cognitive_runtime.cognitive_router)
            providers = engine.cognitive_runtime.cognitive_router.providers()
            # Gemini is the sole authoritative provider
            self.assertIn("gemini", providers)
            self.assertNotIn("openai", providers)
            self.assertNotIn("local_gguf", providers)

    async def test_runtime_verification_uses_slice3_evidence_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = CognitiveRuntime(data_dir=tmp)
            await rt.start()
            try:
                res = CognitiveResult(task_id="t9", provider="stub", model="m",
                                      output="x", status=ResultStatus.SUCCESS,
                                      verification_required=True)
                rt.record_observed_result(res, observation={"ok": True},
                                          source="real_tool")
                self.assertEqual(res.verification_status.value, "OBSERVED_RESULT")
                self.assertEqual(len(rt.evidence_store.list()), 1)
            finally:
                await rt.stop()


if __name__ == "__main__":
    unittest.main()
