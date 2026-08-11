"""
Model Fabric and Learned Model Router
"""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ModelDescriptor:
    model_id: str
    tier: str              # "heuristic", "local_small", "local_code", "cloud_reasoning", "specialized"
    cost_per_1k_tokens: float
    avg_latency_ms: float
    supported_modalities: List[str]
    success_rate: float = 1.0
    total_calls: int = 0
    is_available: bool = True


class ModelFabric:
    def __init__(self):
        self._registry: Dict[str, ModelDescriptor] = {}
        self._backends: Dict[str, Callable[[str, Dict[str, Any]], Any]] = {}
        self._bootstrap_models()

    def _bootstrap_models(self):
        self.register_model(
            ModelDescriptor(
                model_id="deterministic_local",
                tier="heuristic",
                cost_per_1k_tokens=0.0,
                avg_latency_ms=2.0,
                supported_modalities=["text", "code", "structured"],
                success_rate=0.99
            ),
            handler=self._heuristic_handler
        )
        self.register_model(
            ModelDescriptor(
                model_id="local_code_engine",
                tier="local_code",
                cost_per_1k_tokens=0.0,
                avg_latency_ms=45.0,
                supported_modalities=["code", "debugging", "verification"],
                success_rate=0.95
            ),
            handler=self._code_engine_handler
        )
        self.register_model(
            ModelDescriptor(
                model_id="cloud_deep_reasoner",
                tier="cloud_reasoning",
                cost_per_1k_tokens=0.015,
                avg_latency_ms=450.0,
                supported_modalities=["text", "reasoning", "synthesis"],
                success_rate=0.97
            ),
            handler=self._cloud_reasoner_handler
        )

    def register_model(self, descriptor: ModelDescriptor, handler: Optional[Callable] = None):
        self._registry[descriptor.model_id] = descriptor
        if handler:
            self._backends[descriptor.model_id] = handler

    def select_best_model(self, task_type: str, max_latency_ms: float = 1000.0, require_local: bool = False) -> str:
        """
        Evidence-based model selection balancing latency, cost, and reliability.
        """
        candidates = []
        for mid, desc in self._registry.items():
            if not desc.is_available:
                continue
            if require_local and desc.tier.startswith("cloud"):
                continue
            if desc.avg_latency_ms > max_latency_ms:
                continue
            
            # Score candidate
            score = (desc.success_rate * 100.0) - (desc.cost_per_1k_tokens * 10.0) - (desc.avg_latency_ms / 50.0)
            candidates.append((score, mid))

        if not candidates:
            return "deterministic_local"
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    async def invoke(self, model_id: str, prompt: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        start = time.perf_counter()
        desc = self._registry.get(model_id) or self._registry["deterministic_local"]
        handler = self._backends.get(desc.model_id, self._heuristic_handler)

        try:
            if asyncio.iscoroutinefunction(handler):
                response = await handler(prompt, context or {})
            else:
                response = handler(prompt, context or {})
            latency = (time.perf_counter() - start) * 1000.0
            desc.total_calls += 1
            desc.avg_latency_ms = round(((desc.avg_latency_ms * (desc.total_calls - 1)) + latency) / desc.total_calls, 2)
            return {
                "success": True,
                "model_id": desc.model_id,
                "response": response,
                "latency_ms": round(latency, 2)
            }
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000.0
            desc.total_calls += 1
            desc.success_rate = max(0.1, desc.success_rate - 0.05)
            return {
                "success": False,
                "model_id": desc.model_id,
                "error": str(e),
                "latency_ms": round(latency, 2)
            }

    def _heuristic_handler(self, prompt: str, context: Dict[str, Any]) -> str:
        return f"Deterministic resolution for '{prompt[:40]}'"

    def _code_engine_handler(self, prompt: str, context: Dict[str, Any]) -> str:
        return f"# Validated code execution path for: {prompt[:30]}"

    def _cloud_reasoner_handler(self, prompt: str, context: Dict[str, Any]) -> str:
        return f"Comprehensive multi-step reasoning synthesis for: {prompt[:40]}"
