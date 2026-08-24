"""
Slice 2 — Hypothesis.

A Hypothesis is structured, falsifiable and explicitly NOT knowledge: it carries
assumptions, predictions, expected evidence and failure conditions, and its status
is never auto-promoted to CONFIRMED by generation. Competing hypotheses are data —
they are never executed and never grant permissions.
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


class HypothesisLifecycle(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUPPORTED = "SUPPORTED"
    WEAKENED = "WEAKENED"
    CONTRADICTED = "CONTRADICTED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"


class HypothesisValidationError(ValueError):
    """Raised for structurally invalid hypotheses."""


class HypothesisStoreIntegrityError(RuntimeError):
    """Raised when persisted hypothesis data is corrupt and strict loading is enabled."""


_MAX_TEXT_LENGTH = 4000
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: str) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def hypothesis_fingerprint(question_id: str, statement: str) -> str:
    """Deterministic dedup key for a hypothesis within a question."""
    norm = re.sub(r"\s+", " ", str(statement).lower()).strip()
    key = f"{question_id}|{norm}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _clamp01(value: Any, name: str) -> float:
    f = float(value)
    if not (0.0 <= f <= 1.0):
        raise HypothesisValidationError(f"Hypothesis {name} must be in [0.0, 1.0], got {f!r}")
    return f


@dataclass
class Hypothesis:
    hypothesis_id: str = field(default_factory=lambda: f"hyp_{uuid.uuid4().hex[:10]}")
    question_id: str = ""
    statement: str = ""
    source: str = "hypothesis_engine"
    created_at: float = field(default_factory=time.time)
    confidence: float = 0.4              # [0.0, 1.0] — a belief, never knowledge
    assumptions: List[str] = field(default_factory=list)
    predictions: List[str] = field(default_factory=list)
    expected_evidence: List[str] = field(default_factory=list)
    failure_conditions: List[str] = field(default_factory=list)
    status: HypothesisLifecycle = HypothesisLifecycle.PROPOSED
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    score: float = 0.0
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        statement = _clean_text(self.statement)
        if not statement:
            raise HypothesisValidationError("Hypothesis statement must not be empty")
        if len(statement) > _MAX_TEXT_LENGTH:
            raise HypothesisValidationError(
                f"Hypothesis statement exceeds {_MAX_TEXT_LENGTH} chars ({len(statement)})"
            )
        self.statement = statement
        if not self.question_id.strip():
            raise HypothesisValidationError("Hypothesis must reference a question_id")
        if isinstance(self.status, str):
            self.status = HypothesisLifecycle(self.status)
        self.confidence = _clamp01(self.confidence, "confidence")
        self.score = _clamp01(self.score, "score")

    @property
    def fingerprint(self) -> str:
        return hypothesis_fingerprint(self.question_id, self.statement)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "question_id": self.question_id,
            "statement": self.statement,
            "source": self.source,
            "created_at": self.created_at,
            "confidence": round(self.confidence, 6),
            "assumptions": self.assumptions,
            "predictions": self.predictions,
            "expected_evidence": self.expected_evidence,
            "failure_conditions": self.failure_conditions,
            "status": self.status.value,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "score": round(self.score, 6),
            "revision_history": self.revision_history,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hypothesis":
        status = data.get("status", HypothesisLifecycle.PROPOSED.value)
        try:
            status = HypothesisLifecycle(status)
        except ValueError:
            status = HypothesisLifecycle.PROPOSED
        return cls(
            hypothesis_id=data.get("hypothesis_id", f"hyp_{uuid.uuid4().hex[:10]}"),
            question_id=data.get("question_id", ""),
            statement=data.get("statement", ""),
            source=data.get("source", "hypothesis_engine"),
            created_at=float(data.get("created_at", time.time())),
            confidence=float(data.get("confidence", 0.4)),
            assumptions=list(data.get("assumptions", [])),
            predictions=list(data.get("predictions", [])),
            expected_evidence=list(data.get("expected_evidence", [])),
            failure_conditions=list(data.get("failure_conditions", [])),
            status=status,
            supporting_evidence=list(data.get("supporting_evidence", [])),
            contradicting_evidence=list(data.get("contradicting_evidence", [])),
            score=float(data.get("score", 0.0)),
            revision_history=list(data.get("revision_history", [])),
            updated_at=float(data.get("updated_at", time.time())),
        )


class HypothesisStore:
    """SQLite WAL-backed store for Hypotheses (corruption-safe, same pattern as
    QuestionStore / StateStore: per-row SHA-256 checksum, load_errors, strict_load)."""

    def __init__(self, db_path: Optional[str] = "data/hypotheses.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._hypotheses: Dict[str, Hypothesis] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hypotheses (
                    hypothesis_id TEXT PRIMARY KEY,
                    question_id TEXT,
                    payload TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    status TEXT,
                    updated_at REAL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hypotheses_question ON hypotheses (question_id)"
            )
            conn.commit()
            conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, hypothesis: Hypothesis) -> Hypothesis:
        self._hypotheses[hypothesis.hypothesis_id] = hypothesis
        if not self.db_path:
            return hypothesis
        payload = json.dumps(hypothesis.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO hypotheses VALUES (?, ?, ?, ?, ?, ?)",
                (hypothesis.hypothesis_id, hypothesis.question_id, payload,
                 self._checksum(payload), hypothesis.status.value, hypothesis.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return hypothesis

    def get(self, hypothesis_id: str) -> Optional[Hypothesis]:
        return self._hypotheses.get(hypothesis_id)

    def list_by_question(self, question_id: str) -> List[Hypothesis]:
        return sorted(
            [h for h in self._hypotheses.values() if h.question_id == question_id],
            key=lambda h: h.created_at,
        )

    def list(self, status: Optional[HypothesisLifecycle] = None) -> List[Hypothesis]:
        hyps = list(self._hypotheses.values())
        if status is not None:
            hyps = [h for h in hyps if h.status == status]
        return sorted(hyps, key=lambda h: h.created_at)

    def get_by_fingerprint(self, question_id: str, statement: str) -> Optional[Hypothesis]:
        key = hypothesis_fingerprint(question_id, statement)
        for h in self._hypotheses.values():
            if h.fingerprint == key:
                return h
        return None

    def count(self) -> int:
        return len(self._hypotheses)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM hypotheses").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise HypothesisStoreIntegrityError(
                    f"Failed to load persisted hypotheses from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise HypothesisStoreIntegrityError(
                        "Hypothesis row checksum mismatch (corrupt or partial write)"
                    )
                data = json.loads(payload)
                h = Hypothesis.from_dict(data)
                self._hypotheses[h.hypothesis_id] = h
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise HypothesisStoreIntegrityError(
                        f"Failed to load persisted hypotheses from {self.db_path}: {e}"
                    ) from e
