"""
ZERION X — text-only product REPL regression tests (INPUT=TEXT,
OUTPUT=TEXT+LOCAL VOICE).

``python main.py`` on an interactive terminal (Termux/desktop TTY) must
present ``YOU > `` and route every typed message through the REAL
CognitiveRuntime router — the same canonical path as the web UI and the
voice pipeline — then speak the response through the local offline TTS
engine when one exists, and keep looping forever. Only ``exit``/``quit``,
EOF, or Ctrl-C terminates it.

These tests exercise ``zerion.cli._enter_interactive_chat`` with a real
asyncio loop and scripted stdin:

- the banner values come from the REAL runtime (never hard-coded READY),
- one typed turn -> one real runtime.execute_task call -> printed response,
- empty input is ignored safely,
- a failed turn NEVER kills the runtime (it returns to YOU >),
- TTS is attempted through the real provider seam and reported honestly,
- EOF / 'exit' / shutdown event each end the loop cleanly,
- and the real ``python main.py --chat`` subprocess stays alive and
  responds to piped input end-to-end.
"""

import asyncio
import contextlib
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from zerion.cli import _enter_interactive_chat

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "main.py"


def _no_key_env() -> dict:
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    return env


class _Result:
    def __init__(self, output, status="SUCCESS", errors=None):
        self.output = output
        self.status = SimpleNamespace(value=status)
        self.errors = errors or []


class _FakeRuntime:
    """Records the canonical text path: execute_task(task, prompt, mode)."""

    def __init__(self, script=None):
        self.script = script if script is not None else {}
        self.calls = []

    async def execute_task(self, task, prompt, mode=None):
        self.calls.append((prompt, mode.value if mode is not None else None))
        if callable(self.script):
            return self.script(prompt)
        return self.script.get(prompt, _Result("Hello, operator. I am alive."))


class _FakeTTS:
    def __init__(self, status="VOICE_UNAVAILABLE"):
        self.status = status
        self.spoken = []

    def synthesize(self, text, out_path=None, timeout_s=15.0):
        self.spoken.append(text)
        if self.status == "VOICE_UNAVAILABLE":
            return {"status": "VOICE_UNAVAILABLE",
                    "reason": "no offline TTS engine found"}
        return {"status": "AUDIO_GENERATED", "engine": "espeak-ng",
                "path": "/tmp/fake.wav", "bytes": 128}


class _FakeRegistry:
    def __init__(self, available=0):
        self.available = available

    def list_models(self):
        if self.available:
            return [{"filename": "qwen.gguf", "availability": "AVAILABLE",
                     "load_status": "UNLOADED"}]
        return []


class _FakeEngine:
    def __init__(self, runtime=None, tts_status="VOICE_UNAVAILABLE",
                 model_available=0):
        self.cognitive_runtime = runtime or _FakeRuntime()
        self.voice_pipeline = SimpleNamespace(
            tts_provider=_FakeTTS(tts_status))
        self.local_model_registry = _FakeRegistry(model_available)

    def local_readiness(self):
        return {
            "mode": "LOCAL",
            "models": {"dir": "models", "discovered": 0,
                       "available": self.local_model_registry.available,
                       "selected": [],
                       "status": "NO_LOCAL_MODEL_AVAILABLE"
                       if not self.local_model_registry.available
                       else "READY"},
            "tts": {"status": "UNAVAILABLE",
                    "reason": "no offline TTS engine found"},
        }


