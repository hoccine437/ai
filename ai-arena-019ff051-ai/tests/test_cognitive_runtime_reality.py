"""
ZERION X — cognitive runtime reality tests (T01-T17).

Behavior tests over the REAL runtime objects (no full-engine subprocess here,
except the ledger/pipeline integration which uses the real CognitiveRuntime +
router + GGUF adapter):

T01 goal understanding + persistence      T10 environmental limitation handling
T02 solution loop terminates + persists   T11 actual GGUF inference (stub backend)
T03 failure learning + escalation         T12 user input -> model path
T04 strategy switching (provenance)       T13 offline inference (no keys)
T05 capability lifecycle (evidence gate)  T14 model failure reporting
T06 safe self-testing (gate denies)       T15 no fake fallback cognition
T07 reality is the judge (belief)         T16 runtime persistence
T08 user learning (explicit signals)      T17 recovery after failure
T09 act/ask/retreat decision policy

T11-T13 use a STUB ``llama-cli`` binary and a valid-GGUF-magic fixture: the
full canonical pipeline (discovery -> router -> adapter -> subprocess backend
-> token capture -> runtime response) is exercised with REAL executed code.
Real llama.cpp weights cannot run in this container (no backend, no GGUF);
that limitation is stated in the test docstring, never hidden.
"""

import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.cognitive_os.router_types import RoutingMode, Task, TaskType


def _no_key_env() -> dict:
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    env.pop("ZERION_MODELS_DIR", None)
    return env


def _conv_task(prompt_note="task", uncertainty=0.4, stakes=0.1) -> Task:
    return Task(
        type=TaskType.CONVERSATION, description=prompt_note,
        difficulty=0.3, uncertainty=uncertainty, novelty=0.3,
        stakes=stakes, goal_relevance=0.5, required_capabilities=set(),
        offline_required=True, verification_required=False, metadata={})


def _make_runtime(data_dir: str, models_dir=None) -> CognitiveRuntime:
    env = _no_key_env()
    for k, v in env.items():
        os.environ[k] = v
    return CognitiveRuntime(data_dir=data_dir, models_dir=models_dir)


class TestGoalAndPersistence(unittest.IsolatedAsyncioTestCase):
    async def test_t01_t02_t16_goals_survive_restart_and_loop_terminates(self):
        from zerion.engine import AscendantEngine
        d = tempfile.mkdtemp(prefix="zerion_t01_")
        engine = AscendantEngine(data_dir=d)
        await engine.start()
        try:
            rt = engine.cognitive_runtime
            # T01: goal understanding (objective vs purpose vs progress).
            goal = await rt.create_goal(
                "Reduce code duplication", purpose="maintainability")
            self.assertTrue(goal.objective_id.startswith("goal_"))
            active = rt.objectives.list_active_objectives()
            self.assertTrue(any(g.objective_id == goal.objective_id
                                for g in active))
            await rt.set_goal_progress(goal.objective_id, 0.5,
                                       note="refactored",
                                       evidence="tests pass")
            # T02: the solution loop is bounded — one flywheel cycle
            # terminates with a real trace (no unbounded loop).
            trace = await engine.run_developmental_cycle()
            self.assertIsNotNone(trace.cycle_id)
        finally:
            await engine.stop()
        # T16: state persists across a full engine restart on the same data dir.
        engine2 = AscendantEngine(data_dir=d)
        await engine2.start()
        try:
            g2 = engine2.cognitive_runtime.objectives.get_goal(
                goal.objective_id)
            self.assertIsNotNone(g2, "goal lost after restart")
            self.assertAlmostEqual(g2.progress, 0.5, places=6)
        finally:
            await engine2.stop()


class TestFailureLearning(unittest.IsolatedAsyncioTestCase):
    async def test_t03_repeated_failure_escalates_investigation(self):
        rt = _make_runtime(tempfile.mkdtemp(prefix="zerion_t03_"))
        # First occurrence -> created, no escalation.
        first = rt.failure_learning.record_failure(
            episode_id="ep1", action="parse_config", error="syntax error",
            signals=["cfg parse"])
        self.assertTrue(first["created"])
        # Repeat with identical fingerprint -> recurrence, repeat_count grows.
        second = rt.failure_learning.record_failure(
            episode_id="ep2", action="parse_config", error="syntax error",
            signals=["cfg parse"])
        self.assertFalse(second["created"])
        self.assertEqual(second["repeat_count"], 2)
        self.assertFalse(second["escalated"])
        # Threshold (3) reached -> escalation fires: strategy must change,
        # never repeat the same failed approach silently.
        third = rt.failure_learning.record_failure(
            episode_id="ep3", action="parse_config", error="syntax error",
            signals=["cfg parse"])
        self.assertEqual(third["repeat_count"], 3)
        self.assertTrue(third["escalated"])


