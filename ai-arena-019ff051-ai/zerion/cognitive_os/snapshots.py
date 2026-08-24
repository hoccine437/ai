"""
Slice 7 — Versioned runtime snapshots.

Every approved change produces a snapshot that captures the PREVIOUS known-good
state before anything is applied, plus the approval state, tests, benchmark
results and a rollback reference. Rollback restores the previous snapshot.
Snapshot creation is atomic: the snapshot row is written (and verified) BEFORE
the production mutation is applied, so a crash mid-promotion never leaves a
partially-promoted state. A snapshot is never called "better" without evidence.
"""

import hashlib
import json
import time
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


class SnapshotIntegrityError(RuntimeError):
    pass


class RuntimeSnapshot:
    def __init__(self, *, version: int, timestamp: float,
                 changed_components: List[str],
                 configuration: Dict[str, Any],
                 tests: List[Dict[str, Any]],
                 benchmark_results: Dict[str, Any],
                 approval_state: Dict[str, Any],
                 rollback_reference: str = "",
                 label: str = ""):
        self.version = version
        self.timestamp = timestamp
        self.changed_components = list(changed_components)
        self.configuration = configuration
        self.tests = list(tests)
        self.benchmark_results = dict(benchmark_results)
        self.approval_state = dict(approval_state)
        self.rollback_reference = rollback_reference
        self.label = label

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "changed_components": list(self.changed_components),
            "configuration": self.configuration,
            "tests": list(self.tests),
            "benchmark_results": self.benchmark_results,
            "approval_state": self.approval_state,
            "rollback_reference": self.rollback_reference,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSnapshot":
        return cls(
            version=data["version"],
            timestamp=data.get("timestamp", time.time()),
            changed_components=data.get("changed_components", []),
            configuration=data.get("configuration", {}),
            tests=data.get("tests", []),
            benchmark_results=data.get("benchmark_results", {}),
            approval_state=data.get("approval_state", {}),
            rollback_reference=data.get("rollback_reference", ""),
            label=data.get("label", ""),
        )


class SnapshotStore:
    """SQLite-WAL + SHA-256 persistence for runtime snapshots."""

    def __init__(self, db_path: Optional[str] = "data/snapshots.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._snapshots: Dict[int, RuntimeSnapshot] = {}
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
            CREATE TABLE IF NOT EXISTS snapshots (
                version INTEGER PRIMARY KEY,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                created_at REAL
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def next_version(self) -> int:
        return (max(self._snapshots) + 1) if self._snapshots else 1

    def put(self, snapshot: RuntimeSnapshot) -> RuntimeSnapshot:
        self._snapshots[snapshot.version] = snapshot
        if not self.db_path:
            return snapshot
        payload = json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?)",
                         (snapshot.version, payload, self._checksum(payload),
                          snapshot.timestamp))
            conn.commit()
        finally:
            conn.close()
        return snapshot

    def get(self, version: int) -> Optional[RuntimeSnapshot]:
        return self._snapshots.get(version)

    def latest(self) -> Optional[RuntimeSnapshot]:
        if not self._snapshots:
            return None
        return self._snapshots[max(self._snapshots)]

    def list(self) -> List[RuntimeSnapshot]:
        return [self._snapshots[v] for v in sorted(self._snapshots)]

    def count(self) -> int:
        return len(self._snapshots)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT payload, checksum FROM snapshots").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise SnapshotIntegrityError(
                    f"Failed to load snapshots from {self.db_path}: {e}") from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise SnapshotIntegrityError(
                        "snapshot row checksum mismatch (corrupt write)")
                data = json.loads(payload)
                self._snapshots[data["version"]] = RuntimeSnapshot.from_dict(data)
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise SnapshotIntegrityError(
                        f"Failed to load snapshots from {self.db_path}: {e}") from e
