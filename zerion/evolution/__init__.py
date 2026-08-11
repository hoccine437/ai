"""
Evolution & Ascension subsystem exports for ASCENDANT
"""

from zerion.evolution.plasticity import PlasticityConfig, CognitivePlasticityManager
from zerion.evolution.self_modification import (
    ModificationProposal,
    ModificationResult,
    ControlledSelfModificationEngine,
)
from zerion.evolution.ascension import AscensionCycleReport, AscensionEngine
from zerion.evolution.timeline import DevelopmentSnapshot, DevelopmentTimelineManager

__all__ = [
    "PlasticityConfig",
    "CognitivePlasticityManager",
    "ModificationProposal",
    "ModificationResult",
    "ControlledSelfModificationEngine",
    "AscensionCycleReport",
    "AscensionEngine",
    "DevelopmentSnapshot",
    "DevelopmentTimelineManager",
]
