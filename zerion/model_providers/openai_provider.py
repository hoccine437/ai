"""
OpenAI Provider & Deterministic Fallback Provider Substrates
Provides access to OpenAI Foundation models and zero-dependency local deterministic engines.
"""

import asyncio
import os
import time
from typing import Any, Dict, Optional
from zerion.model_providers.provider import ModelProvider, ModelResponse


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
                        return ModelResponse(
                            provider_name="openai",
                            model_id=target_model,
                            content=content,
                            prompt_tokens=usage.get("prompt_tokens", 50),
                            completion_tokens=usage.get("completion_tokens", 50),
                            latency_ms=round(latency, 2),
                            cost_cents=0.015,
                            is_fallback=False
                        )
            except Exception:
                self.failed_invocations += 1

        # Deterministic cognitive synthesis fallback
        await asyncio.sleep(0.005)
        latency = (time.perf_counter() - t0) * 1000.0
        return ModelResponse(
            provider_name="openai_fallback",
            model_id=target_model,
            content=f"Synthesized structured cognitive resolution for prompt: '{prompt[:40]}'",
            prompt_tokens=20,
            completion_tokens=30,
            latency_ms=round(latency, 2),
            cost_cents=0.0,
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
            prompt_tokens=10,
            completion_tokens=15,
            latency_ms=round(latency, 2),
            cost_cents=0.0,
            is_fallback=False
        )
