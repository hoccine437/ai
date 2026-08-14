"""
Gemini Voice/Multimodal Provider & Local GGUF Provider Substrates
"""

import asyncio
import glob
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.runtime.evidence import ExecutionMode


class GeminiProvider(ModelProvider):
    def __init__(self, default_model: str = "gemini-2.0-flash-exp"):
        super().__init__("gemini")
        self.default_model = default_model
        self.api_key = os.environ.get("GEMINI_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        structured_schema: Optional[Dict[str, Any]] = None
    ) -> ModelResponse:
        t0 = time.perf_counter()
        target_model = model_id or self.default_model
        self.total_invocations += 1

        # NOTE (correction phase): no real HTTP call to the Gemini API is
        # implemented here yet, regardless of whether GEMINI_API_KEY is set.
        # Previously this returned the same canned text either way and reported
        # a flat 0.005 cost unconditionally, which could look like a real paid
        # call even when nothing was sent. Marked explicitly as fallback until
        # a genuine API integration is added (mirroring OpenAIProvider's pattern).
        await asyncio.sleep(0.005)
        latency = (time.perf_counter() - t0) * 1000.0
        return ModelResponse(
            provider_name="gemini",
            model_id=target_model,
            content=f"[FALLBACK - NOT A MODEL RESPONSE] No Gemini API integration is "
                     f"implemented yet. Templated placeholder for '{prompt[:30]}'",
            execution_mode=ExecutionMode.FALLBACK_RESPONSE,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=round(latency, 2),
            cost_cents=None,
            is_fallback=True
        )


