"""
Developmental Timeline & Reproducible Snapshots Substrate
Allows historical reconstruction of what the system knew, believed, predicted, and learned;
provides reproducible snapshot creation, branching, comparison, and rollback.
"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class DevelopmentSnapshot:
    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:8]}")
    code_version: str = "3.0.0-genesis-x10"
    memory_version: int = 1
    strategy_version: int = 1
    capability_version: int = 1
    genome_version: int = 1
    world_model_hash: str = ""
    identity_hash: str = ""
    total_capabilities: Optional[int] = None
    total_strategies: Optional[int] = None
    brier_score: Optional[float] = None      # None = NOT_MEASURED, never fabricated
    maturity_level: Optional[str] = None     # None = NOT_MEASURED, never fabricated
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def _metric(value: Any) -> Dict[str, Any]:
        if value is None:
            return {"value": None, "measurement_status": "NOT_MEASURED"}
        if isinstance(value, float):
            return {"value": round(value, 4), "measurement_status": "MEASURED"}
        return {"value": value, "measurement_status": "MEASURED"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "code_version": self.code_version,
            "memory_version": self.memory_version,
            "strategy_version": self.strategy_version,
            "capability_version": self.capability_version,
            "genome_version": self.genome_version,
            "world_model_hash": self.world_model_hash,
            "identity_hash": self.identity_hash,
            "total_capabilities": self._metric(self.total_capabilities),
            "total_strategies": self._metric(self.total_strategies),
            "brier_score": self._metric(self.brier_score),
            "maturity_level": self._metric(self.maturity_level),
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


class DevelopmentTimelineManager:
    def __init__(self, db_path: Optional[str] = "data/timeline.db"):
        self.db_path = db_path
        self._snapshots: List[DevelopmentSnapshot] = []
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS timeline_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    genome_version INTEGER,
                    maturity_level TEXT,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.commit()
            conn.close()

    def capture_snapshot(
        self,
        engine_instance: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DevelopmentSnapshot:
        snap_id = f"snap_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        
        g_ver = getattr(engine_instance.genome_manager.current_genome, "version", 1) if hasattr(engine_instance, "genome_manager") else 1
        id_hash = engine_instance.identity.get_identity_hash() if hasattr(engine_instance, "identity") else "hash_id"
        caps_cnt = len(engine_instance.self_model._capabilities) if hasattr(engine_instance, "self_model") else None
        strats_cnt = len(engine_instance.strategy_registry.list_strategies()) if hasattr(engine_instance, "strategy_registry") else None

        # Real measured values only. When a measurement is unavailable it stays
        # None (NOT_MEASURED) — never a fabricated 0.02 / L6 placeholder.
        brier = None
        calibrator = getattr(getattr(engine_instance, "self_model", None), "calibrator", None)
        if calibrator is not None and hasattr(calibrator, "calculate_brier_score"):
            brier = calibrator.calculate_brier_score()
        maturity_level = None
        mat_eval = getattr(engine_instance, "maturity_evaluator", None)
        if mat_eval is not None and hasattr(mat_eval, "evaluate_from_evidence"):
            try:
                from zerion.runtime.evidence import collect_runtime_evidence
                mat = mat_eval.evaluate_from_evidence(collect_runtime_evidence(engine_instance))
                maturity_level = mat.current_level.value
            except Exception:  # noqa: BLE001 — honest NOT_MEASURED on any failure
                maturity_level = None

        snapshot = DevelopmentSnapshot(
            snapshot_id=snap_id,
            genome_version=g_ver,
            identity_hash=id_hash,
            total_capabilities=caps_cnt,
            total_strategies=strats_cnt,
            brier_score=brier,
            maturity_level=maturity_level,
            metadata=metadata or {}
        )
        self._snapshots.append(snapshot)
        self._persist(snapshot)
        return snapshot

    def restore_snapshot(self, snapshot_id: str) -> Optional[DevelopmentSnapshot]:
        for s in self._snapshots:
            if s.snapshot_id == snapshot_id:
                return s
        return None

    def _persist(self, s: DevelopmentSnapshot):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO timeline_snapshots VALUES (?, ?, ?, ?, ?)",
            (s.snapshot_id, s.genome_version, s.maturity_level, json.dumps(s.to_dict()), s.timestamp)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM timeline_snapshots ORDER BY timestamp ASC").fetchall():
                d = json.loads(row[0])
                self._snapshots.append(DevelopmentSnapshot(
                    snapshot_id=d["snapshot_id"],
                    code_version=d.get("code_version", "3.0.0"),
                    memory_version=d.get("memory_version", 1),
                    strategy_version=d.get("strategy_version", 1),
                    capability_version=d.get("capability_version", 1),
                    genome_version=d.get("genome_version", 1),
                    world_model_hash=d.get("world_model_hash", ""),
                    identity_hash=d.get("identity_hash", ""),
                    total_capabilities=d.get("total_capabilities"),
                    total_strategies=d.get("total_strategies"),
                    brier_score=d.get("brier_score"),
                    maturity_level=d.get("maturity_level"),
                    timestamp=d.get("timestamp", time.time()),
                    metadata=d.get("metadata", {})
                ))
            conn.close()
        except Exception:
            pass
