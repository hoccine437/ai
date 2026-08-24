"""
Slice 4 — FailureLearning.

Every meaningful failure produces a structured FailureRecord. Root causes are
NEVER assumed: a failure creates a root-cause hypothesis (UNCONFIRMED until
evidence supports it, REJECTED when contradicted). Repeated identical failures
are detected via fingerprint: each recurrence increments repeat_count, emits
FAILURE_REPEATED, and after an escalation threshold publishes
REPEATED_FAILURE_DETECTED so the Slice 2 question field + Slice 1 attention
economy investigate it — the runtime does not endlessly repeat the same strategy
without escalation.
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


class FailureClassification(str, Enum):
    TOOL_FAILURE = "TOOL_FAILURE"
    MODEL_FAILURE = "MODEL_FAILURE"
    PLANNING_FAILURE = "PLANNING_FAILURE"
    MEMORY_FAILURE = "MEMORY_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    RESOURCE_FAILURE = "RESOURCE_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class FailureStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"


class RootCauseStatus(str, Enum):
    PROPOSED = "PROPOSED"            # hypothesis created, no evidence yet
    UNCONFIRMED = "UNCONFIRMED"      # evidence insufficient — never a fabricated cause
    CONFIRMED = "CONFIRMED"          # recurrence + no counterexamples
    REJECTED = "REJECTED"            # contradicted by counterexamples


class FailureValidationError(ValueError):
    """Raised for structurally invalid failure records."""


class FailureStoreIntegrityError(RuntimeError):
    """Raised when persisted failure data is corrupt and strict loading is enabled."""


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Any) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def _clean_str_list(values: Any) -> List[str]:
    if not values:
        return []
    return [_clean_text(v) for v in values if _clean_text(v)]


def failure_fingerprint(action: str, error: str) -> str:
    """Deterministic recurrence key: same action + normalized error = same failure."""
    norm_action = re.sub(r"\s+", " ", action.lower()).strip()
    norm_error = re.sub(r"\s+", " ", error.lower()).strip()
    key = f"{norm_action}|{norm_error}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class RootCauseHypothesis:
    hypothesis_id: str = field(default_factory=lambda: f"rc_{uuid.uuid4().hex[:10]}")
    failure_id: str = ""
    statement: str = ""
    signals: List[str] = field(default_factory=list)   # environment-observed signals
    confidence: float = 0.2                            # [0.0, 1.0]
    status: RootCauseStatus = RootCauseStatus.PROPOSED
    supporting_episodes: List[str] = field(default_factory=list)
    contradicting_episodes: List[str] = field(default_factory=list)
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.statement = _clean_text(self.statement)
        if not self.statement:
            raise FailureValidationError("Root cause statement must not be empty")
        if isinstance(self.status, str):
            self.status = RootCauseStatus(self.status)
        self.signals = _clean_str_list(self.signals)
        self.supporting_episodes = _clean_str_list(self.supporting_episodes)
        self.contradicting_episodes = _clean_str_list(self.contradicting_episodes)
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise FailureValidationError("Root cause confidence must be in [0.0, 1.0]")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "failure_id": self.failure_id,
            "statement": self.statement,
            "signals": self.signals,
            "confidence": round(self.confidence, 6),
            "status": self.status.value,
            "supporting_episodes": self.supporting_episodes,
            "contradicting_episodes": self.contradicting_episodes,
            "revision_history": self.revision_history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseHypothesis":
        status = data.get("status", RootCauseStatus.PROPOSED.value)
        try:
            status = RootCauseStatus(status)
        except ValueError:
            status = RootCauseStatus.PROPOSED
        return cls(
            hypothesis_id=data.get("hypothesis_id", f"rc_{uuid.uuid4().hex[:10]}"),
            failure_id=data.get("failure_id", ""),
            statement=data.get("statement", ""),
            signals=list(data.get("signals", [])),
            confidence=float(data.get("confidence", 0.2)),
            status=status,
            supporting_episodes=list(data.get("supporting_episodes", [])),
            contradicting_episodes=list(data.get("contradicting_episodes", [])),
            revision_history=list(data.get("revision_history", [])),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


@dataclass
class FailureRecord:
    failure_id: str = field(default_factory=lambda: f"fail_{uuid.uuid4().hex[:10]}")
    episode_id: str = ""
    classification: FailureClassification = FailureClassification.UNKNOWN_FAILURE
    context: str = ""
    action: str = ""
    error: str = ""
    signals: List[str] = field(default_factory=list)     # observed by the environment
    root_cause_hypothesis_id: Optional[str] = None
    recovery_attempt: str = ""
    recovery_result: str = ""
    lesson: str = ""
    prevention_rule: str = ""
    evidence: List[str] = field(default_factory=list)    # evidence/observation ids
    confidence: float = 0.2                              # [0.0, 1.0]
    repeat_count: int = 1
    episodes: List[str] = field(default_factory=list)    # all episodes sharing this failure
    status: FailureStatus = FailureStatus.OPEN
    fingerprint: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.context = _clean_text(self.context)
        self.action = _clean_text(self.action)
        self.error = _clean_text(self.error)
        if not self.action:
            raise FailureValidationError("Failure action must not be empty")
        if not self.error:
            raise FailureValidationError("Failure error must not be empty")
        if isinstance(self.classification, str):
            self.classification = FailureClassification(self.classification)
        if isinstance(self.status, str):
            self.status = FailureStatus(self.status)
        self.signals = _clean_str_list(self.signals)
        self.evidence = _clean_str_list(self.evidence)
        self.episodes = _clean_str_list(self.episodes)
        self.recovery_attempt = _clean_text(self.recovery_attempt)
        self.recovery_result = _clean_text(self.recovery_result)
        self.lesson = _clean_text(self.lesson)
        self.prevention_rule = _clean_text(self.prevention_rule)
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise FailureValidationError("Failure confidence must be in [0.0, 1.0]")
        if not self.fingerprint:
            self.fingerprint = failure_fingerprint(self.action, self.error)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "episode_id": self.episode_id,
            "classification": self.classification.value,
            "context": self.context,
            "action": self.action,
            "error": self.error,
            "signals": self.signals,
            "root_cause_hypothesis_id": self.root_cause_hypothesis_id,
            "recovery_attempt": self.recovery_attempt,
            "recovery_result": self.recovery_result,
            "lesson": self.lesson,
            "prevention_rule": self.prevention_rule,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 6),
            "repeat_count": self.repeat_count,
            "episodes": self.episodes,
            "status": self.status.value,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailureRecord":
        classification = data.get("classification", FailureClassification.UNKNOWN_FAILURE.value)
        try:
            classification = FailureClassification(classification)
        except ValueError:
            classification = FailureClassification.UNKNOWN_FAILURE
        status = data.get("status", FailureStatus.OPEN.value)
        try:
            status = FailureStatus(status)
        except ValueError:
            status = FailureStatus.OPEN
        return cls(
            failure_id=data.get("failure_id", f"fail_{uuid.uuid4().hex[:10]}"),
            episode_id=data.get("episode_id", ""),
            classification=classification,
            context=data.get("context", ""),
            action=data.get("action", ""),
            error=data.get("error", ""),
            signals=list(data.get("signals", [])),
            root_cause_hypothesis_id=data.get("root_cause_hypothesis_id"),
            recovery_attempt=data.get("recovery_attempt", ""),
            recovery_result=data.get("recovery_result", ""),
            lesson=data.get("lesson", ""),
            prevention_rule=data.get("prevention_rule", ""),
            evidence=list(data.get("evidence", [])),
            confidence=float(data.get("confidence", 0.2)),
            repeat_count=int(data.get("repeat_count", 1)),
            episodes=list(data.get("episodes", [])),
            status=status,
            fingerprint=data.get("fingerprint", ""),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


class FailureStore:
    """SQLite WAL-backed store for FailureRecords and RootCauseHypotheses
    (corruption-safe, same pattern as the Slice 1-3 stores). DB ``failures.db``
    — no legacy collision. Failure knowledge lives here, separate from episodic
    and procedural knowledge."""

    def __init__(self, db_path: Optional[str] = "data/failures.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._failures: Dict[str, FailureRecord] = {}
        self._root_causes: Dict[str, RootCauseHypothesis] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS failures (
                    failure_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    repeat_count INTEGER,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS root_causes (
                    hypothesis_id TEXT PRIMARY KEY,
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

    def put_failure(self, failure: FailureRecord) -> FailureRecord:
        self._failures[failure.failure_id] = failure
        if not self.db_path:
            return failure
        payload = json.dumps(failure.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO failures VALUES (?, ?, ?, ?, ?)",
                (failure.failure_id, payload, self._checksum(payload),
                 failure.repeat_count, failure.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return failure

    def put_root_cause(self, hypothesis: RootCauseHypothesis) -> RootCauseHypothesis:
        self._root_causes[hypothesis.hypothesis_id] = hypothesis
        if not self.db_path:
            return hypothesis
        payload = json.dumps(hypothesis.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO root_causes VALUES (?, ?, ?, ?, ?)",
                (hypothesis.hypothesis_id, payload, self._checksum(payload),
                 hypothesis.status.value, hypothesis.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return hypothesis

    def get_failure(self, failure_id: str) -> Optional[FailureRecord]:
        return self._failures.get(failure_id)

    def get_root_cause(self, hypothesis_id: str) -> Optional[RootCauseHypothesis]:
        return self._root_causes.get(hypothesis_id)

    def get_failure_by_fingerprint(self, fingerprint: str) -> Optional[FailureRecord]:
        for f in self._failures.values():
            if f.fingerprint == fingerprint:
                return f
        return None

    def list_failures(self, status: Optional[FailureStatus] = None) -> List[FailureRecord]:
        fails = list(self._failures.values())
        if status is not None:
            fails = [f for f in fails if f.status == status]
        return sorted(fails, key=lambda f: f.created_at)

    def list_root_causes(self, status: Optional[RootCauseStatus] = None) -> List[RootCauseHypothesis]:
        causes = list(self._root_causes.values())
        if status is not None:
            causes = [c for c in causes if c.status == status]
        return sorted(causes, key=lambda c: c.created_at)

    def count_failures(self) -> int:
        return len(self._failures)

    def count_root_causes(self) -> int:
        return len(self._root_causes)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            frows = conn.execute(
                "SELECT payload, checksum FROM failures").fetchall()
            rrows = conn.execute(
                "SELECT payload, checksum FROM root_causes").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise FailureStoreIntegrityError(
                    f"Failed to load persisted failures from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in frows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise FailureStoreIntegrityError(
                        "Failure row checksum mismatch (corrupt or partial write)")
                f = FailureRecord.from_dict(json.loads(payload))
                self._failures[f.failure_id] = f
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise FailureStoreIntegrityError(
                        f"Failed to load persisted failures from {self.db_path}: {e}"
                    ) from e
        for payload, stored_checksum in rrows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise FailureStoreIntegrityError(
                        "Root cause row checksum mismatch (corrupt or partial write)")
                rc = RootCauseHypothesis.from_dict(json.loads(payload))
                self._root_causes[rc.hypothesis_id] = rc
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise FailureStoreIntegrityError(
                        f"Failed to load persisted failures from {self.db_path}: {e}"
                    ) from e


class FailureLearning:
    """Recurrence detection + root-cause lifecycle. Deterministic and
    evidence-driven: the observed signals come from the environment, the
    recurrence/counterexample counts come from the evidence, and the conclusion
    is never hard-coded."""

    def __init__(self, failure_store: FailureStore,
                 escalation_repeat_threshold: int = 3):
        self.store = failure_store
        self.escalation_repeat_threshold = escalation_repeat_threshold

    def record_failure(self, *, episode_id: str, action: str, error: str,
                       context: str = "",
                       classification: FailureClassification = FailureClassification.UNKNOWN_FAILURE,
                       signals: Optional[List[str]] = None,
                       signal_reliability: float = 0.9,
                       recovery_attempt: str = "",
                       recovery_result: str = "",
                       evidence: Optional[List[str]] = None) -> Dict[str, Any]:
        """Record one failure occurrence. Returns metadata describing what
        happened: created vs recurrence, repeat_count, whether escalation fired."""
        fingerprint = failure_fingerprint(action, error)
        existing = self.store.get_failure_by_fingerprint(fingerprint)
        if existing is not None:
            existing.repeat_count += 1
            if episode_id not in existing.episodes:
                existing.episodes.append(episode_id)
            existing.updated_at = time.time()
            # Recurrence strengthens the root-cause hypothesis for this failure.
            rc = self._refresh_root_cause(existing, signal_reliability,
                                          added_episode=episode_id)
            self.store.put_failure(existing)
            if rc is not None:
                self.store.put_root_cause(rc)
            escalated = existing.repeat_count >= self.escalation_repeat_threshold
            return {"created": False, "failure": existing, "root_cause": rc,
                    "repeat_count": existing.repeat_count, "escalated": escalated}

        failure = FailureRecord(
            episode_id=episode_id,
            classification=classification,
            context=context,
            action=action,
            error=error,
            signals=signals or [],
            recovery_attempt=recovery_attempt,
            recovery_result=recovery_result,
            evidence=evidence or [],
            confidence=round(min(1.0, signal_reliability * 0.5 + 0.1), 6),
            episodes=[episode_id],
        )
        self.store.put_failure(failure)
        root_cause = self._propose_root_cause(failure, signal_reliability)
        failure.root_cause_hypothesis_id = root_cause.hypothesis_id
        self.store.put_failure(failure)
        self.store.put_root_cause(root_cause)
        return {"created": True, "failure": failure, "root_cause": root_cause,
                "repeat_count": 1, "escalated": False}

    def _propose_root_cause(self, failure: FailureRecord,
                            reliability: float) -> RootCauseHypothesis:
        """A root cause is a HYPOTHESIS: it names the environment-observed
        signals, never assumes them, and starts UNCONFIRMED — not a fabricated
        cause. The statement is a generic template over the observed signals, so
        no specific cause (e.g. 'authentication expiration') is ever hard-coded."""
        signals = failure.signals or ["the reported error"]
        statement = (f"The failure of '{failure.action}' is explained by the "
                     f"observed signals: {', '.join(signals)}.")
        return RootCauseHypothesis(
            failure_id=failure.failure_id,
            statement=statement,
            signals=failure.signals,
            confidence=round(min(1.0, reliability * 0.4 + 0.1), 6),
            status=RootCauseStatus.UNCONFIRMED,
            supporting_episodes=[failure.episode_id],
            revision_history=[{
                "event": "proposed", "at": time.time(),
                "status": RootCauseStatus.UNCONFIRMED.value,
                "confidence": round(reliability * 0.4 + 0.1, 6),
                "evidence": "single occurrence — insufficient, not assumed",
            }],
        )

    def _refresh_root_cause(self, failure: FailureRecord, reliability: float,
                            added_episode: str) -> Optional[RootCauseHypothesis]:
        """Recurrence of the same failure with the same signals increases root
        cause confidence. A counterexample episode (recorded via
        add_counterexample) decreases it and can reject the hypothesis."""
        rc = self.store.get_root_cause(failure.root_cause_hypothesis_id or "")
        if rc is None:
            return None
        previous = (rc.confidence, rc.status)
        rc.confidence = min(1.0, rc.confidence + reliability * 0.1)
        if added_episode not in rc.supporting_episodes:
            rc.supporting_episodes.append(added_episode)
        if (failure.repeat_count >= 3 and not rc.contradicting_episodes
                and rc.confidence >= 0.6):
            rc.status = RootCauseStatus.CONFIRMED
        elif rc.contradicting_episodes:
            rc.status = RootCauseStatus.REJECTED
        rc.updated_at = time.time()
        rc.revision_history.append({
            "event": "recurrence" if failure.repeat_count > 1 else "revision",
            "at": time.time(),
            "repeat_count": failure.repeat_count,
            "previous_status": previous[1].value,
            "new_status": rc.status.value,
            "previous_confidence": round(previous[0], 6),
            "new_confidence": round(rc.confidence, 6),
        })
        return rc

    def add_counterexample(self, failure_id: str, episode_id: str,
                           contradiction_strength: float = 0.5) -> RootCauseHypothesis:
        """A contradictory experience weakens the root cause; a strong
        contradiction rejects it (the first explanation is not assumed correct)."""
        failure = self.store.get_failure(failure_id)
        if failure is None:
            raise KeyError(f"Unknown failure {failure_id}")
        rc = self.store.get_root_cause(failure.root_cause_hypothesis_id or "")
        if rc is None:
            raise KeyError(f"Unknown root cause for {failure_id}")
        previous = rc.status
        rc.confidence = max(0.0, rc.confidence - contradiction_strength)
        if episode_id not in rc.contradicting_episodes:
            rc.contradicting_episodes.append(episode_id)
        if rc.confidence < 0.25 or len(rc.contradicting_episodes) >= 1:
            rc.status = RootCauseStatus.REJECTED
        rc.updated_at = time.time()
        rc.revision_history.append({
            "event": "counterexample", "at": time.time(),
            "episode_id": episode_id,
            "previous_status": previous.value,
            "new_status": rc.status.value,
            "confidence": round(rc.confidence, 6),
        })
        self.store.put_root_cause(rc)
        self.store.put_failure(failure)
        return rc
