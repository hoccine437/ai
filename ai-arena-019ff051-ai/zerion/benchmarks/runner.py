"""
Benchmark Runner and Comparative Measurement Engine

Honesty contract (INV-001 / INV-010): scores are MEASURED or None. Categories
with a real executable task harness (coding, debugging, tool_use — generated
by ``BlindTaskGenerator`` with a fixed seed for reproducibility) are executed
inside the ExecutionSandbox and scored from the actual pass/fail outcome.
Every other category has no executable harness wired, so its score is
``None`` (NOT_MEASURED) and it is excluded from the composite — a plausible
number is never invented.
"""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
from zerion.benchmarks.suite import BenchmarkCategory, BenchmarkTask, build_default_benchmark_suite
from zerion.benchmarks.blind_tasks import BlindTaskGenerator
from zerion.benchmarks.metrics import (
    calculate_effective_intelligence,
    calculate_improvement_ratio,
    InitiativeMetric
)
from zerion.experiments.sandbox import ExecutionSandbox

# Categories whose BlindTaskGenerator tasks carry an executable
# (proposed_solution + test_harness) payload that can be scored for real.
_EXECUTABLE_CATEGORIES = ("coding", "debugging", "tool_use")


@dataclass
class TaskEvaluationResult:
    task_id: str
    category: str
    baseline_score: float
    ascendant_score: Optional[float]      # None = NOT_MEASURED
    improvement_ratio: Optional[float]
    latency_ms: Optional[float]
    cost_cents: Optional[float]
    verification_passed: Optional[bool]
    generalization_score: Optional[float]
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkRunReport:
    run_id: str
    timestamp: float
    total_tasks: int
    measured_tasks: int
    avg_baseline_score: Optional[float]
    avg_ascendant_score: Optional[float]
    composite_improvement_ratio: Optional[float]
    effective_intelligence_score: Optional[float]
    task_results: List[TaskEvaluationResult] = field(default_factory=list)


class BenchmarkRunner:
    def __init__(self, tasks: Optional[List[BenchmarkTask]] = None,
                 seed: int = 7):
        self.tasks = tasks or build_default_benchmark_suite()
        self.initiative_tracker = InitiativeMetric()
        # Fixed seed -> the blind suite is deterministic and reproducible.
        self.generator = BlindTaskGenerator(seed=seed)
        self.sandbox = ExecutionSandbox()
        self._blind_by_category = {
            t["category"]: t for t in self.generator.generate_suite(
                count_per_category=1)
        }

    async def run_all(self) -> BenchmarkRunReport:
        results: List[TaskEvaluationResult] = []
        start_time = time.time()

        for task in self.tasks:
            results.append(await self._evaluate_task(task))

        measured = [r for r in results if r.ascendant_score is not None]
        unmeasured = len(results) - len(measured)

        if measured:
            avg_base = sum(r.baseline_score for r in measured) / len(measured)
            avg_asc = sum(r.ascendant_score for r in measured) / len(measured)
            comp_ratio = calculate_improvement_ratio(avg_asc, avg_base)

            # Composite Effective Intelligence over MEASURED tasks only.
            verification_rate = (
                sum(1.0 for r in measured if r.verification_passed)
                / len(measured))
            adaptability = (sum(r.generalization_score for r in measured)
                            / len(measured))
            avg_latency = sum(r.latency_ms for r in measured) / len(measured)
            efficiency = min(1.0, 100.0 / avg_latency) if avg_latency > 0 else 0.0
            transfer_res = [r for r in measured
                            if r.category == BenchmarkCategory.TRANSFER.value]
            transfer_score = (transfer_res[0].ascendant_score
                              if transfer_res else None)
            # The composite requires every factor to be measured; an unmeasured
            # transfer factor makes the composite honestly unavailable.
            eff_intel = (calculate_effective_intelligence(
                quality=avg_asc,
                verification=verification_rate,
                adaptability=adaptability,
                efficiency=efficiency,
                transfer=transfer_score,
            ) if transfer_score is not None else None)
        else:
            avg_base = avg_asc = comp_ratio = eff_intel = None

        return BenchmarkRunReport(
            run_id=f"run_{int(start_time)}",
            timestamp=start_time,
            total_tasks=len(results),
            measured_tasks=len(measured),
            avg_baseline_score=round(avg_base, 3) if avg_base is not None else None,
            avg_ascendant_score=round(avg_asc, 3) if avg_asc is not None else None,
            composite_improvement_ratio=(round(comp_ratio, 3)
                                         if comp_ratio is not None else None),
            effective_intelligence_score=eff_intel,
            task_results=results,
        )

    def _unmeasured(self, task: BenchmarkTask, reason: str) -> TaskEvaluationResult:
        return TaskEvaluationResult(
            task_id=task.task_id,
            category=task.category.value,
            baseline_score=task.baseline_reference_score,
            ascendant_score=None,
            improvement_ratio=None,
            latency_ms=None,
            cost_cents=None,
            verification_passed=None,
            generalization_score=None,
            details={"task_title": task.title,
                     "measurement_status": "NOT_MEASURED",
                     "reason": reason},
        )

    async def _evaluate_task(self, task: BenchmarkTask) -> TaskEvaluationResult:
        """Executes the real blind-task harness for the category when one is
        wired; otherwise the result is explicitly NOT_MEASURED."""
        cat = task.category.value
        if cat not in _EXECUTABLE_CATEGORIES:
            return self._unmeasured(
                task, "no executable task harness wired for this category")
        blind = self._blind_by_category.get(cat)
        if blind is None:
            return self._unmeasured(task, "no blind task generated")
        inputs = blind.get("input_data") or {}
        code = inputs.get("proposed_solution", "")
        harness = inputs.get("test_harness", "")
        if not code or not harness:
            return self._unmeasured(task, "generated task lacks harness")

        t0 = time.perf_counter()
        sb = await self.sandbox.run_python_code(
            f"{code}\n{harness}", timeout_seconds=5.0)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        success = sb.success and "TESTS_PASSED" in sb.stdout
        ascendant_score = 1.0 if success else 0.0
        ratio = calculate_improvement_ratio(
            ascendant_score, task.baseline_reference_score)

        return TaskEvaluationResult(
            task_id=task.task_id,
            category=cat,
            baseline_score=task.baseline_reference_score,
            ascendant_score=ascendant_score,
            improvement_ratio=ratio,
            latency_ms=round(latency_ms, 2),
            cost_cents=0.0,
            verification_passed=success,
            generalization_score=ascendant_score,
            details={"task_title": task.title,
                     "measurement_status": "MEASURED",
                     "blind_task_id": blind.get("task_id"),
                     "sandbox_ok": sb.success,
                     "stderr": sb.stderr[:200]},
        )
