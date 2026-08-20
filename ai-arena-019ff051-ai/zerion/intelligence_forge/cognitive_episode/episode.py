"""
Cognitive Episode Substrate for ZERION-X Ω
A Cognitive Episode is the fundamental unit of task-specific cognition:
A durable, compiled cognitive execution system with lifecycle transitions, budget allocations,
evidence linkage, cognitive credit assignment, and crash-resilient persistence.
"""

from dataclasses import dataclass, field
from enum import Enum
import json
import time
from typing import Any, Dict, List, Optional
import uuid


class EpisodeLifecycleState(str, Enum):
    CREATED = "CREATED"
    SCOPING = "SCOPING"
    COMPILING = "COMPILING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    LEARNING = "LEARNING"
    CONSOLIDATING = "CONSOLIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ANALYZING_FAILURE = "ANALYZING_FAILURE"
    RECOVERY = "RECOVERY"


@dataclass
class CognitiveBudget:
    time_budget_ms: float = 2000.0
    token_budget: int = 4000
    model_calls_max: int = 4
    tool_calls_max: int = 6
    experiment_budget: int = 2
    risk_budget: float = 0.20
    cost_budget_cents: float = 5.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_budget_ms": self.time_budget_ms,
            "token_budget": self.token_budget,
            "model_calls_max": self.model_calls_max,
            "tool_calls_max": self.tool_calls_max,
            "experiment_budget": self.experiment_budget,
            "risk_budget": self.risk_budget,
            "cost_budget_cents": self.cost_budget_cents
        }


@dataclass
class CognitiveEpisode:
    objective: str
    episode_id: str = field(default_factory=lambda: f"ep_omega_{uuid.uuid4().hex[:8]}")
    problem_statement: str = ""
    questions: List[str] = field(default_factory=list)
    hypotheses: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    budget: CognitiveBudget = field(default_factory=CognitiveBudget)
    selected_models: List[str] = field(default_factory=lambda: ["openai_gpt4o_mini", "deterministic_local"])
    selected_tools: List[str] = field(default_factory=list)
    selected_strategies: List[str] = field(default_factory=list)
    cognitive_program_topology: str = "DYNAMIC_DIRECT"
    execution_steps_log: List[Dict[str, Any]] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    cognitive_credit_assignment: Dict[str, float] = field(default_factory=dict)
    developmental_effect: Dict[str, Any] = field(default_factory=dict)
    status: EpisodeLifecycleState = EpisodeLifecycleState.CREATED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def transition(self, new_state: EpisodeLifecycleState):
        self.status = new_state
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "objective": self.objective,
            "problem_statement": self.problem_statement,
            "questions": self.questions,
            "hypotheses": self.hypotheses,
            "constraints": self.constraints,
            "budget": self.budget.to_dict(),
            "selected_models": self.selected_models,
            "selected_tools": self.selected_tools,
            "selected_strategies": self.selected_strategies,
            "cognitive_program_topology": self.cognitive_program_topology,
            "execution_steps_log": self.execution_steps_log,
            "evidence_ids": self.evidence_ids,
            "results": self.results,
            "failures": self.failures,
            "cognitive_credit_assignment": self.cognitive_credit_assignment,
            "developmental_effect": self.developmental_effect,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveEpisode":
        st_str = data.get("status", EpisodeLifecycleState.CREATED.value)
        try:
            status = EpisodeLifecycleState(st_str)
        except ValueError:
            status = EpisodeLifecycleState.CREATED

        b_data = data.get("budget", {})
        budget = CognitiveBudget(
            time_budget_ms=b_data.get("time_budget_ms", 2000.0),
            token_budget=b_data.get("token_budget", 4000),
            model_calls_max=b_data.get("model_calls_max", 4),
            tool_calls_max=b_data.get("tool_calls_max", 6),
            experiment_budget=b_data.get("experiment_budget", 2),
            risk_budget=b_data.get("risk_budget", 0.20),
            cost_budget_cents=b_data.get("cost_budget_cents", 5.0)
        )

        return cls(
            episode_id=data.get("episode_id", f"ep_omega_{uuid.uuid4().hex[:8]}"),
            objective=data.get("objective", ""),
            problem_statement=data.get("problem_statement", ""),
            questions=data.get("questions", []),
            hypotheses=data.get("hypotheses", []),
            constraints=data.get("constraints", []),
            budget=budget,
            selected_models=data.get("selected_models", []),
            selected_tools=data.get("selected_tools", []),
            selected_strategies=data.get("selected_strategies", []),
            cognitive_program_topology=data.get("cognitive_program_topology", "DYNAMIC_DIRECT"),
            execution_steps_log=data.get("execution_steps_log", []),
            evidence_ids=data.get("evidence_ids", []),
            results=data.get("results", {}),
            failures=data.get("failures", []),
            cognitive_credit_assignment=data.get("cognitive_credit_assignment", {}),
            developmental_effect=data.get("developmental_effect", {}),
            status=status,
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time())
        )
