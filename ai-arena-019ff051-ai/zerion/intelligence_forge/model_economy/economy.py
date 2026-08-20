"""
Model Economy & Model Discovery Substrate for ZERION-X Ω
Manages interchangeable foundation models (OpenAI API, Local GGUF discovery, Specialists, Heuristic engines)
with dynamic cost/latency routing and zero-downtime fallback.
"""

from dataclasses import dataclass, field
import glob
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ModelProfile:
    model_id: str
    provider: str               # "openai", "local_gguf", "deterministic_local", "specialist"
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
    def __init__(self, models_dir: str = "models"):
        self.models_dir = Path(models_dir)
        self._registry: Dict[str, ModelProfile] = {}
        self._bootstrap_foundation_models()
        self.discover_gguf_models()

    def _bootstrap_foundation_models(self):
        # OpenAI Foundation Tier (Official production models)
        self._registry["openai_gpt4o_mini"] = ModelProfile(
            model_id="openai_gpt4o_mini",
            provider="openai",
            tier="FAST",
            cost_per_1k_tokens=0.00015,
            avg_latency_ms=350.0,
            context_window=128000,
            capabilities=["reasoning", "structured_output", "tool_calling"]
        )
        self._registry["openai_gpt4o"] = ModelProfile(
            model_id="openai_gpt4o",
            provider="openai",
            tier="REASONING",
            cost_per_1k_tokens=0.005,
            avg_latency_ms=750.0,
            context_window=128000,
            capabilities=["deep_reasoning", "multimodal", "code_synthesis"]
        )
        # Local Micro / Deterministic Fallback Tiers
        self._registry["deterministic_local"] = ModelProfile(
            model_id="deterministic_local",
            provider="deterministic_local",
            tier="REFLEX",
            cost_per_1k_tokens=0.0,
            avg_latency_ms=2.0,
            context_window=32000,
            capabilities=["procedural_execution", "invariant_checks", "reflex"]
        )

    def discover_gguf_models(self) -> List[ModelProfile]:
        """Automatically discovers any local .gguf models in models/ directory."""
        discovered = []
        if not self.models_dir.exists():
            return discovered

        for file_path in glob.glob(str(self.models_dir / "*.gguf")):
            p = Path(file_path)
            model_id = f"gguf_{p.stem.lower()}"
            profile = ModelProfile(
                model_id=model_id,
                provider="local_gguf",
                tier="FAST",
                cost_per_1k_tokens=0.0,
                avg_latency_ms=45.0,
                context_window=8192,
                path=str(p),
                quantization="Q4_K_M" if "q4" in p.stem.lower() else "Q8_0",
                capabilities=["local_reasoning", "offline"]
            )
            self._registry[model_id] = profile
            discovered.append(profile)
        return discovered

    def select_optimal_model(
        self,
        required_capability: str = "reasoning",
        max_cost_cents: float = 1.0,
        is_offline: bool = False
    ) -> ModelProfile:
        """Selects the best available model based on task constraints and network availability."""
        candidates = [
            m for m in self._registry.values()
            if m.is_available and (not is_offline or m.provider in ("local_gguf", "deterministic_local"))
        ]
        if not candidates:
            return self._registry["deterministic_local"]

        # Sort by capability match and cost efficiency
        candidates.sort(key=lambda m: (required_capability in m.capabilities, -m.cost_per_1k_tokens, m.reliability), reverse=True)
        return candidates[0]
