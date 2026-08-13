"""
Slice 6 — Provider-independent model interface.

The cognitive core depends ONLY on this protocol. Provider-specific libraries
(openai, google SDK, llama.cpp) may only appear inside adapters that implement
it. A provider that is not genuinely functional must report UNAVAILABLE /
NOT_CONFIGURED — never fake support.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, Set

from zerion.cognitive_os.router_types import (
    ProviderStatus,
    ResultStatus,
    Task,
    redact_secrets,
)


# Canonical capability vocabulary. Capabilities are DECLARED by the adapter and
# verified where possible; the router never infers them from a model name.
TEXT = "text"
REASONING = "reasoning"
CODE = "code"
VISION = "vision"
AUDIO = "audio"
TOOL_USE = "tool_use"
LONG_CONTEXT = "long_context"
PLANNING = "planning"
MULTIMODAL = "multimodal"


class ProviderFailureKind(str, Enum):
    TIMEOUT = "TIMEOUT"
    QUOTA_FAILURE = "QUOTA_FAILURE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    MODEL_LOAD_FAILURE = "MODEL_LOAD_FAILURE"
    INTERNAL = "INTERNAL"


# Failure kinds that retrying (or failing over) can plausibly fix. Malformed
# output / invalid response are NOT retried — a retry will not repair them.
RETRIABLE_FAILURES = {
    ProviderFailureKind.TIMEOUT,
    ProviderFailureKind.QUOTA_FAILURE,
    ProviderFailureKind.PROVIDER_UNAVAILABLE,
    ProviderFailureKind.NETWORK_UNAVAILABLE,
    ProviderFailureKind.RESOURCE_EXHAUSTION,
    ProviderFailureKind.MODEL_LOAD_FAILURE,
    ProviderFailureKind.MODEL_UNAVAILABLE,
}

FAILURE_TO_STATUS: Dict[ProviderFailureKind, ResultStatus] = {
    ProviderFailureKind.TIMEOUT: ResultStatus.TIMEOUT,
    ProviderFailureKind.QUOTA_FAILURE: ResultStatus.QUOTA_FAILURE,
    ProviderFailureKind.INVALID_RESPONSE: ResultStatus.INVALID_RESPONSE,
    ProviderFailureKind.MALFORMED_OUTPUT: ResultStatus.MALFORMED_OUTPUT,
    ProviderFailureKind.PROVIDER_UNAVAILABLE: ResultStatus.PROVIDER_UNAVAILABLE,
    ProviderFailureKind.MODEL_UNAVAILABLE: ResultStatus.MODEL_UNAVAILABLE,
    ProviderFailureKind.CONTEXT_OVERFLOW: ResultStatus.CONTEXT_OVERFLOW,
    ProviderFailureKind.RESOURCE_EXHAUSTION: ResultStatus.RESOURCE_EXHAUSTION,
    ProviderFailureKind.NETWORK_UNAVAILABLE: ResultStatus.NETWORK_UNAVAILABLE,
    ProviderFailureKind.MODEL_LOAD_FAILURE: ResultStatus.MODEL_LOAD_FAILURE,
    ProviderFailureKind.INTERNAL: ResultStatus.PROVIDER_UNAVAILABLE,
}


@dataclass
class ModelInfo:
    """Description of one model a provider can serve."""

    model_id: str
    provider: str
    capabilities: Set[str] = field(default_factory=set)
    context_window: Optional[int] = None     # None = unknown
    size_bytes: Optional[int] = None
    status: ProviderStatus = ProviderStatus.UNKNOWN
    status_reason: str = ""
    format: str = ""                         # e.g. "gguf", "api"
    path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "model_id": self.model_id,
            "provider": self.provider,
            "capabilities": sorted(self.capabilities),
            "context_window": self.context_window,
            "size_bytes": self.size_bytes,
            "status": self.status.value,
            "status_reason": self.status_reason,
            "format": self.format,
            "path": self.path,
            "details": dict(self.details),
        }
        return redact_secrets(d)


@dataclass
class ProviderCall:
    """Typed request to a provider (never exposes provider SDK objects)."""

    task: Task
    prompt: str
    model_id: str
    timeout_s: float = 30.0
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RawProviderResponse:
    """Provider-layer response. Telemetry that was not actually measured stays
    None — nothing is fabricated here."""

    output: Optional[str] = None
    latency_ms: Optional[float] = None
    usage: Optional[Dict[str, Any]] = None    # only real usage from the provider
    success: bool = False
    failure_kind: Optional[ProviderFailureKind] = None
    error: str = ""
    confidence: Optional[float] = None        # None = provider gave none

    @property
    def result_status(self) -> ResultStatus:
        if self.success:
            return ResultStatus.SUCCESS
        if self.failure_kind is None:
            return ResultStatus.PROVIDER_UNAVAILABLE
        return FAILURE_TO_STATUS.get(self.failure_kind, ResultStatus.PROVIDER_UNAVAILABLE)


class ModelProvider(Protocol):
    """The only interface the cognitive router depends on."""

    provider_name: str
    is_local: bool = False
    # Optional declaration of which cognitive field this provider is best for
    # ("FAST_FIELD" / "DEEP_FIELD" / None = unknown). Used by the router to
    # match computation depth to actual task properties.
    field_profile: Optional[str] = None

    async def generate(self, call: ProviderCall) -> RawProviderResponse: ...

    async def stream(self, call: ProviderCall) -> AsyncIterator[RawProviderResponse]: ...

    async def health_check(self) -> ProviderStatus: ...

    def capabilities(self) -> Set[str]: ...

    def list_models(self) -> List[ModelInfo]: ...

    def model_info(self, model_id: str) -> Optional[ModelInfo]: ...
