"""
ZERION runtime identity & capability integration tests.

Proves the local model (Qwen) is only the reasoning engine underneath a
ZERION-owned runtime:

- the identity layer injects ZERION identity, constitution, cognition mode,
  memory, goals, capabilities and tools into EVERY model prompt (bounded);
- "who are you?" / "what can you do?" / "remember X" / "recall X" route to
  REAL local tools (identity store, capability registry, episodic memory);
- a model-requested tool call is validated against the real registry and
  executed with the result fed back for the final response;
- the self-critic verifies low-confidence results (bounded revise/retry)
  and never presents empty output as success;
- every turn updates episodic memory.

Hermetic: a stub model provider stands in for the GGUF engine.
"""

import asyncio
import os
import tempfile
import unittest

from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.cognitive_os.provider_interface import (
    TEXT,
    ModelInfo,
    RawProviderResponse,
)
from zerion.cognitive_os.router_types import (
    ProviderStatus,
    RoutingMode,
    Task,
    TaskType,
)
from zerion.cognitive_os.self_critic import (
    DEFAULT_MAX_REVISIONS,
    SelfCriticDecision,
    ZerionSelfCritic,
)
from zerion.cognitive_os.tool_router import ZerionToolRouter
from zerion.cognitive_os.zerion_context import (
    IDENTITY_RULE,
    ZerionRuntimeContext,
)
from zerion.identity.invariants import CORE_INVARIANTS

_ENV_KEYS = ("ZERION_CONTEXT_MAX_CHARS",)


class _FakeIdentity:
    system_name = "ZERION-X ASCENDANT"
    system_id = "ascendant-core-v1"
    invariants = list(CORE_INVARIANTS)


class _FakeSelfModel:
    def __init__(self, names):
        self.names = names

    def what_can_i_do(self):
        return [{"name": n, "category": "native", "reliability": 0.9}
                for n in self.names]


class _StubProvider:
    """Stand-in for the GGUF engine: echoes a scripted answer and records the
    exact prompt it received (so tests can assert the identity layer)."""

    provider_name = "stub"
    is_local = True
    field_profile = None

    def __init__(self, script, model_id="stub-model"):
        self.script = script
        self.model_id = model_id
        self.calls = []

    async def generate(self, call):
        self.calls.append(call.prompt)
        text = self.script(call.prompt) if callable(self.script) \
            else self.script
        if text is None:
            return RawProviderResponse(output=None, success=False,
                                       error="stub returned nothing")
        return RawProviderResponse(output=text, success=True, latency_ms=1.0,
                                   usage={})

    async def stream(self, call):
        raise NotImplementedError

    async def health_check(self):
        return ProviderStatus.AVAILABLE

    def capabilities(self):
        return {TEXT}

    def list_models(self):
        return [ModelInfo(model_id=self.model_id, provider=self.provider_name,
                          capabilities={TEXT},
                          status=ProviderStatus.AVAILABLE)]

    def model_info(self, model_id):
        return self.list_models()[0] if model_id == self.model_id else None


class _ZerionIdentityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zerion_identity_")
        self._saved_env = dict(os.environ)
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _runtime(self):
        runtime = CognitiveRuntime(data_dir=self._tmp)
        self.stub = _StubProvider(script="hello from stub engine")
        runtime.cognitive_router.register_provider(
            self.stub, configured=True)
        return runtime

    def _task(self, text, **overrides):
        defaults = dict(type=TaskType.CONVERSATION,
                        description=f"User message: {text[:200]}",
                        difficulty=0.3, uncertainty=0.4, novelty=0.3,
                        stakes=0.1, goal_relevance=0.5,
                        required_capabilities={TEXT},
                        offline_required=True, verification_required=False,
                        metadata={"source": "test"})
        defaults.update(overrides)
        return Task(**defaults)


# ---------------------------------------------------------------------------
# Identity / context layer
# ---------------------------------------------------------------------------


