"""
Semantic, Causal, Failure, Capability, and Metacognitive Memory Domains
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


# --- SEMANTIC MEMORY ---
@dataclass
class SemanticConcept:
    concept_id: str
    name: str
    definition: str
    properties: Dict[str, Any] = field(default_factory=dict)
    related_concepts: List[str] = field(default_factory=list)
    confidence: float = 1.0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "definition": self.definition,
            "properties": self.properties,
            "related_concepts": self.related_concepts,
            "confidence": self.confidence,
            "updated_at": self.updated_at
        }


# --- CAUSAL MEMORY ---
@dataclass
class CausalLink:
    id: str = field(default_factory=lambda: f"clink_{uuid.uuid4().hex[:8]}")
    cause: str = ""
    effect: str = ""
    intervention_tested: bool = False
    p_effect_given_cause: float = 0.9
    p_effect_without_cause: float = 0.1
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cause": self.cause,
            "effect": self.effect,
            "intervention_tested": self.intervention_tested,
            "p_effect_given_cause": self.p_effect_given_cause,
            "p_effect_without_cause": self.p_effect_without_cause,
            "updated_at": self.updated_at
        }


# --- FAILURE MEMORY ---
@dataclass
class FailureMemoryRecord:
    id: str = field(default_factory=lambda: f"fail_{uuid.uuid4().hex[:8]}")
    task_goal: str = ""
    failure_type: str = "reasoning_gap"  # knowledge_gap, tool_gap, reasoning_gap, etc.
    root_cause: str = ""
    preventive_rule: str = ""
    recurrence_count: int = 1
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_goal": self.task_goal,
            "failure_type": self.failure_type,
            "root_cause": self.root_cause,
            "preventive_rule": self.preventive_rule,
            "recurrence_count": self.recurrence_count,
            "timestamp": self.timestamp
        }


# --- METACOGNITIVE MEMORY ---
@dataclass
class MetacognitiveRecord:
    id: str = field(default_factory=lambda: f"meta_{uuid.uuid4().hex[:8]}")
    strategy_name: str = ""
    problem_domain: str = ""
    compute_tier_used: str = "NORMAL"
    effective_gain: float = 0.8
    cost_efficiency: float = 0.9
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "strategy_name": self.strategy_name,
            "problem_domain": self.problem_domain,
            "compute_tier_used": self.compute_tier_used,
            "effective_gain": self.effective_gain,
            "cost_efficiency": self.cost_efficiency,
            "timestamp": self.timestamp
        }
