"""
Hermetic tests for the real GGUF backend layer (``gguf_backend``):

- ``probe_local_gguf`` produces the full evidence lifecycle
  (DISCOVERED -> BACKEND -> LOAD -> INFERENCE_VERIFIED -> READY); READY is
  only earned by a real probe whose output contains the expected token.
- the CLI backend is always invoked single-shot (``-no-cnv -st``, stdin from
  /dev/null) and its output parser strips the logo/info header, the prompt
  echo and the stats footer — the exact shapes real ``llama-cli`` prints.
- no backend / no model / failed probe are honest BLOCKED states with the
  actual cause, never a fake READY.

Hermetic: no real model files or llama.cpp binaries are required.
"""

import os
from pathlib import Path
import tempfile
import unittest

from zerion.cognitive_os.gguf_backend import (
    LocalGGUFBackend,
    extract_cli_output,
    probe_local_gguf,
)
from zerion.model_providers.gemini_provider import LocalGGUFProvider

_GGUF_ENV_KEYS = (
    "ZERION_GGUF_BACKEND", "ZERION_GGUF_CLI", "ZERION_GGUF_PROBE",
    "ZERION_GGUF_PROBE_TIMEOUT", "ZERION_GGUF_PROBE_TTL",
    "ZERION_GGUF_THREADS", "ZERION_GGUF_CONTEXT", "ZERION_GGUF_MAX_TOKENS",
    "ZERION_GGUF_TEMPERATURE", "ZERION_GGUF_TIMEOUT_SECONDS",
)


def _write_fake_gguf(path: Path, size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"GGUF")
        f.write(b"\x00" * max(0, size - 4))