class TestZerionContext(_ZerionIdentityTestBase):
    def test_context_injects_zerion_identity_and_constitution(self):
        runtime = self._runtime()
        ctx = ZerionRuntimeContext(runtime, identity=_FakeIdentity(),
                                   self_model=_FakeSelfModel(
                                       ["observe_reality",
                                        "causal_inference"]))
        system = ctx.build_system_prompt("hello", field="FAST_FIELD")
        self.assertIn(IDENTITY_RULE, system)
        self.assertIn("ZERION-X ASCENDANT", system)
        # Qwen is the engine, never the identity.
        self.assertIn("Never claim to be Qwen", system)
        # Constitution: real invariants.
        self.assertIn("INV-001", system)
        self.assertIn("Epistemic Integrity", system)
        # Cognition mode + capability registry from REAL state.
        self.assertIn("FAST_FIELD", system)
        self.assertIn("observe_reality", system)
        self.assertIn("causal_inference", system)

    def test_context_includes_memory_goals_and_tools(self):
        runtime = self._runtime()
        ctx = ZerionRuntimeContext(runtime, identity=_FakeIdentity())
        # A real stored memory surfaces via relevance retrieval.
        from zerion.cognitive_os.episode import (
            EpisodeMode,
            EpisodeStatus,
            ExperienceEpisode,
        )
        runtime.episode_store.put(ExperienceEpisode(
            context="user asked ZERION to remember: the sky is blue",
            mode=EpisodeMode.OBSERVED, status=EpisodeStatus.COMPLETED,
            success=True))
        system = ctx.build_system_prompt(
            "what do you remember about the sky",
            tools=[{"name": "memory_recall",
                    "description": "retrieve stored memory"}])
        self.assertIn("the sky is blue", system)
        self.assertIn("memory_recall", system)
        self.assertIn("Available tools", system)

    def test_context_is_size_bounded(self):
        runtime = self._runtime()
        ctx = ZerionRuntimeContext(runtime, identity=_FakeIdentity(),
                                   self_model=_FakeSelfModel(
                                       ["c" + str(i) for i in range(60)]))
        os.environ["ZERION_CONTEXT_MAX_CHARS"] = "700"
        ctx.max_chars = 700
        system = ctx.build_system_prompt("hello")
        self.assertLessEqual(len(system), 700)
        # The identity rule is never truncated away.
        self.assertIn(IDENTITY_RULE, system)

    def test_context_never_breaks_on_partial_runtime(self):
        # A bare object (no stores) must produce a usable prompt.
        class _Bare:
            pass
        ctx = ZerionRuntimeContext(_Bare(), identity=None, self_model=None)
        system = ctx.build_system_prompt("hello")
        self.assertIn(IDENTITY_RULE, system)


# ---------------------------------------------------------------------------
# Tool router (real local capabilities)
# ---------------------------------------------------------------------------


