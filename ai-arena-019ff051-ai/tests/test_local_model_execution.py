"""
ZERION X — 100% LOCAL MODEL EXECUTION tests (spec §31–§43).

Covers:
- main.py is the canonical startup command and starts the real Zerion X
  runtime (not a legacy/competing architecture)
- main.py prints the ZERION LOCAL READINESS block from REAL runtime checks
- default `python main.py` runs the flywheel with LOCAL mode, no keys
- no canned cognitive fallback: a failed local model yields a structured
  MODEL_LOAD_FAILURE / MODEL_UNAVAILABLE with output=None, never fake text
- model identity: provider + model + backend + timestamp ride on results
- network isolation: engine start + cognition never require the network

Real GGUF inference itself cannot execute in this environment (no model file
and no llama.cpp backend), so that step is honestly reported as
NOT VERIFIED — the structured failure path it produces IS verified here.
"""

import asyncio
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "main.py"


def _tmp() -> str:
    return tempfile.mkdtemp(prefix="local_model_exec_")


def _no_key_env(extra: dict | None = None) -> dict:
    """Environment with OpenAI/Gemini keys removed and the network isolated
    (dead proxy: any HTTP attempt fails fast instead of silently succeeding)."""
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    # Force every potential HTTP call into an immediate connection failure.
    env["HTTP_PROXY"] = "http://127.0.0.1:9"
    env["HTTPS_PROXY"] = "http://127.0.0.1:9"
    env["http_proxy"] = "http://127.0.0.1:9"
    env["https_proxy"] = "http://127.0.0.1:9"
    env["NO_PROXY"] = ""
    env["no_proxy"] = ""
    if extra:
        env.update(extra)
    return env


class TestMainPyCanonicalEntrypoint(unittest.TestCase):
    def test_readiness_flag_starts_real_runtime(self):
        """python main.py --readiness starts the engine and prints the honest
        LOCAL readiness block. Exit code 0."""
        proc = subprocess.run(
            [sys.executable, str(MAIN_PY), "--readiness",
             "--data-dir", _tmp()],
            capture_output=True, text=True, timeout=120,
            env=_no_key_env(), cwd=str(REPO_ROOT))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0,
                         msg=f"main.py exited {proc.returncode}:\n{out}")
        # Canonical startup contract: real readiness, LOCAL mode, no keys.
        self.assertIn("ZERION LOCAL READINESS", out)
        self.assertIn("MODE:            LOCAL", out)
        self.assertIn("MICROPHONE:", out)
        self.assertIn("LOCAL MODEL:", out)
        self.assertIn("LOCAL TTS:", out)
        self.assertIn("UI BRIDGE:", out)
        self.assertIn("KEYS:            OPENAI=NOT_REQUIRED", out)
        # The readiness values must be real states, never hard-coded READY.
        self.assertIn("NO_LOCAL_MODEL_AVAILABLE", out)

    def test_default_python_main_py_enters_active_runtime_and_stays_alive(self):
        """`python main.py` (no flags) prints readiness, executes the real
        Zerion X developmental flywheel, prints the scoreboard, then enters
        ACTIVE / WAITING_FOR_EVENTS and STAYS ALIVE until explicit shutdown
        (SIGINT) — it must NOT exit after the initial cycle (lifecycle fix)."""
        proc = subprocess.Popen(
            [sys.executable, "-u", str(MAIN_PY), "--data-dir", _tmp()],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=_no_key_env(), cwd=str(REPO_ROOT))
        lines: list = []
        try:
            deadline = time.monotonic() + 90
            saw_cycle = saw_active = False
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line)
                if "developmental flywheel cycle" in line:
                    saw_cycle = True
                if "ZERION RUNTIME: ACTIVE" in line:
                    saw_active = True
                if saw_cycle and saw_active and "STATE: WAITING_FOR_EVENTS" in line:
                    break
            out = "".join(lines)
            self.assertTrue(saw_cycle, msg=f"no flywheel cycle line:\n{out}")
            self.assertTrue(saw_active, msg=f"never reached ACTIVE runtime:\n{out}")
            self.assertIn("ZERION LOCAL READINESS", out)
            self.assertIn("MODE:            LOCAL", out)
            self.assertIn("[GENESIS X10]", out)
            # The process must still be alive AFTER the cycle + scoreboard.
            self.assertIsNone(proc.poll(),
                              msg=f"main.py exited after the cycle: {out}")
            # Explicit shutdown -> clean exit code 0.
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=20)
            self.assertEqual(proc.returncode, 0,
                             msg=f"main.py exited {proc.returncode} on SIGINT:\n"
                                 f"{out}")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


