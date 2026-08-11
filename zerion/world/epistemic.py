"""
Epistemic Status and Confidence Categorization - World Model 3.0
Distinguishes all 8 fundamental epistemic categories:
OBSERVED, MEASURED, INFERRED, PREDICTED, HYPOTHESIZED, ASSUMED, UNKNOWN, CONTRADICTED
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional


class EpistemicStatus(str, Enum):
    OBSERVED = "OBSERVED"          # Sampled qualitative/discrete reality observation
    MEASURED = "MEASURED"          # Quantitative metric empirically measured in sandbox/hardware
    INFERRED = "INFERRED"          # Deduced mathematically or derived logically from verified premises
    PREDICTED = "PREDICTED"        # Forecasted future state prior to reality sampling
    HYPOTHESIZED = "HYPOTHESIZED"  # Testable causal proposal undergoing experimental evaluation
    ASSUMED = "ASSUMED"            # Unverified working premise
    UNKNOWN = "UNKNOWN"            # Explicitly recognized epistemic void / missing variable
    CONTRADICTED = "CONTRADICTED"  # Falsified by counter-evidence or invariant breach


class EpistemicAssertion(str, Enum):
    I_KNOW = "I_KNOW"              # Backed by direct measurement / observation (confidence >= 0.90)
    I_INFER = "I_INFER"            # Derived deductively from verified facts (0.75 <= confidence < 0.90)
    I_SUSPECT = "I_SUSPECT"        # Plausible working hypothesis (0.40 <= confidence < 0.75)
    I_DO_NOT_KNOW = "I_DO_NOT_KNOW"# Insufficient evidence (< 0.40)


@dataclass
class EpistemicValue:
    value: Any
    status: EpistemicStatus
    confidence: float = 1.0        # 0.0 to 1.0
    source: str = "environment"
    temporal_validity_seconds: float = 3600.0  # Time before belief requires re-sampling
    last_verified_at: float = field(default_factory=time.time)
    contradictions_count: int = 0
    provenance_chain: List[str] = field(default_factory=list)

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_verified_at) > self.temporal_validity_seconds

    @property
    def epistemic_assertion(self) -> EpistemicAssertion:
        if self.status == EpistemicStatus.CONTRADICTED or self.status == EpistemicStatus.UNKNOWN:
            return EpistemicAssertion.I_DO_NOT_KNOW
        if self.confidence >= 0.90 and self.status in (EpistemicStatus.OBSERVED, EpistemicStatus.MEASURED):
            return EpistemicAssertion.I_KNOW
        if self.confidence >= 0.75:
            return EpistemicAssertion.I_INFER
        if self.confidence >= 0.40:
            return EpistemicAssertion.I_SUSPECT
        return EpistemicAssertion.I_DO_NOT_KNOW

    def record_contradiction(self, counter_source: str):
        self.contradictions_count += 1
        self.confidence = max(0.10, self.confidence - 0.35)
        if self.contradictions_count >= 2 or self.confidence < 0.30:
            self.status = EpistemicStatus.CONTRADICTED
        self.provenance_chain.append(f"Contradicted by {counter_source} at {time.time()}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status.value if isinstance(self.status, EpistemicStatus) else str(self.status),
            "confidence": round(self.confidence, 4),
            "assertion": self.epistemic_assertion.value,
            "source": self.source,
            "is_stale": self.is_stale,
            "temporal_validity_seconds": self.temporal_validity_seconds,
            "last_verified_at": self.last_verified_at,
            "contradictions_count": self.contradictions_count,
            "provenance_chain": self.provenance_chain
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpistemicValue":
        status_str = data.get("status", EpistemicStatus.UNKNOWN.value)
        try:
            status = EpistemicStatus(status_str)
        except ValueError:
            status = EpistemicStatus.UNKNOWN
        return cls(
            value=data.get("value"),
            status=status,
            confidence=data.get("confidence", 1.0),
            source=data.get("source", "unknown"),
            temporal_validity_seconds=data.get("temporal_validity_seconds", 3600.0),
            last_verified_at=data.get("last_verified_at", time.time()),
            contradictions_count=data.get("contradictions_count", 0),
            provenance_chain=data.get("provenance_chain", [])
        )
