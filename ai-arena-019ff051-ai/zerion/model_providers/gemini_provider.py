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
    """Real local GGUF inference.

    All backend machinery lives in ``zerion.cognitive_os.gguf_backend`` — the
    provider only selects a model and delegates execution. The backend chain
    (evidence-based, all lazy, module stays pure stdlib at import time):

      1. ``llama-cpp-python``  (``pip install llama-cpp-python``; desktops/servers)
      2. ``llama.cpp`` CLI     (``llama-cli`` / legacy ``main`` on PATH; Termux
         via a local llama.cpp build, per TERMUX.md)

    Model selection reuses the validated ``LocalModelDiscovery`` from the
    cognitive OS (recursive scan, GGUF magic check, model_id -> absolute path
    map). Explicit ``model_id`` wins; otherwise the smallest valid model is
    chosen deterministically (mobile-friendly). The provider hands the REAL
    discovered filesystem path to the backend — it never reconstructs a path
    from a model name. When no model file exists or no backend can run it,
    the provider returns an honest ``FALLBACK_RESPONSE`` that names the
    missing piece — never fabricated model text.

    Tunables (env): ZERION_GGUF_BACKEND (auto|python|cli|none),
    ZERION_GGUF_CLI, ZERION_GGUF_THREADS, ZERION_GGUF_CONTEXT,
    ZERION_GGUF_MAX_TOKENS, ZERION_GGUF_TEMPERATURE,
    ZERION_GGUF_TIMEOUT_SECONDS.
    """

    BACKEND_AUTO = "auto"
    BACKEND_PYTHON = "python"
    BACKEND_CLI = "cli"
    BACKEND_NONE = "none"

    def __init__(self, models_dir: str = "models", backend: str = BACKEND_AUTO):
        super().__init__("local_gguf")
        # Lazy: keeps module import order independent of the cognitive OS tree.
        from zerion.cognitive_os.gguf_discovery import resolve_models_dir
        self.models_dir = Path(resolve_models_dir(models_dir))
        self.backend = backend
        self.last_error = ""
        # Backend instances are cached per requested mode (the python backend
        # keeps one resident model). Detection hooks stay live: env changes
        # (e.g. a backend installed mid-run) produce a fresh instance.
        self._backend_cache: Dict[str, Any] = {}

    # -- backend detection (evidence-based, never assumed) -----------------

    def _requested_backend(self) -> str:
        env = os.environ.get("ZERION_GGUF_BACKEND", "").strip().lower()
        if env in ("python", "py", "llama-cpp-python", "llama_cpp"):
            return self.BACKEND_PYTHON
        if env in ("cli", "llama-cli", "main"):
            return self.BACKEND_CLI
        if env in ("server", "llama-server"):
            return "server"
        if env in ("none", "off", "disabled"):
            return self.BACKEND_NONE
        return self.backend

    def _has_python_backend(self) -> bool:
        import importlib.util
        return importlib.util.find_spec("llama_cpp") is not None

    def _find_cli(self) -> Optional[str]:
        import shutil
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

    def _resolve_backend(self):
        """The concrete backend for the current requested mode (cached per
        mode so the python backend's resident model survives across calls)."""
        from zerion.cognitive_os.gguf_backend import LocalGGUFBackend
        mode = self._requested_backend()
        if mode not in self._backend_cache:
            self._backend_cache[mode] = LocalGGUFBackend.detect(
                requested=mode,
                python_available=self._has_python_backend,
                find_cli=self._find_cli)
        return self._backend_cache[mode]

    def backend_info(self) -> Dict[str, Any]:
        """Evidence-based report of what inference machinery actually exists."""
        backend = None
        try:
            backend = self._resolve_backend()
        except Exception:  # noqa: BLE001 — detection must never crash reporting
            backend = None
        info = {
            "mode": self._requested_backend(),
            "models_dir": str(self.models_dir),
            "model_available": self.is_available(),
            "name": "NONE",
            "available": False,
            "install_hint": None,
        }
        if backend is None:
            info["python_backend"] = False
            info["cli"] = None
            info["server"] = None
            info["install_hint"] = "local GGUF inference disabled " \
                                   "(ZERION_GGUF_BACKEND=none)"
            return info
        info["python_backend"] = bool(backend.kind == "python")
        info["cli"] = getattr(backend, "cli_path", None) \
            if backend.kind == "cli" else None
        info["server"] = getattr(backend, "server_url", None) \
            if backend.kind == "server" else None
        info["name"] = backend.display_name
        info["available"] = bool(backend.available())
        if not backend.available():
            info["install_hint"] = backend.unavailable_message()
        return info

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

        backend = self._resolve_backend()
        if backend is None:
            self.last_error = "local GGUF inference disabled " \
                              "(ZERION_GGUF_BACKEND=none)"
            return self._fallback(prompt, t0)
        if not backend.available():
            self.last_error = backend.unavailable_message()
            return self._fallback(prompt, t0)

        # Real inference through the detected backend (python or CLI). The
        # backend receives the DISCOVERED absolute model path — never a path
        # reconstructed from the model name. Local timeouts are unlimited by
        # default: a first load on a slow phone must never be killed
        # mid-turn. ZERION_GGUF_TIMEOUT_SECONDS still bounds the wait.
        try:
            text, usage = await asyncio.to_thread(
                backend.generate,
                str(model.path), prompt,
                max_tokens=self._int_env("ZERION_GGUF_MAX_TOKENS", 512),
                context=self._int_env("ZERION_GGUF_CONTEXT", 2048),
                threads=self._threads(),
                temperature=self._float_env("ZERION_GGUF_TEMPERATURE", 0.7),
                timeout_s=self._timeout_env())
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{backend.error_label} failed: {exc}"
            return self._fallback(prompt, t0)
        if not text:
            self.last_error = \
                f"{backend.error_label} produced empty output"
            return self._fallback(prompt, t0)
        return self._real(model, text, usage, t0)

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
    def _timeout_env() -> Optional[float]:
        """Local inference budget in seconds. None = UNLIMITED (default); an
        explicit ZERION_GGUF_TIMEOUT_SECONDS still bounds the wait, and the
        values ``0``, ``none``, ``null`` and ``unlimited`` all mean UNLIMITED
        — never an artificial zero-second kill window for a slow phone."""
        raw = os.environ.get("ZERION_GGUF_TIMEOUT_SECONDS", "").strip().lower()
        if not raw or raw in ("0", "none", "null", "unlimited", "inf"):
            return None
        try:
            return max(1.0, float(raw))
        except ValueError:
            return None

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