class TestStrategySwitching(unittest.TestCase):
    def test_t04_strategy_retirement_is_provenanced_and_nondestructive(self):
        from zerion.cognitive_genesis.registry import StrategyRegistry
        from zerion.cognitive_genesis.strategy import CognitiveStrategy
        from zerion.strategy_evolution.evolution_engine import \
            StrategyEvolutionEngine
        d = tempfile.mkdtemp(prefix="zerion_t04_")
        reg = StrategyRegistry(db_path=str(Path(d) / "strategies.db"))
        s1 = CognitiveStrategy(name="s1", domain="reasoning")
        s2 = CognitiveStrategy(name="s2", domain="reasoning")
        reg.register_strategy(s1)
        reg.register_strategy(s2)
        active_ids = [s.strategy_id
                      for s in reg.list_strategies(active_only=True)]
        self.assertIn(s1.strategy_id, active_ids)
        self.assertIn(s2.strategy_id, active_ids)
        evo = StrategyEvolutionEngine(db_path=str(Path(d) / "evo.db"))
        evo.retire_strategy(s1, reason="underperformed",
                            superseded_by=s2.strategy_id)
        self.assertFalse(s1.is_active)
        active_ids = [s.strategy_id
                      for s in reg.list_strategies(active_only=True)]
        self.assertNotIn(s1.strategy_id, active_ids)
        # Non-destructive: the retired strategy is still retrievable.
        self.assertIsNotNone(reg.get_strategy(s1.strategy_id))


class TestCapabilityLifecycle(unittest.TestCase):
    def test_t05_evidence_is_required_for_capability_registration(self):
        from zerion.capabilities.birth import BornCapability
        from zerion.capabilities.registry import DynamicCapabilityRegistry
        d = tempfile.mkdtemp(prefix="zerion_t05_")
        reg = DynamicCapabilityRegistry(db_path=str(Path(d) / "caps.db"))
        # A generated capability without validation evidence is NOT a capability.
        unvalidated = BornCapability(
            name="fake_cap", category="coding", specification="s",
            implementation_code="def fake(): pass", unit_tests_code="",
            benchmark_score=0.0, is_validated=False)
        self.assertFalse(reg.register_born_capability(unvalidated))
        self.assertEqual(reg.list_born_capabilities(), [])
        # Evidence-validated capability registers and is listed.
        validated = BornCapability(
            name="real_cap", category="coding", specification="s",
            implementation_code="def real(): return 1", unit_tests_code="",
            benchmark_score=0.9, is_validated=True)
        self.assertTrue(reg.register_born_capability(validated))
        self.assertEqual([c.name for c in reg.list_born_capabilities()],
                         ["real_cap"])


class TestSelfTestingGate(unittest.TestCase):
    def test_t06_self_modification_gate_denies_unverified_claims(self):
        from zerion.cognitive_os.improvement import ImprovementProposal
        from zerion.cognitive_os.self_modification_gate import SelfModificationGate
        gate = SelfModificationGate()
        # A proposal presenting unmeasured claims as fact must be denied by
        # the invariant gate (INV-*), never silently accepted.
        bad = ImprovementProposal(
            target_component="router", problem="p", hypothesis="h",
            proposed_change={"policy": "x", "value": 1},
            analysis={"claims_measured": False})
        ok, reason = gate.approve(bad)
        self.assertFalse(ok)
        self.assertNotEqual(reason, "")


