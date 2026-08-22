"""
Structured Executable Cognitive Strategy Representation
Represents a synthesized method of thinking with preconditions, procedural steps, and empirical evidence.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Dict, List, Optional
import uuid


@dataclass
class CognitiveStrategy:
    name: str
    domain: str
    strategy_id: str = field(default_factory=lambda: f"strat_{uuid.uuid4().hex[:8]}")
    preconditions: List[str] = field(default_factory=list)
    procedure_steps: List[str] = field(default_factory=list)
    executable_code: Optional[str] = None
    expected_benefit: str = ""
    failure_modes: List[str] = field(default_factory=list)
    cost: float = 1.0                     # Estimated cost weight
    latency_ms: float = 50.0              # Estimated execution latency
    risk: float = 0.2                     # 0.0 to 1.0
    evidence_ids: List[str] = field(default_factory=list)
    # benchmark_results values may be None (NOT_MEASURED) alongside measured
    # numbers; an explicit "measurement_status" key marks absent benchmarks.
    benchmark_results: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.85
    provenance: str = "cognitive_genesis"
    is_active: bool = True
    invocations: int = 0
    successes: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def reliability(self) -> float:
        if self.invocations == 0:
            return self.confidence
        return round(self.successes / self.invocations, 4)

    def record_execution(self, success: bool, latency: float, evidence_id: Optional[str] = None):
        self.invocations += 1
        if success:
            self.successes += 1
        self.latency_ms = round(((self.latency_ms * (self.invocations - 1)) + latency) / self.invocations, 2)
        if evidence_id and evidence_id not in self.evidence_ids:
            self.evidence_ids.append(evidence_id)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "domain": self.domain,
            "preconditions": self.preconditions,
            "procedure_steps": self.procedure_steps,
            "executable_code": self.executable_code,
            "expected_benefit": self.expected_benefit,
            "failure_modes": self.failure_modes,
            "cost": round(self.cost, 3),
            "latency_ms": round(self.latency_ms, 2),
            "risk": round(self.risk, 3),
            "evidence_ids": self.evidence_ids,
            "benchmark_results": self.benchmark_results,
            "confidence": round(self.confidence, 3),
            "provenance": self.provenance,
            "is_active": self.is_active,
            "invocations": self.invocations,
            "successes": self.successes,
            "reliability": self.reliability,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveStrategy":
        return cls(
            strategy_id=data.get("strategy_id", f"strat_{uuid.uuid4().hex[:8]}"),
            name=data["name"],
            domain=data.get("domain", "general"),
            preconditions=data.get("preconditions", []),
            procedure_steps=data.get("procedure_steps", []),
            executable_code=data.get("executable_code"),
            expected_benefit=data.get("expected_benefit", ""),
            failure_modes=data.get("failure_modes", []),
            cost=data.get("cost", 1.0),
            latency_ms=data.get("latency_ms", 50.0),
            risk=data.get("risk", 0.2),
            evidence_ids=data.get("evidence_ids", []),
            benchmark_results=data.get("benchmark_results", {}),
            confidence=data.get("confidence", 0.85),
            provenance=data.get("provenance", "cognitive_genesis"),
            is_active=data.get("is_active", True),
            invocations=data.get("invocations", 0),
            successes=data.get("successes", 0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time())
        )
