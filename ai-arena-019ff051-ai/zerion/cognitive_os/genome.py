"""
Slice 7 — CognitiveGenome.

The runtime's CONFIGURATION (policies), not model weights. Each genome has
genome_id, parent_id, version, created_at, configuration, evaluation_results
and a status: CANDIDATE -> TESTING -> VALIDATED -> PROMOTED | REJECTED |
DEPRECATED. Random configuration changes are not "evolution" — a candidate is
only promoted after deterministic benchmark evaluation against the current
genome, and the production genome is never mutated during experimentation
(candidates are clones).

The legacy ``zerion/cognitive_genome/`` (22-dimension genome for the legacy
25-stage engine, its own GenomeManager) is left untouched; this is the Slice
1–7 runtime's policy genome.
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

DEFAULT_GENOME_CONFIG: Dict[str, Any] = {
    "reasoning_strategy": "balanced",
    "attention_policy": {"capacity_slots": 3},
    "memory_policy": {"retention": 0.5},
    "verification_policy": {"strictness": 0.5},
    "routing_policy": {"prefer_local": False, "policy_version": 6},
    "planning_policy": {"depth": 2},
    "question_generation_policy": {"rate": 0.7},
    "experiment_policy": {"max_attempts": 2},
    "capability_registry_version": 1,
    "architecture_version": 1,
}


class GenomeStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    TESTING = "TESTING"
    VALIDATED = "VALIDATED"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class GenomeIntegrityError(RuntimeError):
    pass


def fingerprint_config(config: Dict[str, Any]) -> str:
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class CognitiveGenome:
    configuration: Dict[str, Any] = field(default_factory=dict)
    genome_id: str = field(default_factory=lambda: f"genome_{uuid.uuid4().hex[:10]}")
    parent_id: Optional[str] = None
    version: int = 1
    created_at: float = field(default_factory=time.time)
    evaluation_results: Dict[str, Any] = field(default_factory=dict)
    status: GenomeStatus = GenomeStatus.CANDIDATE

    def __post_init__(self):
        if not self.configuration:
            self.configuration = json.loads(json.dumps(DEFAULT_GENOME_CONFIG))

    def fingerprint(self) -> str:
        return fingerprint_config(self.configuration)

    def clone(self) -> "CognitiveGenome":
        return CognitiveGenome(
            configuration=json.loads(json.dumps(self.configuration)),
            parent_id=self.genome_id,
            version=self.version + 1,
            status=GenomeStatus.CANDIDATE,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "genome_id": self.genome_id,
            "parent_id": self.parent_id,
            "version": self.version,
            "created_at": self.created_at,
            "configuration": self.configuration,
            "evaluation_results": self.evaluation_results,
            "status": self.status.value,
            "fingerprint": self.fingerprint(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveGenome":
        return cls(
            configuration=data.get("configuration", {}),
            genome_id=data.get("genome_id", f"genome_{uuid.uuid4().hex[:10]}"),
            parent_id=data.get("parent_id"),
            version=data.get("version", 1),
            created_at=data.get("created_at", time.time()),
            evaluation_results=data.get("evaluation_results", {}),
            status=GenomeStatus(data.get("status", "CANDIDATE")),
        )


def apply_changes(config: Dict[str, Any], changes: Dict[str, Any],
                  allow_new_keys: bool = True) -> Dict[str, Any]:
    """Deep-ish merge of changes into a config copy. Nested dict values are
    merged one level; scalars replace. Never mutates the input."""
    out = json.loads(json.dumps(config))
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            merged = dict(out[key])
            merged.update(value)
            out[key] = merged
        else:
            if not allow_new_keys and key not in out:
                raise ValueError(f"unknown configuration key: {key}")
            out[key] = value
    return out


class GenomeStore:
    """SQLite-WAL + SHA-256 persistence for genomes."""

    def __init__(self, db_path: Optional[str] = "data/genomes.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._genomes: Dict[str, CognitiveGenome] = {}
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
            CREATE TABLE IF NOT EXISTS genomes (
                genome_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                status TEXT,
                created_at REAL
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, genome: CognitiveGenome) -> CognitiveGenome:
        self._genomes[genome.genome_id] = genome
        if not self.db_path:
            return genome
        payload = json.dumps(genome.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("INSERT OR REPLACE INTO genomes VALUES (?, ?, ?, ?, ?)",
                         (genome.genome_id, payload, self._checksum(payload),
                          genome.status.value, genome.created_at))
            conn.commit()
        finally:
            conn.close()
        return genome

    def get(self, genome_id: str) -> Optional[CognitiveGenome]:
        return self._genomes.get(genome_id)

    def list(self, status: Optional[GenomeStatus] = None) -> List[CognitiveGenome]:
        gens = list(self._genomes.values())
        if status is not None:
            gens = [g for g in gens if g.status == status]
        return sorted(gens, key=lambda g: g.created_at)

    def promoted(self) -> Optional[CognitiveGenome]:
        promoted = [g for g in self._genomes.values()
                    if g.status == GenomeStatus.PROMOTED]
        if not promoted:
            return None
        return max(promoted, key=lambda g: g.version)

    def count(self) -> int:
        return len(self._genomes)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT payload, checksum FROM genomes").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise GenomeIntegrityError(
                    f"Failed to load genomes from {self.db_path}: {e}") from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise GenomeIntegrityError(
                        "genome row checksum mismatch (corrupt write)")
                data = json.loads(payload)
                self._genomes[data["genome_id"]] = CognitiveGenome.from_dict(data)
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise GenomeIntegrityError(
                        f"Failed to load genomes from {self.db_path}: {e}") from e


class GenomeManager:
    """Controlled candidate evaluation: CURRENT -> PROPOSE_VARIATION -> TEST ->
    BENCHMARK -> COMPARE -> PROMOTE/REJECT. The production genome is never
    mutated during experimentation — candidates are clones."""

    def __init__(self, store: Optional[GenomeStore] = None):
        self.store = store or GenomeStore(db_path=None)
        self._ensure_current()

    def _ensure_current(self) -> None:
        if self.store.promoted() is None:
            current = CognitiveGenome(status=GenomeStatus.PROMOTED, version=1)
            self.store.put(current)

    def current(self) -> CognitiveGenome:
        g = self.store.promoted()
        if g is None:
            self._ensure_current()
            g = self.store.promoted()
        return g

    def propose_variation(self, changes: Dict[str, Any],
                          allow_new_keys: bool = False) -> CognitiveGenome:
        current = self.current()
        config = apply_changes(current.configuration, changes,
                               allow_new_keys=allow_new_keys)
        candidate = current.clone()
        candidate.configuration = config
        candidate.status = GenomeStatus.CANDIDATE
        self.store.put(candidate)
        return candidate

    def record_evaluation(self, genome_id: str,
                          evaluation: Dict[str, Any]) -> CognitiveGenome:
        g = self.store.get(genome_id)
        if g is None:
            raise KeyError(f"unknown genome {genome_id}")
        g.evaluation_results = dict(evaluation)
        g.status = GenomeStatus.VALIDATED
        self.store.put(g)
        return g

    def promote(self, genome_id: str) -> CognitiveGenome:
        g = self.store.get(genome_id)
        if g is None:
            raise KeyError(f"unknown genome {genome_id}")
        if g.status not in (GenomeStatus.CANDIDATE, GenomeStatus.VALIDATED):
            raise ValueError(f"cannot promote genome in status {g.status.value}")
        if not g.evaluation_results:
            raise ValueError("cannot promote a genome with no evaluation evidence")
        # Demote the previous production genome (kept for rollback).
        prev = self.store.promoted()
        if prev is not None and prev.genome_id != g.genome_id:
            prev.status = GenomeStatus.DEPRECATED
            self.store.put(prev)
        g.status = GenomeStatus.PROMOTED
        self.store.put(g)
        return g

    def reject(self, genome_id: str, reason: str = "") -> CognitiveGenome:
        g = self.store.get(genome_id)
        if g is None:
            raise KeyError(f"unknown genome {genome_id}")
        g.status = GenomeStatus.REJECTED
        g.evaluation_results["rejection_reason"] = reason
        self.store.put(g)
        return g

    def rollback_to(self, genome: CognitiveGenome) -> CognitiveGenome:
        """Restore a previously-promoted genome (rollback target)."""
        prev = self.store.promoted()
        if prev is not None and prev.genome_id != genome.genome_id:
            prev.status = GenomeStatus.DEPRECATED
            self.store.put(prev)
        genome.status = GenomeStatus.PROMOTED
        self.store.put(genome)
        return genome
