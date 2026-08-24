"""
Model Provider Abstraction Substrate for ZERION-X
Decouples the cognitive entity from underlying model providers (OpenAI, Gemini, Local GGUF, Deterministic).
The model is a replaceable cognitive organ; the entity is the system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional

from zerion.runtime.evidence import ExecutionMode


@dataclass
class ModelResponse:
    provider_name: str
    model_id: str
    content: str
    execution_mode: ExecutionMode
    structured_data: Optional[Dict[str, Any]] = None
    # None means "not measured" -- callers must not treat None as 0. Only a real
    # REAL_MODEL_RESPONSE populates these from the provider's actual usage payload.
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: float = 0.0
    cost_cents: Optional[float] = None
    is_fallback: bool = False
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        # Keep is_fallback consistent with execution_mode for any code that still
        # reads the older boolean flag, without letting the two disagree silently.
        if self.execution_mode != ExecutionMode.REAL_MODEL_RESPONSE:
            self.is_fallback = True


class ModelProvider(ABC):
    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.is_healthy = True
        self.total_invocations = 0
        self.failed_invocations = 0

    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model_id: Optional[str] = None,
        structured_schema: Optional[Dict[str, Any]] = None
    ) -> ModelResponse:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass
