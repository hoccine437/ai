"""
Slice 4 — DistilledExperience.

A reusable knowledge item distilled from episodes: invariant, procedure, warning,
decision rule, causal pattern, failure prevention rule or reusable strategy.
A distilled item is NEVER promoted to truth at creation — it starts as a CANDIDATE
and can only become VALIDATED after evidence (repeatability, counterexample check,
confidence calculation). Causal items stay CAUSAL_HYPOTHESIS unless OBSERVED
experimental evidence supports them: correlation is never converted into causation
automatically.
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


class DistilledType(str, Enum):
    INVARIANT = "INVARIANT"
    PROCEDURE = "PROCEDURE"
    WARNING = "WARNING"
    DECISION_RULE = "DECISION_RULE"
    CAUSAL_PATTERN = "CAUSAL_PATTERN"
    FAILURE_PREVENTION_RULE = "FAILURE_PREVENTION_RULE"
    REUSABLE_STRATEGY = "REUSABLE_STRATEGY"


class ValidationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    WEAKENED = "WEAKENED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class CausalityStatus(str, Enum):
    """How certain the item's causal claim is. CAUSAL_HYPOTHESIS is the default:
    correlation is never converted into causation automatically."""
    CAUSAL_HYPOTHESIS = "CAUSAL_HYPOTHESIS"
    CORRELATIONAL = "CORRELATIONAL"
    CONFIRMED_CAUSAL = "CONFIRMED_CAUSAL"


class DistilledValidationError(ValueError):
    """Raised for structurally invalid distilled items."""


class DistilledStoreIntegrityError(RuntimeError):
    """Raised when persisted distilled items are corrupt and strict loading is enabled."""


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Any) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def _clean_str_list(values: Any) -> List[str]:
    if not values:
        return []
    return [_clean_text(v) for v in values if _clean_text(v)]


def distilled_fingerprint(dtype: DistilledType, statement: str,
                          conditions: str) -> str:
    norm_stmt = re.sub(r"\s+", " ", statement.lower()).strip()
    norm_cond = re.sub(r"\s+", " ", conditions.lower()).strip()
    key = f"{dtype.value}|{norm_stmt}|{norm_cond}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class DistilledExperience:
    id: str = field(default_factory=lambda: f"dis_{uuid.uuid4().hex[:10]}")
    type: DistilledType = DistilledType.PROCEDURE
    statement: str = ""
    conditions: str = ""                 # when this item applies
    action: str = ""                     # what to do (procedure / prevention rule)
    expected_outcome: str = ""
    evidence: List[str] = field(default_factory=list)          # evidence/observation ids
    confidence: float = 0.3              # [0.0, 1.0] — computed, never assumed
    source_episodes: List[str] = field(default_factory=list)   # episode_ids
    counterexamples: List[str] = field(default_factory=list)   # episode_ids that contradict
    validation_status: ValidationStatus = ValidationStatus.CANDIDATE
    causality_status: CausalityStatus = CausalityStatus.CAUSAL_HYPOTHESIS
    provenance: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    fingerprint: str = ""
    times_used: int = 0                  # retrieval/reuse history (historical usefulness)
    times_successful: int = 0

    def __post_init__(self):
        self.statement = _clean_text(self.statement)
        if not self.statement:
            raise DistilledValidationError("Distilled statement must not be empty")
        if isinstance(self.type, str):
            self.type = DistilledType(self.type)
        if isinstance(self.validation_status, str):
            self.validation_status = ValidationStatus(self.validation_status)
        if isinstance(self.causality_status, str):
            self.causality_status = CausalityStatus(self.causality_status)
        self.conditions = _clean_text(self.conditions)
        self.action = _clean_text(self.action)
        self.expected_outcome = _clean_text(self.expected_outcome)
        self.evidence = _clean_str_list(self.evidence)
        self.source_episodes = _clean_str_list(self.source_episodes)
        self.counterexamples = _clean_str_list(self.counterexamples)
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise DistilledValidationError(
                f"Distilled confidence must be in [0.0, 1.0], got {self.confidence!r}")
        if not self.fingerprint:
            self.fingerprint = distilled_fingerprint(self.type, self.statement,
                                                     self.conditions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "statement": self.statement,
            "conditions": self.conditions,
            "action": self.action,
            "expected_outcome": self.expected_outcome,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 6),
            "source_episodes": self.source_episodes,
            "counterexamples": self.counterexamples,
            "validation_status": self.validation_status.value,
            "causality_status": self.causality_status.value,
            "provenance": self.provenance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision_history": self.revision_history,
            "fingerprint": self.fingerprint,
            "times_used": self.times_used,
            "times_successful": self.times_successful,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistilledExperience":
        dtype = data.get("type", DistilledType.PROCEDURE.value)
        try:
            dtype = DistilledType(dtype)
        except ValueError:
            dtype = DistilledType.PROCEDURE
        vstatus = data.get("validation_status", ValidationStatus.CANDIDATE.value)
        try:
            vstatus = ValidationStatus(vstatus)
        except ValueError:
            vstatus = ValidationStatus.CANDIDATE
        cstatus = data.get("causality_status", CausalityStatus.CAUSAL_HYPOTHESIS.value)
        try:
            cstatus = CausalityStatus(cstatus)
        except ValueError:
            cstatus = CausalityStatus.CAUSAL_HYPOTHESIS
        return cls(
            id=data.get("id", f"dis_{uuid.uuid4().hex[:10]}"),
            type=dtype,
            statement=data.get("statement", ""),
            conditions=data.get("conditions", ""),
            action=data.get("action", ""),
            expected_outcome=data.get("expected_outcome", ""),
            evidence=list(data.get("evidence", [])),
            confidence=float(data.get("confidence", 0.3)),
            source_episodes=list(data.get("source_episodes", [])),
            counterexamples=list(data.get("counterexamples", [])),
            validation_status=vstatus,
            causality_status=cstatus,
            provenance=dict(data.get("provenance", {})),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            revision_history=list(data.get("revision_history", [])),
            fingerprint=data.get("fingerprint", ""),
            times_used=int(data.get("times_used", 0)),
            times_successful=int(data.get("times_successful", 0)),
        )


class DistilledExperienceStore:
    """SQLite WAL-backed store for DistilledExperience (corruption-safe, same
    pattern as the Slice 1-3 stores). DB ``distilled_experiences.db`` — no legacy
    collision. Procedural knowledge (PROCEDURE/REUSABLE_STRATEGY) and validated
    rules live here, separate from episodic and failure knowledge."""

    def __init__(self, db_path: Optional[str] = "data/distilled_experiences.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._items: Dict[str, DistilledExperience] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS distilled (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    validation_status TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, item: DistilledExperience) -> DistilledExperience:
        self._items[item.id] = item
        if not self.db_path:
            return item
        payload = json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO distilled VALUES (?, ?, ?, ?, ?)",
                (item.id, payload, self._checksum(payload),
                 item.validation_status.value, item.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return item

    def get(self, item_id: str) -> Optional[DistilledExperience]:
        return self._items.get(item_id)

    def get_by_fingerprint(self, fingerprint: str) -> Optional[DistilledExperience]:
        for item in self._items.values():
            if item.fingerprint == fingerprint:
                return item
        return None

    def list(self, status: Optional[ValidationStatus] = None,
             dtype: Optional[DistilledType] = None) -> List[DistilledExperience]:
        items = list(self._items.values())
        if status is not None:
            items = [i for i in items if i.validation_status == status]
        if dtype is not None:
            items = [i for i in items if i.type == dtype]
        return sorted(items, key=lambda i: i.confidence, reverse=True)

    def count(self) -> int:
        return len(self._items)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM distilled").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise DistilledStoreIntegrityError(
                    f"Failed to load persisted distilled items from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise DistilledStoreIntegrityError(
                        "Distilled row checksum mismatch (corrupt or partial write)")
                data = json.loads(payload)
                item = DistilledExperience.from_dict(data)
                self._items[item.id] = item
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise DistilledStoreIntegrityError(
                        f"Failed to load persisted distilled items from {self.db_path}: {e}"
                    ) from e
