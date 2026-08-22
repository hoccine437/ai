"""
Slice 6 — Provider adapters.

The ONLY place provider-specific knowledge may live. Each adapter wraps the
legacy ``zerion.model_providers`` implementations (reused, not duplicated) and
reports an HONEST status:

- Gemini : NOT_CONFIGURED without a key; AVAILABLE with a key (real stdlib
  urllib API integration in the legacy provider). This is the ONLY provider —
  there is no OpenAI integration and no local GGUF/offline fallback anywhere
  in the runtime. When Gemini fails the router reports a structured failure;
  it never substitutes another brain.
"""

import os
from typing import AsyncIterator, List, Optional, Set

from zerion.cognitive_os.provider_interface import (
    REASONING,
    TEXT,
    ModelInfo,
    ModelProvider,
    ProviderCall,
    ProviderFailureKind,
    RawProviderResponse,
)
from zerion.cognitive_os.router_types import ProviderStatus
from zerion.model_providers.gemini_provider import (
    GeminiProvider as LegacyGeminiProvider,
)


class LegacyGeminiAdapter:
    """Wraps the GeminiProvider. Real API integration using stdlib urllib —
    no SDK required. AVAILABLE when GEMINI_API_KEY is set.

    Note: health_check() returns AVAILABLE whenever a key is configured,
    because the real API integration works and transient provider-level
    availability checks should not block routing."""

    provider_name = "gemini"
    is_local = False

    def __init__(self, provider: Optional[LegacyGeminiProvider] = None):
        self._provider = provider or LegacyGeminiProvider()
        self._default_model = self._provider.default_model
        self._configured = bool(os.environ.get("GEMINI_API_KEY", ""))

    async def generate(self, call: ProviderCall) -> RawProviderResponse:
        resp = await self._provider.generate_response(
            call.prompt, model_id=call.model_id)
        if resp.execution_mode.value == "REAL_MODEL_RESPONSE":
            return RawProviderResponse(
                output=resp.content, latency_ms=resp.latency_ms,
                usage={"prompt_tokens": resp.prompt_tokens,
                       "completion_tokens": resp.completion_tokens,
                       "cost_cents": resp.cost_cents},
                success=True)
        # Gemini call failed — structured failure
        return RawProviderResponse(
            output=None, success=False,
            failure_kind=ProviderFailureKind.PROVIDER_UNAVAILABLE,
            error=resp.content[:200] if resp.content else "gemini call failed")

    async def stream(self, call: ProviderCall) -> AsyncIterator[RawProviderResponse]:
        raise NotImplementedError("gemini adapter: streaming not supported")

    async def health_check(self) -> ProviderStatus:
        # When a key is configured, the real urllib integration works.
        # Do NOT gate on the legacy provider's is_available() which can
        # return False transiently — that causes ROUTING_FAILED after
        # the first successful call.
        if self._configured:
            return ProviderStatus.AVAILABLE
        return ProviderStatus.NOT_CONFIGURED

    def capabilities(self) -> Set[str]:
        return {TEXT, REASONING}

    def list_models(self) -> List[ModelInfo]:
        configured = self._configured
        return [ModelInfo(
            model_id=self._default_model, provider=self.provider_name,
            capabilities=self.capabilities(),
            status=(ProviderStatus.AVAILABLE if configured
                    else ProviderStatus.NOT_CONFIGURED),
            status_reason=("real API integration (stdlib urllib)" if configured
                           else "missing GEMINI_API_KEY"),
            format="api")]

    def model_info(self, model_id: str) -> Optional[ModelInfo]:
        if model_id == self._default_model:
            return self.list_models()[0]
        return None
