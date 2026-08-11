"""
Integration subsystem exports for ASCENDANT
"""

from zerion.integration.termux_adapter import TermuxAdapter
from zerion.integration.offline_fallback import OfflineFallbackManager

__all__ = [
    "TermuxAdapter",
    "OfflineFallbackManager",
]
