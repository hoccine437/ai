"""
Cognition subsystem exports for ASCENDANT
"""

from zerion.cognition.cells import CognitiveCell, CellType, CellInput, CellOutput
from zerion.cognition.program import CognitiveProgram, ProgramStep
from zerion.cognition.compiler import CognitiveCompiler
from zerion.cognition.adaptive_compute import ComputeMode, ComputeProfile, resolve_compute_profile, COMPUTE_PROFILES
from zerion.cognition.multi_path import MultiPathReasoner, ReasoningPathResult
from zerion.cognition.adversarial import AdversarialEngine, AdversarialAttackResult

__all__ = [
    "CognitiveCell",
    "CellType",
    "CellInput",
    "CellOutput",
    "CognitiveProgram",
    "ProgramStep",
    "CognitiveCompiler",
    "ComputeMode",
    "ComputeProfile",
    "resolve_compute_profile",
    "COMPUTE_PROFILES",
    "MultiPathReasoner",
    "ReasoningPathResult",
    "AdversarialEngine",
    "AdversarialAttackResult",
]
