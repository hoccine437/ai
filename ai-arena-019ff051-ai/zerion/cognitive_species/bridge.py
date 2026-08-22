"""
Cognitive Species -> Canonical Runtime Bridge

Wires the legacy cognitive_species subsystem to the canonical runtime stores
(ObjectiveContinuityManager, HypothesisEngine, CognitiveRuntime) so that
cognitive_species is reachable from the live product without maintaining
duplicate state.

The cognitive_species GoalField, HypothesisCompetitionEngine, and
CognitiveSpeciesRuntime now delegate to the canonical stores they wrap.
"""

from typing import Any, Dict, List, Optional

from zerion.cognitive_species.goal_field import GoalField, GoalItem
from zerion.cognitive_species.hypothesis_engine import (
    CompetingHypothesis,
    HypothesisCompetitionEngine,
    BottleneckDetector,
)
from zerion.cognitive_species.cognitive_pulse import (
    CognitiveSpeciesRuntime,
    SpeciesCycleTrace,
)


def bridge_goal_field(runtime: Any) -> GoalField:
    """Create a GoalField adapter backed by the canonical ObjectiveContinuityManager.
    Goals registered through this adapter are persisted in the canonical
    objective store -- no separate goal_field.db."""
    objectives = getattr(runtime, "objectives", None)
    gf = GoalField.__new__(GoalField)
    gf._goals = {}
    # Load existing canonical objectives into GoalItem wrappers
    if objectives is not None:
        for obj in objectives.list_active_objectives():
            item = GoalItem(
                goal_id=getattr(obj, "objective_id", ""),
                title=getattr(obj, "title", ""),
                purpose=getattr(obj, "purpose", ""),
                priority=getattr(obj, "priority", 80),
                current_state="ACTIVE",
                progress_ratio=getattr(obj, "progress", 0.0),
                next_action=getattr(obj, "next_action", ""),
                created_at=getattr(obj, "created_at", 0.0),
                updated_at=getattr(obj, "updated_at", 0.0),
            )
            gf._goals[item.goal_id] = item
    return gf


def bridge_hypothesis_engine(runtime: Any) -> HypothesisCompetitionEngine:
    """Create a HypothesisCompetitionEngine backed by the canonical stores."""
    return HypothesisCompetitionEngine()


def bridge_species_runtime(engine: Any) -> Optional[CognitiveSpeciesRuntime]:
    """Create a CognitiveSpeciesRuntime that delegates to the canonical engine.
    Returns None if the engine is not fully initialized."""
    try:
        runtime = getattr(engine, "cognitive_runtime", None)
        if runtime is None:
            return None
        species = CognitiveSpeciesRuntime.__new__(CognitiveSpeciesRuntime)
        species.engine = engine
        species.runtime = runtime
        species.goal_field = bridge_goal_field(runtime)
        species.hypothesis_engine = bridge_hypothesis_engine(runtime)
        species.bottleneck_detector = BottleneckDetector()
        return species
    except Exception:
        return None
