"""
ZERION — Slice 9: ZERION_COGNITIVE_BENCHMARK.

A real, adversarial, evidence-required comparison of the Cognitive Runtime
(ZERION) against a plain model + tool-calling loop (BASELINE) on the same
deterministic model, the same tasks, the same tools and the same seeds.

Design rules honored here:
- The benchmark decides the result. No hard-coded conclusions, no
  pre-determined "5x" claims. Improvement ratios are metric/task-class
  specific or not reported.
- The deterministic model is IDENTICAL for BASELINE and ZERION. The only
  difference is the Cognitive Runtime around it (goals, questions, evidence
  verification, failure learning, experience, capabilities).
- Nothing is fabricated: every metric is measured from the actual run;
  UNKNOWN / NOT_MEASURED is reported when a metric cannot be measured.
- Results are immutable per run and integrity-checked; benchmark
  infrastructure is protected from self-modification (Slice 9 rule 36).
"""

from zerion.cognitive_os.benchmark.types import (
    AblationSpec,
    BenchmarkCategory,
    BenchmarkMode,
    BenchmarkTask,
    FailureTaxonomy,
    MetricKey,
    RunManifest,
    TrialRecord,
)
from zerion.cognitive_os.benchmark.metrics import (
    EffectiveTaskPerformance,
    Statistics,
    improve,
    summarize,
)
from zerion.cognitive_os.benchmark.runner import (
    CognitiveBenchmark,
    build_default_task_registry,
    run_end_to_end_benchmark,
)

__all__ = [
    "AblationSpec",
    "BenchmarkCategory",
    "BenchmarkMode",
    "BenchmarkTask",
    "CognitiveBenchmark",
    "EffectiveTaskPerformance",
    "FailureTaxonomy",
    "MetricKey",
    "RunManifest",
    "Statistics",
    "TrialRecord",
    "build_default_task_registry",
    "improve",
    "run_end_to_end_benchmark",
    "summarize",
]