class TestBeliefRevision(unittest.TestCase):
    def test_t07_reality_is_the_judge(self):
        from zerion.cognitive_os.belief import Belief, BeliefRevision
        from zerion.cognitive_os.evidence import (
            Evidence,
            EvidenceMode,
            EvidenceVerdict,
            Provenance,
        )
        now = time.time()
        rev = BeliefRevision()
        b = Belief(statement="tests reliably catch regressions",
                   confidence=0.3)
        model_ev = Evidence(
            content={"text": "the model asserts this is true"},
            provenance=Provenance(source="local_gguf", observed_at=now,
                                  evidence_type="model_output",
                                  content_reference="r1", reliability=0.9,
                                  mode=EvidenceMode.MODEL_GENERATED,
                                  recorded_at=now),
            verdict=EvidenceVerdict.SUPPORTS)
        b_after_model, meta_model = rev.apply(b, model_ev)
        # Model output alone can never strengthen a belief (provenance only).
        self.assertAlmostEqual(b_after_model.confidence, 0.3, places=6)
        self.assertFalse(meta_model.get("applied"))
        obs_ev = Evidence(
            content={"observed_result": "passed 41/41"},
            provenance=Provenance(source="test_runner", observed_at=now,
                                  evidence_type="observation",
                                  content_reference="r2", reliability=1.0,
                                  mode=EvidenceMode.OBSERVED, recorded_at=now),
            verdict=EvidenceVerdict.SUPPORTS)
        b_after_obs, meta_obs = rev.apply(b_after_model, obs_ev)
        # Observed reality DOES revise the belief.
        self.assertGreater(b_after_obs.confidence, 0.3)
        self.assertTrue(meta_obs.get("applied"))
        # Revision history is preserved, never overwritten.
        self.assertGreaterEqual(len(b_after_obs.revision_history), 1)


class TestUserLearning(unittest.TestCase):
    def test_t08_explicit_user_signals_are_learned_and_persist(self):
        from zerion.cognitive_os.user_learning import UserLearningStore
        d = tempfile.mkdtemp(prefix="zerion_t08_")
        store = UserLearningStore(data_dir=d)
        pref = store.observe_turn("I prefer short answers from now on")
        self.assertEqual(pref.kind, "instruction")  # "from now on" marker
        corr = store.observe_turn("don't repeat the same strategy")
        self.assertEqual(corr.kind, "correction")
        neutral = store.observe_turn("what is the weather?")
        self.assertEqual(neutral.kind, "neutral")
        learned = store.learned_preferences()
        self.assertEqual(len(learned), 2)
        # Persistence across a restart of the store.
        store2 = UserLearningStore(data_dir=d)
        self.assertEqual(len(store2.learned_preferences()), 2)


class TestDecisionPolicy(unittest.TestCase):
    def test_t09_act_ask_retreat_policy_is_deterministic(self):
        from zerion.cognitive_os.decision_policy import (
            Decision,
            DecisionPolicy,
        )
        p = DecisionPolicy()
        self.assertEqual(p.decide(
            permissions_allowed=False).decision, Decision.STOP)
        self.assertEqual(p.decide(
            provider_available=False).decision, Decision.RETRY)
        self.assertEqual(p.decide(
            uncertainty=0.9, stakes=0.9).decision, Decision.ASK)
        self.assertEqual(p.decide(
            uncertainty=0.85, stakes=0.2).decision, Decision.VERIFY)
        self.assertEqual(p.decide(
            missing_information=True).decision, Decision.DEFER)
        self.assertEqual(p.decide(
            stakes=0.1, confidence=0.9).decision, Decision.ACT)
        self.assertEqual(p.decide(
            uncertainty=0.5, stakes=0.5, confidence=0.5).decision,
            Decision.WAIT)
        # Every verdict carries an explicit reason.
        for kwargs in ({"permissions_allowed": False},
                       {"provider_available": False},
                       {"uncertainty": 0.9, "stakes": 0.9}):
            self.assertTrue(p.decide(**kwargs).reason)


class TestResourceLimitations(unittest.TestCase):
    def test_t10_environmental_limits_change_recommended_action(self):
        from zerion.runtime.resources import ResourceManager
        m = ResourceManager(low_memory_threshold_mb=256.0)
        low_snap = mock.MagicMock(
            memory_available_mb=64.0, compute_tier="HIGH")
        rich_snap = mock.MagicMock(
            memory_available_mb=4096.0, compute_tier="HIGH")
        with mock.patch.object(m, "sample", return_value=low_snap):
            low = m.get_recommended_compute_mode(50, 0.8)
        with mock.patch.object(m, "sample", return_value=rich_snap):
            rich = m.get_recommended_compute_mode(50, 0.8)
        # A memory limitation forces a more conservative compute mode.
        self.assertIn(low, ("REFLEX", "FAST"))
        self.assertIn(rich, ("NORMAL", "DEEP", "EXTREME", "EXPERIMENTAL",
                             "REFLEX", "FAST"))
        self.assertNotEqual(low, rich)


