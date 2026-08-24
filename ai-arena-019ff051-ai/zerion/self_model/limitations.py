"""
Known Limitations and Failure Modes Catalog
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List


@dataclass
class LimitationRecord:
    id: str
    category: str  # "compute", "sensory", "knowledge", "authorization", "environment"
    title: str
    description: str
    mitigation_strategy: str
    is_active: bool = True
    discovered_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "mitigation_strategy": self.mitigation_strategy,
            "is_active": self.is_active,
            "discovered_at": self.discovered_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LimitationRecord":
        return cls(
            id=data["id"],
            category=data.get("category", "general"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            mitigation_strategy=data.get("mitigation_strategy", ""),
            is_active=data.get("is_active", True),
            discovered_at=data.get("discovered_at", time.time())
        )


DEFAULT_LIMITATIONS: List[LimitationRecord] = [
    LimitationRecord(
        id="LIM-001",
        category="compute",
        title="Local Execution Compute Bounds",
        description="Complex deep combinatorial search on low-tier edge/mobile devices must be bounded by time and memory quotas.",
        mitigation_strategy="Dynamically throttle cognitive compute tier (REFLEX / FAST) and prune search DAGs."
    ),
    LimitationRecord(
        id="LIM-002",
        category="sensory",
        title="Asynchronous Physical Sampling",
        description="Physical reality states change between discrete sampling intervals.",
        mitigation_strategy="Use explicit UNKNOWN / PREDICTED epistemic tagging until verified observations arrive."
    ),
    LimitationRecord(
        id="LIM-003",
        category="authorization",
        title="Host Sandbox Restrictions",
        description="Destructive system commands and unpermitted network endpoints are prohibited by security policy.",
        mitigation_strategy="Simulate or isolate actions inside in-memory sandbox and query user authorization."
    )
]
