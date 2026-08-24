"""
14-Category Benchmark Suite Definitions
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class BenchmarkCategory(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    PLANNING = "planning"
    LONG_HORIZON = "long_horizon"
    TOOL_USE = "tool_use"
    VERIFICATION = "verification"
    GENERALIZATION = "generalization"
    SELF_CORRECTION = "self_correction"
    PROBLEM_DISCOVERY = "problem_discovery"
    QUESTION_GENERATION = "question_generation"
    LEARNING = "learning"
    TRANSFER = "transfer"


@dataclass
class BenchmarkTask:
    task_id: str
    category: BenchmarkCategory
    title: str
    description: str
    input_data: Dict[str, Any]
    expected_output_condition: Dict[str, Any]
    baseline_reference_score: float = 0.5


def build_default_benchmark_suite() -> List[BenchmarkTask]:
    tasks = [
        BenchmarkTask(
            task_id="BM-01-REASON",
            category=BenchmarkCategory.REASONING,
            title="Multi-Step Causal Deduction",
            description="Deduce root cause across 4 causal dependencies",
            input_data={"chain": ["A -> B", "B -> C", "C -> D", "Observed: D failed, B intact"]},
            expected_output_condition={"root_cause": "C"},
            baseline_reference_score=0.45
        ),
        BenchmarkTask(
            task_id="BM-02-CODE",
            category=BenchmarkCategory.CODING,
            title="Deterministic Algorithm Synthesis",
            description="Generate pure function with input validation",
            input_data={"spec": "filter_and_aggregate"},
            expected_output_condition={"valid_ast": True},
            baseline_reference_score=0.50
        ),
        BenchmarkTask(
            task_id="BM-03-DEBUG",
            category=BenchmarkCategory.DEBUGGING,
            title="Isolation of Off-By-One Anomaly",
            description="Diagnose boundary condition fault in sandbox",
            input_data={"fault": "IndexError at len(items)"},
            expected_output_condition={"fixed": True},
            baseline_reference_score=0.40
        ),
        BenchmarkTask(
            task_id="BM-04-RESEARCH",
            category=BenchmarkCategory.RESEARCH,
            title="Epistemic Void Mapping",
            description="Identify unobserved nodes in world graph",
            input_data={"node_count": 10, "unknown_attrs": 3},
            expected_output_condition={"identified_unknowns": 3},
            baseline_reference_score=0.35
        ),
        BenchmarkTask(
            task_id="BM-05-PLAN",
            category=BenchmarkCategory.PLANNING,
            title="DAG Task Decomposition",
            description="Construct acyclic dependency graph for 5 steps",
            input_data={"steps": 5, "dependencies": 3},
            expected_output_condition={"is_dag": True},
            baseline_reference_score=0.55
        ),
        BenchmarkTask(
            task_id="BM-06-LONG_HORIZON",
            category=BenchmarkCategory.LONG_HORIZON,
            title="Crash Resilient Mission Recovery",
            description="Resume interrupted mission from checkpoint without data loss",
            input_data={"interrupted_step": 3, "total_steps": 5},
            expected_output_condition={"recovered": True, "completed": True},
            baseline_reference_score=0.30
        ),
        BenchmarkTask(
            task_id="BM-07-TOOL",
            category=BenchmarkCategory.TOOL_USE,
            title="Typed Sandboxed Tool Dispatch",
            description="Execute code in sandbox and verify return code",
            input_data={"command": "print(42)"},
            expected_output_condition={"stdout": "42"},
            baseline_reference_score=0.60
        ),
        BenchmarkTask(
            task_id="BM-08-VERIFY",
            category=BenchmarkCategory.VERIFICATION,
            title="Adversarial Invariant Defense",
            description="Reject conclusions violating core invariants",
            input_data={"claim": "Unchecked execution is safe", "contra": "Security violation"},
            expected_output_condition={"rejected": True},
            baseline_reference_score=0.40
        ),
        BenchmarkTask(
            task_id="BM-09-GEN",
            category=BenchmarkCategory.GENERALIZATION,
            title="Abstract Rule Extraction",
            description="Generalize 3 episodic experiences into 1 procedural rule",
            input_data={"episodes": 3},
            expected_output_condition={"rules_distilled": 1},
            baseline_reference_score=0.30
        ),
        BenchmarkTask(
            task_id="BM-10-SELF_CORRECT",
            category=BenchmarkCategory.SELF_CORRECTION,
            title="Contradiction-Driven Belief Update",
            description="Overturn prior assumption when confronted with empirical evidence",
            input_data={"prior": "ASSUMED True", "evidence": "OBSERVED False"},
            expected_output_condition={"updated_status": "OBSERVED", "value": False},
            baseline_reference_score=0.35
        ),
        BenchmarkTask(
            task_id="BM-11-DISCOVERY",
            category=BenchmarkCategory.PROBLEM_DISCOVERY,
            title="Unprompted Pressure Anomaly Genesis",
            description="Generate ProblemCandidate from passive drift signal",
            input_data={"signal_magnitude": 0.85, "signal_type": "DRIFT"},
            expected_output_condition={"candidate_created": True},
            baseline_reference_score=0.20
        ),
        BenchmarkTask(
            task_id="BM-12-QUESTION",
            category=BenchmarkCategory.QUESTION_GENERATION,
            title="Expected Information Gain Question Scored",
            description="Generate first-class Question scored by scientific formula",
            input_data={"impact": 0.9, "uncertainty": 0.8, "gain": 0.8, "relevance": 0.9, "cost": 1.0},
            expected_output_condition={"priority_gt": 5.0},
            baseline_reference_score=0.25
        ),
        BenchmarkTask(
            task_id="BM-13-LEARN",
            category=BenchmarkCategory.LEARNING,
            title="Dynamic Capability Birth",
            description="Synthesize, test, benchmark, and validate new capability",
            input_data={"gap": "tool_gap_custom"},
            expected_output_condition={"validated": True},
            baseline_reference_score=0.20
        ),
        BenchmarkTask(
            task_id="BM-14-TRANSFER",
            category=BenchmarkCategory.TRANSFER,
            title="Cross-Domain Strategy Generalization",
            description="Apply debugging strategy to database and network domains",
            input_data={"source": "python", "targets": ["database", "network"]},
            expected_output_condition={"transfer_efficiency_gt": 0.80},
            baseline_reference_score=0.25
        ),
    ]
    return tasks
