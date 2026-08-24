"""
Adaptive Compute Scaling and Budget Resolution
"""

from dataclasses import dataclass
from enum import Enum


class ComputeMode(str, Enum):
    REFLEX = "REFLEX"              # ~10ms, heuristic/lookup table, minimal compute
    FAST = "FAST"                  # ~100ms, single lightweight pass
    NORMAL = "NORMAL"              # ~500ms, standard compilation & verification
    DEEP = "DEEP"                  # ~2000ms, multi-path reasoning + attack
    EXTREME = "EXTREME"            # ~5000ms+, extensive simulation & falsification
    EXPERIMENTAL = "EXPERIMENTAL"  # sandbox prototyping + benchmark loop


@dataclass
class ComputeProfile:
    mode: ComputeMode
    max_reasoning_paths: int
    enable_adversarial_critique: bool
    enable_sandbox_experiment: bool
    timeout_seconds: float
    max_cost_cents: float


COMPUTE_PROFILES = {
    ComputeMode.REFLEX: ComputeProfile(
        mode=ComputeMode.REFLEX,
        max_reasoning_paths=1,
        enable_adversarial_critique=False,
        enable_sandbox_experiment=False,
        timeout_seconds=0.5,
        max_cost_cents=0.01
    ),
    ComputeMode.FAST: ComputeProfile(
        mode=ComputeMode.FAST,
        max_reasoning_paths=1,
        enable_adversarial_critique=False,
        enable_sandbox_experiment=False,
        timeout_seconds=2.0,
        max_cost_cents=0.05
    ),
    ComputeMode.NORMAL: ComputeProfile(
        mode=ComputeMode.NORMAL,
        max_reasoning_paths=2,
        enable_adversarial_critique=True,
        enable_sandbox_experiment=False,
        timeout_seconds=5.0,
        max_cost_cents=0.20
    ),
    ComputeMode.DEEP: ComputeProfile(
        mode=ComputeMode.DEEP,
        max_reasoning_paths=3,
        enable_adversarial_critique=True,
        enable_sandbox_experiment=True,
        timeout_seconds=15.0,
        max_cost_cents=0.80
    ),
    ComputeMode.EXTREME: ComputeProfile(
        mode=ComputeMode.EXTREME,
        max_reasoning_paths=5,
        enable_adversarial_critique=True,
        enable_sandbox_experiment=True,
        timeout_seconds=30.0,
        max_cost_cents=2.00
    ),
    ComputeMode.EXPERIMENTAL: ComputeProfile(
        mode=ComputeMode.EXPERIMENTAL,
        max_reasoning_paths=5,
        enable_adversarial_critique=True,
        enable_sandbox_experiment=True,
        timeout_seconds=60.0,
        max_cost_cents=5.00
    ),
}


def resolve_compute_profile(
    urgency: float,
    uncertainty: float,
    impact: float,
    is_offline: bool = False
) -> ComputeProfile:
    """
    Decides compute tier based on decision risk matrix.
    """
    if is_offline:
        return COMPUTE_PROFILES[ComputeMode.FAST]

    risk_score = (uncertainty * 0.4) + (impact * 0.6)
    if risk_score < 0.25 and urgency > 0.8:
        return COMPUTE_PROFILES[ComputeMode.REFLEX]
    elif risk_score < 0.45:
        return COMPUTE_PROFILES[ComputeMode.FAST]
    elif risk_score < 0.70:
        return COMPUTE_PROFILES[ComputeMode.NORMAL]
    elif risk_score < 0.88:
        return COMPUTE_PROFILES[ComputeMode.DEEP]
    elif uncertainty > 0.85:
        return COMPUTE_PROFILES[ComputeMode.EXPERIMENTAL]
    else:
        return COMPUTE_PROFILES[ComputeMode.EXTREME]