class TestToolRouter(_ZerionIdentityTestBase):
    def test_identity_tool_reports_zerion_not_qwen(self):
        runtime = self._runtime()
        router = ZerionToolRouter(runtime, identity=_FakeIdentity())
        self.assertEqual(router.detect("who are you?"), "identity")
        result = asyncio.run(router.execute("identity", "who are you?"))
        self.assertTrue(result.ok)
        self.assertIn("ZERION-X ASCENDANT", result.output)
        self.assertNotIn("Qwen", result.output)

    def test_capabilities_tool_lists_real_registry(self):
        runtime = self._runtime()
        router = ZerionToolRouter(
            runtime, self_model=_FakeSelfModel(
                ["observe_reality", "causal_inference", "memory_store"]))
        self.assertEqual(router.detect("what can you do?"), "capabilities")
        result = asyncio.run(router.execute("capabilities", "what can you do?"))
        self.assertTrue(result.ok)
        self.assertIn("observe_reality", result.output)
        self.assertIn("causal_inference", result.output)

    def test_memory_store_then_recall_roundtrip(self):
        runtime = self._runtime()
        router = ZerionToolRouter(runtime)
        self.assertEqual(
            router.detect("remember that the project codename is NEXUS"),
            "memory_store")
        result = asyncio.run(
            router.execute("memory_store",
                           "remember that the project codename is NEXUS"))
        self.assertTrue(result.ok, result.error)
        self.assertIn("Learned", result.output)
        # Real persistence in the episodic store.
        self.assertGreaterEqual(runtime.episode_store.count(), 1)
        stored = runtime.episode_store.list()[-1]
        self.assertIn("NEXUS", stored.context)
        # Recall finds it through real retrieval.
        self.assertEqual(router.detect("recall NEXUS"), "memory_recall")
        recalled = asyncio.run(router.execute("memory_recall", "recall NEXUS"))
        self.assertTrue(recalled.ok)
        self.assertIn("NEXUS", recalled.output)

    def test_memory_recall_honest_miss(self):
        runtime = self._runtime()
        router = ZerionToolRouter(runtime)
        result = asyncio.run(
            router.execute("memory_recall", "recall quantum flux"))
        self.assertTrue(result.ok)
        self.assertIn("no stored memory", result.output)

    def test_unknown_tool_never_executed(self):
        runtime = self._runtime()
        router = ZerionToolRouter(runtime)
        parsed = router.parse_model_tool_call("[[TOOL:delete_everything|x]]")
        self.assertIsNone(parsed)  # not registered -> never executed
        result = asyncio.run(router.execute("delete_everything", "x"))
        self.assertFalse(result.ok)
        self.assertIn("not registered", result.error)

    def test_model_tool_call_parses_only_registered_tools(self):
        runtime = self._runtime()
        router = ZerionToolRouter(runtime)
        parsed = router.parse_model_tool_call("[[TOOL:identity|]]")
        self.assertEqual(parsed, ("identity", ""))
        parsed = router.parse_model_tool_call(
            "I need to check.\n[[TOOL:memory_store|remember the passcode]]")
        self.assertEqual(parsed,
                         ("memory_store", "remember the passcode"))
        parsed = router.parse_model_tool_call("plain answer as ZERION")
        self.assertIsNone(parsed)


# ---------------------------------------------------------------------------
# Self-critic
# ---------------------------------------------------------------------------


class TestSelfCritic(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zerion_identity_critic_")
        self._saved_env = dict(os.environ)
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _runtime(self):
        runtime = CognitiveRuntime(data_dir=self._tmp)
        self.stub = _StubProvider(script="hello from stub engine")
        runtime.cognitive_router.register_provider(
            self.stub, configured=True)
        return runtime
    def _result(self, output=None, status="SUCCESS"):
        from types import SimpleNamespace
        return SimpleNamespace(
            output=output,
            status=SimpleNamespace(value=status),
            errors=[], mode=RoutingMode.OFFLINE_ONLY,
            metadata={}, provider="stub", model="stub-model",
            latency_ms=1.0, usage={}, verification_required=False)

    def _task(self, text, **overrides):
        defaults = dict(type=TaskType.CONVERSATION,
                        description=f"User message: {text[:200]}",
                        difficulty=0.3, uncertainty=0.4, novelty=0.3,
                        stakes=0.1, goal_relevance=0.5,
                        required_capabilities={TEXT},
                        offline_required=True, verification_required=False,
                        metadata={"source": "test"})
        defaults.update(overrides)
        return Task(**defaults)

    async def test_accepts_good_output(self):
        runtime = self._runtime()
        critic = ZerionSelfCritic(runtime)
        decision, note, revised = await critic.review(
            self._task("hello"), self._result("a good answer"),
            user_text="hello", revisions_used=0)
        self.assertEqual(decision, SelfCriticDecision.ACCEPT)
        self.assertIsNone(revised)

    async def test_deep_short_answer_triggers_revise(self):
        runtime = self._runtime()
        critic = ZerionSelfCritic(runtime)
        task = self._task("complex novel problem", uncertainty=0.9,
                          novelty=0.9, difficulty=0.9, stakes=0.9)
        decision, note, _ = await critic.review(
            task, self._result("maybe"), user_text="complex novel problem",
            revisions_used=0)
        self.assertEqual(decision, SelfCriticDecision.REVISE)

    async def test_empty_output_escalates_after_budget(self):
        runtime = self._runtime()
        critic = ZerionSelfCritic(runtime)
        decision, note, _ = await critic.review(
            self._task("hi"), self._result(None),
            user_text="hi", revisions_used=DEFAULT_MAX_REVISIONS)
        self.assertEqual(decision, SelfCriticDecision.ESCALATE)

    async def test_critique_pass_returns_better_answer(self):
        runtime = self._runtime()

        def script(prompt):
            return "corrected by critique" if any(w in prompt for w in ("Critique", "Analyze", "critique", "analyze")) \
                else "uncertain"
        self.stub.script = script
        critic = ZerionSelfCritic(runtime)
        original = self._result("uncertain")
        full_prompt = "identity context\n\nUser: hi"
        revised = await critic.critique(self._task("hi"), original,
                                        full_prompt=full_prompt)
        # The stub receives the critique prompt and returns the correction.
        self.assertTrue(self.stub.calls)
        self.assertTrue(any(w in self.stub.calls[-1] for w in ("Critique", "Analyze", "critique", "analyze")))
        self.assertEqual(revised, "corrected by critique")


# ---------------------------------------------------------------------------
# Canonical live loop (execute_task)
# ---------------------------------------------------------------------------


class TestExecuteTaskIdentityLoop(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zerion_identity_loop_")
        self._saved_env = dict(os.environ)
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self.runtime = CognitiveRuntime(data_dir=self._tmp)
        self.stub = _StubProvider(script="hello from stub engine")
        self.runtime.cognitive_router.register_provider(
            self.stub, configured=True)
        self.identity = _FakeIdentity()
        self.runtime._identity = self.identity
        self.runtime.tool_router = ZerionToolRouter(
            self.runtime, identity=self.identity)
        self.runtime.zerion_context = ZerionRuntimeContext(
            self.runtime, identity=self.identity)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _task(self, text, **overrides):
        defaults = dict(type=TaskType.CONVERSATION,
                        description=f"User message: {text[:200]}",
                        difficulty=0.3, uncertainty=0.4, novelty=0.3,
                        stakes=0.1, goal_relevance=0.5,
                        required_capabilities={TEXT},
                        offline_required=True, verification_required=False,
                        metadata={"source": "test"})
        defaults.update(overrides)
        return Task(**defaults)

    async def test_model_prompt_contains_zerion_identity(self):
        result = await self.runtime.execute_task(
            self._task("tell me about quantum physics"), "tell me about quantum physics", mode=RoutingMode.OFFLINE_ONLY)
        self.assertEqual(result.status.value, "SUCCESS")
        self.assertEqual(result.output, "hello from stub engine")
        # The provider received the ZERION identity context, not bare text.
        self.assertTrue(self.stub.calls)
        prompt = self.stub.calls[0]
        self.assertIn(IDENTITY_RULE, prompt)
        self.assertIn("tell me about quantum physics", prompt)  # user message present in prompt
        self.assertIn("ZERION-X ASCENDANT", prompt)
        # The turn became a real episodic memory record.
        self.assertGreaterEqual(self.runtime.episode_store.count(), 1)
        ep = self.runtime.episode_store.list()[-1]
        self.assertIn("tell me about quantum physics", ep.context)
        self.assertTrue(ep.success)

    async def test_who_are_you_fast_path_is_zerion_not_qwen(self):
        stub_calls = len(self.stub.calls)
        result = await self.runtime.execute_task(
            self._task("who are you?"), "who are you?",
            mode=RoutingMode.OFFLINE_ONLY)
        self.assertEqual(result.provider, "local_tool")
        # The fast path answers from the REAL identity store — the stub model
        # was never called, and Qwen never introduces itself.
        self.assertEqual(len(self.stub.calls), stub_calls)
        self.assertIn("I am ZERION", result.output)
        self.assertNotIn("Qwen", result.output)
        # The turn is still recorded to episodic memory.
        self.assertGreaterEqual(self.runtime.episode_store.count(), 1)

    async def test_what_can_you_do_lists_real_capabilities(self):
        self.runtime.tool_router = ZerionToolRouter(
            self.runtime, self_model=_FakeSelfModel(
                ["observe_reality", "causal_inference", "memory_store"]))
        result = await self.runtime.execute_task(
            self._task("what can you do?"), "what can you do?",
            mode=RoutingMode.OFFLINE_ONLY)
        self.assertEqual(result.provider, "local_tool")
        self.assertIn("observe_reality", result.output)
        self.assertIn("causal_inference", result.output)
        self.assertEqual(len(self.stub.calls), 0)

    async def test_remember_and_recall_roundtrip_through_loop(self):
        await self.runtime.execute_task(
            self._task("remember the passcode is 4242"),
            "remember the passcode is 4242",
            mode=RoutingMode.OFFLINE_ONLY)
        self.assertGreaterEqual(self.runtime.episode_store.count(), 1)
        result = await self.runtime.execute_task(
            self._task("recall the passcode"), "recall the passcode",
            mode=RoutingMode.OFFLINE_ONLY)
        self.assertEqual(result.provider, "local_tool")
        self.assertIn("4242", result.output)

    async def test_deep_task_runs_bounded_self_critique(self):
        self.stub.script = "maybe"
        task = self._task("complex novel high-stakes problem",
                          difficulty=0.9, uncertainty=0.9, novelty=0.9,
                          stakes=0.9)
        result = await self.runtime.execute_task(
            task, "complex novel high-stakes problem",
            mode=RoutingMode.OFFLINE_ONLY)
        # The stub returned the same text for both passes; the critic kept the
        # original and recorded the decision (bounded, terminates).
        self.assertEqual(result.output, "maybe")
        decisions = [d["decision"] for d in result.metadata["self_critic"]]
        self.assertIn("REVISE", decisions)
        # Bounded: at most max_revisions + 1 model calls for the critique.
        self.assertLessEqual(len(self.stub.calls), 3)

    async def test_empty_model_output_is_honest_failure(self):
        self.stub.script = None  # stub returns no output
        result = await self.runtime.execute_task(
            self._task("tell me about quantum physics"), "tell me about quantum physics", mode=RoutingMode.OFFLINE_ONLY)
        self.assertIsNone(result.output)
        self.assertNotEqual(result.status.value, "SUCCESS")
        decisions = [d["decision"] for d in result.metadata.get(
            "self_critic", [])]
        self.assertTrue(decisions)  # critic ran
        self.assertIn("ESCALATE", decisions)
        ep = self.runtime.episode_store.list()[-1]
        self.assertFalse(ep.success)

    async def test_model_requested_tool_call_executes_then_phrases(self):
        # First call: model requests the identity tool. Second call (with the
        # tool result): final phrasing. The phrase avoids the FAST-FIELD
        # deterministic "who are you" match so the model path is exercised.
        calls = []

        def script(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                return "[[TOOL:identity|]]"
            return "I am ZERION-X ASCENDANT, the system."
        self.stub.script = script
        result = await self.runtime.execute_task(
            self._task("state your identity formally"),
            "state your identity formally", mode=RoutingMode.OFFLINE_ONLY)
        self.assertEqual(len(calls), 2)
        self.assertIn("Tool result:", calls[1])
        self.assertIn("ZERION-X ASCENDANT", result.output)
        self.assertEqual(result.metadata.get("tool_used"), "identity")
        self.assertTrue(result.metadata.get("tool_success"))


if __name__ == "__main__":
    unittest.main()
