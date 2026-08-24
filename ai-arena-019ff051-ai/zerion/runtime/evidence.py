"""
Runtime Evidence Contract

A single, shared representation for "how do we know this number/status is true".
Introduced to stop individual reporting modules (maturity, scoreboard, providers,
CLI diagnostics) from inventing their own ad-hoc truth model or silently treating
configured defaults as observed runtime measurements.

This is intentionally small. It is not a new subsystem, event bus, or persistence
layer -- it is a shared vocabulary and a couple of dataclasses used by the existing
reporting paths.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional


class MeasurementStatus(str, Enum):
    """Provenance classification for any reported metric or claim."""
    OBSERVED = "OBSERVED"
    CALCULATED_FROM_OBSERVED_DATA = "CALCULATED_FROM_OBSERVED_DATA"
    SIMULATED = "SIMULATED"
    MODEL_ESTIMATE = "MODEL_ESTIMATE"
    CONFIGURED_DEFAULT = "CONFIGURED_DEFAULT"
    UNAVAILABLE = "UNAVAILABLE"


class ExecutionMode(str, Enum):
    """What actually produced a piece of output."""
    REAL_MODEL_RESPONSE = "REAL_MODEL_RESPONSE"
    FALLBACK_RESPONSE = "FALLBACK_RESPONSE"
    SIMULATION = "SIMULATION"
    MOCK = "MOCK"
    ERROR = "ERROR"


@dataclass
class Metric:
    """One reported number/value with explicit provenance."""
    name: str
    value: Optional[float]
    status: MeasurementStatus
    sample_count: int = 0
    evidence: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.name,
            "value": self.value,
            "status": self.status.value,
            "sample_count": self.sample_count,
            "evidence": list(self.evidence),
            "timestamp": self.timestamp,
        }

    @classmethod
    def unavailable(cls, name: str, reason: str = "not yet measured") -> "Metric":
        return cls(name=name, value=None, status=MeasurementStatus.UNAVAILABLE,
                    sample_count=0, evidence=[reason])


@dataclass
class RuntimeEvidence:
    """
    Snapshot of measured runtime state, collected from the live engine.
    This is the ONLY object that should be threaded into maturity/scoreboard
    evaluation for anything claiming to reflect "current system state".
    Nothing in here may be a hard-coded default -- every field is read from
    a live counter/collection at collection time.
    """
    episodes_count: int
    procedural_rules_count: int
    born_capabilities_count: int
    total_capabilities_count: int
    synthesized_strategies_count: int
    active_objectives_count: int
    flywheel_cycles: int
    brier_score: Optional[float]
    learning_acceleration: Optional[float]
    has_native_caps: bool
    has_adaptive_phenotypes: bool
    has_pressure_field: bool
    collected_at: float = field(default_factory=time.time)
    source: str = "engine_live_state"
    brier_samples: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episodes_count": self.episodes_count,
            "procedural_rules_count": self.procedural_rules_count,
            "born_capabilities_count": self.born_capabilities_count,
            "total_capabilities_count": self.total_capabilities_count,
            "synthesized_strategies_count": self.synthesized_strategies_count,
            "active_objectives_count": self.active_objectives_count,
            "flywheel_cycles": self.flywheel_cycles,
            "brier_score": self.brier_score,
            "learning_acceleration": self.learning_acceleration,
            "has_native_caps": self.has_native_caps,
            "has_adaptive_phenotypes": self.has_adaptive_phenotypes,
            "has_pressure_field": self.has_pressure_field,
            "collected_at": self.collected_at,
            "source": self.source,
        }


def collect_runtime_evidence(engine: Any) -> RuntimeEvidence:
    """
    Reads live state off a running AscendantEngine. This is the single
    authoritative place that turns "the engine object" into "measured facts",
    so every reporting surface (CLI --status, UI server, scoreboard, maturity)
    can share one source instead of each inventing/defaulting its own.
    """
    try:
        brier = engine.self_model.calibrator.calculate_brier_score()
        brier_samples = len(getattr(engine.self_model.calibrator, "_samples", []))
    except Exception:
        brier = None
        brier_samples = 0

    try:
        acc_ratio = engine.learning_to_learn.calculate_learning_acceleration()
    except Exception:
        acc_ratio = None

    return RuntimeEvidence(
        episodes_count=len(engine.memory._episodes),
        procedural_rules_count=len(engine.memory._procedural_rules),
        born_capabilities_count=len(engine.capability_registry.list_born_capabilities()),
        total_capabilities_count=len(engine.self_model._capabilities),
        synthesized_strategies_count=len(engine.strategy_registry.list_strategies()),
        active_objectives_count=len(engine.continuous_objectives.list_active_objectives()),
        flywheel_cycles=engine._cycle_count,
        brier_score=brier,
        brier_samples=brier_samples,
        learning_acceleration=acc_ratio,
        has_native_caps=len(engine.self_model._capabilities) > 0,
        has_adaptive_phenotypes=True,   # structurally always constructed at engine.start(); not a measured count
        has_pressure_field=True,        # same: object existence, not an empirical claim
    )
