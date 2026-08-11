"""
Internal Capability Catalog and Execution Statistics
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional


@dataclass
class CapabilityRecord:
    name: str
    category: str  # "reasoning", "coding", "debugging", "verification", "tool", "experiment"
    description: str
    is_native: bool = True
    invocations: int = 0
    successes: int = 0
    failures: int = 0
    avg_latency_ms: float = 0.0
    evidence_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def reliability(self) -> float:
        if self.invocations == 0:
            return 0.5  # Neutral prior for untried capability
        return round(self.successes / self.invocations, 4)

    def record_execution(self, success: bool, latency_ms: float, evidence_id: Optional[str] = None):
        self.invocations += 1
        if success:
            self.successes += 1
        else:
            self.failures += 1

        # Incremental moving average
        self.avg_latency_ms = round(((self.avg_latency_ms * (self.invocations - 1)) + latency_ms) / self.invocations, 2)
        if evidence_id and evidence_id not in self.evidence_ids:
            self.evidence_ids.append(evidence_id)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "is_native": self.is_native,
            "invocations": self.invocations,
            "successes": self.successes,
            "failures": self.failures,
            "reliability": self.reliability,
            "avg_latency_ms": self.avg_latency_ms,
            "evidence_ids": self.evidence_ids,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityRecord":
        return cls(
            name=data["name"],
            category=data.get("category", "general"),
            description=data.get("description", ""),
            is_native=data.get("is_native", True),
            invocations=data.get("invocations", 0),
            successes=data.get("successes", 0),
            failures=data.get("failures", 0),
            avg_latency_ms=data.get("avg_latency_ms", 0.0),
            evidence_ids=data.get("evidence_ids", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time())
        )
