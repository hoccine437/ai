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
    def __init__(self, models_dir: str = "models"):
        super().__init__("local_gguf")
        self.models_dir = Path(models_dir)

    def is_available(self) -> bool:
        if not self.models_dir.exists():
            return False
        return len(glob.glob(str(self.models_dir / "*.gguf"))) > 0

    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        structured_schema: Optional[Dict[str, Any]] = None
    ) -> ModelResponse:
        t0 = time.perf_counter()
        self.total_invocations += 1
        # NOTE (correction phase): is_available() checks for a real .gguf file, but
        # no actual local model loading/inference is implemented here yet, so this
        # is templated output even when a model file is present. Previously reported
        # is_fallback=False, which misrepresented this as a genuine local inference.
        await asyncio.sleep(0.008)
        latency = (time.perf_counter() - t0) * 1000.0
        return ModelResponse(
            provider_name="local_gguf",
            model_id=model_id or "local_qwen_gguf",
            content=f"[FALLBACK - NOT A MODEL RESPONSE] No local GGUF inference is "
                     f"implemented yet. Templated placeholder for: {prompt[:30]}",
            execution_mode=ExecutionMode.FALLBACK_RESPONSE,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=round(latency, 2),
            cost_cents=None,
            is_fallback=True
        )