class TestGGUFPipeline(unittest.TestCase):
    """T11-T15: real canonical pipeline with a stub llama.cpp backend.

    The stub binary is a TEST HARNESS (clearly labeled): it receives the real
    CLI invocation produced by ``LocalGGUFProvider._run_cli`` and emits real
    stdout tokens, proving discovery -> router -> adapter -> backend -> token
    capture -> runtime response end to end. Real llama.cpp weights are not
    present in this container; that is the only simulated component."""

    STUB = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "def val(flag):\n"
        "    try:\n"
        "        return args[args.index(flag) + 1]\n"
        "    except (ValueError, IndexError):\n"
        "        return None\n"
        "prompt = val('-p') or ''\n"
        "model = val('-m') or ''\n"
        "sys.stdout.write('STUB-INFERENCE[' + model.split('/')[-1] + '] '\n"
        "                 'REPLY TO: ' + prompt)\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="zerion_gguf_")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.models_dir = root / "models"
        self.models_dir.mkdir(parents=True)
        (self.models_dir / "test-model.gguf").write_bytes(
            b"GGUF" + b"\x00" * 64)  # valid GGUF magic -> AVAILABLE
        self.bin_dir = root / "bin"
        self.bin_dir.mkdir()
        stub = self.bin_dir / "llama-cli"
        stub.write_text(self.STUB, encoding="utf-8")
        stub.chmod(0o755)
        self._old_env = dict(os.environ)
        os.environ.update(_no_key_env())
        os.environ["ZERION_GGUF_BACKEND"] = "cli"
        os.environ["PATH"] = str(self.bin_dir) + os.pathsep + \
            os.environ.get("PATH", "")
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_t11_t12_t13_user_input_reaches_model_and_tokens_return_offline(self):
        d = Path(self.tmp.name) / "data"
        rt = CognitiveRuntime(data_dir=str(d), models_dir=str(self.models_dir))
        task = _conv_task()
        res = asyncio.run(rt.execute_task(
            task, "What is 25 x 4?", mode=RoutingMode.OFFLINE_ONLY))
        # T11: real inference result from the backend (stub), not canned text.
        self.assertEqual(res.status.value, "SUCCESS")
        self.assertEqual(res.provider, "local_gguf")
        self.assertEqual(res.model, "test-model")
        self.assertIn("What is 25 x 4?", res.output)
        self.assertNotIn("[FALLBACK", res.output)
        # T12: user input is observable in the ledger request.
        req = rt.inference_ledger.last_request()
        self.assertEqual(req.user_input, "What is 25 x 4?")
        self.assertEqual(req.selected_provider, "local_gguf")
        self.assertEqual(req.selected_model, "test-model")
        # T13: offline — no API keys present, OFFLINE_ONLY mode.
        self.assertNotIn("OPENAI_API_KEY", os.environ)
        self.assertNotIn("GEMINI_API_KEY", os.environ)
        last = rt.inference_ledger.last_result()
        self.assertTrue(last.success)
        self.assertIn("What is 25 x 4?", last.generated_text)
        self.assertEqual(last.termination_reason, "SUCCESS")

    def test_t14_model_failure_is_reported_not_pretended(self):
        # Model file exists but backend is disabled -> honest failure reported.
        os.environ["ZERION_GGUF_BACKEND"] = "none"
        d = Path(self.tmp.name) / "data2"
        rt = CognitiveRuntime(data_dir=str(d), models_dir=str(self.models_dir))
        res = asyncio.run(rt.execute_task(
            _conv_task(), "tell me about quantum physics", mode=RoutingMode.OFFLINE_ONLY))
        # Failure is reported honestly — output must be None, errors must exist.
        # The exact status depends on routing: MODEL_LOAD_FAILURE or ROUTING_FAILED.
        self.assertIsNone(res.output)
        self.assertTrue(res.errors, "Errors must explain the failure")
        last = rt.inference_ledger.last_result()
        self.assertFalse(last.success)
        self.assertIsNone(last.generated_text)

    def test_t15_no_fake_fallback_cognition_when_model_absent(self):
        # No model file at all -> ROUTING_FAILED, output None, never canned.
        empty_models = Path(self.tmp.name) / "models_empty"
        empty_models.mkdir(exist_ok=True)
        d = Path(self.tmp.name) / "data3"
        rt = CognitiveRuntime(data_dir=str(d), models_dir=str(empty_models))
        res = asyncio.run(rt.execute_task(
            _conv_task(), "tell me about quantum physics", mode=RoutingMode.OFFLINE_ONLY))
        self.assertEqual(res.status.value, "ROUTING_FAILED")
        self.assertIsNone(res.output)
        self.assertTrue(res.errors)

    def test_t17_recovery_after_failure_same_runtime_stays_alive(self):
        from zerion.cognitive_os.router_types import ProviderStatus
        os.environ["ZERION_GGUF_BACKEND"] = "none"
        d = Path(self.tmp.name) / "data4"
        rt = CognitiveRuntime(data_dir=str(d), models_dir=str(self.models_dir))
        fail = asyncio.run(rt.execute_task(
            _conv_task(), "first", mode=RoutingMode.OFFLINE_ONLY))
        self.assertEqual(fail.status.value, "MODEL_LOAD_FAILURE")
        # The runtime reports the failure and stays alive; the circuit
        # breaker honestly opens (provider UNAVAILABLE after the failure).
        self.assertEqual(
            rt.cognitive_router.health.status("local_gguf"),
            ProviderStatus.UNAVAILABLE)
        # Environment fixed (backend enabled) + operator clears the breaker:
        # the SAME runtime instance recovers with a real inference.
        os.environ["ZERION_GGUF_BACKEND"] = "cli"
        rt.cognitive_router.health.reset("local_gguf")
        ok = asyncio.run(rt.execute_task(
            _conv_task(), "second", mode=RoutingMode.OFFLINE_ONLY))
        self.assertEqual(ok.status.value, "SUCCESS")
        self.assertIn("second", ok.output)
        ledger = rt.inference_ledger.summary()
        self.assertEqual(ledger["total"], 2)
        self.assertEqual(ledger["failures"], 1)
        self.assertEqual(ledger["successes"], 1)