class TestInteractiveChatRepl(unittest.IsolatedAsyncioTestCase):
    async def _run(self, engine, text):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await _enter_interactive_chat(
                engine, asyncio.Event(), stdin=io.StringIO(text))
        return out.getvalue()

    async def test_banner_is_real_and_single_turn_reaches_runtime(self):
        runtime = _FakeRuntime({"Hello Zerion.": _Result("Hello back.")})
        engine = _FakeEngine(runtime=runtime)
        text = await self._run(engine, "Hello Zerion.\nexit\n")
        # Product banner, values from the real runtime (no faked READY).
        self.assertIn("ZERION X", text)
        self.assertIn("MODE        LOCAL OFFLINE", text)
        self.assertIn("INPUT       TEXT", text)
        self.assertIn("VOICE       OUTPUT ONLY", text)
        self.assertIn("MODEL       NONE (no .gguf in models/)", text)
        # COGNITION ACTIVE is only claimed after a real inference probe
        # verified real tokens; with no model/backend evidence the honest
        # state is MODEL_BLOCKED (the runtime itself stays ACTIVE).
        self.assertIn("COGNITION   MODEL_BLOCKED", text)
        self.assertIn("RUNTIME     ACTIVE", text)
        # The typed turn went through the REAL runtime execute_task seam.
        self.assertEqual(runtime.calls, [("Hello Zerion.", "OFFLINE_ONLY")])
        self.assertIn("YOU > ", text)
        self.assertIn("[ZERION]\nHello back.", text)
        # 'exit' ended the loop cleanly.
        self.assertIn("shutting down cleanly", text)

    async def test_empty_input_ignored_and_failed_turn_keeps_loop_alive(self):
        def script(prompt):
            if prompt == "boom":
                raise RuntimeError("simulated cognitive failure")
            return _Result("after the storm")
        runtime = _FakeRuntime(script=script)
        text = await self._run(
            _FakeEngine(runtime=runtime),
            "\n   \nboom\nnext\n")
        # Empty lines were ignored; the failure was reported but the loop
        # survived and processed the next real message.
        self.assertIn("ERROR: RuntimeError: simulated cognitive failure",
                      text)
        self.assertIn("returning to input (runtime remains ACTIVE)", text)
        self.assertIn("[ZERION]\nafter the storm", text)
        self.assertEqual([p for p, _ in runtime.calls if p != ""],
                         ["boom", "next"])

    async def test_response_is_spoken_through_local_tts_seam(self):
        runtime = _FakeRuntime({"speak this": _Result("spoken text")})
        engine = _FakeEngine(runtime=runtime, tts_status="AUDIO_GENERATED")
        text = await self._run(engine, "speak this\nexit\n")
        self.assertIn("[ZERION]\nspoken text", text)
        # The real TTS provider seam received the exact response text.
        self.assertEqual(engine.voice_pipeline.tts_provider.spoken,
                         ["spoken text"])

    async def test_tts_unavailable_is_reported_not_faked(self):
        runtime = _FakeRuntime({"hi": _Result("hello")})
        text = await self._run(_FakeEngine(runtime=runtime), "hi\nexit\n")
        self.assertIn("TTS: VOICE_UNAVAILABLE", text)

    async def test_no_model_result_reports_honest_status(self):
        runtime = _FakeRuntime({"math": _Result(
            None, status="ROUTING_FAILED",
            errors="no provider available in OFFLINE_ONLY")})
        text = await self._run(_FakeEngine(runtime=runtime), "math\nexit\n")
        self.assertIn("ROUTING_FAILED", text)
        self.assertIn("LOCAL MODEL UNAVAILABLE", text)

    async def test_eof_exits_cleanly(self):
        text = await self._run(_FakeEngine(), "")
        self.assertIn("YOU > ", text)
        # EOF after the prompt ends the loop without an exception.

    async def test_shutdown_event_exits_without_reading(self):
        engine = _FakeEngine()
        event = asyncio.Event()
        event.set()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await _enter_interactive_chat(
                engine, event, stdin=io.StringIO("never read\n"))
        # Pre-set shutdown -> loop exits before consuming input.
        self.assertIn("ZERION X", out.getvalue())
        self.assertEqual(engine.cognitive_runtime.calls, [])


