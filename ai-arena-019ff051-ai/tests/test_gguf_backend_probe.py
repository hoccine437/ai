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
    "ZERION_GGUF_SERVER_URL",
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

    def test_probe_ready_when_output_missing_expected_token(self):
        """A backend that runs and produces REAL usable text WITHOUT the exact
        probe token is INFERENCE AVAILABLE, not blocked — exact-token
        matching is only a secondary diagnostic. A subprocess that returns
        nothing is the actual failure case (MODEL_OUTPUT_EMPTY)."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli("printf 'WRONG ANSWER but real generated text\\n'\n")
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["probe"]["inference"], "VERIFIED")
        self.assertEqual(report["probe"]["loadable"], "LOADED")
        self.assertEqual(report["probe"]["process"], "EXITED_OK")
        self.assertEqual(report["probe"]["model_output"], "NONEMPTY")
        self.assertFalse(report["probe"]["probe_token_match"])
        self.assertEqual(report["probe"]["error_class"],
                         "MODEL_INFERENCE_AVAILABLE")
        self.assertIsNone(report["reason"])

    def test_probe_blocked_only_when_output_is_actually_empty(self):
        """Empty output after a successful exit is the ONLY output-side
        blocker: MODEL_OUTPUT_EMPTY with the real cause, never a fake
        'model broken'."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli("printf '\\n\\n'\n")  # banners only, no content
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["probe"]["inference"], "FAILED")
        self.assertEqual(report["probe"]["loadable"], "LOADED")
        self.assertEqual(report["probe"]["model_output"], "EMPTY")
        self.assertEqual(report["probe"]["error_class"], "MODEL_OUTPUT_EMPTY")
        self.assertIn("no usable output", report["reason"])

    def test_probe_normalizes_ansi_around_real_output(self):
        """llama-cli banners may wrap the response in ANSI escape sequences;
        normalization must strip them so real output is still recognized."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli(
            "printf '\\033[32m\\033[1mZERION_LOCAL_OK\\033[0m\\n'\n")
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["probe"]["inference"], "VERIFIED")
        self.assertTrue(report["probe"]["probe_token_match"])
        self.assertEqual(report["probe"]["probe_output"], "ZERION_LOCAL_OK")

    def test_probe_normalizes_control_chars_and_formatting(self):
        """Control chars / formatting around the response are not content and
        must not corrupt the extracted output."""
        from zerion.cognitive_os.gguf_backend import normalize_model_output
        self.assertEqual(
            normalize_model_output("\x1b[2J\x1b[H  hello \x1b[31mworld\x1b[0m \n"),
            "hello world")

    def test_adaptive_probe_timeout_is_unlimited_by_default(self):
        """The probe budget is UNLIMITED by default: a first model load on a
        phone can legitimately take many minutes, and any fixed kill window
        produced false 'model broken' failures. An explicit
        ZERION_GGUF_PROBE_TIMEOUT still bounds the wait."""
        from zerion.cognitive_os.gguf_backend import adaptive_probe_timeout
        self.assertIsNone(adaptive_probe_timeout(0))
        self.assertIsNone(adaptive_probe_timeout(1 << 30))
        self.assertIsNone(adaptive_probe_timeout(100 << 30))
        os.environ["ZERION_GGUF_PROBE_TIMEOUT"] = "600"
        self.assertEqual(adaptive_probe_timeout(1 << 30), 600.0)
        self.assertEqual(adaptive_probe_timeout(100 << 30), 600.0)

    def test_probe_timeout_env_0_none_null_unlimited_mean_unlimited(self):
        """0 / none / null / unlimited are UNLIMITED, never a zero-second
        kill window; non-numeric garbage also falls back to unlimited."""
        from zerion.cognitive_os.gguf_backend import adaptive_probe_timeout
        for value in ("0", "none", "NULL", "Unlimited", "NONE", "inf"):
            os.environ["ZERION_GGUF_PROBE_TIMEOUT"] = value
            self.assertIsNone(adaptive_probe_timeout(1 << 30), value)
        os.environ["ZERION_GGUF_PROBE_TIMEOUT"] = "garbage"
        self.assertIsNone(adaptive_probe_timeout(1 << 30))
        os.environ["ZERION_GGUF_PROBE_TIMEOUT"] = "120"
        self.assertEqual(adaptive_probe_timeout(1 << 30), 120.0)

    def test_local_inference_timeout_env_0_none_null_unlimited(self):
        """The local inference budget (router + provider) treats 0 / none /
        null / unlimited as unlimited too."""
        from zerion.cognitive_os.cognitive_router import _local_timeout_from_env
        for value in ("0", "none", "null", "unlimited", "inf"):
            os.environ["ZERION_GGUF_TIMEOUT_SECONDS"] = value
            self.assertIsNone(_local_timeout_from_env(), value)
        from zerion.model_providers.gemini_provider import LocalGGUFProvider
        for value in ("0", "none", "null", "unlimited", "inf"):
            os.environ["ZERION_GGUF_TIMEOUT_SECONDS"] = value
            self.assertIsNone(LocalGGUFProvider._timeout_env(), value)
        os.environ["ZERION_GGUF_TIMEOUT_SECONDS"] = "300"
        self.assertEqual(_local_timeout_from_env(), 300.0)
        self.assertEqual(LocalGGUFProvider._timeout_env(), 300.0)

    def test_probe_reports_the_timeout_used(self):
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli(self._real_shape_body())
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "READY")
        # Unlimited by default — the probe waited as long as the model needed.
        self.assertIsNone(report["probe"]["timeout_s"])
        # An explicit budget is reported so the user sees what bounded it.
        os.environ["ZERION_GGUF_PROBE_TIMEOUT"] = "240"
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["probe"]["timeout_s"], 240.0)

    def test_detect_server_backend_from_env_and_honest_blocked_probe(self):
        """ZERION_GGUF_SERVER_URL selects the persistent-session server
        backend; a live probe verifies real reachability + generation, so a
        dead/misconfigured server is honestly BLOCKED (never a fake READY)."""
        from zerion.cognitive_os.gguf_backend import LocalGGUFBackend
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        os.environ["ZERION_GGUF_SERVER_URL"] = "http://127.0.0.1:1"
        backend = LocalGGUFBackend.detect(requested="auto")
        self.assertEqual(backend.kind, "server")
        self.assertEqual(backend.server_url, "http://127.0.0.1:1")
        # Explicit "server" mode resolves the same way.
        backend = LocalGGUFBackend.detect(requested="server")
        self.assertEqual(backend.kind, "server")
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["backend"]["name"],
                         "llama.cpp server (persistent session)")
        self.assertEqual(report["probe"]["error_class"], "MODEL_LOAD_FAILURE")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("server request failed", report["reason"])

    def test_probe_server_backend_ready_with_live_server(self):
        """A real reachable llama-server-shaped endpoint yields READY through
        the persistent-session backend (hermetic: an in-process HTTP stub)."""
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import urlparse

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if urlparse(self.path).path != "/completion":
                    self.send_response(404)
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                body = _json.dumps({
                    "content": "ZERION_LOCAL_OK (server)",
                    "tokens_evaluated": 10,
                    "tokens_predicted": 4,
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # silence
                pass

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
            os.environ["ZERION_GGUF_SERVER_URL"] = \
                f"http://127.0.0.1:{server.server_port}"
            report = probe_local_gguf(self.models_dir)
            self.assertEqual(report["status"], "READY")
            self.assertEqual(report["probe"]["inference"], "VERIFIED")
            self.assertTrue(report["probe"]["probe_token_match"])
            self.assertEqual(report["backend"]["kind"], "server")
        finally:
            server.shutdown()
            server.server_close()

    def test_probe_uses_simple_io_when_output_file_flag_rejected(self):
        """Regression (device log): post-refactor llama-cli writes 0 bytes to
        a redirected stdout, and a real build rejects `-o`/--output-file as an
        "invalid argument" (ggml-org/llama.cpp#19256; the current llama-cli
        man page has no --output-file flag at all). `--simple-io` alone is the
        documented subprocess flag and must be tried FIRST: the probe then
        captures the real generation from stdout and reports READY instead of
        'probe output did not contain expected token (got '')'."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        body = (
            "case \" $* \" in\n"
            "  *' -o '*)\n"
            "    echo 'error: invalid argument: -o' >&2\n"
            "    exit 1\n"
            "    ;;\n"
            "esac\n"
            "printf 'ZERION_LOCAL_OK\\n'\n"
        )
        self._fake_cli(body)
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["probe"]["inference"], "VERIFIED")
        self.assertEqual(report["probe"]["loadable"], "LOADED")
        self.assertEqual(report["probe"]["probe_output"], "ZERION_LOCAL_OK")
        self.assertIsNone(report["probe"]["error"])

    def test_probe_reads_generation_from_output_file(self):
        """Regression: post-refactor llama-cli writes 0 bytes to a redirected
        stdout (generation goes to the terminal). For builds that support
        `-o <file>` (--output-file) but reject `--simple-io`, the probe must
        capture the response via the output file. Here the model really
        generated ZERION_LOCAL_OK but stdout is empty — the probe must still
        see the token and report READY instead of 'got empty'."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        body = (
            "case \" $* \" in\n"
            "  *' --simple-io '*)\n"
            "    echo 'error: unknown argument: --simple-io' >&2\n"
            "    exit 1\n"
            "    ;;\n"
            "esac\n"
            "out=\n"
            "prev=\n"
            "for a in \"$@\"; do\n"
            "  if [ \"$prev\" = \"-o\" ]; then out=\"$a\"; fi\n"
            "  prev=\"$a\"\n"
            "done\n"
            "printf 'ZERION_LOCAL_OK\\n' > \"$out\"\n"
            "# stdout is intentionally left empty, like the real new llama-cli\n"
        )
        self._fake_cli(body)
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["probe"]["inference"], "VERIFIED")
        self.assertEqual(report["probe"]["loadable"], "LOADED")
        self.assertEqual(report["probe"]["probe_output"], "ZERION_LOCAL_OK")
        self.assertIsNone(report["probe"]["error"])

    def test_probe_falls_back_when_output_file_flags_unsupported(self):
        """Older llama-cli builds don't know -o/--simple-io; the backend must
        retry with plain single-shot args and parse stdout instead of
        failing the whole probe."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        body = (
            "case \" $* \" in\n"
            "  *' --simple-io '*|*' -o '*)\n"
            "    echo 'error: unknown argument' >&2\n"
            "    exit 1\n"
            "    ;;\n"
            "esac\n"
            "printf 'LEGACY OK: ZERION_LOCAL_OK\\n'\n"
        )
        self._fake_cli(body)
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["probe"]["inference"], "VERIFIED")
        self.assertEqual(report["probe"]["probe_output"],
                         "LEGACY OK: ZERION_LOCAL_OK")

    def test_is_unknown_arg_error_matches_real_phrasings(self):
        """llama.cpp has printed its arg-parse error under several phrasings
        across builds; all of them must be recognized as retryable flag
        rejections, while a real (non-flag) failure must not be."""
        from subprocess import CompletedProcess

        from zerion.cognitive_os.gguf_backend import _is_unknown_arg_error
        for msg in (
            "error: unknown argument: -o",
            "error: invalid argument: -o",
            "error: unrecognized option '--output-file'",
            "error: unknown option: --simple-io",
            "llama-cli: invalid option -- 'o'",
            "no such option: -st",
        ):
            proc = CompletedProcess([], 1, stdout="", stderr=msg)
            self.assertTrue(_is_unknown_arg_error(proc), msg)
        proc = CompletedProcess(
            [], 1, stdout="",
            stderr="llama_model_load: failed to load model from file")
        self.assertFalse(_is_unknown_arg_error(proc))

    def test_no_retry_after_slow_model_load_failure(self):
        """A nonzero exit AFTER argument parsing has spent real time (model
        load in progress) is a genuine failure, not a flag rejection — the
        backend must report it instead of re-loading the model up to four
        times on a phone."""
        import subprocess as _sp
        from unittest import mock

        from zerion.cognitive_os import gguf_backend as gb
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        bin_dir = os.path.join(self._tmp, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        script = os.path.join(bin_dir, "llama-cli")
        with open(script, "w") as f:
            f.write("#!/bin/sh\n"
                    "sleep 6\n"  # load takes real time before failing
                    "echo 'error: invalid argument (mmap EINVAL)' >&2\n"
                    "exit 1\n")
        os.chmod(script, 0o755)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        os.environ["ZERION_GGUF_BACKEND"] = "cli"
        with mock.patch.object(gb.subprocess, "run",
                               wraps=_sp.run) as run:
            report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["probe"]["loadable"], "FAILED")
        self.assertEqual(run.call_count, 1)  # one attempt, no retry chain

    def test_probe_timeout_is_distinct_state_with_guidance(self):
        """A backend still alive past the budget is TIMEOUT (an interrupted
        load), never a fake 'model broken' FAILED, and the error names what to
        do on a slow phone."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        self._fake_cli("sleep 5\nprintf 'ZERION_LOCAL_OK\\n'\n")
        os.environ["ZERION_GGUF_PROBE_TIMEOUT"] = "2"
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["probe"]["loadable"], "TIMEOUT")
        self.assertEqual(report["probe"]["inference"], "NOT_VERIFIED")
        self.assertIn("TimeoutExpired after 2s", report["probe"]["error"])
        self.assertIn("still loading/generating", report["probe"]["error"])
        self.assertEqual(report["probe"]["timeout_s"], 2.0)

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

    def test_termux_hint_never_suggests_pip_llama_cpp_python(self):
        """On Termux, the install hint must point at the prebuilt llama-cpp
        package and never suggest `pip install llama-cpp-python` — that path
        has no Android aarch64 wheels and dies building cmake from source
        (iconv not found)."""
        _write_fake_gguf(Path(self.models_dir) / "model_a.gguf")
        os.environ["ZERION_GGUF_BACKEND"] = "auto"
        os.environ["TERMUX_VERSION"] = "0.117.3"
        report = probe_local_gguf(self.models_dir)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("no local GGUF inference backend", report["reason"])
        hint = report["backend"]["install_hint"]
        self.assertIn("pkg install llama-cpp", hint)
        self.assertNotIn("pip install llama-cpp-python", hint)
        # The CLI-backend message is Termux-aware too.
        self.assertIn("pkg install llama-cpp",
                      report["backend"]["detail"])

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
