"""
Claims, Evidence Items, and Epistemic Levels
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid


class EpistemicLevel(str, Enum):
    KNOWN = "KNOWN"              # Direct observation or deductive mathematical proof (confidence >= 0.95)
    SUPPORTED = "SUPPORTED"      # Replicated empirical evidence (0.75 <= confidence < 0.95)
    PROBABLE = "PROBABLE"        # Initial experimental support (0.50 <= confidence < 0.75)
    UNCERTAIN = "UNCERTAIN"      # Ambiguous or contradictory evidence (0.20 <= confidence < 0.50)
    UNKNOWN = "UNKNOWN"          # No empirical or deductive evidence (confidence < 0.20)


class VerificationMethod(str, Enum):
    DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
    FORMAL_PROOF = "FORMAL_PROOF"
    EMPIRICAL_TEST = "EMPIRICAL_TEST"
    CORROBORATION = "CORROBORATION"
    SANDBOX_EXPERIMENT = "SANDBOX_EXPERIMENT"
    HEURISTIC_CHECK = "HEURISTIC_CHECK"


@dataclass
class EvidenceItem:
    id: str = field(default_factory=lambda: f"evi_{uuid.uuid4().hex[:8]}")
    source: str = "environment"
    verification_method: VerificationMethod = VerificationMethod.EMPIRICAL_TEST
    data: Any = None
    confidence_weight: float = 0.8  # 0.0 to 1.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "verification_method": self.verification_method.value if isinstance(self.verification_method, VerificationMethod) else str(self.verification_method),
            "data": self.data,
            "confidence_weight": round(self.confidence_weight, 4),
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceItem":
        vm_str = data.get("verification_method", VerificationMethod.EMPIRICAL_TEST.value)
        try:
            vm = VerificationMethod(vm_str)
        except ValueError:
            vm = VerificationMethod.EMPIRICAL_TEST
        return cls(
            id=data.get("id", f"evi_{uuid.uuid4().hex[:8]}"),
            source=data.get("source", "environment"),
            verification_method=vm,
            data=data.get("data"),
            confidence_weight=data.get("confidence_weight", 0.8),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {})
        )


@dataclass
class Claim:
    statement: str
    id: str = field(default_factory=lambda: f"clm_{uuid.uuid4().hex[:8]}")
    epistemic_level: EpistemicLevel = EpistemicLevel.UNKNOWN
    confidence: float = 0.0
    supporting_evidence_ids: List[str] = field(default_factory=list)
    contradicting_evidence_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "epistemic_level": self.epistemic_level.value if isinstance(self.epistemic_level, EpistemicLevel) else str(self.epistemic_level),
            "confidence": round(self.confidence, 4),
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "contradicting_evidence_ids": self.contradicting_evidence_ids,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Claim":
        el_str = data.get("epistemic_level", EpistemicLevel.UNKNOWN.value)
        try:
            el = EpistemicLevel(el_str)
        except ValueError:
            el = EpistemicLevel.UNKNOWN
        return cls(
            id=data.get("id", f"clm_{uuid.uuid4().hex[:8]}"),
            statement=data.get("statement", ""),
            epistemic_level=el,
            confidence=data.get("confidence", 0.0),
            supporting_evidence_ids=data.get("supporting_evidence_ids", []),
            contradicting_evidence_ids=data.get("contradicting_evidence_ids", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {})
        )
