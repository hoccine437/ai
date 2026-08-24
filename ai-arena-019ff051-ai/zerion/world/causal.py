"""
Causal Hypotheses and Counterfactual Models
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class CausalHypothesis:
    id: str = field(default_factory=lambda: f"hyp_{uuid.uuid4().hex[:8]}")
    cause: str = ""
    effect: str = ""
    mechanism: str = ""
    strength: float = 0.5          # Estimated causal power (0.0 to 1.0)
    counterfactual_support: float = 0.0  # Support when cause was absent
    falsification_attempts: int = 0
    falsification_successes: int = 0
    verified: bool = False
    evidence_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def record_falsification_result(self, falsified: bool, evidence_id: Optional[str] = None):
        self.falsification_attempts += 1
        if falsified:
            self.falsification_successes += 1
            self.strength = max(0.0, self.strength - 0.3)
            self.verified = False
        else:
            self.strength = min(1.0, self.strength + 0.2)
            if self.falsification_attempts >= 2 and self.falsification_successes == 0:
                self.verified = True
        if evidence_id:
            self.evidence_ids.append(evidence_id)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cause": self.cause,
            "effect": self.effect,
            "mechanism": self.mechanism,
            "strength": self.strength,
            "counterfactual_support": self.counterfactual_support,
            "falsification_attempts": self.falsification_attempts,
            "falsification_successes": self.falsification_successes,
            "verified": self.verified,
            "evidence_ids": self.evidence_ids,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CausalHypothesis":
        return cls(
            id=data.get("id", f"hyp_{uuid.uuid4().hex[:8]}"),
            cause=data.get("cause", ""),
            effect=data.get("effect", ""),
            mechanism=data.get("mechanism", ""),
            strength=data.get("strength", 0.5),
            counterfactual_support=data.get("counterfactual_support", 0.0),
            falsification_attempts=data.get("falsification_attempts", 0),
            falsification_successes=data.get("falsification_successes", 0),
            verified=data.get("verified", False),
            evidence_ids=data.get("evidence_ids", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time())
        )
