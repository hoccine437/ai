"""
First-Class Question Entity and Types - Question Genesis 3.0
Supports 9 distinct question modalities:
DIAGNOSTIC, CAUSAL, COUNTERFACTUAL, FALSIFICATION, OPTIMIZATION, STRATEGIC, META_COGNITIVE, LEARNING, CAPABILITY
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid


class QuestionType(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    CAUSAL = "CAUSAL"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    FALSIFICATION = "FALSIFICATION"
    OPTIMIZATION = "OPTIMIZATION"
    STRATEGIC = "STRATEGIC"
    META_COGNITIVE = "META_COGNITIVE"
    LEARNING = "LEARNING"
    CAPABILITY = "CAPABILITY"
    MISSING_INFORMATION = "MISSING_INFORMATION"


class QuestionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    INVESTIGATING = "INVESTIGATING"
    ANSWERED = "ANSWERED"
    FALSIFIED = "FALSIFIED"
    ABANDONED = "ABANDONED"


@dataclass
class Question:
    text: str
    question_type: QuestionType
    id: str = field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    origin: str = "genesis"
    parent_question_id: Optional[str] = None
    priority: float = 0.5
    uncertainty: float = 0.8          # 0.0 to 1.0 (epistemic entropy)
    expected_information_gain: float = 0.7  # 0.0 to 1.0 (bits/utility)
    cost: float = 1.0                 # estimated compute/time cost >= 0.1
    risk: float = 0.0                 # estimated risk of investigative action (0.0 to 1.0)
    goal_relevance: float = 0.8       # 0.0 to 1.0
    impact: float = 0.7               # 0.0 to 1.0
    dependencies: List[str] = field(default_factory=list)
    status: QuestionStatus = QuestionStatus.PROPOSED
    evidence_ids: List[str] = field(default_factory=list)
    answer: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "question_type": self.question_type.value if isinstance(self.question_type, QuestionType) else str(self.question_type),
            "origin": self.origin,
            "parent_question_id": self.parent_question_id,
            "priority": round(self.priority, 4),
            "uncertainty": round(self.uncertainty, 4),
            "expected_information_gain": round(self.expected_information_gain, 4),
            "cost": round(self.cost, 4),
            "risk": round(self.risk, 4),
            "goal_relevance": round(self.goal_relevance, 4),
            "impact": round(self.impact, 4),
            "dependencies": self.dependencies,
            "status": self.status.value if isinstance(self.status, QuestionStatus) else str(self.status),
            "evidence_ids": self.evidence_ids,
            "answer": self.answer,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Question":
        qt_str = data.get("question_type", QuestionType.DIAGNOSTIC.value)
        try:
            qt = QuestionType(qt_str)
        except ValueError:
            qt = QuestionType.DIAGNOSTIC

        qs_str = data.get("status", QuestionStatus.PROPOSED.value)
        try:
            qs = QuestionStatus(qs_str)
        except ValueError:
            qs = QuestionStatus.PROPOSED

        return cls(
            id=data.get("id", f"q_{uuid.uuid4().hex[:8]}"),
            text=data.get("text", ""),
            question_type=qt,
            origin=data.get("origin", "genesis"),
            parent_question_id=data.get("parent_question_id"),
            priority=data.get("priority", 0.5),
            uncertainty=data.get("uncertainty", 0.8),
            expected_information_gain=data.get("expected_information_gain", 0.7),
            cost=data.get("cost", 1.0),
            risk=data.get("risk", 0.0),
            goal_relevance=data.get("goal_relevance", 0.8),
            impact=data.get("impact", 0.7),
            dependencies=data.get("dependencies", []),
            status=qs,
            evidence_ids=data.get("evidence_ids", []),
            answer=data.get("answer"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {})
        )
