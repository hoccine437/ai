"""
Model Provider Abstraction Substrate for ZERION-X
Decouples the cognitive entity from underlying model providers (OpenAI, Gemini, Local GGUF, Deterministic).
The model is a replaceable cognitive organ; the entity is the system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional


@dataclass
class ModelResponse:
    provider_name: str
    model_id: str
    content: str
    structured_data: Optional[Dict[str, Any]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_cents: float = 0.0
    is_fallback: bool = False
    timestamp: float = field(default_factory=time.time)


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