class TestNoCannedCognitiveFallback(unittest.TestCase):
    def test_failed_local_model_returns_structured_failure(self):
        """With no GGUF file and no backend, cognition must fail with a
        structured MODEL_LOAD_FAILURE / MODEL_UNAVAILABLE and output=None —
        never a canned answer pretending inference happened."""
        import asyncio as aio
        from zerion.cognitive_os.provider_adapters import LegacyGGUFAdapter
        from zerion.cognitive_os.provider_interface import ProviderCall
        from zerion.cognitive_os.router_types import Task, TaskType

        adapter = LegacyGGUFAdapter(models_dir=_tmp())
        task = Task(type=TaskType.CONVERSATION, description="local probe")
        loop = aio.new_event_loop()
        try:
            res = loop.run_until_complete(adapter.generate(ProviderCall(
                task=task, prompt="Return the word ZERION.",
                model_id="nonexistent.gguf")))
        finally:
            loop.close()
        self.assertFalse(res.success)
        self.assertIsNone(res.output)
        self.assertIn(res.failure_kind.value,
                      ("MODEL_LOAD_FAILURE", "MODEL_UNAVAILABLE"))
        self.assertNotIn("Synthesized", res.error)
        # Backend resolution is honest even in failure.
        self.assertIn(adapter._resolved_backend(), ("llama-cpp-python",
                                                    "llama.cpp CLI",
                                                    "NONE"))


class TestModelIdentityMetadata(unittest.TestCase):
    def test_result_carries_provider_model_backend_timestamp(self):
        """A successful local inference result must be traceable: provider,
        model filename, backend, timestamp and task correlation id (spec §39).
        Uses a registered LOCAL provider so the router path is real; the local
        GGUF provider itself is exercised for identity in its own unit."""
        import asyncio as aio
        import time
        from zerion.cognitive_os.cognitive_router import CognitiveRouter
        from zerion.cognitive_os.provider_interface import (
            ModelInfo, ModelProvider, ProviderCall, RawProviderResponse,
        )
        from zerion.cognitive_os.router_types import (
            ProviderStatus, ResultStatus, RoutingMode, Task, TaskType,
        )

        class FakeLocalModel(ModelProvider):
            provider_name = "fake_local_gguf"
            is_local = True
            calls = 0

            async def generate(self, call):
                FakeLocalModel.calls += 1
                return RawProviderResponse(
                    output="ZERION",
                    latency_ms=1.5,
                    usage={"backend": "llama-cpp-python",
                           "timestamp": 1234.5},
                    success=True)

            async def stream(self, call):
                raise NotImplementedError

            async def health_check(self):
                return ProviderStatus.AVAILABLE

            def capabilities(self):
                return {"text"}

            def list_models(self):
                return [ModelInfo(
                    model_id="fake-model.gguf", provider=self.provider_name,
                    capabilities={"text"},
                    status=ProviderStatus.AVAILABLE)]

            def model_info(self, model_id):
                return None

        router = CognitiveRouter()
        router.register_provider(FakeLocalModel(), configured=True)
        task = Task(type=TaskType.CONVERSATION, description="identity probe",
                    difficulty=0.3, uncertainty=0.3, novelty=0.2,
                    stakes=0.1, goal_relevance=0.5,
                    required_capabilities={"text"},
                    offline_required=True)

        loop = aio.new_event_loop()
        try:
            result = loop.run_until_complete(
                router.execute(task, "Return the word ZERION.",
                               mode=RoutingMode.OFFLINE_ONLY))
        finally:
            loop.close()

        self.assertEqual(result.status, ResultStatus.SUCCESS)
        self.assertEqual(FakeLocalModel.calls, 1)   # the local model ran
        identity = result.metadata["model_identity"]
        self.assertEqual(identity["provider"], "fake_local_gguf")
        self.assertEqual(identity["backend"], "llama-cpp-python")
        self.assertEqual(identity["timestamp"], 1234.5)
        self.assertEqual(identity["task_id"], task.task_id)
        self.assertEqual(result.model, "fake-model.gguf")
        # output is the real local model output, not a canned fallback
        self.assertEqual(result.output, "ZERION")


class TestNetworkIsolation(unittest.TestCase):
    def test_engine_starts_with_network_unreachable(self):
        """Engine startup, model discovery and runtime init must succeed with
        every HTTP path pointed at a dead port (any network attempt fails)."""
        import asyncio as aio
        from zerion.engine import AscendantEngine

        old = {k: os.environ.get(k) for k in
               ("OPENAI_API_KEY", "GEMINI_API_KEY", "HTTP_PROXY",
                "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY")}
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
        os.environ["http_proxy"] = "http://127.0.0.1:9"
        os.environ["https_proxy"] = "http://127.0.0.1:9"
        os.environ["NO_PROXY"] = ""
        try:
            loop = aio.new_event_loop()
            engine = AscendantEngine(data_dir=_tmp())
            loop.run_until_complete(engine.start())
            try:
                self.assertTrue(engine._running)
                r = engine.local_readiness()
                self.assertEqual(r["mode"], "LOCAL")
                self.assertEqual(r["runtime"]["offline_mode"], "OFFLINE_ONLY")
                self.assertIn(r["models"]["status"],
                              ("NO_LOCAL_MODEL_AVAILABLE", "READY"))
            finally:
                loop.run_until_complete(engine.stop())
                loop.close()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_offline_mode_excludes_cloud_providers(self):
        """With keys PRESENT but OFFLINE_ONLY, cognition must still refuse the
        cloud provider — local mode is structural, not key-gated."""
        import asyncio as aio
        from zerion.cognitive_os.cognitive_router import CognitiveRouter
        from zerion.cognitive_os.provider_interface import (
            ModelProvider, ProviderCall, RawProviderResponse,
        )
        from zerion.cognitive_os.router_types import (
            ProviderStatus, ResultStatus, RoutingMode, Task, TaskType,
        )

        class CloudProbe(ModelProvider):
            provider_name = "cloud_probe"
            is_local = False
            calls = 0

            async def generate(self, call):
                CloudProbe.calls += 1
                return RawProviderResponse(output="cloud", success=True)

            async def stream(self, call):
                raise NotImplementedError

            async def health_check(self):
                return ProviderStatus.AVAILABLE

            def capabilities(self):
                return {"text"}

            def list_models(self):
                return []

            def model_info(self, model_id):
                return None

        router = CognitiveRouter()
        router.register_provider(CloudProbe(), configured=True)
        task = Task(type=TaskType.CONVERSATION, description="isolation",
                    required_capabilities={"text"}, offline_required=True)
        loop = aio.new_event_loop()
        try:
            result = loop.run_until_complete(
                router.execute(task, "hi", mode=RoutingMode.OFFLINE_ONLY))
        finally:
            loop.close()
        self.assertEqual(result.status, ResultStatus.ROUTING_FAILED)
        self.assertEqual(CloudProbe.calls, 0)
        # The route-level message is the honest structural reason.
        self.assertTrue(any("cloud providers excluded" in e
                            for e in result.errors),
                        msg=f"unexpected errors: {result.errors}")


if __name__ == "__main__":
    unittest.main()
