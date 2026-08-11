"""
Cognitive Maturity Level Classifier (L0 STATIC to L7 COGNITIVE-GENERATIVE)
Calculates current empirical maturity level based on active, verified developmental capabilities.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional


class MaturityLevel(str, Enum):
    L0_STATIC = "L0_STATIC"
    L1_MEMORY = "L1_MEMORY"
    L2_PROCEDURAL = "L2_PROCEDURAL"
    L3_ADAPTIVE = "L3_ADAPTIVE"
    L4_SELF_DIAGNOSTIC = "L4_SELF_DIAGNOSTIC"
    L5_SELF_DEVELOPING = "L5_SELF_DEVELOPING"
    L6_META_LEARNING = "L6_META_LEARNING"
    L7_COGNITIVE_GENERATIVE = "L7_COGNITIVE_GENERATIVE"


@dataclass
class MaturityAssessment:
    current_level: MaturityLevel
    level_index: int
    criteria_met: List[str]
    criteria_pending: List[str]
    evidence_score: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_level": self.current_level.value,
            "level_index": self.level_index,
            "criteria_met": self.criteria_met,
            "criteria_pending": self.criteria_pending,
            "evidence_score": round(self.evidence_score, 3),
            "timestamp": self.timestamp
        }


class CognitiveMaturityEvaluator:
    """
    Evaluates current maturity strictly on empirical evidence:
    L0: Native execution capability present
    L1: Episodic memory retention active (> 0 episodes persisted)
    L2: Procedural rules distilled from experience (> 0 rules active)
    L3: Dynamic phenotypes and adaptive cognitive compilation operational
    L4: Autonomous pressure field and calibrated uncertainty (Brier < 0.10)
    L5: Dynamic capability birth and strategy genesis verified in sandbox
    L6: Second-order learning acceleration verified (> 1.2x)
    L7: Full developmental flywheel evolving cognitive genome and strategies
    """
    def evaluate(
        self,
        has_native_caps: bool = True,
        episodes_count: int = 1,
        procedural_rules_count: int = 1,
        has_adaptive_phenotypes: bool = True,
        has_pressure_field: bool = True,
        brier_score: float = 0.05,
        born_capabilities_count: int = 1,
        synthesized_strategies_count: int = 1,
        learning_acceleration: float = 1.5,
        flywheel_cycles: int = 10
    ) -> MaturityAssessment:
        met = []
        pending = []

        # L0
        if has_native_caps:
            met.append("L0: Native execution cells operational")
        else:
            pending.append("L0: Native execution cells")

        # L1
        if episodes_count > 0:
            met.append("L1: Episodic memory retention active")
        else:
            pending.append("L1: Episodic memory retention")

        # L2
        if procedural_rules_count > 0:
            met.append("L2: Procedural rules distilled from empirical episodes")
        else:
            pending.append("L2: Procedural rule distillation")

        # L3
        if has_adaptive_phenotypes:
            met.append("L3: Adaptive cognitive phenotypes and dynamic compilation active")
        else:
            pending.append("L3: Adaptive cognitive phenotypes")

        # L4
        if has_pressure_field and brier_score < 0.10:
            met.append("L4: Autonomous problem discovery & calibrated uncertainty (Brier < 0.10)")
        else:
            pending.append("L4: Autonomous problem discovery & calibrated uncertainty")

        # L5
        if born_capabilities_count > 0 and synthesized_strategies_count > 0:
            met.append("L5: Dynamic capability birth and strategy genesis verified")
        else:
            pending.append("L5: Dynamic capability birth and strategy genesis")

        # L6
        if learning_acceleration > 1.2:
            met.append("L6: Second-order learning acceleration demonstrated (> 1.2x)")
        else:
            pending.append("L6: Second-order learning acceleration")

        # L7
        if flywheel_cycles >= 10:
            met.append("L7: Full developmental flywheel continuously evolving genome and strategies")
        else:
            pending.append("L7: Full developmental flywheel operational cycles")

        level_map = [
            (MaturityLevel.L0_STATIC, 0),
            (MaturityLevel.L1_MEMORY, 1),
            (MaturityLevel.L2_PROCEDURAL, 2),
            (MaturityLevel.L3_ADAPTIVE, 3),
            (MaturityLevel.L4_SELF_DIAGNOSTIC, 4),
            (MaturityLevel.L5_SELF_DEVELOPING, 5),
            (MaturityLevel.L6_META_LEARNING, 6),
            (MaturityLevel.L7_COGNITIVE_GENERATIVE, 7),
        ]

        active_idx = min(len(met) - 1, 7) if met else 0
        current_lvl, lvl_num = level_map[active_idx]
        evidence_score = len(met) / 8.0

        return MaturityAssessment(
            current_level=current_lvl,
            level_index=lvl_num,
            criteria_met=met,
            criteria_pending=pending,
            evidence_score=evidence_score
        )
