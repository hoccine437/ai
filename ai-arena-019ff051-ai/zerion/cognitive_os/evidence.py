"""
Slice 3 — Evidence & Provenance.

Every important observation/evidence identifies its source, timestamp, type,
content/reference, experiment (when applicable), reliability and mode. The
OBSERVED / SIMULATED / TEST / MODEL_GENERATED distinction is mandatory:

- OBSERVED          real-world / tool / system evidence (can confirm beliefs)
- SIMULATED         simulation or prediction only — NOT reality evidence
- TEST              mock / unit-test evidence — explicitly marked as mock
- MODEL_GENERATED   model output — recorded for provenance, NEVER applied to belief

Evidence is DATA with provenance. Fabricated, duplicate, stale or mode-lying
evidence is rejected or flagged before it can influence belief.
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


class EvidenceMode(str, Enum):
    OBSERVED = "OBSERVED"
    SIMULATED = "SIMULATED"
    TEST = "TEST"
    MODEL_GENERATED = "MODEL_GENERATED"


class EvidenceVerdict(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


# How much a unit of evidence influences belief, by mode. OBSERVED is the only
# mode that can confirm; MODEL_GENERATED is never applied (provenance only).
MODE_WEIGHT: Dict[EvidenceMode, float] = {
    EvidenceMode.OBSERVED: 1.0,
    EvidenceMode.TEST: 0.4,
    EvidenceMode.SIMULATED: 0.2,
    EvidenceMode.MODEL_GENERATED: 0.0,
}


class EvidenceValidationError(ValueError):
    """Raised for structurally invalid, fabricated or mode-lying evidence."""


class EvidenceStoreIntegrityError(RuntimeError):
    """Raised when persisted evidence is corrupt and strict loading is enabled."""


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Any) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def _clean_content(content: Dict[str, Any]) -> Dict[str, Any]:
    """Strip control characters from every string inside evidence content so
    stored evidence can never corrupt a document or be executed as a command."""
    cleaned: Dict[str, Any] = {}
    for key, value in (content or {}).items():
        if isinstance(value, str):
            cleaned[_clean_text(key)] = _clean_text(value)
        elif isinstance(value, list):
            cleaned[_clean_text(key)] = [
                _clean_text(v) if isinstance(v, str) else v for v in value
            ]
        elif isinstance(value, dict):
            cleaned[_clean_text(key)] = _clean_content(value)
        else:
            cleaned[_clean_text(key)] = value
    return cleaned


def evidence_fingerprint(experiment_id: Optional[str], hypothesis_ids: List[str],
                         belief_ids: List[str], content: Dict[str, Any],
                         mode: EvidenceMode, verdict: EvidenceVerdict) -> str:
    """Deterministic dedup key. Duplicate evidence is rejected, never double-applied."""
    key = json.dumps({
        "experiment_id": experiment_id,
        "hypothesis_ids": sorted(hypothesis_ids),
        "belief_ids": sorted(belief_ids),
        "content": content,
        "mode": mode.value,
        "verdict": verdict.value,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class Provenance:
    """Every evidence item must identify where it came from."""
    source: str
    observed_at: float
    evidence_type: str
    content_reference: str
    reliability: float            # [0.0, 1.0]
    mode: EvidenceMode
    recorded_at: float
    experiment_id: Optional[str] = None

    def __post_init__(self):
        self.source = _clean_text(self.source)
        if not self.source:
            raise EvidenceValidationError("Provenance source must not be empty")
        self.evidence_type = _clean_text(self.evidence_type)
        self.content_reference = _clean_text(self.content_reference)
        if not (0.0 <= float(self.reliability) <= 1.0):
            raise EvidenceValidationError(
                f"Provenance reliability must be in [0.0, 1.0], got {self.reliability!r}")
        if isinstance(self.mode, str):
            self.mode = EvidenceMode(self.mode)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "observed_at": self.observed_at,
            "evidence_type": self.evidence_type,
            "content_reference": self.content_reference,
            "reliability": round(self.reliability, 6),
            "mode": self.mode.value,
            "recorded_at": self.recorded_at,
            "experiment_id": self.experiment_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Provenance":
        mode = EvidenceMode(data.get("mode", EvidenceMode.OBSERVED.value))
        try:
            mode = EvidenceMode(mode)
        except ValueError:
            mode = EvidenceMode.OBSERVED
        return cls(
            source=data.get("source", ""),
            observed_at=float(data.get("observed_at", time.time())),
            evidence_type=data.get("evidence_type", "observation"),
            content_reference=data.get("content_reference", ""),
            reliability=float(data.get("reliability", 0.9)),
            mode=mode,
            recorded_at=float(data.get("recorded_at", time.time())),
            experiment_id=data.get("experiment_id"),
        )


@dataclass
class Evidence:
    evidence_id: str = field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:10]}")
    content: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[Provenance] = None
    verdict: EvidenceVerdict = EvidenceVerdict.NEUTRAL
    experiment_id: Optional[str] = None
    hypothesis_ids: List[str] = field(default_factory=list)
    belief_ids: List[str] = field(default_factory=list)
    related_predictions: List[str] = field(default_factory=list)
    fingerprint: str = ""
    stale: bool = False
    applied: bool = False          # did belief revision actually apply it
    reject_reason: str = ""        # why it was NOT applied (model output, stale, ...)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.content:
            raise EvidenceValidationError("Evidence content must not be empty")
        self.content = _clean_content(self.content)
        if self.provenance is None:
            raise EvidenceValidationError("Evidence must carry provenance")
        if isinstance(self.verdict, str):
            self.verdict = EvidenceVerdict(self.verdict)
        if not self.fingerprint:
            self.fingerprint = evidence_fingerprint(
                self.experiment_id, self.hypothesis_ids, self.belief_ids,
                self.content, self.provenance.mode, self.verdict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "content": self.content,
            "provenance": self.provenance.to_dict(),
            "verdict": self.verdict.value,
            "experiment_id": self.experiment_id,
            "hypothesis_ids": self.hypothesis_ids,
            "belief_ids": self.belief_ids,
            "related_predictions": self.related_predictions,
            "fingerprint": self.fingerprint,
            "stale": self.stale,
            "applied": self.applied,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        prov = Provenance.from_dict(data.get("provenance", {}))
        return cls(
            evidence_id=data.get("evidence_id", f"ev_{uuid.uuid4().hex[:10]}"),
            content=dict(data.get("content", {})),
            provenance=prov,
            verdict=EvidenceVerdict(data.get("verdict", EvidenceVerdict.NEUTRAL.value)),
            experiment_id=data.get("experiment_id"),
            hypothesis_ids=list(data.get("hypothesis_ids", [])),
            belief_ids=list(data.get("belief_ids", [])),
            related_predictions=list(data.get("related_predictions", [])),
            fingerprint=data.get("fingerprint", ""),
            stale=bool(data.get("stale", False)),
            applied=bool(data.get("applied", False)),
            reject_reason=data.get("reject_reason", ""),
            created_at=float(data.get("created_at", time.time())),
        )


class EvidenceStore:
    """SQLite WAL-backed store for Evidence (corruption-safe: per-row SHA-256
    checksum, load_errors, strict_load — same pattern as the Slice 1/2 stores).

    DB is ``cognitive_evidence.db`` to avoid colliding with the legacy engine's
    ``evidence.db`` (zerion/evidence/engine.py)."""

    def __init__(self, db_path: Optional[str] = "data/cognitive_evidence.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._evidence: Dict[str, Evidence] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    verdict TEXT,
                    created_at REAL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_experiment ON evidence (payload)"
            )
            conn.commit()
            conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, evidence: Evidence) -> Evidence:
        self._evidence[evidence.evidence_id] = evidence
        if not self.db_path:
            return evidence
        payload = json.dumps(evidence.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?)",
                (evidence.evidence_id, payload, self._checksum(payload),
                 evidence.verdict.value, evidence.created_at)
            )
            conn.commit()
        finally:
            conn.close()
        return evidence

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return self._evidence.get(evidence_id)

    def get_by_fingerprint(self, fingerprint: str) -> Optional[Evidence]:
        for e in self._evidence.values():
            if e.fingerprint == fingerprint:
                return e
        return None

    def list(self) -> List[Evidence]:
        return sorted(self._evidence.values(), key=lambda e: e.created_at)

    def list_for_hypothesis(self, hypothesis_id: str) -> List[Evidence]:
        return sorted(
            [e for e in self._evidence.values() if hypothesis_id in e.hypothesis_ids],
            key=lambda e: e.created_at,
        )

    def list_for_belief(self, belief_id: str) -> List[Evidence]:
        return sorted(
            [e for e in self._evidence.values() if belief_id in e.belief_ids],
            key=lambda e: e.created_at,
        )

    def count(self) -> int:
        return len(self._evidence)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM evidence").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise EvidenceStoreIntegrityError(
                    f"Failed to load persisted evidence from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise EvidenceStoreIntegrityError(
                        "Evidence row checksum mismatch (corrupt or partial write)")
                data = json.loads(payload)
                e = Evidence.from_dict(data)
                self._evidence[e.evidence_id] = e
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise EvidenceStoreIntegrityError(
                        f"Failed to load persisted evidence from {self.db_path}: {e}"
                    ) from e
