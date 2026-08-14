"""
Cognitive Router Substrate for ZERION-X
Dynamically calculates Cognitive Depth Score (D0 to D6) and routes tasks across available model providers
with zero-downtime provider failover and cost optimization.
"""

from enum import Enum
import time
from typing import Any, Dict, List, Optional
from zerion.model_providers.provider import ModelProvider, ModelResponse
from zerion.model_providers.openai_provider import OpenAIProvider, DeterministicFallbackProvider
from zerion.model_providers.gemini_provider import GeminiProvider, LocalGGUFProvider


class CognitiveDepthLevel(str, Enum):
    D0_REFLEX = "D0_REFLEX"                  # Immediate lookup / deterministic rule (~2ms)
    D1_DIRECT = "D1_DIRECT"                  # Single-pass fast model (~50ms)
    D2_VERIFY = "D2_VERIFY"                  # Direct reasoning + deterministic verifier (~100ms)
    D3_MULTI_HYPOTHESIS = "D3_MULTI_HYPOTHESIS" # Competing hypotheses evaluated (~300ms)
    D4_EXPERIMENT = "D4_EXPERIMENT"          # Sandbox reality test + empirical delta (~500ms)
    D5_ADVERSARIAL = "D5_ADVERSARIAL"        # Independent adversarial challenge (~1000ms)
    D6_ARCHITECTURE = "D6_ARCHITECTURE"      # Cognitive topology search & Canary (~2000ms)


class CognitiveRouter:
    def __init__(self, models_dir: str = "models"):
        # Lazy import: keeps the model_providers package free of cognitive_os
        # import-order dependencies.
        from zerion.cognitive_os.gguf_discovery import resolve_models_dir
        models_dir = resolve_models_dir(models_dir)
        self.providers: Dict[str, ModelProvider] = {
            "openai": OpenAIProvider(),
            "gemini": GeminiProvider(),
            "local_gguf": LocalGGUFProvider(models_dir=models_dir),
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
        """Calculates dynamic CognitiveDepthScore [0.0 to 1.0]."""
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
        """Executes task through best available provider with automatic graceful failover."""
        # 1. Voice requests prioritize Gemini provider
        if is_voice and not is_offline:
            gemini = self.providers.get("gemini")
            if gemini and gemini.is_available():
                return await gemini.generate_response(prompt)

        # 2. Offline requests route to local GGUF or deterministic engine
        if is_offline:
            gguf = self.providers.get("local_gguf")
            if gguf and gguf.is_available():
                return await gguf.generate_response(prompt)
            return await self.providers["deterministic_local"].generate_response(prompt)

        # 3. High-depth / deep reasoning routes to OpenAI or local fallback
        if depth in (CognitiveDepthLevel.D3_MULTI_HYPOTHESIS, CognitiveDepthLevel.D4_EXPERIMENT, CognitiveDepthLevel.D5_ADVERSARIAL, CognitiveDepthLevel.D6_ARCHITECTURE):
            openai = self.providers.get("openai")
            if openai and openai.is_available():
                res = await openai.generate_response(prompt, model_id="gpt-4o")
                if not res.is_fallback:
                    return res

        # 4. Standard fast pass
        openai_fast = self.providers.get("openai")
        if openai_fast and openai_fast.is_available():
            res = await openai_fast.generate_response(prompt, model_id="gpt-4o-mini")
            if not res.is_fallback:
                return res

        # 5. Deterministic local failover
        return await self.providers["deterministic_local"].generate_response(prompt)
