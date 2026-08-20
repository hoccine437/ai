"""
Cognitive Router for ZERION-X — Gemini-only with deterministic fallback.

Provider priority:
  1. Gemini 3.1 Flash (when GEMINI_API_KEY is set) — fast, free, good quality
  2. Deterministic fallback — always available, no model needed
"""

from enum import Enum
import time
from typing import Any, Dict, List, Optional
from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.model_providers.gemini_provider import GeminiProvider, LocalGGUFProvider
from zerion.model_providers.openai_provider import DeterministicFallbackProvider


class CognitiveDepthLevel(str, Enum):
    D0_REFLEX = "D0_REFLEX"
    D1_DIRECT = "D1_DIRECT"
    D2_VERIFY = "D2_VERIFY"
    D3_MULTI_HYPOTHESIS = "D3_MULTI_HYPOTHESIS"
    D4_EXPERIMENT = "D4_EXPERIMENT"
    D5_ADVERSARIAL = "D5_ADVERSARIAL"
    D6_ARCHITECTURE = "D6_ARCHITECTURE"


class CognitiveRouter:
    def __init__(self, models_dir: str = "models"):
        from zerion.cognitive_os.gguf_discovery import resolve_models_dir
        models_dir = resolve_models_dir(models_dir)
        self.providers: Dict[str, ModelProvider] = {
            "gemini": GeminiProvider(),
            "deterministic_local": DeterministicFallbackProvider()
        }

    def compute_cognitive_depth(
        self,
        uncertainty: float,
        novelty: float,
        stakes_risk: float,
        goal_relevance: float,
        historical_failure_rate: float = 0.1
    ) -> CognitiveDepthLevel:
        depth_score = (
            (uncertainty * 0.30) +
            (novelty * 0.25) +
            (stakes_risk * 0.25) +
            (goal_relevance * 0.10) +
            (historical_failure_rate * 0.10)
        )
        if depth_score < 0.20:
            return CognitiveDepthLevel.D0_REFLEX
        elif depth_score < 0.35:
            return CognitiveDepthLevel.D1_DIRECT
        elif depth_score < 0.50:
            return CognitiveDepthLevel.D2_VERIFY
        elif depth_score < 0.65:
            return CognitiveDepthLevel.D3_MULTI_HYPOTHESIS
        elif depth_score < 0.75:
            return CognitiveDepthLevel.D4_EXPERIMENT
        elif depth_score < 0.85:
            return CognitiveDepthLevel.D5_ADVERSARIAL
        else:
            return CognitiveDepthLevel.D6_ARCHITECTURE

    async def route_and_execute(
        self,
        prompt: str,
        depth: Optional[CognitiveDepthLevel] = None,
        preferred_provider: Optional[str] = None,
        is_voice: bool = False,
        is_offline: bool = False
    ) -> ModelResponse:
        """Route to Gemini 3.1 Flash (primary) with deterministic fallback."""
        # 1. Specific provider requested
        if preferred_provider and preferred_provider in self.providers:
            provider = self.providers[preferred_provider]
            if provider.is_available():
                res = await provider.generate_response(prompt)
                if not res.is_fallback:
                    return res

        # 2. Gemini is the SOLE provider
        gemini = self.providers.get("gemini")
        if gemini and gemini.is_available():
            res = await gemini.generate_response(prompt)
            if not res.is_fallback:
                return res

        # 3. Deterministic fallback (always works, no model needed)
        return await self.providers["deterministic_local"].generate_response(prompt)