class _GGUFProbeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zerion_gguf_backend_")
        self.models_dir = os.path.join(self._tmp, "models")
        os.makedirs(self.models_dir, exist_ok=True)
        self._saved_env = dict(os.environ)
        for key in _GGUF_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------

    def _fake_cli(self, body: str) -> str:
        """A llama-cli stub on PATH; body is sh code that runs after the
        arguments are logged."""
        bin_dir = os.path.join(self._tmp, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        script = os.path.join(bin_dir, "llama-cli")
        log = os.path.join(self._tmp, "args.log")
        with open(script, "w") as f:
            f.write("#!/bin/sh\n")
            f.write(f'echo "$@" > "{log}"\n')
            f.write("prev=\nfor a in \"$@\"; do\n"
                    "  if [ \"$prev\" = \"-p\" ]; then p=\"$a\"; fi\n"
                    "  prev=\"$a\"\n"
                    "done\n")
            f.write(body)
        os.chmod(script, 0o755)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        os.environ["ZERION_GGUF_BACKEND"] = "cli"
        return log

    def _real_shape_body(self) -> str:
        """Reproduce the exact output shape a real llama-cli single-shot run
        prints: logo/info header, ``> {prompt}`` echo, response, stats footer."""
        return ("printf '\\n\\n▄▄ ▄▄\\n██ ██\\n\\n"
                "build      : stub\\nmodel      : stub.gguf\\n"
                "ftype      : Q4_K - Medium\\nmodalities : text\\n\\n"
                "available commands:\\n  /exit or Ctrl+C     stop or exit\\n"
                "  /clear              clear the chat history\\n\\n\\n"
                "> %s\\nSTUB-INFERENCE OK: ZERION_LOCAL_OK\\n\\n"
                "[ Prompt: 42.2 t/s | Generation: 12.8 t/s ]\\n\\n"
                "Exiting...\\n' \"$p\"\n")

    # -- lifecycle probe ----------------------------------------------------

    def test_probe_ready_with_real_cli_output_shape(self):
        """A real-shaped CLI output containing the expected probe token earns
        READY — and only after an actual load + generation subprocess ran."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        log = self._fake_cli(self._real_shape_body())
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["probe"]["inference"], "VERIFIED")
        self.assertEqual(report["probe"]["loadable"], "LOADED")
        self.assertEqual(report["selected"], ["model_a"])
        self.assertTrue(report["selected_path"].endswith("model_a.gguf"))
        self.assertTrue(Path(report["selected_path"]).is_absolute())
        self.assertEqual(report["backend"]["name"], "llama.cpp CLI")
        self.assertTrue(report["backend"]["available"])
        self.assertIsNone(report["reason"])
        # The subprocess actually ran with the discovered absolute path.
        with open(log) as f:
            args = f.read()
        self.assertIn("-m", args)
        self.assertIn("model_a.gguf", args)
        # Single-shot flags: a TTY can never trap llama-cli interactively.
        for flag in ("-no-cnv", "-st", "--no-display-prompt"):
            self.assertIn(flag, args, f"missing {flag} in {args}")

    def test_probe_no_model_is_honest_not_ready(self):
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "NO_LOCAL_MODEL_AVAILABLE")
        self.assertEqual(report["discovered"], 0)
        self.assertEqual(report["probe"]["inference"], "NOT_VERIFIED")
        self.assertIsNone(report["selected_path"])

    def test_probe_missing_backend_is_blocked_with_install_hint(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        # No llama-cli on PATH, no llama_cpp module -> honest BLOCKED.
        os.environ["ZERION_GGUF_BACKEND"] = "auto"
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["selected"], ["model_a"])
        self.assertEqual(report["backend"]["name"], "NONE")
        self.assertFalse(report["backend"]["available"])
        self.assertIn("no local GGUF inference backend", report["reason"])
        self.assertIn("llama-cpp-python", report["backend"]["install_hint"])

    def test_probe_failed_when_output_missing_expected_token(self):
        """A backend that runs but does NOT produce the expected probe token
        is FAILED — a subprocess existing is not proof of cognition."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli("printf 'WRONG ANSWER\\n'\n")
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["probe"]["inference"], "FAILED")
        self.assertIn("expected token", report["reason"])

    def test_probe_disabled_stays_blocked(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli(self._real_shape_body())
        os.environ["ZERION_GGUF_PROBE"] = "0"
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["probe"]["inference"], "NOT_VERIFIED")
        self.assertIn("probe disabled", report["reason"])

    def test_backend_disabled_env_is_none(self):
        os.environ["ZERION_GGUF_BACKEND"] = "none"
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("ZERION_GGUF_BACKEND=none", report["reason"])

    # -- output parser ------------------------------------------------------

    def test_extract_cli_output_strips_header_echo_and_footer(self):
        raw = ("\n\n▄▄ ▄▄\n\nbuild      : stub\nmodel      : stub.gguf\n"
               "ftype      : Q4_K - Medium\nmodalities : text\n\n\n"
               "> hello there\nREAL GENERATED ANSWER</s>\n\n"
               "[ Prompt: 1.2 t/s | Generation: 3.4 t/s ]\n\nExiting...\n")
        self.assertEqual(extract_cli_output(raw, "hello there"),
                         "REAL GENERATED ANSWER")

    def test_extract_cli_output_passes_through_bare_output(self):
        # Stub binaries that print only the response must be untouched.
        self.assertEqual(extract_cli_output("STUB-INFERENCE hello\n", "hi"),
                         "STUB-INFERENCE hello")

    # -- provider delegation -------------------------------------------------

    def test_provider_cli_generation_uses_single_turn_flags(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        log = self._fake_cli("printf 'STUB OK: %s\\n' \"$p\"\n")
        import asyncio
        p = LocalGGUFProvider(models_dir=self.models_dir, backend="cli")
        resp = asyncio.run(p.generate_response("Say something",
                                               model_id="model_a"))
        self.assertEqual(resp.execution_mode.value, "REAL_MODEL_RESPONSE")
        self.assertFalse(resp.is_fallback)
        self.assertEqual(resp.content, "STUB OK: Say something")
        with open(log) as f:
            args = f.read()
        for flag in ("-no-cnv", "-st"):
            self.assertIn(flag, args, f"missing {flag} in {args}")


if __name__ == "__main__":
    unittest.main()
