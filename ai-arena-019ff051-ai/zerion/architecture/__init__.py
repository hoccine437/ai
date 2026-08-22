"""
Architecture Search & Autophagy subsystem exports for ZERION-X Singularity Architecture
"""

from zerion.architecture_search.search_engine import ArchitectureCandidate, ArchitectureSearchEngine
from zerion.architecture.autophagy import AutophagyReplacementRecord, CognitiveAutophagyEngine

__all__ = [
    "ArchitectureCandidate",
    "ArchitectureSearchEngine",
    "AutophagyReplacementRecord",
    "CognitiveAutophagyEngine",
]
