"""
Cognitive Phenotype System - Domain-Specialized Behavioral Configurations
Derives concrete operational execution parameters from the core Cognitive Genome.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
from zerion.cognitive_genome.genome import CognitiveGenome


@dataclass
class CognitivePhenotype:
    name: str
    domain: str
    reasoning_depth: int
    parallel_width: int
    verification_ratio: float
    adversarial_check_rate: float
    experiment_rate: float
    exploration_ratio: float
    tool_policy: str
    memory_policy: str
    risk_tolerance: float
    max_latency_ms: float
    is_dynamic: bool = False
    provenance: str = "core_specification"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "reasoning_depth": self.reasoning_depth,
            "parallel_width": self.parallel_width,
            "verification_ratio": round(self.verification_ratio, 3),
            "adversarial_check_rate": round(self.adversarial_check_rate, 3),
            "experiment_rate": round(self.experiment_rate, 3),
            "exploration_ratio": round(self.exploration_ratio, 3),
            "tool_policy": self.tool_policy,
            "memory_policy": self.memory_policy,
            "risk_tolerance": round(self.risk_tolerance, 3),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "is_dynamic": self.is_dynamic,
            "provenance": self.provenance,
            "created_at": self.created_at
        }


class PhenotypeFactory:
    """
    Derives specialized Cognitive Phenotypes from a parent Cognitive Genome.
    """
    @staticmethod
    def derive_phenotype(genome: CognitiveGenome, phenotype_name: str) -> CognitivePhenotype:
        name_lower = phenotype_name.lower()

        if "code" in name_lower or "coding" in name_lower:
            return CognitivePhenotype(
                name="CodingPhenotype",
                domain="software_engineering",
                reasoning_depth=max(3, genome.reasoning_depth),
                parallel_width=max(2, genome.parallel_reasoning_width),
                verification_ratio=min(1.0, genome.verification_ratio * 1.15),
                adversarial_check_rate=0.90,
                experiment_rate=0.85,
                exploration_ratio=0.20,
                tool_policy="sandbox_unit_test_mandatory",
                memory_policy="procedural_first",
                risk_tolerance=min(0.20, genome.risk_tolerance),
                max_latency_ms=genome.latency_budget_ms * 1.5
            )

        elif "debug" in name_lower:
            return CognitivePhenotype(
                name="DebuggingPhenotype",
                domain="fault_localization",
                reasoning_depth=max(4, genome.reasoning_depth + 1),
                parallel_width=max(3, genome.parallel_reasoning_width),
                verification_ratio=0.95,
                adversarial_check_rate=0.95,
                experiment_rate=0.90,
                exploration_ratio=0.30,
                tool_policy="bisection_fault_isolation",
                memory_policy="failure_and_procedural",
                risk_tolerance=0.15,
                max_latency_ms=genome.latency_budget_ms * 2.0
            )

        elif "research" in name_lower or "investigat" in name_lower:
            return CognitivePhenotype(
                name="ResearchPhenotype",
                domain="epistemic_discovery",
                reasoning_depth=max(4, genome.reasoning_depth + 1),
                parallel_width=max(4, genome.parallel_reasoning_width + 1),
                verification_ratio=0.80,
                adversarial_check_rate=0.75,
                experiment_rate=0.75,
                exploration_ratio=0.65,
                tool_policy="epistemic_graph_search",
                memory_policy="semantic_and_causal",
                risk_tolerance=0.45,
                max_latency_ms=genome.latency_budget_ms * 3.0
            )

        elif "math" in name_lower:
            return CognitivePhenotype(
                name="MathematicalPhenotype",
                domain="formal_deduction",
                reasoning_depth=max(5, genome.reasoning_depth + 2),
                parallel_width=2,
                verification_ratio=1.0,
                adversarial_check_rate=1.0,
                experiment_rate=0.40,
                exploration_ratio=0.10,
                tool_policy="formal_proof_symbolic",
                memory_policy="semantic_axioms",
                risk_tolerance=0.05,
                max_latency_ms=genome.latency_budget_ms * 1.8
            )

        elif "security" in name_lower:
            return CognitivePhenotype(
                name="SecurityPhenotype",
                domain="adversarial_defense",
                reasoning_depth=max(4, genome.reasoning_depth),
                parallel_width=4,
                verification_ratio=1.0,
                adversarial_check_rate=1.0,
                experiment_rate=0.90,
                exploration_ratio=0.40,
                tool_policy="zero_trust_strict_boundary",
                memory_policy="failure_and_invariants",
                risk_tolerance=0.01,
                max_latency_ms=genome.latency_budget_ms
            )

        elif "plan" in name_lower:
            return CognitivePhenotype(
                name="PlanningPhenotype",
                domain="task_orchestration",
                reasoning_depth=max(3, genome.reasoning_depth),
                parallel_width=3,
                verification_ratio=0.85,
                adversarial_check_rate=0.70,
                experiment_rate=0.50,
                exploration_ratio=0.35,
                tool_policy="dag_scheduler_checkpointed",
                memory_policy="procedural_and_episodic",
                risk_tolerance=0.25,
                max_latency_ms=genome.latency_budget_ms
            )

        elif "creative" in name_lower:
            return CognitivePhenotype(
                name="CreativePhenotype",
                domain="novel_hypothesis_generation",
                reasoning_depth=2,
                parallel_width=5,
                verification_ratio=0.60,
                adversarial_check_rate=0.40,
                experiment_rate=0.60,
                exploration_ratio=0.85,
                tool_policy="divergent_sampling",
                memory_policy="semantic_associative",
                risk_tolerance=0.70,
                max_latency_ms=genome.latency_budget_ms
            )

        elif "diagnostic" in name_lower:
            return CognitivePhenotype(
                name="DiagnosticPhenotype",
                domain="causal_anomaly_tracing",
                reasoning_depth=max(3, genome.reasoning_depth),
                parallel_width=3,
                verification_ratio=0.90,
                adversarial_check_rate=0.85,
                experiment_rate=0.80,
                exploration_ratio=0.40,
                tool_policy="causal_counterfactual_probe",
                memory_policy="causal_and_failure",
                risk_tolerance=0.20,
                max_latency_ms=genome.latency_budget_ms * 1.2
            )

        elif "experiment" in name_lower:
            return CognitivePhenotype(
                name="ExperimentationPhenotype",
                domain="empirical_reality_sampling",
                reasoning_depth=3,
                parallel_width=3,
                verification_ratio=0.95,
                adversarial_check_rate=0.80,
                experiment_rate=1.0,
                exploration_ratio=0.50,
                tool_policy="sandbox_reality_loop",
                memory_policy="empirical_episodes",
                risk_tolerance=0.30,
                max_latency_ms=genome.latency_budget_ms * 1.5
            )

        else:
            return CognitivePhenotype(
                name="GeneralReasoningPhenotype",
                domain="general_cognition",
                reasoning_depth=genome.reasoning_depth,
                parallel_width=genome.parallel_reasoning_width,
                verification_ratio=genome.verification_ratio,
                adversarial_check_rate=genome.adversarial_check_rate,
                experiment_rate=genome.experiment_rate,
                exploration_ratio=genome.exploration_ratio,
                tool_policy="adaptive_multi_tier",
                memory_policy="hybrid_semantic_procedural",
                risk_tolerance=genome.risk_tolerance,
                max_latency_ms=genome.latency_budget_ms
            )
