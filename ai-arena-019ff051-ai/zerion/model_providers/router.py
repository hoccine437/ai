"""
Cognitive Router for ZERION-X — Gemini-only.

There is exactly ONE provider: Gemini. When it is unavailable (missing key,
network failure, API error) the router returns an honest structured failure —
it never substitutes a deterministic/fake/local brain.
"""

from enum import Enum
from typing import Optional

from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.model_providers.gemini_provider import GeminiProvider
from zerion.runtime.evidence import ExecutionMode


class CognitiveDepthLevel(str, Enum):
    D0_REFLEX = "D0_REFLEX"
    D1_DIRECT = "D1_DIRECT"
    D2_VERIFY = "D2_VERIFY"
    D3_MULTI_HYPOTHESIS = "D3_MULTI_HYPOTHESIS"
    D4_EXPERIMENT = "D4_EXPERIMENT"
    D5_ADVERSARIAL = "D5_ADVERSARIAL"
    D6_ARCHITECTURE = "D6_ARCHITECTURE"


class CognitiveRouter:
    def __init__(self):
        self.providers = {"gemini": GeminiProvider()}

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
        """Route to Gemini — the sole provider. No fallback brain exists."""
        gemini = self.providers.get("gemini")
        if gemini is None or not gemini.is_available():
            return ModelResponse(
                provider_name="gemini",
                model_id="gemini",
                content="[GEMINI UNAVAILABLE] GEMINI_API_KEY is missing or the "
                        "provider is unreachable. No offline/fake fallback exists.",
                execution_mode=ExecutionMode.FALLBACK_RESPONSE,
                is_fallback=True,
            )
        return await gemini.generate_response(prompt)
