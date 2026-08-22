"""
Adaptive Cognitive Scaling Controller
Dynamically allocates computational effort (search depth, verification, parallel paths, experimentation)
based on task difficulty, uncertainty, novelty, risk, and hardware compute quotas.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, Optional
from zerion.cognitive_genome.genome import CognitiveGenome
from zerion.cognitive_genome.phenotype import CognitivePhenotype


@dataclass
class AdaptiveCognitiveAllocation:
    task_id: str
    selected_mode: str          # "REFLEX", "FAST", "NORMAL", "DEEP", "EXTREME", "EXPERIMENTAL"
    reasoning_depth: int
    parallel_paths: int
    enable_sandbox_experiment: bool
    enable_adversarial_critique: bool
    enable_epistemic_graph_search: bool
    memory_retrieval_depth: int
    timeout_seconds: float
    cost_budget_cents: float
    rationale: str
    timestamp: float = field(default_factory=time.time)


class AdaptiveCognitiveController:
    def __init__(self, default_genome: Optional[CognitiveGenome] = None):
        self.genome = default_genome or CognitiveGenome()

    def allocate_cognition(
        self,
        task_id: str,
        uncertainty: float,
        difficulty: float,
        novelty: float,
        risk: float,
        phenotype: Optional[CognitivePhenotype] = None,
        available_compute_mb: float = 1024.0,
        is_offline: bool = False
    ) -> AdaptiveCognitiveAllocation:
        """
        Computes the optimal cognitive scaling vector for a task.
        """
        # Composite task intensity index: [0.0, 1.0]
        intensity = (uncertainty * 0.3) + (difficulty * 0.3) + (novelty * 0.2) + (risk * 0.2)
        base_depth = phenotype.reasoning_depth if phenotype else self.genome.reasoning_depth
        base_width = phenotype.parallel_width if phenotype else self.genome.parallel_reasoning_width

        if is_offline or available_compute_mb < 256.0:
            return AdaptiveCognitiveAllocation(
                task_id=task_id,
                selected_mode="REFLEX" if intensity < 0.5 else "FAST",
                reasoning_depth=min(2, base_depth),
                parallel_paths=1,
                enable_sandbox_experiment=False,
                enable_adversarial_critique=False,
                enable_epistemic_graph_search=True,
                memory_retrieval_depth=2,
                timeout_seconds=2.0,
                cost_budget_cents=0.01,
                rationale="Offline/low-memory constraint: throttled to local deterministic fast mode."
            )

        if intensity < 0.25:
            # Simple task -> Local Reflex
            return AdaptiveCognitiveAllocation(
                task_id=task_id,
                selected_mode="REFLEX",
                reasoning_depth=1,
                parallel_paths=1,
                enable_sandbox_experiment=False,
                enable_adversarial_critique=False,
                enable_epistemic_graph_search=False,
                memory_retrieval_depth=1,
                timeout_seconds=0.5,
                cost_budget_cents=0.01,
                rationale="Low uncertainty and low risk: resolved via direct procedural lookup."
            )

        elif intensity < 0.50:
            # Moderate task -> Fast Single Pass
            return AdaptiveCognitiveAllocation(
                task_id=task_id,
                selected_mode="FAST",
                reasoning_depth=base_depth,
                parallel_paths=1,
                enable_sandbox_experiment=False,
                enable_adversarial_critique=False,
                enable_epistemic_graph_search=True,
                memory_retrieval_depth=3,
                timeout_seconds=2.0,
                cost_budget_cents=0.05,
                rationale="Moderate complexity: standard single-pass cognition."
            )

        elif intensity < 0.75:
            # Uncertain / High-value task -> Normal with Verification
            return AdaptiveCognitiveAllocation(
                task_id=task_id,
                selected_mode="NORMAL",
                reasoning_depth=base_depth,
                parallel_paths=min(3, base_width),
                enable_sandbox_experiment=(novelty > 0.5),
                enable_adversarial_critique=True,
                enable_epistemic_graph_search=True,
                memory_retrieval_depth=5,
                timeout_seconds=5.0,
                cost_budget_cents=0.20,
                rationale="Elevated uncertainty: multi-path reasoning with adversarial invariant check."
            )

        elif novelty > 0.75 or uncertainty > 0.80:
            # Novel / High-Entropy task -> Deep Reality Experimentation
            return AdaptiveCognitiveAllocation(
                task_id=task_id,
                selected_mode="EXPERIMENTAL",
                reasoning_depth=max(4, base_depth + 1),
                parallel_paths=max(3, base_width),
                enable_sandbox_experiment=True,
                enable_adversarial_critique=True,
                enable_epistemic_graph_search=True,
                memory_retrieval_depth=8,
                timeout_seconds=15.0,
                cost_budget_cents=1.50,
                rationale="Novel problem topology: active hypothesis experimentation in sandbox."
            )

        else:
            # High-risk / Critical task -> Extreme Adversarial Defense
            return AdaptiveCognitiveAllocation(
                task_id=task_id,
                selected_mode="DEEP",
                reasoning_depth=max(5, base_depth + 2),
                parallel_paths=max(4, base_width + 1),
                enable_sandbox_experiment=True,
                enable_adversarial_critique=True,
                enable_epistemic_graph_search=True,
                memory_retrieval_depth=10,
                timeout_seconds=30.0,
                cost_budget_cents=2.50,
                rationale="High risk & high difficulty: exhaustive multi-path adversarial verification."
            )
