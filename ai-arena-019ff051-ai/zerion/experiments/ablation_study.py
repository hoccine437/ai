"""
Phase 5: Systematic Ablation Matrix (SIMULATED REFERENCE STUDY)

This runner does NOT execute 8 real engine configurations. It emits a
reference table of plausible ablation priors so the reporting/pipeline shape
can be exercised. Every result is explicitly labeled SIMULATED with
measurement_status=NOT_MEASURED — the scores are illustrative priors, never
presented as measured performance. A real empirical ablation is a future
instrumentation task, not this module.
"""

import asyncio
from dataclasses import dataclass, field
import os
import shutil
import tempfile
from typing import Any, Dict, List
from zerion.benchmarks.blind_tasks import BlindTaskGenerator
from zerion.experiments.sandbox import ExecutionSandbox


@dataclass
class AblationResult:
    config_name: str
    ablated_subsystem: str
    overall_score: float
    degradation_percent: float
    criticality: str  # "CRITICAL", "HIGH", "MODERATE", "NON_CONTRIBUTING"
    category_scores: Dict[str, float] = field(default_factory=dict)
    # Honest provenance: SIMULATED means these numbers were never measured.
    measurement_status: str = "SIMULATED"


@dataclass
class AblationStudyReport:
    full_ascendant_baseline: float
    ablation_results: List[AblationResult] = field(default_factory=list)
    non_contributing_components: List[str] = field(default_factory=list)
    most_critical_component: str = ""


class AblationStudyRunner:
    def __init__(self):
        self.generator = BlindTaskGenerator(seed=101)
        self.sandbox = ExecutionSandbox()

    async def run_ablation_matrix(self) -> AblationStudyReport:
        tasks = self.generator.generate_suite(count_per_category=2)

        # Baseline: Full ASCENDANT
        full_score = 0.942

        # Configurations to evaluate
        configs = [
            ("Full_ASCENDANT", "None (Baseline)", 0.942),
            ("Ablation_1", "- Episodic Memory", 0.815),
            ("Ablation_2", "- Procedural Memory (No Distillation)", 0.740),
            ("Ablation_3", "- Question Genesis (Reactive Only)", 0.765),
            ("Ablation_4", "- World Model (No Epistemic Graph)", 0.690),
            ("Ablation_5", "- Self Model (No Calibration/Introspection)", 0.835),
            ("Ablation_6", "- Developmental Loop (No Pressure Field)", 0.710),
            ("Ablation_7", "- Capability Birth (No Code Synthesis)", 0.780),
        ]

        ablation_results = []
        non_contributing = []

        # NOTE: `tasks` is generated but no real engine configuration is run
        # against it — see module docstring. All numbers below are SIMULATED
        # reference priors and carry measurement_status="SIMULATED".
        for name, ablated, score in configs:
            deg = round(((full_score - score) / full_score) * 100.0, 2) if name != "Full_ASCENDANT" else 0.0

            if deg > 20.0:
                crit = "CRITICAL"
            elif deg > 12.0:
                crit = "HIGH"
            elif deg > 5.0:
                crit = "MODERATE"
            else:
                crit = "NON_CONTRIBUTING" if name != "Full_ASCENDANT" else "BASELINE"
                if name != "Full_ASCENDANT":
                    non_contributing.append(ablated)

            ablation_results.append(AblationResult(
                config_name=name,
                ablated_subsystem=ablated,
                overall_score=score,
                degradation_percent=deg,
                criticality=crit,
                category_scores={"reasoning": score * 0.98, "coding": score * 0.95, "learning": score * 0.92}
            ))

        most_crit = max(ablation_results[1:], key=lambda x: x.degradation_percent).ablated_subsystem

        return AblationStudyReport(
            full_ascendant_baseline=full_score,
            ablation_results=ablation_results,
            non_contributing_components=non_contributing,
            most_critical_component=most_crit
        )
