"""
Slice 12 — Real local GGUF inference backends.

The ONLY layer that knows how to execute a GGUF model file. Selection is
evidence-based and every readiness claim is verified by a real probe:

    LocalGGUFBackend.detect() -> LlamaCppPythonBackend
                              |  LlamaCppCLIBackend
                              |  UnsupportedBackend
                              |  None          (ZERION_GGUF_BACKEND=none)

- ``LlamaCppPythonBackend`` — in-process llama-cpp-python (desktops/servers).
- ``LlamaCppCLIBackend``    — llama.cpp CLI binary (``llama-cli`` / ``main``)
                              on PATH (Termux/Android: a locally built
                              llama.cpp, see TERMUX.md). Always invoked
                              single-shot (``-no-cnv -st``, stdin from
                              /dev/null) so a TTY can never trap it in
                              interactive mode.
- ``UnsupportedBackend``    — honest BLOCKED report naming what is missing and
                              how to install it.

``probe_local_gguf()`` produces the canonical lifecycle report consumed by
``AscendantEngine.local_readiness()``:

    GGUF FILE FOUND -> GGUF METADATA READ -> BACKEND AVAILABLE ->
    MODEL LOAD TEST -> REAL INFERENCE PROBE -> INFERENCE_VERIFIED -> READY

A file existing is only DISCOVERY. Nothing reports READY until a real load
and a real generation probe succeeded against the actual model file.
"""

import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# Tokens llama.cpp may emit at the end of generation; anything after the
# first occurrence is not model content.
EOS_MARKERS = ("</s>", "<|endoftext|>", "<|im_end|>", "<|end|>",
               "<end_of_turn>", "<|eot_id|>", "[end of text]")


def is_termux() -> bool:
    """True when running under Termux (Android). Same evidence as the rest of
    the runtime (VoiceEnvironment / TermuxAdapter / resources): Termux sets
    ``TERMUX_VERSION`` and the on-device data dir exists."""
    return bool(os.environ.get("TERMUX_VERSION")) or os.path.exists(
        "/data/data/com.termux")


def _install_hint() -> str:
    """How to get a real GGUF backend, platform-aware.

    On Termux the answer is NEVER ``pip install llama-cpp-python``: pip has no
    Android aarch64 wheels for it or for its ``cmake`` build dependency, so it
    tries to compile cmake from source and the bootstrap dies with
    ``iconv is required, but was not found``. Termux ships a prebuilt
    ``llama-cpp`` package instead (provides ``llama-cli``, no compilation).
    """
    if is_termux():
        return ("install llama.cpp via pkg: `pkg install llama-cpp` (prebuilt "
                "llama-cli, no compilation). Never install the "
                "llama-cpp-python package on Termux via pip — there are no "
                "Android aarch64 wheels, so pip tries to build cmake from "
                "source and fails (iconv not found). If llama-cpp is "
                "unavailable on your channel, build llama.cpp per TERMUX.md")
    return ("install llama-cpp-python (pip install llama-cpp-python) or put "
            "llama-cli/main on PATH (Termux: pkg install llama-cpp; see "
            "TERMUX.md)")

# Minimal liveness probe: the backend must produce these exact tokens back.
PROBE_PROMPT = "Reply with exactly: ZERION_LOCAL_OK"
PROBE_TOKEN = "ZERION_LOCAL_OK"


def clean_generated_text(text: str) -> str:
    for marker in EOS_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip()


def extract_cli_output(stdout: str, prompt: str) -> str:
    """Extract the generated text from a llama.cpp CLI invocation.

    Handles both shapes seen in the wild:
    - real ``llama-cli``: logo/info header, then ``> {prompt}`` echo, then the
      generated text, then a ``[ Prompt: x t/s | Generation: y t/s ]`` stats
      footer and ``Exiting...``;
    - stub/alternative binaries that only print the generated text.

    Never guesses: the footer and the FIRST interactive echo are the only
    structural markers removed; everything else is returned untouched.
    """
    text = stdout or ""
    # 1) Drop the generation-stats footer llama-cli prints after generation.
    m = re.search(r"\n\[[^\n]*?t/s[^\n]*?\]", text)
    if m:
        text = text[: m.start()]
    else:
        idx = text.find("Exiting...")
        if idx != -1:
            text = text[:idx]
    # 2) In single-turn (-st) mode llama-cli echoes "> {prompt}" before the
    #    generated text; cut at the FIRST interactive prompt echo (including
    #    the echoed prompt itself) and keep only the generated text. Binaries
    #    that never echo are left untouched.
    idx = text.find("\n> ")
    if idx != -1:
        text = text[idx + 3:]
        if text.startswith(prompt):
            text = text[len(prompt):]
    elif text.startswith("> "):
        text = text[3:]
        if text.startswith(prompt):
            text = text[len(prompt):]
    return clean_generated_text(text)


