"""
Gemini API Provider — the ONLY Zerion intelligence substrate

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
from typing import Any, Dict, Optional
from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.runtime.evidence import ExecutionMode


# Gemini API endpoint
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Default model — fast, cheap, good quality
_DEFAULT_MODEL = "gemini-2.5-flash"


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
