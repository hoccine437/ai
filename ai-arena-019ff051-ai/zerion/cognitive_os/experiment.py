"""
Slice 3 — Experiment.

A controlled test. Before execution an experiment must define: the hypothesis(es)
it tests, its predictions, expected evidence, success conditions, failure
conditions and safety constraints. The hypothesis is never rewritten after the
result is seen to make it appear correct.

Supported experiment types:
    CODE_TEST, SYSTEM_OBSERVATION, WEB_VERIFICATION, TOOL_EXECUTION,
    SIMULATION, DATA_COMPARISON

Mode distinction (mandatory): an experiment's result carries a mode —
OBSERVED (real-world/tool/system), SIMULATED (simulation only), TEST (mock).
SIMULATED and TEST evidence can inform planning but can never be recorded as
real-world confirmation.
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


class ExperimentType(str, Enum):
    CODE_TEST = "CODE_TEST"
    SYSTEM_OBSERVATION = "SYSTEM_OBSERVATION"
    WEB_VERIFICATION = "WEB_VERIFICATION"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    SIMULATION = "SIMULATION"
    DATA_COMPARISON = "DATA_COMPARISON"


class ExperimentLifecycle(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class ExperimentValidationError(ValueError):
    """Raised for structurally invalid experiments (missing predictions, etc.)."""


class ExperimentTransitionError(RuntimeError):
    """Raised for illegal lifecycle transitions (e.g. running a BLOCKED experiment)."""


class ExperimentStoreIntegrityError(RuntimeError):
    """Raised when persisted experiment data is corrupt and strict loading is enabled."""


_MAX_TEXT_LENGTH = 4000
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Any) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def _clean_str_list(values: List[Any]) -> List[str]:
    return [_clean_text(v) for v in (values or []) if _clean_text(v)]


def _clamp01(value: Any, name: str) -> float:
    f = float(value)
    if not (0.0 <= f <= 1.0):
        raise ExperimentValidationError(f"Experiment {name} must be in [0.0, 1.0], got {f!r}")
    return f


def _clamp_non_negative(value: Any, name: str) -> float:
    f = float(value)
    if f < 0.0:
        raise ExperimentValidationError(f"Experiment {name} must be >= 0.0, got {f!r}")
    return f


@dataclass
class Experiment:
    experiment_id: str = field(default_factory=lambda: f"exp_{uuid.uuid4().hex[:10]}")
    question_id: str = ""
    hypothesis_ids: List[str] = field(default_factory=list)
    objective: str = ""
    type: ExperimentType = ExperimentType.SIMULATION
    inputs: Dict[str, Any] = field(default_factory=dict)
    procedure: List[str] = field(default_factory=list)
    predictions: List[str] = field(default_factory=list)
    expected_evidence: List[str] = field(default_factory=list)
    success_conditions: List[str] = field(default_factory=list)
    failure_conditions: List[str] = field(default_factory=list)
    safety_constraints: List[str] = field(default_factory=list)
    actual_observation: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    status: ExperimentLifecycle = ExperimentLifecycle.PROPOSED
    result: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    risk: float = 0.1            # [0.0, 1.0]
    cost: float = 1.0            # >= 0.0 abstract compute units
    evidence_ids: List[str] = field(default_factory=list)
    mode: str = "SIMULATED"      # result mode: OBSERVED / SIMULATED / TEST
    errors: List[str] = field(default_factory=list)
    rollback_info: str = ""
    attempts: int = 0
    max_attempts: int = 2
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.objective = _clean_text(self.objective)
        if not self.objective:
            raise ExperimentValidationError("Experiment objective must not be empty")
        if isinstance(self.type, str):
            self.type = ExperimentType(self.type)
        if isinstance(self.status, str):
            self.status = ExperimentLifecycle(self.status)
        self.hypothesis_ids = _clean_str_list(self.hypothesis_ids)
        self.procedure = _clean_str_list(self.procedure)
        self.predictions = _clean_str_list(self.predictions)
        self.expected_evidence = _clean_str_list(self.expected_evidence)
        self.success_conditions = _clean_str_list(self.success_conditions)
        self.failure_conditions = _clean_str_list(self.failure_conditions)
        self.safety_constraints = _clean_str_list(self.safety_constraints)
        if not self.hypothesis_ids:
            raise ExperimentValidationError("Experiment must reference at least one hypothesis")
        if not self.predictions:
            raise ExperimentValidationError(
                "Experiment must define predictions before execution (never after the result)")
        if not self.success_conditions:
            raise ExperimentValidationError("Experiment must define success conditions up front")
        if not self.failure_conditions:
            raise ExperimentValidationError("Experiment must define failure conditions up front")
        self.risk = _clamp01(self.risk, "risk")
        self.cost = _clamp_non_negative(self.cost, "cost")
        self.confidence = _clamp01(self.confidence, "confidence")
        self.mode = _clean_text(self.mode)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "question_id": self.question_id,
            "hypothesis_ids": self.hypothesis_ids,
            "objective": self.objective,
            "type": self.type.value,
            "inputs": self.inputs,
            "procedure": self.procedure,
            "predictions": self.predictions,
            "expected_evidence": self.expected_evidence,
            "success_conditions": self.success_conditions,
            "failure_conditions": self.failure_conditions,
            "safety_constraints": self.safety_constraints,
            "actual_observation": self.actual_observation,
            "environment": self.environment,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status.value,
            "result": self.result,
            "confidence": round(self.confidence, 6),
            "risk": round(self.risk, 6),
            "cost": round(self.cost, 6),
            "evidence_ids": self.evidence_ids,
            "mode": self.mode,
            "errors": self.errors,
            "rollback_info": self.rollback_info,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experiment":
        etype = data.get("type", ExperimentType.SIMULATION.value)
        try:
            etype = ExperimentType(etype)
        except ValueError:
            etype = ExperimentType.SIMULATION
        status = data.get("status", ExperimentLifecycle.PROPOSED.value)
        try:
            status = ExperimentLifecycle(status)
        except ValueError:
            status = ExperimentLifecycle.PROPOSED
        return cls(
            experiment_id=data.get("experiment_id", f"exp_{uuid.uuid4().hex[:10]}"),
            question_id=data.get("question_id", ""),
            hypothesis_ids=list(data.get("hypothesis_ids", [])),
            objective=data.get("objective", ""),
            type=etype,
            inputs=dict(data.get("inputs", {})),
            procedure=list(data.get("procedure", [])),
            predictions=list(data.get("predictions", [])),
            expected_evidence=list(data.get("expected_evidence", [])),
            success_conditions=list(data.get("success_conditions", [])),
            failure_conditions=list(data.get("failure_conditions", [])),
            safety_constraints=list(data.get("safety_constraints", [])),
            actual_observation=dict(data.get("actual_observation", {})),
            environment=dict(data.get("environment", {})),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            status=status,
            result=dict(data.get("result", {})),
            confidence=float(data.get("confidence", 0.0)),
            risk=float(data.get("risk", 0.1)),
            cost=float(data.get("cost", 1.0)),
            evidence_ids=list(data.get("evidence_ids", [])),
            mode=data.get("mode", "SIMULATED"),
            errors=list(data.get("errors", [])),
            rollback_info=data.get("rollback_info", ""),
            attempts=int(data.get("attempts", 0)),
            max_attempts=int(data.get("max_attempts", 2)),
            updated_at=float(data.get("updated_at", time.time())),
        )


def transition(experiment: Experiment, to: ExperimentLifecycle,
               max_attempts: Optional[int] = None) -> Experiment:
    """Validated lifecycle transitions. Raises ExperimentTransitionError for
    illegal moves (e.g. running a BLOCKED experiment, retrying past max_attempts)."""
    current = experiment.status
    valid: Dict[ExperimentLifecycle, set] = {
        ExperimentLifecycle.PROPOSED: {ExperimentLifecycle.APPROVED,
                                       ExperimentLifecycle.BLOCKED,
                                       ExperimentLifecycle.CANCELLED},
        ExperimentLifecycle.APPROVED: {ExperimentLifecycle.RUNNING,
                                       ExperimentLifecycle.CANCELLED},
        ExperimentLifecycle.RUNNING: {ExperimentLifecycle.COMPLETED,
                                      ExperimentLifecycle.FAILED},
        ExperimentLifecycle.FAILED: {ExperimentLifecycle.APPROVED},  # retry, bounded
        ExperimentLifecycle.BLOCKED: set(),
        ExperimentLifecycle.COMPLETED: set(),
        ExperimentLifecycle.CANCELLED: set(),
    }
    if to not in valid[current]:
        raise ExperimentTransitionError(
            f"Illegal experiment transition {current.value} -> {to.value} "
            f"({experiment.experiment_id})")
    if to == ExperimentLifecycle.APPROVED and current == ExperimentLifecycle.FAILED:
        cap = max_attempts if max_attempts is not None else experiment.max_attempts
        if experiment.attempts >= cap:
            raise ExperimentTransitionError(
                f"Experiment {experiment.experiment_id} already failed "
                f"{experiment.attempts}/{cap} times; no further retries")
    experiment.status = to
    experiment.updated_at = time.time()
    return experiment


class ExperimentStore:
    """SQLite WAL-backed store for Experiments (corruption-safe, same pattern
    as the Slice 1/2 stores). DB ``experiments.db`` — no legacy collision."""

    def __init__(self, db_path: Optional[str] = "data/experiments.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._experiments: Dict[str, Experiment] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    question_id TEXT,
                    payload TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    status TEXT,
                    updated_at REAL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiments_question ON experiments (question_id)"
            )
            conn.commit()
            conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, experiment: Experiment) -> Experiment:
        self._experiments[experiment.experiment_id] = experiment
        if not self.db_path:
            return experiment
        payload = json.dumps(experiment.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?, ?, ?, ?, ?, ?)",
                (experiment.experiment_id, experiment.question_id, payload,
                 self._checksum(payload), experiment.status.value, experiment.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return experiment

    def get(self, experiment_id: str) -> Optional[Experiment]:
        return self._experiments.get(experiment_id)

    def list_by_question(self, question_id: str) -> List[Experiment]:
        return sorted(
            [e for e in self._experiments.values() if e.question_id == question_id],
            key=lambda e: e.updated_at,
        )

    def list(self, status: Optional[ExperimentLifecycle] = None) -> List[Experiment]:
        exps = list(self._experiments.values())
        if status is not None:
            exps = [e for e in exps if e.status == status]
        return sorted(exps, key=lambda e: e.updated_at)

    def list_unresolved(self) -> List[Experiment]:
        """PROPOSED / APPROVED / RUNNING / FAILED experiments are unresolved:
        they must never be silently lost on restart."""
        live = {ExperimentLifecycle.PROPOSED, ExperimentLifecycle.APPROVED,
                ExperimentLifecycle.RUNNING, ExperimentLifecycle.FAILED}
        return sorted(
            [e for e in self._experiments.values() if e.status in live],
            key=lambda e: e.updated_at,
        )

    def count(self) -> int:
        return len(self._experiments)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM experiments").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise ExperimentStoreIntegrityError(
                    f"Failed to load persisted experiments from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise ExperimentStoreIntegrityError(
                        "Experiment row checksum mismatch (corrupt or partial write)")
                data = json.loads(payload)
                exp = Experiment.from_dict(data)
                self._experiments[exp.experiment_id] = exp
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise ExperimentStoreIntegrityError(
                        f"Failed to load persisted experiments from {self.db_path}: {e}"
                    ) from e
