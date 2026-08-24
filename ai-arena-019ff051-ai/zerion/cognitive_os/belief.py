"""
Slice 3 — Belief & Belief Revision.

A Belief is a structured, versioned epistemic state. Revision rules are explicit,
deterministic and inspectable:

- Model output alone can never confirm a belief (MODEL_GENERATED evidence is
  recorded for provenance but never applied).
- Every applied piece of evidence changes confidence by an explicit rule:
      supporting:      conf += (1 - conf) * weight * support_rate
      contradicting:   conf -= conf * weight * contradiction_rate
      weight = reliability * MODE_WEIGHT[mode]
- A strong contradiction (weight >= strong_contradiction_weight) flips the
  status to CONTRADICTED.
- Every revision records the previous and new belief state, the evidence, the
  reason, a timestamp and the source. Old beliefs are never silently overwritten
  (the full history is preserved in ``revision_history``).
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from zerion.cognitive_os.evidence import (
    Evidence,
    EvidenceMode,
    EvidenceVerdict,
    MODE_WEIGHT,
)


class BeliefLifecycle(str, Enum):
    UNKNOWN = "UNKNOWN"
    HYPOTHESIS = "HYPOTHESIS"
    PREDICTED = "PREDICTED"
    SUPPORTED = "SUPPORTED"
    WEAKENED = "WEAKENED"
    CONTRADICTED = "CONTRADICTED"
    CONFIRMED = "CONFIRMED"


class BeliefValidationError(ValueError):
    """Raised for structurally invalid beliefs."""


class BeliefStoreIntegrityError(RuntimeError):
    """Raised when persisted belief data is corrupt and strict loading is enabled."""


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Any) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def _clamp01(value: Any, name: str) -> float:
    f = float(value)
    if not (0.0 <= f <= 1.0):
        raise BeliefValidationError(f"Belief {name} must be in [0.0, 1.0], got {f!r}")
    return f


def belief_fingerprint(statement: str, source: str) -> str:
    norm = re.sub(r"\s+", " ", statement.lower()).strip()
    key = f"{source}|{norm}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class Belief:
    belief_id: str = field(default_factory=lambda: f"bel_{uuid.uuid4().hex[:10]}")
    statement: str = ""
    source: str = "runtime"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    confidence: float = 0.3            # [0.0, 1.0]
    status: BeliefLifecycle = BeliefLifecycle.UNKNOWN
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    predictions: List[str] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    contradiction_history: List[Dict[str, Any]] = field(default_factory=list)
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    related_hypotheses: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    def __post_init__(self):
        self.statement = _clean_text(self.statement)
        if not self.statement:
            raise BeliefValidationError("Belief statement must not be empty")
        self.source = _clean_text(self.source)
        if isinstance(self.status, str):
            self.status = BeliefLifecycle(self.status)
        self.confidence = _clamp01(self.confidence, "confidence")
        if not self.fingerprint:
            self.fingerprint = belief_fingerprint(self.statement, self.source)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "belief_id": self.belief_id,
            "statement": self.statement,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "confidence": round(self.confidence, 6),
            "status": self.status.value,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "predictions": self.predictions,
            "observations": self.observations,
            "contradiction_history": self.contradiction_history,
            "revision_history": self.revision_history,
            "related_hypotheses": self.related_hypotheses,
            "provenance": self.provenance,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Belief":
        status = data.get("status", BeliefLifecycle.UNKNOWN.value)
        try:
            status = BeliefLifecycle(status)
        except ValueError:
            status = BeliefLifecycle.UNKNOWN
        return cls(
            belief_id=data.get("belief_id", f"bel_{uuid.uuid4().hex[:10]}"),
            statement=data.get("statement", ""),
            source=data.get("source", "runtime"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            confidence=float(data.get("confidence", 0.3)),
            status=status,
            supporting_evidence=list(data.get("supporting_evidence", [])),
            contradicting_evidence=list(data.get("contradicting_evidence", [])),
            predictions=list(data.get("predictions", [])),
            observations=list(data.get("observations", [])),
            contradiction_history=list(data.get("contradiction_history", [])),
            revision_history=list(data.get("revision_history", [])),
            related_hypotheses=list(data.get("related_hypotheses", [])),
            provenance=dict(data.get("provenance", {})),
            fingerprint=data.get("fingerprint", ""),
        )


class BeliefRevision:
    """Explicit, deterministic, inspectable belief-update rules."""

    def __init__(self, support_rate: float = 0.5,
                 contradiction_rate: float = 0.6,
                 confirm_threshold: float = 0.85,
                 supported_threshold: float = 0.6,
                 weakened_threshold: float = 0.2,
                 strong_contradiction_weight: float = 0.75):
        self.support_rate = support_rate
        self.contradiction_rate = contradiction_rate
        self.confirm_threshold = confirm_threshold
        self.supported_threshold = supported_threshold
        self.weakened_threshold = weakened_threshold
        self.strong_contradiction_weight = strong_contradiction_weight

    def apply(self, belief: Belief, evidence: Evidence) -> Tuple[Belief, Dict[str, Any]]:
        """Apply one evidence item to a belief. Returns (belief, revision_record).

        The revision record always contains the previous and new belief state, the
        evidence id, the reason, a timestamp and the source. Evidence that must not
        influence belief (model output, stale, duplicate, neutral) is still recorded
        — never silently dropped — with ``applied=False`` on the evidence.
        """
        previous_conf = belief.confidence
        previous_status = belief.status
        reason = ""
        weight = 0.0
        applied = False

        mode = evidence.provenance.mode
        verdict = evidence.verdict

        if mode == EvidenceMode.MODEL_GENERATED:
            reason = "model output alone cannot revise a belief"
        elif evidence.stale:
            reason = "stale evidence (observed long before recorded) not applied"
        elif evidence.applied:
            reason = "duplicate evidence already applied"
        elif verdict in (EvidenceVerdict.NEUTRAL, EvidenceVerdict.MIXED):
            reason = f"no decisive signal (verdict={verdict.value})"
        else:
            weight = evidence.provenance.reliability * MODE_WEIGHT[mode]
            if weight <= 0.0:
                reason = f"zero-weight evidence mode ({mode.value})"
            else:
                applied = True
                if verdict == EvidenceVerdict.SUPPORTS:
                    belief.confidence += (1.0 - belief.confidence) * weight * self.support_rate
                    reason = f"supporting {mode.value} evidence (weight={weight:.3f})"
                    if evidence.evidence_id not in belief.supporting_evidence:
                        belief.supporting_evidence.append(evidence.evidence_id)
                elif verdict == EvidenceVerdict.CONTRADICTS:
                    belief.confidence -= belief.confidence * weight * self.contradiction_rate
                    reason = f"contradicting {mode.value} evidence (weight={weight:.3f})"
                    if evidence.evidence_id not in belief.contradicting_evidence:
                        belief.contradicting_evidence.append(evidence.evidence_id)
                    belief.contradiction_history.append({
                        "evidence_id": evidence.evidence_id,
                        "verdict": verdict.value,
                        "weight": round(weight, 6),
                        "at": time.time(),
                    })
                belief.confidence = min(0.98, max(0.02, belief.confidence))

        evidence.applied = applied
        if not applied and evidence.reject_reason == "":
            evidence.reject_reason = reason

        new_status = self._recompute_status(belief, evidence, applied, weight)
        belief.status = new_status
        belief.updated_at = time.time()

        revision = {
            "previous_confidence": round(previous_conf, 6),
            "previous_status": previous_status.value,
            "new_confidence": round(belief.confidence, 6),
            "new_status": belief.status.value,
            "evidence_id": evidence.evidence_id,
            "evidence_mode": mode.value,
            "verdict": verdict.value,
            "weight": round(weight, 6),
            "reason": reason,
            "applied": applied,
            "timestamp": time.time(),
            "source": evidence.provenance.source,
        }
        belief.revision_history.append(revision)
        return belief, revision

    def _recompute_status(self, belief: Belief, evidence: Evidence,
                          applied: bool, weight: float) -> BeliefLifecycle:
        if not applied:
            return belief.status
        # Strong contradiction always marks the belief CONTRADICTED.
        if (evidence.verdict == EvidenceVerdict.CONTRADICTS
                and weight >= self.strong_contradiction_weight):
            return BeliefLifecycle.CONTRADICTED
        conf = belief.confidence
        if (conf >= self.confirm_threshold
                and evidence.provenance.mode == EvidenceMode.OBSERVED
                and evidence.verdict == EvidenceVerdict.SUPPORTS
                and belief.supporting_evidence):
            return BeliefLifecycle.CONFIRMED
        if conf >= self.supported_threshold:
            return BeliefLifecycle.SUPPORTED
        if conf <= self.weakened_threshold:
            return BeliefLifecycle.WEAKENED
        if belief.status in (BeliefLifecycle.UNKNOWN, BeliefLifecycle.HYPOTHESIS,
                             BeliefLifecycle.PREDICTED):
            return belief.status
        return BeliefLifecycle.WEAKENED


class BeliefStore:
    """SQLite WAL-backed store for Beliefs (corruption-safe, same pattern as the
    Slice 1/2 stores). DB ``beliefs.db`` — no legacy collision. Revision history
    is persisted inside each belief document and survives restarts."""

    def __init__(self, db_path: Optional[str] = "data/beliefs.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._beliefs: Dict[str, Belief] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS beliefs (
                    belief_id TEXT PRIMARY KEY,
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

    def put(self, belief: Belief) -> Belief:
        self._beliefs[belief.belief_id] = belief
        if not self.db_path:
            return belief
        payload = json.dumps(belief.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO beliefs VALUES (?, ?, ?, ?, ?)",
                (belief.belief_id, payload, self._checksum(payload),
                 belief.status.value, belief.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return belief

    def get(self, belief_id: str) -> Optional[Belief]:
        return self._beliefs.get(belief_id)

    def get_by_fingerprint(self, statement: str, source: str) -> Optional[Belief]:
        key = belief_fingerprint(statement, source)
        for b in self._beliefs.values():
            if b.fingerprint == key:
                return b
        return None

    def list(self, status: Optional[BeliefLifecycle] = None) -> List[Belief]:
        beliefs = list(self._beliefs.values())
        if status is not None:
            beliefs = [b for b in beliefs if b.status == status]
        return sorted(beliefs, key=lambda b: b.created_at)

    def list_for_hypothesis(self, hypothesis_id: str) -> List[Belief]:
        return sorted(
            [b for b in self._beliefs.values() if hypothesis_id in b.related_hypotheses],
            key=lambda b: b.created_at,
        )

    def count(self) -> int:
        return len(self._beliefs)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM beliefs").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise BeliefStoreIntegrityError(
                    f"Failed to load persisted beliefs from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise BeliefStoreIntegrityError(
                        "Belief row checksum mismatch (corrupt or partial write)")
                data = json.loads(payload)
                b = Belief.from_dict(data)
                self._beliefs[b.belief_id] = b
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise BeliefStoreIntegrityError(
                        f"Failed to load persisted beliefs from {self.db_path}: {e}"
                    ) from e
