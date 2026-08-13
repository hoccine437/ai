"""
Slice 2 — Question Field.

A Question is a first-class structured cognitive object (never a plain string). It
carries its genesis source, scoring metrics, goal/event/belief/hypothesis links and
a full lifecycle. Unresolved questions are persisted and survive restarts.

Prioritization explicitly REUSES the Slice 1 attention economy (CognitivePriority):
``question_to_attention_item()`` maps a Question onto the AttentionItem contract, so
questions compete for cognitive resources through the exact same mechanism as every
other candidate. No second priority system is created here.
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from zerion.cognitive_os.attention import AttentionItem, CognitivePriority


class QuestionLifecycle(str, Enum):
    GENERATED = "GENERATED"
    QUEUED = "QUEUED"
    SELECTED = "SELECTED"
    INVESTIGATING = "INVESTIGATING"
    ANSWERED = "ANSWERED"
    PARTIALLY_ANSWERED = "PARTIALLY_ANSWERED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    EXPIRED = "EXPIRED"


class QuestionSource(str, Enum):
    """Who originated the question: the user or Zerion itself."""

    USER_REQUESTED = "USER_REQUESTED"
    ZERION_GENERATED = "ZERION_GENERATED"


# Statuses that still need cognitive work (an unresolved question can be deduplicated
# against; terminal statuses can not).
UNRESOLVED_QUESTION_STATUSES = {
    QuestionLifecycle.GENERATED,
    QuestionLifecycle.QUEUED,
    QuestionLifecycle.SELECTED,
    QuestionLifecycle.INVESTIGATING,
    QuestionLifecycle.PARTIALLY_ANSWERED,
    QuestionLifecycle.DEFERRED,
}


class QuestionValidationError(ValueError):
    """Raised for structurally invalid questions (empty text, out-of-range metrics)."""


class QuestionStoreIntegrityError(RuntimeError):
    """Raised when persisted question data is corrupt and strict loading is enabled."""


_MAX_TEXT_LENGTH = 4000
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: str) -> str:
    """Strip control characters so stored question text can never corrupt a document."""
    return _CTRL_RE.sub("", str(value)).strip()


def _clamp01(value: Any, name: str, allow_none: bool = False) -> Optional[float]:
    if value is None and allow_none:
        return None
    f = float(value)
    if not (0.0 <= f <= 1.0):
        raise QuestionValidationError(f"Question {name} must be in [0.0, 1.0], got {f!r}")
    return f


def _clamp_non_negative(value: Any, name: str) -> float:
    f = float(value)
    if f < 0.0:
        raise QuestionValidationError(f"Question {name} must be >= 0.0, got {f!r}")
    return f


@dataclass
class Question:
    question_id: str = field(default_factory=lambda: f"q_{uuid.uuid4().hex[:10]}")
    question: str = ""
    source: str = "UNCERTAINTY"          # genesis source (UNCERTAINTY, CONTRADICTION, ... USER_REQUEST)
    source_kind: QuestionSource = QuestionSource.ZERION_GENERATED
    created_at: float = field(default_factory=time.time)
    status: QuestionLifecycle = QuestionLifecycle.QUEUED
    priority: float = 0.0                # attention-field score [0.0, 1.0] (Slice 1 CognitivePriority)
    urgency: float = 0.5                 # [0.0, 1.0]
    uncertainty: float = 0.5             # [0.0, 1.0]
    novelty: float = 0.5                 # [0.0, 1.0]
    goal_relevance: float = 0.5          # [0.0, 1.0]
    expected_information_gain: float = 0.5  # [0.0, 1.0]
    expected_decision_impact: float = 0.5   # [0.0, 1.0]
    estimated_cost: float = 1.0          # >= 0.0 abstract compute units
    risk: float = 0.1                    # [0.0, 1.0]
    related_goal: Optional[str] = None
    related_event: Optional[str] = None
    related_beliefs: List[str] = field(default_factory=list)
    related_hypotheses: List[str] = field(default_factory=list)
    parent_question: Optional[str] = None
    resolution: Optional[str] = None
    fingerprint: str = ""                # deduplication key
    metadata: Dict[str, Any] = field(default_factory=dict)  # structured genesis context (observed/expected/...)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        text = _clean_text(self.question)
        if not text:
            raise QuestionValidationError("Question text must not be empty")
        if len(text) > _MAX_TEXT_LENGTH:
            raise QuestionValidationError(
                f"Question text exceeds {_MAX_TEXT_LENGTH} chars ({len(text)})"
            )
        self.question = text
        if isinstance(self.source_kind, str):
            self.source_kind = QuestionSource(self.source_kind)
        if isinstance(self.status, str):
            self.status = QuestionLifecycle(self.status)
        # Deterministic dedup key: same source + normalized text + same related goal.
        if not self.fingerprint:
            norm = re.sub(r"\s+", " ", self.question.lower()).strip()
            key = f"{self.source_kind.value}|{self.source}|{norm}|{self.related_goal or ''}"
            self.fingerprint = hashlib.sha1(key.encode("utf-8")).hexdigest()
        self.urgency = _clamp01(self.urgency, "urgency")
        self.uncertainty = _clamp01(self.uncertainty, "uncertainty")
        self.novelty = _clamp01(self.novelty, "novelty")
        self.goal_relevance = _clamp01(self.goal_relevance, "goal_relevance")
        self.expected_information_gain = _clamp01(self.expected_information_gain,
                                                  "expected_information_gain")
        self.expected_decision_impact = _clamp01(self.expected_decision_impact,
                                                 "expected_decision_impact")
        self.risk = _clamp01(self.risk, "risk")
        self.estimated_cost = _clamp_non_negative(self.estimated_cost, "estimated_cost")
        self.priority = _clamp01(self.priority, "priority")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "source": self.source,
            "source_kind": self.source_kind.value,
            "created_at": self.created_at,
            "status": self.status.value,
            "priority": round(self.priority, 6),
            "urgency": round(self.urgency, 6),
            "uncertainty": round(self.uncertainty, 6),
            "novelty": round(self.novelty, 6),
            "goal_relevance": round(self.goal_relevance, 6),
            "expected_information_gain": round(self.expected_information_gain, 6),
            "expected_decision_impact": round(self.expected_decision_impact, 6),
            "estimated_cost": round(self.estimated_cost, 6),
            "risk": round(self.risk, 6),
            "related_goal": self.related_goal,
            "related_event": self.related_event,
            "related_beliefs": self.related_beliefs,
            "related_hypotheses": self.related_hypotheses,
            "parent_question": self.parent_question,
            "resolution": self.resolution,
            "fingerprint": self.fingerprint,
            "metadata": self.metadata,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Question":
        source_kind = data.get("source_kind", QuestionSource.ZERION_GENERATED.value)
        try:
            source_kind = QuestionSource(source_kind)
        except ValueError:
            source_kind = QuestionSource.ZERION_GENERATED
        status = data.get("status", QuestionLifecycle.QUEUED.value)
        try:
            status = QuestionLifecycle(status)
        except ValueError:
            status = QuestionLifecycle.QUEUED
        return cls(
            question_id=data.get("question_id", f"q_{uuid.uuid4().hex[:10]}"),
            question=data.get("question", ""),
            source=data.get("source", "UNCERTAINTY"),
            source_kind=source_kind,
            created_at=float(data.get("created_at", time.time())),
            status=status,
            priority=float(data.get("priority", 0.0)),
            urgency=float(data.get("urgency", 0.5)),
            uncertainty=float(data.get("uncertainty", 0.5)),
            novelty=float(data.get("novelty", 0.5)),
            goal_relevance=float(data.get("goal_relevance", 0.5)),
            expected_information_gain=float(data.get("expected_information_gain", 0.5)),
            expected_decision_impact=float(data.get("expected_decision_impact", 0.5)),
            estimated_cost=float(data.get("estimated_cost", 1.0)),
            risk=float(data.get("risk", 0.1)),
            related_goal=data.get("related_goal"),
            related_event=data.get("related_event"),
            related_beliefs=list(data.get("related_beliefs", [])),
            related_hypotheses=list(data.get("related_hypotheses", [])),
            parent_question=data.get("parent_question"),
            resolution=data.get("resolution"),
            fingerprint=data.get("fingerprint", ""),
            metadata=dict(data.get("metadata", {})),
            updated_at=float(data.get("updated_at", time.time())),
        )


def question_to_attention_item(question: Question) -> AttentionItem:
    """Map a Question onto the Slice 1 AttentionItem contract.

    The attention field (CognitivePriority) is the single priority mechanism:
    importance stays at a neutral 0.5 (questions are scored on their own metrics),
    expected_decision_impact maps to expected_utility, estimated_cost to
    resource_cost, goal relevance to objective_relevance.
    """
    return AttentionItem(
        topic=question.question,
        source=f"question:{question.source}",
        urgency=question.urgency,
        importance=0.5,
        uncertainty=question.uncertainty,
        novelty=question.novelty,
        objective_relevance=question.goal_relevance,
        expected_information_gain=question.expected_information_gain,
        expected_utility=question.expected_decision_impact,
        risk=question.risk,
        resource_cost=question.estimated_cost,
        api_cost=0.0,
        estimated_latency_ms=0.0,
        goal_id=question.related_goal,
        payload={"question_id": question.question_id},
    )


def score_question(question: Question,
                   scorer: Optional[CognitivePriority] = None) -> float:
    """Provisional attention score for a question (same formula the attention field uses)."""
    return (scorer or CognitivePriority()).score(question_to_attention_item(question))


class QuestionStore:
    """SQLite WAL-backed store for Questions (corruption-safe).

    Each row carries a SHA-256 checksum of its JSON payload. On load, checksum
    mismatches / malformed payloads are recorded in ``load_errors``; with
    ``strict_load=True`` they raise QuestionStoreIntegrityError instead of
    silently returning empty state.
    """

    def __init__(self, db_path: Optional[str] = "data/question_field.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._questions: Dict[str, Question] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    question_id TEXT PRIMARY KEY,
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

    def put(self, question: Question) -> Question:
        self._questions[question.question_id] = question
        if not self.db_path:
            return question
        payload = json.dumps(question.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO questions VALUES (?, ?, ?, ?, ?)",
                (question.question_id, payload, self._checksum(payload),
                 question.status.value, question.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return question

    def get(self, question_id: str) -> Optional[Question]:
        return self._questions.get(question_id)

    def list(self, status: Optional[QuestionLifecycle] = None) -> List[Question]:
        qs = list(self._questions.values())
        if status is not None:
            qs = [q for q in qs if q.status == status]
        return sorted(qs, key=lambda q: q.priority, reverse=True)

    def list_unresolved(self) -> List[Question]:
        return sorted(
            [q for q in self._questions.values() if q.status in UNRESOLVED_QUESTION_STATUSES],
            key=lambda q: q.priority,
            reverse=True,
        )

    def get_by_fingerprint(self, fingerprint: str,
                           unresolved_only: bool = True) -> Optional[Question]:
        for q in self._questions.values():
            if q.fingerprint != fingerprint:
                continue
            if unresolved_only and q.status not in UNRESOLVED_QUESTION_STATUSES:
                continue
            return q
        return None

    def count(self) -> int:
        return len(self._questions)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM questions").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise QuestionStoreIntegrityError(
                    f"Failed to load persisted questions from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise QuestionStoreIntegrityError(
                        "Question row checksum mismatch (corrupt or partial write)"
                    )
                data = json.loads(payload)
                q = Question.from_dict(data)
                self._questions[q.question_id] = q
            except Exception as e:  # noqa: BLE001 - recorded per row, never silent
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise QuestionStoreIntegrityError(
                        f"Failed to load persisted questions from {self.db_path}: {e}"
                    ) from e
