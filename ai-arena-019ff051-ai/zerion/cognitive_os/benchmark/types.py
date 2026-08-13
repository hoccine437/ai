"""
Slice 9 — benchmark type system.

Provider-independent, model-independent structures only. A ``BenchmarkTask`` is
a deterministic specification with objective success/failure criteria; every
task has its own seeded world (ground truth reachable only through tools) so
neither BASELINE nor ZERION ever sees hidden evaluator information.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid


class BenchmarkMode(str, Enum):
    """The two system configurations required by the spec, plus ablations."""

    BASELINE = "BASELINE"          # model + normal tool calling
    ZERION = "ZERION"              # same model + Cognitive Runtime

    # Ablations: FULL ZERION minus one component (Slice 9 rule 29).
    ABLATION_NO_VERIFICATION = "ABLATION_NO_VERIFICATION"
    ABLATION_NO_MEMORY = "ABLATION_NO_MEMORY"
    ABLATION_NO_GOALS = "ABLATION_NO_GOALS"
    ABLATION_NO_QUESTIONS = "ABLATION_NO_QUESTIONS"
    ABLATION_NO_CAPABILITIES = "ABLATION_NO_CAPABILITIES"


class BenchmarkCategory(str, Enum):
    NOVEL_PROBLEM_SOLVING = "NOVEL_PROBLEM_SOLVING"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    LONG_HORIZON_COMPLETION = "LONG_HORIZON_COMPLETION"
    FAILURE_RECOVERY = "FAILURE_RECOVERY"
    REALITY_VERIFICATION = "REALITY_VERIFICATION"
    QUESTION_GENERATION = "QUESTION_GENERATION"
    GOAL_PERSISTENCE = "GOAL_PERSISTENCE"
    CROSS_DOMAIN_REASONING = "CROSS_DOMAIN_REASONING"
    ADAPTATION = "ADAPTATION"
    CAPABILITY_REUSE = "CAPABILITY_REUSE"


class FailureTaxonomy(str, Enum):
    MODEL_REASONING = "MODEL_REASONING"
    TOOL_FAILURE = "TOOL_FAILURE"
    PLANNING_FAILURE = "PLANNING_FAILURE"
    MEMORY_FAILURE = "MEMORY_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    GOAL_FAILURE = "GOAL_FAILURE"
    ROUTING_FAILURE = "ROUTING_FAILURE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    CAPABILITY_FAILURE = "CAPABILITY_FAILURE"
    OTHER = "OTHER"


class MetricKey(str, Enum):
    TASK_SUCCESS = "task_success"
    TIME_TO_SOLUTION = "time_to_solution_s"
    RETRY_COUNT = "retry_count"
    RECOVERY_RATE = "recovery_rate"
    VERIFICATION_ACCURACY = "verification_accuracy"
    KNOWLEDGE_REUSE = "knowledge_reuse"
    QUESTION_QUALITY = "question_quality"
    GOAL_PERSISTENCE = "goal_persistence"
    TOOL_SUCCESS = "tool_success"
    RESOURCE_COST = "resource_cost"

    # time breakdown components (Slice 9 rule 12)
    MODEL_LATENCY = "model_latency_s"
    TOOL_LATENCY = "tool_latency_s"
    RUNTIME_OVERHEAD = "runtime_overhead_s"
    TOTAL_TIME = "total_time_s"

    # verification detail (Slice 9 rule 14)
    CORRECT_VERIFICATION = "correct_verification"
    FALSE_VERIFICATION = "false_verification"
    MISSED_CONTRADICTION = "missed_contradiction"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    VERIFIED_RESULT = "verified_result"

    # failure recovery detail (Slice 9 rule 15)
    FAILURE_DETECTED = "failure_detected"
    RECOVERY_ATTEMPTED = "recovery_attempted"
    SUCCESSFUL_RECOVERY = "successful_recovery"
    REPEATED_FAILED_STRATEGY = "repeated_failed_strategy"
    TIME_TO_RECOVERY = "time_to_recovery_s"

    # model/tool usage (Slice 9 rules 13, 30)
    MODEL_CALLS = "model_calls"
    TOOL_CALLS = "tool_calls"
    MODEL_RETRIES = "model_retries"
    TOOL_RETRIES = "tool_retries"
    STRATEGY_RETRIES = "strategy_retries"
    RECOVERY_ATTEMPTS = "recovery_attempts"

    # question generation (Slice 9 rule 16)
    QUESTION_RELEVANCE = "question_relevance"
    QUESTION_INFO_GAIN = "question_info_gain"
    QUESTION_DECISION_IMPACT = "question_decision_impact"
    QUESTION_REDUNDANCY = "question_redundancy"
    QUESTION_ACTIONABILITY = "question_actionability"


class AblationSpec(str, Enum):
    """Which ZERION component to remove (rule 29). ``FULL`` is not an ablation."""

    VERIFICATION = "VERIFICATION"
    MEMORY = "MEMORY"
    GOALS = "GOALS"
    QUESTION_GENESIS = "QUESTION_GENESIS"
    CAPABILITIES = "CAPABILITIES"


@dataclass
class BenchmarkTask:
    """Slice 9 rule 3 — the full task schema."""

    task_id: str
    category: BenchmarkCategory
    description: str
    initial_state: Dict[str, Any] = field(default_factory=dict)
    available_information: List[str] = field(default_factory=list)
    available_tools: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    failure_criteria: List[str] = field(default_factory=list)
    difficulty: float = 0.0
    novelty: float = 0.0
    stakes: float = 0.0
    expected_behavior: str = ""
    timeout_s: float = 60.0
    resource_budget: Dict[str, Any] = field(default_factory=dict)
    evaluation_method: str = "deterministic_ground_truth"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("BenchmarkTask.task_id must not be empty")
        if not self.description.strip():
            raise ValueError("BenchmarkTask.description must not be empty")
        if not self.success_criteria:
            raise ValueError(
                f"task {self.task_id}: success_criteria must be objective and non-empty")
        if self.timeout_s <= 0:
            raise ValueError(f"task {self.task_id}: timeout_s must be > 0")
        # Normalize the category to the enum (builders may pass plain strings
        # that match enum member names).
        if isinstance(self.category, str):
            self.category = BenchmarkCategory(self.category)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "category": self.category.value,
            "description": self.description,
            "initial_state": dict(self.initial_state),
            "available_information": list(self.available_information),
            "available_tools": list(self.available_tools),
            "success_criteria": list(self.success_criteria),
            "failure_criteria": list(self.failure_criteria),
            "difficulty": self.difficulty,
            "novelty": self.novelty,
            "stakes": self.stakes,
            "expected_behavior": self.expected_behavior,
            "timeout_s": self.timeout_s,
            "resource_budget": dict(self.resource_budget),
            "evaluation_method": self.evaluation_method,
            "metadata": dict(self.metadata),
        }


@dataclass
class AgentAction:
    """One deterministic model decision inside a trial."""

    kind: str                 # "tool" | "answer"
    tool: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    claim: Dict[str, Any] = field(default_factory=dict)   # for "answer"
    source: str = "model"     # "model" | "capability" | "guidance"


@dataclass
class TrialRecord:
    """One executed trial — every metric here is measured, never invented."""

    trial_id: str
    run_id: str
    mode: BenchmarkMode
    task_id: str
    category: str
    seed: int
    success: bool
    outcome: str                    # "success" | "failed" | "timeout" | "error"
    answer: Optional[Dict[str, Any]] = None
    started_at: float = 0.0
    ended_at: float = 0.0
    total_time_s: float = 0.0
    model_time_s: float = 0.0
    tool_time_s: float = 0.0
    runtime_overhead_s: float = 0.0
    tool_call_log: List[Dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    tool_successes: int = 0
    tool_failures: int = 0
    tool_retries: int = 0
    model_retries: int = 0
    strategy_retries: int = 0
    recovery_attempts: int = 0
    successful_recovery: bool = False
    failure_detected: bool = False
    failure_taxonomy: Optional[str] = None
    failure_evidence: List[str] = field(default_factory=list)
    hallucination_detected: bool = False
    verification_required: bool = False
    verification_attempted: bool = False
    verified_result: bool = False
    correct_verification: int = 0
    false_verification: int = 0
    missed_contradiction: int = 0
    unsupported_claim: int = 0
    knowledge_reuse: bool = False
    capability_reuse: bool = False
    capability_name: str = ""
    question_generated: bool = False
    question_relevance: float = 0.0
    question_info_gain: float = 0.0
    question_decision_impact: float = 0.0
    question_redundancy: float = 0.0
    question_actionability: float = 0.0
    goal_created: bool = False
    goal_persistence: Optional[Dict[str, bool]] = None
    resource_cost: float = 0.0
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "run_id": self.run_id,
            "mode": self.mode.value,
            "task_id": self.task_id,
            "category": self.category,
            "seed": self.seed,
            "success": self.success,
            "outcome": self.outcome,
            "answer": self.answer,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_time_s": round(self.total_time_s, 6),
            "model_time_s": round(self.model_time_s, 6),
            "tool_time_s": round(self.tool_time_s, 6),
            "runtime_overhead_s": round(self.runtime_overhead_s, 6),
            "tool_call_log": self.tool_call_log,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "tool_successes": self.tool_successes,
            "tool_failures": self.tool_failures,
            "tool_retries": self.tool_retries,
            "model_retries": self.model_retries,
            "strategy_retries": self.strategy_retries,
            "recovery_attempts": self.recovery_attempts,
            "successful_recovery": self.successful_recovery,
            "failure_detected": self.failure_detected,
            "failure_taxonomy": self.failure_taxonomy,
            "failure_evidence": self.failure_evidence,
            "hallucination_detected": self.hallucination_detected,
            "verification_required": self.verification_required,
            "verification_attempted": self.verification_attempted,
            "verified_result": self.verified_result,
            "correct_verification": self.correct_verification,
            "false_verification": self.false_verification,
            "missed_contradiction": self.missed_contradiction,
            "unsupported_claim": self.unsupported_claim,
            "knowledge_reuse": self.knowledge_reuse,
            "capability_reuse": self.capability_reuse,
            "capability_name": self.capability_name,
            "question_generated": self.question_generated,
            "question_relevance": self.question_relevance,
            "question_info_gain": self.question_info_gain,
            "question_decision_impact": self.question_decision_impact,
            "question_redundancy": self.question_redundancy,
            "question_actionability": self.question_actionability,
            "goal_created": self.goal_created,
            "goal_persistence": self.goal_persistence,
            "resource_cost": self.resource_cost,
            "errors": self.errors,
            "metrics": dict(self.metrics),
        }


@dataclass
class RunManifest:
    """Reproducibility record for one benchmark run (rule 33)."""

    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    created_at: float = field(default_factory=time.time)
    seed: int = 0
    trials_per_task: int = 5
    modes: List[str] = field(default_factory=list)
    model_profile: Dict[str, Any] = field(default_factory=dict)
    provider: str = "deterministic_local"
    task_versions: Dict[str, str] = field(default_factory=dict)
    git_revision: str = ""
    runtime_config: Dict[str, Any] = field(default_factory=dict)
    resource_budget: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "seed": self.seed,
            "trials_per_task": self.trials_per_task,
            "modes": list(self.modes),
            "model_profile": dict(self.model_profile),
            "provider": self.provider,
            "task_versions": dict(self.task_versions),
            "git_revision": self.git_revision,
            "runtime_config": dict(self.runtime_config),
            "resource_budget": dict(self.resource_budget),
            "notes": self.notes,
        }
