"""
Model Providers Subsystem exports for ZERION-X

Gemini is the ONLY provider. There is no OpenAI integration and no local
model — when Gemini is unavailable the failure is reported honestly.
"""

from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.model_providers.gemini_provider import GeminiProvider
from zerion.model_providers.router import CognitiveDepthLevel, CognitiveRouter

__all__ = [
    "ModelProvider",
    "ModelResponse",
    "GeminiProvider",
    "CognitiveDepthLevel",
    "CognitiveRouter",
]