class TestMainPyGGUFProductRun(unittest.TestCase):
    """Phase 8 product proof: the REAL ``python main.py --chat`` product,
    with a discovered .gguf and the stub llama.cpp backend on PATH, accepts a
    typed message, routes it through the real runtime to the backend, prints
    the generated response, loops for a second turn, and exits cleanly."""

    def test_product_end_to_end_with_local_model_backend(self):
        import signal as _signal
        from pathlib import Path as _Path
        tmp = tempfile.mkdtemp(prefix="zerion_prod_")
        root = _Path(tmp)
        models = root / "models"
        models.mkdir(parents=True)
        (models / "qwen2-0.5b.gguf").write_bytes(b"GGUF" + b"\x00" * 64)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "llama-cli"
        stub.write_text(TestGGUFPipeline.STUB, encoding="utf-8")
        stub.chmod(0o755)
        env = _no_key_env()
        env["ZERION_MODELS_DIR"] = str(models)
        env["ZERION_GGUF_BACKEND"] = "cli"
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        proc = subprocess.Popen(
            [sys.executable, "-u", "main.py", "--chat", "--data-dir",
             str(root / "data")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, env=env,
            cwd=str(Path(__file__).resolve().parent.parent))
        buf: list = []

        def read_until(sub: str, timeout: float) -> tuple:
            start = len(buf)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ch = proc.stdout.read(1)
                if not ch:
                    return "".join(buf), False
                buf.append(ch)
                if sub in "".join(buf[start:]):
                    return "".join(buf), True
            return "".join(buf), False

        try:
            out, ok = read_until("YOU > ", 90)
            self.assertTrue(ok, msg=f"no prompt:\n{out}")
            # Honest banner: the discovered model is named, not faked.
            self.assertIn("MODEL:", out)
            self.assertIn("qwen2-0.5b", out)
            proc.stdin.write("What is 25 x 4?\n")
            proc.stdin.flush()
            out, ok = read_until("YOU > ", 60)
            self.assertTrue(ok, msg=f"no response:\n{out}")
            self.assertIn("STUB-INFERENCE[qwen2-0.5b.gguf]", out)
            self.assertIn("What is 25 x 4?", out)
            # Second turn proves the loop is persistent.
            proc.stdin.write("Hello again.\n")
            proc.stdin.flush()
            out, ok = read_until("YOU > ", 60)
            self.assertTrue(ok, msg=f"no second response:\n{out}")
            proc.stdin.write("exit\n")
            proc.stdin.flush()
            read_until("shutting down cleanly", 20)
            proc.stdin.close()
            proc.wait(timeout=30)
            self.assertEqual(proc.returncode, 0,
                             msg=f"exit {proc.returncode}: {out}")
        finally:
            if proc.poll() is None:
                proc.send_signal(_signal.SIGINT)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    unittest.main()
