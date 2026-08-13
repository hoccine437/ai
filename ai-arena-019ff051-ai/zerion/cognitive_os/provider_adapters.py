"""
Slice 6 — Provider adapters.

The ONLY place provider-specific knowledge may live. Each adapter wraps the
legacy ``zerion.model_providers`` implementations (reused, not duplicated) and
reports an HONEST status:

- OpenAI   : NOT_CONFIGURED without a key; AVAILABLE with a key (real httpx
             integration exists in the legacy provider).
- Gemini   : NOT_CONFIGURED without a key; UNAVAILABLE with a key — the legacy
             provider explicitly has NO real Gemini API integration and always
             returns a labeled fallback. We never fake support.
- Local GGUF: discovery is REAL (file scan + GGUF magic validation); execution
             is UNAVAILABLE because no local inference engine is wired in this
             runtime (llama-cpp is not installed). generate() therefore
             returns a structured MODEL_LOAD_FAILURE with output=None — never
             canned model text.
"""

import os
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
from zerion.cognitive_os.provider_interface import (
    CODE,
    LONG_CONTEXT,
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
from zerion.model_providers.gemini_provider import (
    LocalGGUFProvider as LegacyGGUFProvider,
)
from zerion.model_providers.openai_provider import (
    OpenAIProvider as LegacyOpenAIProvider,
)


class LegacyOpenAIAdapter:
    """Wraps the legacy OpenAIProvider. Real integration when a key exists."""

    provider_name = "openai"
    is_local = False

    def __init__(self, provider: Optional[LegacyOpenAIProvider] = None):
        self._provider = provider or LegacyOpenAIProvider()
        self._default_model = self._provider.default_model
        self._configured = bool(os.environ.get("OPENAI_API_KEY", ""))

    # -- interface ----------------------------------------------------------

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
        # Legacy provider could not make a real call (missing key / request
        # failure). Return a structured failure — never the canned fallback.
        return RawProviderResponse(
            output=None, success=False,
            failure_kind=ProviderFailureKind.PROVIDER_UNAVAILABLE,
            error="openai call failed or not configured")

    async def stream(self, call: ProviderCall) -> AsyncIterator[RawProviderResponse]:
        raise NotImplementedError("openai adapter: streaming not supported")

    async def health_check(self) -> ProviderStatus:
        return (ProviderStatus.AVAILABLE if self._configured
                else ProviderStatus.NOT_CONFIGURED)

    def capabilities(self) -> Set[str]:
        return {TEXT, REASONING, CODE, LONG_CONTEXT}

    def list_models(self) -> List[ModelInfo]:
        return [ModelInfo(
            model_id=self._default_model, provider=self.provider_name,
            capabilities=self.capabilities(),
            status=(ProviderStatus.AVAILABLE if self._configured
                    else ProviderStatus.NOT_CONFIGURED),
            status_reason=("configured" if self._configured
                           else "missing OPENAI_API_KEY"),
            format="api")]

    def model_info(self, model_id: str) -> Optional[ModelInfo]:
        if model_id == self._default_model:
            return self.list_models()[0]
        return None


class LegacyGeminiAdapter:
    """Wraps the legacy GeminiProvider. The legacy provider has NO real API
    integration — it always returns a labeled fallback. Honest status:
    NOT_CONFIGURED without a key, UNAVAILABLE with one."""

    provider_name = "gemini"
    is_local = False

    def __init__(self, provider: Optional[LegacyGeminiProvider] = None):
        self._provider = provider or LegacyGeminiProvider()
        self._default_model = self._provider.default_model
        self._configured = bool(os.environ.get("GEMINI_API_KEY", ""))

    async def generate(self, call: ProviderCall) -> RawProviderResponse:
        # No real integration exists in the legacy provider — never return its
        # canned fallback as if it were model output.
        return RawProviderResponse(
            output=None, success=False,
            failure_kind=ProviderFailureKind.PROVIDER_UNAVAILABLE,
            error="gemini API integration not implemented")

    async def stream(self, call: ProviderCall) -> AsyncIterator[RawProviderResponse]:
        raise NotImplementedError("gemini adapter: streaming not supported")

    async def health_check(self) -> ProviderStatus:
        if not self._configured:
            return ProviderStatus.NOT_CONFIGURED
        return ProviderStatus.UNAVAILABLE

    def capabilities(self) -> Set[str]:
        return {TEXT, REASONING}

    def list_models(self) -> List[ModelInfo]:
        return [ModelInfo(
            model_id=self._default_model, provider=self.provider_name,
            capabilities=self.capabilities(),
            status=(ProviderStatus.UNAVAILABLE if self._configured
                    else ProviderStatus.NOT_CONFIGURED),
            status_reason=("no API integration implemented" if self._configured
                           else "missing GEMINI_API_KEY"),
            format="api")]

    def model_info(self, model_id: str) -> Optional[ModelInfo]:
        if model_id == self._default_model:
            return self.list_models()[0]
        return None


class LegacyGGUFAdapter:
    """Local GGUF adapter. Discovery is real (file scan + magic validation);
    generation is a structured MODEL_LOAD_FAILURE until a real inference
    engine is wired in (llama-cpp is not installed in this runtime)."""

    provider_name = "local_gguf"
    is_local = True

    def __init__(self, models_dir: str = "models",
                 discovery: Optional[LocalModelDiscovery] = None,
                 provider: Optional[LegacyGGUFProvider] = None):
        self._legacy = provider or LegacyGGUFProvider(models_dir=models_dir)
        self.discovery = discovery or LocalModelDiscovery(models_dir=models_dir)

    # -- interface ----------------------------------------------------------

    async def generate(self, call: ProviderCall) -> RawProviderResponse:
        # A valid local model exists but there is no inference engine wired in.
        # Honest structured failure: no output, no fabricated text.
        info = self.discovery.get(call.model_id)
        if info is None or info.status != ProviderStatus.AVAILABLE:
            return RawProviderResponse(
                output=None, success=False,
                failure_kind=ProviderFailureKind.MODEL_UNAVAILABLE,
                error=f"local model {call.model_id} unavailable or not found")
        return RawProviderResponse(
            output=None, success=False,
            failure_kind=ProviderFailureKind.MODEL_LOAD_FAILURE,
            error="local inference engine not wired into this runtime "
                  "(discovery is real; GGUF runtime unavailable)")

    async def stream(self, call: ProviderCall) -> AsyncIterator[RawProviderResponse]:
        raise NotImplementedError("local gguf adapter: streaming not supported")

    async def health_check(self) -> ProviderStatus:
        if self.discovery.any_available():
            return ProviderStatus.AVAILABLE
        return ProviderStatus.UNAVAILABLE

    def capabilities(self) -> Set[str]:
        caps: Set[str] = set()
        for m in self.discovery.models().values():
            if m.status == ProviderStatus.AVAILABLE:
                caps |= m.capabilities
        return caps or {TEXT}

    def list_models(self) -> List[ModelInfo]:
        return list(self.discovery.models().values())

    def model_info(self, model_id: str) -> Optional[ModelInfo]:
        return self.discovery.get(model_id)