# -- real detection hooks (monkeypatchable seams used by the legacy provider) -

def _real_python_available() -> bool:
    try:
        return importlib.util.find_spec("llama_cpp") is not None
    except Exception:  # noqa: BLE001 — a broken import must never crash detection
        return False


def _real_find_cli() -> Optional[str]:
    env = os.environ.get("ZERION_GGUF_CLI", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    for name in ("llama-cli", "main", "llama-llama-cli"):
        found = shutil.which(name)
        if found:
            return found
    return None


class LlamaCppPythonBackend:
    """In-process backend via llama-cpp-python. One resident model at a time,
    cached by (model_path, context, threads)."""

    kind = "python"
    display_name = "llama-cpp-python"
    error_label = "llama-cpp-python"

    def __init__(self, python_available: Optional[Callable[[], bool]] = None):
        self._python_available = python_available or _real_python_available
        self._engine = None
        self._engine_key: Optional[tuple] = None

    def available(self) -> bool:
        return bool(self._python_available())

    def unavailable_message(self) -> str:
        if is_termux():
            # On Termux the pip path is a guaranteed cmake/iconv build
            # failure (no aarch64 wheels) — point at the prebuilt package.
            return _install_hint()
        return ("llama-cpp-python not importable — install it with "
                "pip install llama-cpp-python (desktop/server)")

    # -- execution ----------------------------------------------------------

    def _llama(self, model_path: str, context: int, threads: int):
        import gc
        import importlib as _il
        key = (str(model_path), int(context), int(threads))
        if self._engine is None or self._engine_key != key:
            llama_cpp = _il.import_module("llama_cpp")
            self._engine = None
            gc.collect()
            self._engine = llama_cpp.Llama(
                model_path=str(model_path), n_ctx=int(context),
                n_threads=int(threads), verbose=False)
            self._engine_key = key
        return self._engine

    def generate(self, model_path: str, prompt: str, *, max_tokens: int,
                 context: int, threads: int, temperature: float,
                 timeout_s: float) -> Tuple[str, Dict[str, Any]]:
        engine = self._llama(model_path, context, threads)
        out = engine.create_completion(
            prompt, max_tokens=int(max_tokens),
            temperature=float(temperature), echo=False,
            stop=list(EOS_MARKERS))
        text = clean_generated_text(
            (out.get("choices") or [{}])[0].get("text", ""))
        usage = out.get("usage") or {}
        return text, {"prompt_tokens": usage.get("prompt_tokens"),
                      "completion_tokens": usage.get("completion_tokens")}


class LlamaCppCLIBackend:
    """llama.cpp CLI binary on PATH (the Termux/Android path). Single-shot
    invocation only: ``-no-cnv -st`` and stdin from /dev/null, so a TTY can
    never trap it in interactive mode (which previously made it echo ``> ``.
    prompts forever instead of returning generated text)."""

    kind = "cli"
    display_name = "llama.cpp CLI"
    error_label = "llama.cpp CLI"

    def __init__(self, cli_path: str):
        self.cli_path = str(cli_path)

    def available(self) -> bool:
        return bool(self.cli_path) and os.path.isfile(self.cli_path) \
            and os.access(self.cli_path, os.X_OK)

    def unavailable_message(self) -> str:
        return f"no local GGUF inference backend available — {_install_hint()}"

    # -- execution ----------------------------------------------------------

    def generate(self, model_path: str, prompt: str, *, max_tokens: int,
                 context: int, threads: int, temperature: float,
                 timeout_s: float) -> Tuple[str, Dict[str, Any]]:
        cmd = [
            self.cli_path, "-m", str(model_path), "-p", prompt,
            "-n", str(max_tokens), "-c", str(context), "-t", str(threads),
            "--temp", str(temperature), "--no-display-prompt",
            "-no-cnv", "-st", "-s", "0",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s, check=False,
                              stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"exit {proc.returncode}: {detail[:200]}")
        return extract_cli_output(proc.stdout, prompt), {}


class UnsupportedBackend:
    """No executable backend exists. Honest BLOCKED report + install steps."""

    kind = "none"
    display_name = "NONE"
    error_label = "local GGUF"

    def __init__(self, reason: Optional[str] = None):
        self._reason = reason

    def available(self) -> bool:
        return False

    def unavailable_message(self) -> str:
        return (self._reason or
                f"no local GGUF inference backend available — {_install_hint()}")

    def generate(self, *args: Any, **kwargs: Any) -> Tuple[str, Dict[str, Any]]:
        raise RuntimeError(self.unavailable_message())


class LocalGGUFBackend:
    """Factory facade: turns a requested mode + real detection into the single
    concrete backend the runtime should use for inference."""

    @classmethod
    def detect(cls, requested: str = "auto",
               python_available: Optional[Callable[[], bool]] = None,
               find_cli: Optional[Callable[[], Optional[str]]] = None
               ) -> Optional[object]:
        req = (requested or "auto").strip().lower()
        if req in ("none", "off", "disabled"):
            return None
        py = python_available or _real_python_available
        cli = find_cli or _real_find_cli
        if req in ("python", "py", "llama-cpp-python", "llama_cpp"):
            return LlamaCppPythonBackend(python_available=py)
        if req in ("cli", "llama-cli", "main"):
            path = cli()
            if path:
                return LlamaCppCLIBackend(cli_path=path)
            return UnsupportedBackend(
                reason="ZERION_GGUF_BACKEND=cli but no llama-cli/main found "
                       "on PATH (set ZERION_GGUF_CLI to a llama.cpp binary)")
        # auto: python backend first, then the CLI binary, then honest NONE.
        if py():
            return LlamaCppPythonBackend(python_available=py)
        path = cli()
        if path:
            return LlamaCppCLIBackend(cli_path=path)
        return UnsupportedBackend()


# -- the canonical lifecycle probe -------------------------------------------

def probe_backend(backend: object, model_path: str, *,
                  timeout_s: float = 120.0,
                  probe_prompt: str = PROBE_PROMPT) -> Dict[str, Any]:
    """Real load + real generation against the actual model file. VERIFIED
    only when the generated output actually contains the expected token."""
    t0 = time.perf_counter()
    threads = _int_env("ZERION_GGUF_THREADS", 0)
    if threads <= 0:
        threads = min(os.cpu_count() or 4, 8)
    try:
        text, _usage = backend.generate(
            str(model_path), probe_prompt, max_tokens=24,
            context=_int_env("ZERION_GGUF_CONTEXT", 512),
            threads=threads, temperature=0.0, timeout_s=timeout_s)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        ok = bool(text) and PROBE_TOKEN in text
        return {
            "loadable": "LOADED",
            "inference": "VERIFIED" if ok else "FAILED",
            "probe_prompt": probe_prompt,
            "probe_output": (text or "")[:200],
            "probe_latency_ms": latency_ms,
            "error": None if ok else (
                f"probe output did not contain expected token "
                f"{PROBE_TOKEN!r} (got {text[:120]!r})"),
        }
    except Exception as exc:  # noqa: BLE001 — structured, never a crash
        return {
            "loadable": "FAILED",
            "inference": "NOT_VERIFIED",
            "probe_prompt": probe_prompt,
            "probe_output": None,
            "probe_latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }


def _backend_report(backend: Optional[object],
                    requested: str) -> Dict[str, Any]:
    if backend is None:
        return {"requested": requested, "name": "NONE", "available": False,
                "kind": "none",
                "detail": "ZERION_GGUF_BACKEND=none (disabled)",
                "install_hint": None}
    return {
        "requested": requested,
        "name": getattr(backend, "display_name", "NONE"),
        "available": bool(backend.available()),
        "kind": getattr(backend, "kind", "none"),
        "detail": (getattr(backend, "cli_path", None)
                   if getattr(backend, "kind", "") == "cli"
                   else getattr(backend, "unavailable_message", lambda: "")()),
        "install_hint": (backend.unavailable_message()
                         if not backend.available() else None),
    }


def probe_local_gguf(models_dir: str, *, timeout_s: Optional[float] = None
                     ) -> Dict[str, Any]:
    """Canonical lifecycle report for the local GGUF stack:

        DISCOVERED -> BACKEND -> LOADED -> INFERENCE_VERIFIED -> READY

    ``status`` is READY only when a real inference probe verified real tokens;
    otherwise NO_LOCAL_MODEL_AVAILABLE or BLOCKED with the actual cause.
    """
    from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery

    requested = os.environ.get("ZERION_GGUF_BACKEND", "auto").strip().lower() \
        or "auto"
    disc = LocalModelDiscovery(models_dir=models_dir)
    models = disc.models()
    available = [m for m in models.values()
                 if getattr(getattr(m, "status", None), "value", "") == "AVAILABLE"]
    # Deterministic: smallest valid model first (mobile-friendly).
    available.sort(key=lambda m: ((m.size_bytes or 0), m.model_id))
    sel = available[0] if available else None

    base = {
        "dir": str(disc.models_dir),
        "discovered": len(models),
        "available": len(available),
        "selected": [sel.model_id] if sel else [],
        # The real absolute filesystem path — never reconstructed from names.
        "selected_path": str(sel.path) if sel else None,
    }

    if sel is None:
        return {**base,
                "backend": _backend_report(None if requested == "none"
                                           else UnsupportedBackend(), requested),
                "probe": {"loadable": "NOT_ATTEMPTED",
                          "inference": "NOT_VERIFIED",
                          "probe_prompt": PROBE_PROMPT,
                          "probe_output": None,
                          "probe_latency_ms": None, "error": None},
                "status": "NO_LOCAL_MODEL_AVAILABLE",
                "reason": f"no valid .gguf file under '{disc.models_dir}'"}

    backend = LocalGGUFBackend.detect(requested=requested)
    if backend is None:
        return {**base,
                "backend": _backend_report(None, requested),
                "probe": {"loadable": "NOT_ATTEMPTED",
                          "inference": "NOT_VERIFIED",
                          "probe_prompt": PROBE_PROMPT,
                          "probe_output": None,
                          "probe_latency_ms": None, "error": None},
                "status": "BLOCKED",
                "reason": "local GGUF inference disabled (ZERION_GGUF_BACKEND=none)"}

    if not backend.available():
        return {**base,
                "backend": _backend_report(backend, requested),
                "probe": {"loadable": "NOT_ATTEMPTED",
                          "inference": "NOT_VERIFIED",
                          "probe_prompt": PROBE_PROMPT,
                          "probe_output": None,
                          "probe_latency_ms": None, "error": None},
                "status": "BLOCKED",
                "reason": backend.unavailable_message()}

    if os.environ.get("ZERION_GGUF_PROBE", "1").strip().lower() in (
            "0", "false", "off", "no"):
        return {**base,
                "backend": _backend_report(backend, requested),
                "probe": {"loadable": "NOT_ATTEMPTED",
                          "inference": "NOT_VERIFIED",
                          "probe_prompt": PROBE_PROMPT,
                          "probe_output": None,
                          "probe_latency_ms": None,
                          "error": "probe disabled by ZERION_GGUF_PROBE=0"},
                "status": "BLOCKED",
                "reason": "inference not verified (probe disabled)"}

    if timeout_s is None:
        timeout_s = _float_env("ZERION_GGUF_PROBE_TIMEOUT", 120.0)
    probe = probe_backend(backend, str(sel.path), timeout_s=timeout_s)
    verified = probe.get("inference") == "VERIFIED"
    return {**base,
            "backend": _backend_report(backend, requested),
            "probe": probe,
            "status": "READY" if verified else "BLOCKED",
            "reason": None if verified else (
                probe.get("error") or "inference probe failed")}


# -- tunables ----------------------------------------------------------------

def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