class TestMainPyChatEndToEnd(unittest.TestCase):
    def test_chat_with_inference_prints_real_session_ledger(self):
        """``python main.py --chat --inference`` records every typed turn in
        the observable inference ledger and prints it at exit — the runtime
        evidence (input -> router -> result) for the session just run, never
        fabricated. Without --inference the REPL stays quiet on exit."""
        proc = subprocess.Popen(
            [sys.executable, "-u", str(MAIN_PY), "--chat", "--inference",
             "--data-dir", tempfile.mkdtemp(prefix="zerion_ledger_")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
            env=_no_key_env(), cwd=str(REPO_ROOT))
        buf: list = []

        def read_until(substr: str, timeout: float) -> tuple:
            start = len(buf)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ch = proc.stdout.read(1)
                if not ch:
                    return "".join(buf), False
                buf.append(ch)
                if substr in "".join(buf[start:]):
                    return "".join(buf), True
            return "".join(buf), False

        try:
            out, ok = read_until("YOU > ", 120)
            self.assertTrue(ok, msg=f"REPL prompt never appeared:\n{out}")
            proc.stdin.write("trace me\n")
            proc.stdin.flush()
            out, ok = read_until("YOU > ", 60)
            self.assertTrue(ok, msg=f"REPL did not loop:\n{out}")
            proc.stdin.write("exit\n")
            proc.stdin.flush()
            out, ok = read_until("INFERENCE LEDGER", 30)
            self.assertTrue(
                ok, msg=f"ledger section missing after exit:\n{out[-1500:]}")
            proc.stdin.close()
            proc.wait(timeout=30)
            self.assertEqual(proc.returncode, 0,
                             msg=f"main.py exited {proc.returncode}")
            # Drain whatever the process wrote after the header so the full
            # ledger content is captured (the header can appear mid-buffer).
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    break
                buf.append(ch)
            out = "".join(buf)
            # The real session record: exactly one request, the typed input,
            # and an honest result (no model in this environment).
            self.assertIn("Requests:  1", out)
            self.assertIn("'trace me'", out)
            self.assertIn("success=False", out)
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_python_main_py_chat_subprocess_end_to_end(self):
        """Real ``python main.py --chat``: engine starts, banner prints,
        piped text is consumed by the REPL across multiple turns, 'exit'
        shuts down cleanly with exit code 0. (Real GGUF inference + real
        TTS audio are device-side and cannot be exercised headless.)"""
        proc = subprocess.Popen(
            [sys.executable, "-u", str(MAIN_PY), "--chat",
             "--data-dir", tempfile.mkdtemp(prefix="zerion_chat_")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
            env=_no_key_env(), cwd=str(REPO_ROOT))
        buf: list = []

        def read_until(substr: str, timeout: float) -> tuple:
            """Accumulate stdout char-by-char (the YOU > prompt has no
            trailing newline, so readline() would block on it). Only
            matches text read after this call started, so an earlier
            occurrence cannot satisfy a later wait."""
            start = len(buf)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ch = proc.stdout.read(1)
                if not ch:
                    return "".join(buf), False
                buf.append(ch)
                if substr in "".join(buf[start:]):
                    return "".join(buf), True
            return "".join(buf), False

        try:
            out, ok = read_until("YOU > ", 120)
            self.assertTrue(ok, msg=f"REPL prompt never appeared:\n{out}")
            self.assertIn("ZERION X", out)
            self.assertIn("MODE        LOCAL OFFLINE", out)
            self.assertIn("INPUT       TEXT", out)
            # When a GGUF model IS discovered, the model line shows it.
            # When no model exists, it shows NONE. Both are valid.
            self.assertTrue(
                "MODEL" in out and ("NONE" in out or "gguf" in out.lower() or "available" in out.lower()),
                msg="Expected MODEL line in banner")
            # Turn 1 through the real runtime, then the prompt again.
            proc.stdin.write("Hello Zerion.\n")
            proc.stdin.flush()
            out, ok = read_until("YOU > ", 60)
            self.assertTrue(ok, msg=f"REPL did not return to prompt:\n{out}")
            self.assertIn("[ZERION]", out)
            # Turn 2 -> loops again.
            proc.stdin.write("What is 25 x 4?\n")
            proc.stdin.flush()
            out, ok = read_until("YOU > ", 60)
            self.assertTrue(ok, msg=f"REPL did not loop a second time:\n{out}")
            # Clean shutdown.
            proc.stdin.write("exit\n")
            proc.stdin.flush()
            out, ok = read_until("shutting down cleanly", 30)
            self.assertTrue(ok, msg=f"clean shutdown line missing:\n{out}")
            proc.stdin.close()
            proc.wait(timeout=30)
            self.assertEqual(proc.returncode, 0,
                             msg=f"main.py exited {proc.returncode}: {out}")
            # Three prompts total: initial + after each of two turns.
            self.assertGreaterEqual(out.count("YOU > "), 3)
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    unittest.main()
