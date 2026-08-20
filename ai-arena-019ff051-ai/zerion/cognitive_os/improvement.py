"""
Slice 7 — ImprovementProposal.

A proposal is NOT an improvement merely because an LLM suggested it, code was
generated, tests passed, or latency decreased once. Improvement requires
measurement of BASELINE vs CANDIDATE with sufficient evidence and no
regression. Every proposal carries problem, evidence, hypothesis, proposed
change, expected benefit/cost, risk, dependencies, affected capabilities,
test plan and rollback plan.

Lifecycle: PROPOSED -> ANALYZING -> SANDBOXED -> TESTING -> BENCHMARKING ->
APPROVED | REJECTED | ROLLED_BACK.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


class ModificationType(str, Enum):
    CONFIGURATION_CHANGE = "CONFIGURATION_CHANGE"
    STRATEGY_CHANGE = "STRATEGY_CHANGE"
    PROMPT_CHANGE = "PROMPT_CHANGE"
    ROUTING_CHANGE = "ROUTING_CHANGE"
    MEMORY_POLICY_CHANGE = "MEMORY_POLICY_CHANGE"
    CAPABILITY_CHANGE = "CAPABILITY_CHANGE"
    CODE_CHANGE = "CODE_CHANGE"
    ARCHITECTURE_CHANGE = "ARCHITECTURE_CHANGE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ANALYZING = "ANALYZING"
    SANDBOXED = "SANDBOXED"
    TESTING = "TESTING"
    BENCHMARKING = "BENCHMARKING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


# Risk by modification type (base risk before policy/permissions adjust it).
BASE_RISK: Dict[ModificationType, RiskLevel] = {
    ModificationType.CONFIGURATION_CHANGE: RiskLevel.LOW,
    ModificationType.STRATEGY_CHANGE: RiskLevel.LOW,
    ModificationType.PROMPT_CHANGE: RiskLevel.LOW,
    ModificationType.ROUTING_CHANGE: RiskLevel.MEDIUM,
    ModificationType.MEMORY_POLICY_CHANGE: RiskLevel.MEDIUM,
    ModificationType.CAPABILITY_CHANGE: RiskLevel.HIGH,
    ModificationType.CODE_CHANGE: RiskLevel.HIGH,
    ModificationType.ARCHITECTURE_CHANGE: RiskLevel.CRITICAL,
}

_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1,
               RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


class ProposalIntegrityError(RuntimeError):
    pass


@dataclass
class ImprovementProposal:
    proposal_id: str = field(default_factory=lambda: f"prop_{uuid.uuid4().hex[:10]}")
    target_component: str = ""
    problem: str = ""
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    hypothesis: str = ""
    proposed_change: Any = None            # config dict or code string
    expected_benefit: str = ""
    expected_cost: str = ""
    risk: RiskLevel = RiskLevel.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    affected_capabilities: List[str] = field(default_factory=list)
    test_plan: List[Dict[str, Any]] = field(default_factory=list)
    rollback_plan: str = "restore previous snapshot"
    created_at: float = field(default_factory=time.time)
    status: ProposalStatus = ProposalStatus.PROPOSED
    modification_type: ModificationType = ModificationType.CONFIGURATION_CHANGE
    scope: List[str] = field(default_factory=list)   # allowed components
    analysis: Dict[str, Any] = field(default_factory=dict)
    test_results: List[Dict[str, Any]] = field(default_factory=list)
    benchmark: Dict[str, Any] = field(default_factory=dict)
    snapshot_version: Optional[int] = None
    approval: Dict[str, Any] = field(default_factory=dict)
    rejection_reason: str = ""
    rollback_reason: str = ""
    promoted_at: Optional[float] = None
    promoted_version: Optional[int] = None
    policy_version: Optional[int] = None   # Slice 8: runtime policy promotion
    rejection_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "target_component": self.target_component,
            "problem": self.problem,
            "evidence": list(self.evidence),
            "hypothesis": self.hypothesis,
            "proposed_change": self.proposed_change,
            "expected_benefit": self.expected_benefit,
            "expected_cost": self.expected_cost,
            "risk": self.risk.value,
            "dependencies": list(self.dependencies),
            "affected_capabilities": list(self.affected_capabilities),
            "test_plan": list(self.test_plan),
            "rollback_plan": self.rollback_plan,
            "created_at": self.created_at,
            "status": self.status.value,
            "modification_type": self.modification_type.value,
            "scope": list(self.scope),
            "analysis": dict(self.analysis),
            "test_results": list(self.test_results),
            "benchmark": dict(self.benchmark),
            "snapshot_version": self.snapshot_version,
            "approval": dict(self.approval),
            "rejection_reason": self.rejection_reason,
            "rollback_reason": self.rollback_reason,
            "promoted_at": self.promoted_at,
            "promoted_version": self.promoted_version,
            "policy_version": self.policy_version,
            "rejection_history": list(self.rejection_history),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImprovementProposal":
        p = cls(
            proposal_id=data.get("proposal_id", ""),
            target_component=data.get("target_component", ""),
            problem=data.get("problem", ""),
            evidence=data.get("evidence", []),
            hypothesis=data.get("hypothesis", ""),
            proposed_change=data.get("proposed_change"),
            expected_benefit=data.get("expected_benefit", ""),
            expected_cost=data.get("expected_cost", ""),
            risk=RiskLevel(data.get("risk", "MEDIUM")),
            dependencies=data.get("dependencies", []),
            affected_capabilities=data.get("affected_capabilities", []),
            test_plan=data.get("test_plan", []),
            rollback_plan=data.get("rollback_plan", "restore previous snapshot"),
            created_at=data.get("created_at", time.time()),
            status=ProposalStatus(data.get("status", "PROPOSED")),
            modification_type=ModificationType(
                data.get("modification_type", "CONFIGURATION_CHANGE")),
            scope=data.get("scope", []),
            analysis=data.get("analysis", {}),
            test_results=data.get("test_results", []),
            benchmark=data.get("benchmark", {}),
            snapshot_version=data.get("snapshot_version"),
            approval=data.get("approval", {}),
            rejection_reason=data.get("rejection_reason", ""),
            rollback_reason=data.get("rollback_reason", ""),
            promoted_at=data.get("promoted_at"),
            promoted_version=data.get("promoted_version"),
            policy_version=data.get("policy_version"),
            rejection_history=data.get("rejection_history", []),
        )
        return p

    def transition(self, new_status: ProposalStatus) -> None:
        allowed = {
            ProposalStatus.PROPOSED: {ProposalStatus.ANALYZING,
                                      ProposalStatus.REJECTED},
            ProposalStatus.ANALYZING: {ProposalStatus.SANDBOXED,
                                       ProposalStatus.TESTING,
                                       ProposalStatus.REJECTED},
            ProposalStatus.SANDBOXED: {ProposalStatus.TESTING,
                                       ProposalStatus.REJECTED},
            ProposalStatus.TESTING: {ProposalStatus.BENCHMARKING,
                                     ProposalStatus.REJECTED},
            ProposalStatus.BENCHMARKING: {ProposalStatus.APPROVED,
                                          ProposalStatus.REJECTED},
            ProposalStatus.APPROVED: {ProposalStatus.ROLLED_BACK,
                                      ProposalStatus.REJECTED},
            ProposalStatus.REJECTED: set(),
            ProposalStatus.ROLLED_BACK: set(),
        }
        if new_status not in allowed.get(self.status, set()):
            raise ValueError(
                f"Invalid proposal transition {self.status.value} -> {new_status.value}")
        self.status = new_status


class ProposalStore:
    """SQLite-WAL + SHA-256 persistence for improvement proposals."""

    def __init__(self, db_path: Optional[str] = "data/proposals.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._proposals: Dict[str, ImprovementProposal] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if not self.db_path:
            return
        p = Path(self.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                proposal_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                status TEXT,
                updated_at REAL
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, proposal: ImprovementProposal) -> ImprovementProposal:
        self._proposals[proposal.proposal_id] = proposal
        if not self.db_path:
            return proposal
        payload = json.dumps(proposal.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO proposals VALUES (?, ?, ?, ?, ?)",
                (proposal.proposal_id, payload, self._checksum(payload),
                 proposal.status.value, time.time()))
            conn.commit()
        finally:
            conn.close()
        return proposal

    def get(self, proposal_id: str) -> Optional[ImprovementProposal]:
        return self._proposals.get(proposal_id)

    def list(self, status: Optional[ProposalStatus] = None) -> List[ImprovementProposal]:
        props = list(self._proposals.values())
        if status is not None:
            props = [p for p in props if p.status == status]
        return sorted(props, key=lambda p: p.created_at)

    def count(self) -> int:
        return len(self._proposals)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT payload, checksum FROM proposals").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise ProposalIntegrityError(
                    f"Failed to load proposals from {self.db_path}: {e}") from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise ProposalIntegrityError(
                        "proposal row checksum mismatch (corrupt write)")
                data = json.loads(payload)
                self._proposals[data["proposal_id"]] = ImprovementProposal.from_dict(data)
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise ProposalIntegrityError(
                        f"Failed to load proposals from {self.db_path}: {e}") from e
