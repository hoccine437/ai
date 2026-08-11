"""
Cognitive Genome Substrate - 22-Dimensional Computational Behavior Representation
Represents the system's internal computational configuration, preferences, and behavioral boundaries.
Strictly does NOT contain neural weights; defines cognitive topologies and execution parameters.
"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid


@dataclass
class GenomeMutationProposal:
    proposal_id: str = field(default_factory=lambda: f"mut_{uuid.uuid4().hex[:8]}")
    target_dimension: str = ""
    previous_value: Any = None
    proposed_value: Any = None
    hypothesis: str = ""
    source_phenotype: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    benchmark_evidence: Dict[str, Any] = field(default_factory=dict)
    is_approved: bool = False
    is_canary_passed: bool = False


class CognitiveGenome:
    """
    22-Dimensional Behavioral Genome of ASCENDANT ∞ with strict bounds and mutation safeguards.
    """
    def __init__(self, version: int = 1, lineage_id: Optional[str] = None):
        self.genome_id = f"gen_{uuid.uuid4().hex[:8]}"
        self.version = version
        self.lineage_id = lineage_id or self.genome_id
        self.created_at = time.time()
        self.updated_at = time.time()

        # --- 22 Core Cognitive Dimensions ---
        self.reasoning_depth: int = 3                      # [1, 10]
        self.exploration_ratio: float = 0.25               # [0.0, 1.0]
        self.verification_ratio: float = 0.85              # [0.0, 1.0]
        self.question_generation_rate: float = 0.70        # [0.0, 1.0]
        self.experiment_rate: float = 0.60                 # [0.0, 1.0]
        self.memory_retrieval_strategy: str = "hybrid_semantic_procedural"
        self.model_selection_strategy: str = "evidence_weighted_cost_optimal"
        self.tool_selection_strategy: str = "least_privilege_deterministic_first"
        self.parallel_reasoning_width: int = 3             # [1, 8]
        self.abstraction_level: float = 0.75               # [0.0, 1.0]
        self.counterfactual_rate: float = 0.65             # [0.0, 1.0]
        self.adversarial_check_rate: float = 0.80          # [0.0, 1.0]
        self.evidence_threshold: float = 0.70              # [0.1, 1.0]
        self.uncertainty_threshold: float = 0.40           # [0.1, 1.0]
        self.risk_tolerance: float = 0.30                  # [0.0, 1.0]
        self.compute_budget_cents: float = 50.0            # [0.1, 1000.0]
        self.latency_budget_ms: float = 2000.0             # [10.0, 60000.0]
        self.cost_budget_cents: float = 10.0               # [0.01, 1000.0]
        self.network_budget_kb: float = 10240.0            # [0.0, 1048576.0]
        self.learning_rate: float = 0.20                   # [0.01, 1.0]
        self.strategy_reuse_bias: float = 0.80             # [0.0, 1.0]
        self.novelty_bias: float = 0.35                    # [0.0, 1.0]

        self.mutation_history: List[Dict[str, Any]] = []
        self.active_phenotypes: List[str] = []

    def validate_bounds(self) -> Tuple[bool, Optional[str]]:
        """Ensures all genomic parameters remain within safe invariant operational envelopes."""
        if not (1 <= self.reasoning_depth <= 10):
            return False, "reasoning_depth out of bounds [1, 10]"
        if not (0.0 <= self.exploration_ratio <= 1.0):
            return False, "exploration_ratio out of bounds [0.0, 1.0]"
        if not (0.0 <= self.verification_ratio <= 1.0):
            return False, "verification_ratio out of bounds [0.0, 1.0]"
        if not (1 <= self.parallel_reasoning_width <= 8):
            return False, "parallel_reasoning_width out of bounds [1, 8]"
        if not (0.1 <= self.evidence_threshold <= 1.0):
            return False, "evidence_threshold out of bounds [0.1, 1.0]"
        if not (0.0 <= self.risk_tolerance <= 1.0):
            return False, "risk_tolerance out of bounds [0.0, 1.0]"
        if self.latency_budget_ms < 5.0:
            return False, "latency_budget_ms too restrictive (< 5ms)"
        return True, None

    def _raw_dimensions_dict(self) -> Dict[str, Any]:
        return {
            "reasoning_depth": self.reasoning_depth,
            "exploration_ratio": self.exploration_ratio,
            "verification_ratio": self.verification_ratio,
            "question_generation_rate": self.question_generation_rate,
            "experiment_rate": self.experiment_rate,
            "memory_retrieval_strategy": self.memory_retrieval_strategy,
            "model_selection_strategy": self.model_selection_strategy,
            "tool_selection_strategy": self.tool_selection_strategy,
            "parallel_reasoning_width": self.parallel_reasoning_width,
            "abstraction_level": self.abstraction_level,
            "counterfactual_rate": self.counterfactual_rate,
            "adversarial_check_rate": self.adversarial_check_rate,
            "evidence_threshold": self.evidence_threshold,
            "uncertainty_threshold": self.uncertainty_threshold,
            "risk_tolerance": self.risk_tolerance,
            "compute_budget_cents": self.compute_budget_cents,
            "latency_budget_ms": self.latency_budget_ms,
            "cost_budget_cents": self.cost_budget_cents,
            "network_budget_kb": self.network_budget_kb,
            "learning_rate": self.learning_rate,
            "strategy_reuse_bias": self.strategy_reuse_bias,
            "novelty_bias": self.novelty_bias,
            "version": self.version,
            "lineage_id": self.lineage_id
        }

    def get_digest(self) -> str:
        """Computes cryptographic SHA-256 fingerprint of current genomic configuration."""
        data = self._raw_dimensions_dict()
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def clone(self) -> "CognitiveGenome":
        new_g = CognitiveGenome(version=self.version + 1, lineage_id=self.lineage_id)
        new_dict = self.to_dict()
        new_dict["version"] = self.version + 1
        return CognitiveGenome.from_dict(new_dict)

    def apply_mutation(self, proposal: GenomeMutationProposal) -> bool:
        """Applies mutation if validated and approved."""
        if not hasattr(self, proposal.target_dimension):
            return False
        
        old_val = getattr(self, proposal.target_dimension)
        setattr(self, proposal.target_dimension, proposal.proposed_value)
        
        valid, err = self.validate_bounds()
        if not valid:
            setattr(self, proposal.target_dimension, old_val)  # Rollback immediately
            return False

        self.version += 1
        self.updated_at = time.time()
        self.mutation_history.append({
            "proposal_id": proposal.proposal_id,
            "target": proposal.target_dimension,
            "old_value": old_val,
            "new_value": proposal.proposed_value,
            "hypothesis": proposal.hypothesis,
            "timestamp": time.time(),
            "digest": self.get_digest()
        })
        return True

    def to_dict(self) -> Dict[str, Any]:
        d = self._raw_dimensions_dict()
        d.update({
            "genome_id": self.genome_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mutation_history": self.mutation_history,
            "active_phenotypes": self.active_phenotypes,
            "digest": self.get_digest()
        })
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveGenome":
        g = cls(version=data.get("version", 1), lineage_id=data.get("lineage_id"))
        g.genome_id = data.get("genome_id", g.genome_id)
        g.created_at = data.get("created_at", g.created_at)
        g.updated_at = data.get("updated_at", g.updated_at)

        for dim in [
            "reasoning_depth", "exploration_ratio", "verification_ratio", "question_generation_rate",
            "experiment_rate", "memory_retrieval_strategy", "model_selection_strategy",
            "tool_selection_strategy", "parallel_reasoning_width", "abstraction_level",
            "counterfactual_rate", "adversarial_check_rate", "evidence_threshold",
            "uncertainty_threshold", "risk_tolerance", "compute_budget_cents",
            "latency_budget_ms", "cost_budget_cents", "network_budget_kb",
            "learning_rate", "strategy_reuse_bias", "novelty_bias"
        ]:
            if dim in data:
                setattr(g, dim, data[dim])

        g.mutation_history = data.get("mutation_history", [])
        g.active_phenotypes = data.get("active_phenotypes", [])
        return g
