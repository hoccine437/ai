"""
Gemini API Provider & Local GGUF Provider Substrates

GeminiProvider makes REAL HTTP calls to the Gemini API using only stdlib (urllib).
No external SDK required — works on Android/Termux without pip install.

Env vars:
  GEMINI_API_KEY        — Required for Gemini (get from https://aistudio.google.com/apikey)
  GEMINI_MODEL          — Override model (default: gemini-3.1-flash)
  GEMINI_TEMPERATURE    — Override temperature (default: 0.7)
  GEMINI_MAX_TOKENS     — Override max tokens (default: 2048)
"""

import asyncio
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional
from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.runtime.evidence import ExecutionMode


# Gemini API endpoint
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Default model — fast, cheap, good quality
_DEFAULT_MODEL = "gemini-3.1-flash"


class GeminiProvider(ModelProvider):
    """Real Gemini API integration using only Python stdlib.

    Makes actual HTTP POST calls to the Gemini generateContent endpoint.
    No google-generativeai SDK required.
    """

    def __init__(self, default_model: str = _DEFAULT_MODEL):
        super().__init__("gemini")
        self.default_model = default_model
        self.api_key = os.environ.get("GEMINI_API_KEY", "")
        self._system_instruction = (
            "You are ZERION, an autonomous cognitive assistant. "
            "You think, reason, and understand before responding. "
            "You are NOT a generic chatbot — you are a specialized "
            "cognitive system that investigates, learns, and adapts. "
            "Always respond as ZERION."
        )

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 10)

    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        structured_schema: Optional[Dict[str, Any]] = None
    ) -> ModelResponse:
        t0 = time.perf_counter()
        target_model = model_id or os.environ.get("GEMINI_MODEL", self.default_model)
        self.total_invocations += 1

        if not self.is_available():
            latency = (time.perf_counter() - t0) * 1000.0
            return ModelResponse(
                provider_name="gemini",
                model_id=target_model,
                content="[FALLBACK] Gemini API key not configured. "
                        "Set GEMINI_API_KEY environment variable.",
                execution_mode=ExecutionMode.FALLBACK_RESPONSE,
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=round(latency, 2),
                cost_cents=None,
                is_fallback=True
            )

        try:
            result = await asyncio.to_thread(
                self._call_gemini,
                target_model,
                prompt,
                context
            )

            latency = (time.perf_counter() - t0) * 1000.0

            if result.get("error"):
                return ModelResponse(
                    provider_name="gemini",
                    model_id=target_model,
                    content=f"[FALLBACK] Gemini API error: {result['error']}",
                    execution_mode=ExecutionMode.FALLBACK_RESPONSE,
                    prompt_tokens=None,
                    completion_tokens=None,
                    latency_ms=round(latency, 2),
                    cost_cents=None,
                    is_fallback=True
                )

            # Extract usage metadata
            usage = result.get("usageMetadata", {})
            prompt_tokens = usage.get("promptTokenCount")
            completion_tokens = usage.get("candidatesTokenCount")

            # Extract text from response
            candidates = result.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
            else:
                text = ""

            if not text:
                return ModelResponse(
                    provider_name="gemini",
                    model_id=target_model,
                    content="[FALLBACK] Gemini returned empty response",
                    execution_mode=ExecutionMode.FALLBACK_RESPONSE,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=round(latency, 2),
                    cost_cents=None,
                    is_fallback=True
                )

            return ModelResponse(
                provider_name="gemini",
                model_id=target_model,
                content=text,
                execution_mode=ExecutionMode.REAL_MODEL_RESPONSE,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round(latency, 2),
                cost_cents=None,  # Free tier = no cost
                is_fallback=False,
            )

        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000.0
            return ModelResponse(
                provider_name="gemini",
                model_id=target_model,
                content=f"[FALLBACK] Gemini API call failed: {exc}",
                execution_mode=ExecutionMode.FALLBACK_RESPONSE,
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=round(latency, 2),
                cost_cents=None,
                is_fallback=True
            )

    def _call_gemini(
        self,
        model: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Synchronous Gemini API call using only stdlib urllib."""
        url = f"{_GEMINI_BASE}/{model}:generateContent?key={self.api_key}"

        # Build the request body
        body: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": float(os.environ.get("GEMINI_TEMPERATURE", "0.7")),
                "maxOutputTokens": int(os.environ.get("GEMINI_MAX_TOKENS", "2048")),
            }
        }

        # Add system instruction if available
        if self._system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": self._system_instruction}]
            }

        # Add conversation history from context if provided
        if context and "history" in context:
            history = context["history"]
            if isinstance(history, list) and history:
                body["contents"] = history + body["contents"]

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                pass
            return {"error": f"HTTP {exc.code}: {error_body[:200]}"}
        except urllib.error.URLError as exc:
            return {"error": f"Network error: {exc.reason}"}
        except Exception as exc:
            return {"error": str(exc)}


class LocalGGUFProvider(ModelProvider):
    """Real local GGUF inference.

    All backend machinery lives in ``zerion.cognitive_os.gguf_backend`` — the
    provider only selects a model and delegates execution.
    """

    BACKEND_AUTO = "auto"
    BACKEND_PYTHON = "python"
    BACKEND_CLI = "cli"
    BACKEND_NONE = "none"

    def __init__(self, models_dir: str = "models", backend: str = BACKEND_AUTO):
        super().__init__("local_gguf")
        from zerion.cognitive_os.gguf_discovery import resolve_models_dir
        self.models_dir = Path(resolve_models_dir(models_dir))
        self.backend = backend
        self.last_error = ""
        self._backend_cache: Dict[str, Any] = {}

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
        from zerion.cognitive_os.gguf_backend import LocalGGUFBackend
        mode = self._requested_backend()
        if mode not in self._backend_cache:
            self._backend_cache[mode] = LocalGGUFBackend.detect(
                requested=mode,
                python_available=self._has_python_backend,
                find_cli=self._find_cli)
        return self._backend_cache[mode]

    def backend_info(self) -> Dict[str, Any]:
        backend = None
        try:
            backend = self._resolve_backend()
        except Exception:
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
            info["install_hint"] = "local GGUF inference disabled "
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

    @staticmethod
    def _discovery(models_dir: str):
        from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
        return LocalModelDiscovery(models_dir=models_dir)

    def _select_model(self, model_id: Optional[str] = None):
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
        try:
            return self._select_model() is not None
        except Exception:
            return False

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
            self.last_error = "local GGUF inference disabled "
            return self._fallback(prompt, t0)
        if not backend.available():
            self.last_error = backend.unavailable_message()
            return self._fallback(prompt, t0)

        try:
            text, usage = await asyncio.to_thread(
                backend.generate,
                str(model.path), prompt,
                max_tokens=self._int_env("ZERION_GGUF_MAX_TOKENS", 512),
                context=self._int_env("ZERION_GGUF_CONTEXT", 2048),
                threads=self._threads(),
                temperature=self._float_env("ZERION_GGUF_TEMPERATURE", 0.7),
                timeout_s=self._timeout_env())
        except Exception as exc:
            self.last_error = f"{backend.error_label} failed: {exc}"
            return self._fallback(prompt, t0)
        if not text:
            self.last_error = \
                f"{backend.error_label} produced empty output"
            return self._fallback(prompt, t0)
        return self._real(model, text, usage, t0)

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

    @staticmethod
    def _timeout_env() -> Optional[float]:
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
        return min(os.cpu_count() or 4, 8)
