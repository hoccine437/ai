"""
OpenAI Provider & Deterministic Fallback Provider Substrates
Provides access to OpenAI Foundation models and zero-dependency local deterministic engines.
"""

import asyncio
import os
import time
from typing import Any, Dict, Optional
from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.runtime.evidence import ExecutionMode


class OpenAIProvider(ModelProvider):
    def __init__(self, default_model: str = "gpt-4o-mini"):
        super().__init__("openai")
        self.default_model = default_model
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

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

        # Check if actual SDK or HTTP library is present and configured
        if self.is_available():
            try:
                # Use httpx or standard urllib if configured
                import httpx
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": target_model,
                    "messages": [
                        {"role": "system", "content": "You are ZERION-X Cognitive Engine. Reason rigorously."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                        usage = data.get("usage", {})
                        latency = (time.perf_counter() - t0) * 1000.0
                        # Only report token counts we actually received from the API.
                        # If the API omitted usage data, mark it unavailable rather
                        # than substituting a made-up number.
                        prompt_toks = usage.get("prompt_tokens")
                        completion_toks = usage.get("completion_tokens")
                        return ModelResponse(
                            provider_name="openai",
                            model_id=target_model,
                            content=content,
                            execution_mode=ExecutionMode.REAL_MODEL_RESPONSE,
                            prompt_tokens=prompt_toks,
                            completion_tokens=completion_toks,
                            latency_ms=round(latency, 2),
                            # Real cost requires per-model pricing lookup, not implemented;
                            # do not fabricate a flat 0.015 figure.
                            cost_cents=None,
                            is_fallback=False
                        )
            except Exception:
                self.failed_invocations += 1

        # No API key configured, or the real call failed/errored above.
        # This is template text, NOT model cognition. It must never be reported
        # with fabricated token/cost telemetry, and callers must be able to tell
        # this apart from a real response via execution_mode.
        await asyncio.sleep(0.005)
        latency = (time.perf_counter() - t0) * 1000.0
        return ModelResponse(
            provider_name="openai",
            model_id=target_model,
            content=f"[FALLBACK - NOT A MODEL RESPONSE] No OpenAI API call was made "
                     f"(missing/invalid API key or request failure). Templated "
                     f"placeholder for prompt: '{prompt[:40]}'",
            execution_mode=ExecutionMode.FALLBACK_RESPONSE,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=round(latency, 2),
            cost_cents=None,
            is_fallback=True
        )


class DeterministicFallbackProvider(ModelProvider):
    def __init__(self):
        super().__init__("deterministic_local")

    def is_available(self) -> bool:
        return True

    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        structured_schema: Optional[Dict[str, Any]] = None
    ) -> ModelResponse:
        t0 = time.perf_counter()
        self.total_invocations += 1
        await asyncio.sleep(0.002)
        latency = (time.perf_counter() - t0) * 1000.0
        return ModelResponse(
            provider_name="deterministic_local",
            model_id="deterministic_local_v1",
            content=f"Local deterministic procedural resolution for: {prompt[:30]}",
            execution_mode=ExecutionMode.SIMULATION,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=round(latency, 2),
            cost_cents=0.0,  # genuinely zero-cost by design, this one is real
            is_fallback=False
        )