class LocalGGUFProvider(ModelProvider):
    """Real local GGUF inference (correction phase).

    Backend chain — all lazy, the module stays pure stdlib at import time:

      1. ``llama-cpp-python``  (``pip install llama-cpp-python``; desktops/servers)
      2. ``llama.cpp`` CLI     (``llama-cli`` / legacy ``main`` on PATH; Termux
         via a local llama.cpp build, per TERMUX.md)

    Model selection reuses the validated ``LocalModelDiscovery`` from the
    cognitive OS (recursive scan, GGUF magic check, model_id -> path map).
    Explicit ``model_id`` wins; otherwise the smallest valid model is chosen
    deterministically (mobile-friendly). When no model file exists or no
    backend can run it, the provider returns an honest
    ``FALLBACK_RESPONSE`` that names the missing piece — never fabricated
    model text.

    Tunables (env): ZERION_GGUF_BACKEND (auto|python|cli|none),
    ZERION_GGUF_THREADS, ZERION_GGUF_CONTEXT, ZERION_GGUF_MAX_TOKENS,
    ZERION_GGUF_TEMPERATURE, ZERION_GGUF_TIMEOUT_SECONDS.
    """

    BACKEND_AUTO = "auto"
    BACKEND_PYTHON = "python"
    BACKEND_CLI = "cli"
    BACKEND_NONE = "none"

    # Tokens llama.cpp may emit at the end of generation; anything after the
    # first occurrence is not model content.
    _EOS_MARKERS = ("</s>", "<|endoftext|>", "<|im_end|>", "<|end|>",
                    "<end_of_turn>", "<|eot_id|>", "[end of text]")

    def __init__(self, models_dir: str = "models", backend: str = BACKEND_AUTO):
        super().__init__("local_gguf")
        # Lazy: keeps module import order independent of the cognitive OS tree.
        from zerion.cognitive_os.gguf_discovery import resolve_models_dir
        self.models_dir = Path(resolve_models_dir(models_dir))
        self.backend = backend
        self.last_error = ""
        # Cached llama-cpp-python engine: one resident model at a time.
        self._engine = None
        self._engine_key: Optional[tuple] = None

    # -- backend detection (evidence-based, never assumed) -----------------

    def _requested_backend(self) -> str:
        env = os.environ.get("ZERION_GGUF_BACKEND", "").strip().lower()
        if env in ("python", "py", "llama-cpp-python", "llama_cpp"):
            return self.BACKEND_PYTHON
        if env in ("cli", "llama-cli", "main"):
            return self.BACKEND_CLI
        if env in ("none", "off", "disabled"):
            return self.BACKEND_NONE
        return self.backend

    def _has_python_backend(self) -> bool:
        import importlib.util
        return importlib.util.find_spec("llama_cpp") is not None

    def _find_cli(self) -> Optional[str]:
        import shutil
        for name in ("llama-cli", "main", "llama-llama-cli"):
            found = shutil.which(name)
            if found:
                return found
        return None

    def backend_info(self) -> Dict[str, Any]:
        """Evidence-based report of what inference machinery actually exists."""
        return {
            "mode": self._requested_backend(),
            "python_backend": self._has_python_backend(),
            "cli": self._find_cli(),
            "models_dir": str(self.models_dir),
            "model_available": self.is_available(),
        }

    # -- model discovery ---------------------------------------------------

    @staticmethod
    def _discovery(models_dir: str):
        # Lazy: keeps module import order independent of the cognitive OS tree.
        from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
        return LocalModelDiscovery(models_dir=models_dir)

    def _select_model(self, model_id: Optional[str] = None):
        """Deterministic selection. Explicit model_id wins; otherwise the
        smallest valid model (fastest load on constrained devices). Returns
        a ModelInfo or None."""
        discovery = self._discovery(str(self.models_dir))
        discovery.discover()
        if model_id:
            info = discovery.get(model_id)
            if info is not None and info.status.value == "AVAILABLE":
                return info
        available = discovery.available()
        if not available:
            return None
        return min(available, key=lambda m: (m.size_bytes or 0, m.model_id))

    def is_available(self) -> bool:
        """A valid model file exists (recursive scan). Backend presence is
        reported separately via ``backend_info()``; routing keeps its contract
        that offline traffic prefers local_gguf whenever a model file exists,
        and generation reports honestly if no backend can run it."""
        try:
            return self._select_model() is not None
        except Exception:
            return False

    # -- inference ---------------------------------------------------------

    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        structured_schema: Optional[Dict[str, Any]] = None
    ) -> ModelResponse:
        t0 = time.perf_counter()
        self.total_invocations += 1
        self.last_error = ""

        model = self._select_model(model_id)
        if model is None:
            self.last_error = (
                f"no valid .gguf model found under '{self.models_dir}'")
            return self._fallback(prompt, t0)

        mode = self._requested_backend()
        if mode == self.BACKEND_NONE:
            self.last_error = "local GGUF inference disabled " \
                              "(ZERION_GGUF_BACKEND=none)"
            return self._fallback(prompt, t0)

        # CLI backend (primary on Termux where llama-cpp-python does not
        # build; also tried automatically when the Python backend is absent).
        if mode == self.BACKEND_CLI or (mode == self.BACKEND_AUTO
                                        and not self._has_python_backend()):
            cli = self._find_cli()
            if cli is not None:
                try:
                    text, usage = await asyncio.to_thread(
                        self._run_cli, cli, model, prompt)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"llama.cpp CLI failed: {exc}"
                    return self._fallback(prompt, t0)
                if text:
                    return self._real(model, text, usage, t0)
                self.last_error = "llama.cpp CLI produced empty output"
                return self._fallback(prompt, t0)

        # Python backend (llama-cpp-python) — in-process, reports token usage.
        if mode in (self.BACKEND_AUTO, self.BACKEND_PYTHON):
            if self._has_python_backend():
                try:
                    text, usage = await asyncio.to_thread(
                        self._run_python, model, prompt)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"llama-cpp-python failed: {exc}"
                    return self._fallback(prompt, t0)
                if text:
                    return self._real(model, text, usage, t0)
                self.last_error = "llama-cpp-python produced empty output"
                return self._fallback(prompt, t0)

        self.last_error = (
            "no local GGUF inference backend available — install "
            "llama-cpp-python (pip install llama-cpp-python) or put "
            "llama-cli/main on PATH (Termux: build llama.cpp locally)")
        return self._fallback(prompt, t0)

    def _run_python(self, model, prompt: str):
        import importlib
        import gc
        llama_cpp = importlib.import_module("llama_cpp")
        ctx = self._int_env("ZERION_GGUF_CONTEXT", 2048)
        threads = self._threads()
        max_tokens = self._int_env("ZERION_GGUF_MAX_TOKENS", 512)
        temperature = self._float_env("ZERION_GGUF_TEMPERATURE", 0.7)
        key = (str(model.path), ctx, threads)
        if self._engine is None or self._engine_key != key:
            # Release the previous resident model before loading a new one.
            self._engine = None
            gc.collect()
            self._engine = llama_cpp.Llama(
                model_path=str(model.path), n_ctx=ctx,
                n_threads=threads, verbose=False)
            self._engine_key = key
        out = self._engine.create_completion(
            prompt, max_tokens=max_tokens, temperature=temperature,
            echo=False, stop=list(self._EOS_MARKERS))
        text = self._clean_output(
            (out.get("choices") or [{}])[0].get("text", ""))
        usage = out.get("usage") or {}
        return text, {"prompt_tokens": usage.get("prompt_tokens"),
                      "completion_tokens": usage.get("completion_tokens")}

    def _run_cli(self, cli: str, model, prompt: str):
        import subprocess
        max_tokens = self._int_env("ZERION_GGUF_MAX_TOKENS", 512)
        ctx = self._int_env("ZERION_GGUF_CONTEXT", 2048)
        threads = self._threads()
        temperature = self._float_env("ZERION_GGUF_TEMPERATURE", 0.7)
        timeout = self._int_env("ZERION_GGUF_TIMEOUT_SECONDS", 300)
        cmd = [
            cli, "-m", str(model.path), "-p", prompt,
            "-n", str(max_tokens), "-c", str(ctx), "-t", str(threads),
            "--temp", str(temperature), "--no-display-prompt", "-s", "0",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"exit {proc.returncode}: {detail[:200]}")
        text = self._clean_output(proc.stdout)
        return text, {}

    @classmethod
    def _clean_output(cls, text: str) -> str:
        for marker in cls._EOS_MARKERS:
            idx = text.find(marker)
            if idx != -1:
                text = text[:idx]
        return text.strip()

    # -- response helpers --------------------------------------------------

    def _real(self, model, text: str, usage: Dict[str, Any],
              t0: float) -> ModelResponse:
        latency = (time.perf_counter() - t0) * 1000.0
        return ModelResponse(
            provider_name="local_gguf",
            model_id=model.model_id,
            content=text,
            execution_mode=ExecutionMode.REAL_MODEL_RESPONSE,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=round(latency, 2),
            cost_cents=None,
            is_fallback=False,
        )

    def _fallback(self, prompt: str, t0: float) -> ModelResponse:
        latency = (time.perf_counter() - t0) * 1000.0
        return ModelResponse(
            provider_name="local_gguf",
            model_id="local_gguf",
            content=f"[FALLBACK - NOT A MODEL RESPONSE] Local GGUF inference "
                     f"unavailable: {self.last_error}",
            execution_mode=ExecutionMode.FALLBACK_RESPONSE,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=round(latency, 2),
            cost_cents=None,
            is_fallback=True,
        )

    # -- tunables ----------------------------------------------------------

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @staticmethod
    def _float_env(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    @classmethod
    def _threads(cls) -> int:
        n = cls._int_env("ZERION_GGUF_THREADS", 0)
        if n > 0:
            return n
        # Cap at 8: bounded compute for thermal/mobile friendliness.
        return min(os.cpu_count() or 4, 8)
