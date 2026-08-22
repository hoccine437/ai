"""
Zerion Unified Memory — ONE Smart Memory System

Replaces the old 8-layer architecture with a single intelligent
SmartMemory that manages 7 JSON storage files.
"""

from zerion.memory.episodic import Episode
from zerion.memory.procedural import ProceduralRule
from zerion.memory.semantic import (
    CausalLink,
    FailureMemoryRecord,
    MetacognitiveRecord,
    SemanticConcept,
)
from zerion.memory.distillation import ExperienceDistiller
from zerion.memory.developmental_store import SmartMemory

# Backward compatibility alias
DevelopmentalMemoryStore = SmartMemory

__all__ = [
    # The ONE unified memory
    "SmartMemory",
    "DevelopmentalMemoryStore",  # backward compat alias
    # Data classes (still useful for structured data)
    "Episode",
    "ProceduralRule",
    "SemanticConcept",
    "CausalLink",
    "FailureMemoryRecord",
    "MetacognitiveRecord",
    # Distillation engine
    "ExperienceDistiller",
]
