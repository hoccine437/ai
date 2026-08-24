"""
Cognitive Plasticity Engine - Dynamic Reconfiguration with Invariant Safety
"""

from dataclasses import dataclass, field
import json
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class PlasticityConfig:
    version: int = 1
    reasoning_depth: int = 3
    compute_threshold_fast: float = 0.4
    compute_threshold_deep: float = 0.75
    verification_strictness: float = 0.85
    model_routing_weights: Dict[str, float] = field(default_factory=lambda: {
        "deterministic_local": 1.0,
        "local_code_engine": 1.2,
        "cloud_deep_reasoner": 1.5
    })
    procedural_distillation_support: int = 2
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "reasoning_depth": self.reasoning_depth,
            "compute_threshold_fast": self.compute_threshold_fast,
            "compute_threshold_deep": self.compute_threshold_deep,
            "verification_strictness": self.verification_strictness,
            "model_routing_weights": dict(self.model_routing_weights),
            "procedural_distillation_support": self.procedural_distillation_support,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlasticityConfig":
        return cls(
            version=data.get("version", 1),
            reasoning_depth=data.get("reasoning_depth", 3),
            compute_threshold_fast=data.get("compute_threshold_fast", 0.4),
            compute_threshold_deep=data.get("compute_threshold_deep", 0.75),
            verification_strictness=data.get("verification_strictness", 0.85),
            model_routing_weights=data.get("model_routing_weights", {}),
            procedural_distillation_support=data.get("procedural_distillation_support", 2),
            updated_at=data.get("updated_at", time.time())
        )


class CognitivePlasticityManager:
    def __init__(self):
        self._current_config = PlasticityConfig()
        self._history: List[PlasticityConfig] = [self._current_config]

    @property
    def current(self) -> PlasticityConfig:
        return self._current_config

    def apply_mutation(self, changes: Dict[str, Any]) -> PlasticityConfig:
        """
        Creates a new version of cognitive config applying specified parameter mutations.
        """
        curr_dict = self._current_config.to_dict()
        for k, v in changes.items():
            if k in curr_dict and k not in ("version", "updated_at"):
                curr_dict[k] = v

        new_cfg = PlasticityConfig.from_dict(curr_dict)
        new_cfg.version = self._current_config.version + 1
        new_cfg.updated_at = time.time()
        self._history.append(new_cfg)
        self._current_config = new_cfg
        return new_cfg

    def rollback_to_previous(self) -> Optional[PlasticityConfig]:
        """
        Rollback in case of benchmark regression.
        """
        if len(self._history) > 1:
            self._history.pop()  # Discard failed head
            self._current_config = self._history[-1]
            return self._current_config
        return None
