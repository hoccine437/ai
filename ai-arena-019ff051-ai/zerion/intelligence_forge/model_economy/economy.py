"""
Model Economy & Model Registry for ZERION-X Ω

There is exactly ONE foundation model: Gemini. This module keeps the model
profile registry the Foundry uses for episode metadata. There is no OpenAI
tier, no deterministic fallback tier, and no local GGUF discovery anywhere in
Zerion — when Gemini is unavailable its state is reported honestly.
"""

from dataclasses import dataclass, field
import os
from typing import List, Optional


@dataclass
class ModelProfile:
    model_id: str
    provider: str               # "gemini" — the only provider
    tier: str                   # "FAST", "REASONING", "CODING", "REFLEX"
    cost_per_1k_tokens: float
    avg_latency_ms: float
    context_window: int
    is_available: bool = True
    reliability: float = 0.98
    path: Optional[str] = None
    quantization: Optional[str] = None
    capabilities: List[str] = field(default_factory=lambda: ["reasoning", "structured_output"])


class ModelEconomy:
    """Registry of the single authoritative model: Gemini."""

    def __init__(self, models_dir: str = "models"):
        # models_dir kept for constructor compatibility; no local models exist.
        self._registry = {"gemini": ModelProfile(
            model_id="gemini",
            provider="gemini",
            tier="REASONING",
            cost_per_1k_tokens=0.0,
            avg_latency_ms=450.0,
            context_window=1_000_000,
            is_available=bool(os.environ.get("GEMINI_API_KEY", "")),
            reliability=0.98,
            capabilities=["reasoning", "structured_output", "tool_calling",
                          "multimodal", "code_synthesis"],
        )}

    def discover_gguf_models(self) -> List[ModelProfile]:
        """Removed: there are no local GGUF models in Zerion. Always empty."""
        return []

    def select_optimal_model(
        self,
        required_capability: str = "reasoning",
        max_cost_cents: float = 1.0,
        is_offline: bool = False
    ) -> ModelProfile:
        """Returns Gemini — the only model. There is no fallback brain."""
        return self._registry["gemini"]

    def availability(self) -> str:
        """Honest availability string derived from the real environment."""
        return ("GEMINI_API_KEY: SET" if self._registry["gemini"].is_available
                else "GEMINI_API_KEY: MISSING — Gemini unavailable")
