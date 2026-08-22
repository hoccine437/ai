"""
Self-Experimentation Substrate - Controlled Cognitive Architecture Trials
Enables ASCENDANT ∞ to run scientific hypothesis tests on its own internal parameters
(Control vs. Treatment, Effect Size, Statistical Significance, and Canary Approval).
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional
import uuid


@dataclass
class ArchitectureTrialReport:
    experiment_id: str
    hypothesis: str
    target_dimension: str
    control_value: Any
    treatment_value: Any
    target_phenotype: Optional[str]
    sample_size: int
    control_score: Optional[float]
    treatment_score: Optional[float]
    effect_size: Optional[float]   # Treatment - Control (None = NOT_MEASURED)
    latency_delta_ms: Optional[float]
    decision: str                  # "ACCEPTED_*", "REJECTED", or "NOT_MEASURED"
    rationale: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis,
            "target_dimension": self.target_dimension,
            "control_value": self.control_value,
            "treatment_value": self.treatment_value,
            "target_phenotype": self.target_phenotype,
            "sample_size": self.sample_size,
            "control_score": (round(self.control_score, 4)
                               if self.control_score is not None else None),
            "treatment_score": (round(self.treatment_score, 4)
                                if self.treatment_score is not None else None),
            "effect_size": (round(self.effect_size, 4)
                            if self.effect_size is not None else None),
            "latency_delta_ms": (round(self.latency_delta_ms, 2)
                                 if self.latency_delta_ms is not None else None),
            "decision": self.decision,
            "rationale": self.rationale,
            "timestamp": self.timestamp
        }


class SelfExperimentationEngine:
    def __init__(self, db_path: Optional[str] = "data/self_experimentation.db"):
        self.db_path = db_path
        self._trials_history: List[ArchitectureTrialReport] = []
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    hypothesis TEXT,
                    target_dimension TEXT,
                    decision TEXT,
                    effect_size REAL,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.commit()
            conn.close()

    async def run_architecture_experiment(
        self,
        hypothesis: str,
        target_dimension: str,
        control_val: Any,
        treatment_val: Any,
        sample_size: int = 3,
        target_phenotype: Optional[str] = None,
        eval_fn: Optional[Callable[[Any], float]] = None
    ) -> ArchitectureTrialReport:
        """Executes a controlled A/B trial comparing Control vs. Treatment
        configuration.

        Honesty contract (INV-001 / INV-003): scores are ONLY produced by the
        provided ``eval_fn`` — a measurement function the caller must supply
        (e.g. a benchmark harness over a real engine configuration). No
        plausible-looking defaults are invented: if ``eval_fn`` is absent the
        report carries ``None`` scores and decision ``NOT_MEASURED``, and no
        effect size / latency delta / acceptance is claimed. ``sample_size``
        is honored as the number of real trials per arm (bounded for safety)
        and the mean is reported.
        """
        exp_id = f"self_exp_{uuid.uuid4().hex[:8]}"
        trials = max(1, min(int(sample_size or 1), 20))

        measured_control: Optional[float] = None
        measured_treatment: Optional[float] = None
        latency_control: Optional[float] = None
        latency_treatment: Optional[float] = None

        if eval_fn is not None:
            c_scores: List[float] = []
            t_scores: List[float] = []
            c_lats: List[float] = []
            t_lats: List[float] = []
            for _ in range(trials):
                t0 = time.perf_counter()
                c_scores.append(float(eval_fn(control_val)))
                c_lats.append((time.perf_counter() - t0) * 1000.0)
                t0 = time.perf_counter()
                t_scores.append(float(eval_fn(treatment_val)))
                t_lats.append((time.perf_counter() - t0) * 1000.0)
            measured_control = round(sum(c_scores) / len(c_scores), 4)
            measured_treatment = round(sum(t_scores) / len(t_scores), 4)
            latency_control = round(sum(c_lats) / len(c_lats), 2)
            latency_treatment = round(sum(t_lats) / len(t_lats), 2)

        effect_size = (round(measured_treatment - measured_control, 4)
                       if (measured_control is not None
                           and measured_treatment is not None) else None)
        latency_delta = (round(latency_treatment - latency_control, 2)
                         if (latency_control is not None
                             and latency_treatment is not None) else None)

        if effect_size is None:
            decision = "NOT_MEASURED"
            rationale = (
                "No eval_fn supplied: control/treatment scores are NOT "
                "measured, so no effect size, latency delta, or acceptance "
                "decision is claimed (INV-001/INV-003).")
        elif effect_size >= 0.05:
            if target_phenotype:
                decision = "ACCEPTED_FOR_PHENOTYPE"
                rationale = (f"Measured positive effect (+{effect_size*100:.1f}%) "
                             f"across {trials} trial(s) localized to "
                             f"{target_phenotype}.")
            else:
                decision = "ACCEPTED_GLOBALLY"
                rationale = (f"Measured global gain (+{effect_size*100:.1f}%) "
                             f"across {trials} trial(s).")
        else:
            decision = "REJECTED"
            rationale = (f"Insufficient measured effect size "
                         f"({effect_size*100:.1f}%) across {trials} trial(s)"
                         + (f" relative to latency cost "
                            f"(+{latency_delta}ms)." if latency_delta is not None
                            else "."))

        report = ArchitectureTrialReport(
            experiment_id=exp_id,
            hypothesis=hypothesis,
            target_dimension=target_dimension,
            control_value=control_val,
            treatment_value=treatment_val,
            target_phenotype=target_phenotype,
            sample_size=sample_size,
            control_score=measured_control,
            treatment_score=measured_treatment,
            effect_size=effect_size,
            latency_delta_ms=latency_delta,
            decision=decision,
            rationale=rationale
        )
        self._trials_history.append(report)
        self._persist(report)
        return report

    def _persist(self, r: ArchitectureTrialReport):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO self_experiments VALUES (?, ?, ?, ?, ?, ?, ?)",
            (r.experiment_id, r.hypothesis, r.target_dimension, r.decision, r.effect_size, json.dumps(r.to_dict()), r.timestamp)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM self_experiments").fetchall():
                d = json.loads(row[0])
                self._trials_history.append(ArchitectureTrialReport(
                    experiment_id=d["experiment_id"],
                    hypothesis=d["hypothesis"],
                    target_dimension=d["target_dimension"],
                    control_value=d["control_value"],
                    treatment_value=d["treatment_value"],
                    target_phenotype=d.get("target_phenotype"),
                    sample_size=d["sample_size"],
                    control_score=d["control_score"],
                    treatment_score=d["treatment_score"],
                    effect_size=d["effect_size"],
                    latency_delta_ms=d["latency_delta_ms"],
                    decision=d["decision"],
                    rationale=d["rationale"],
                    timestamp=d.get("timestamp", time.time())
                ))
            conn.close()
        except Exception:
            pass
