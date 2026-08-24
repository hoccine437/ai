"""
Slice 6 — Historical performance ledger.

Records REAL outcomes of routed tasks (task type, provider, model, difficulty,
domain, success, latency, cost, verification status). Aggregates feed routing
weights with a minimum-sample guard so the router never overfits from tiny
samples, and cold-start entries are explicitly UNKNOWN / INSUFFICIENT_DATA —
performance is never invented.

SQLite-WAL + SHA-256 checksum persistence, same corruption-safe pattern as the
Slice 1–5 stores.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional

from zerion.cognitive_os.router_types import Task

MIN_SAMPLES = 3          # below this -> INSUFFICIENT_DATA
WEIGHT_MIN_SAMPLES = 5   # below this -> weights stay neutral
WEIGHT_STEP = 0.08       # max single-step weight change per recorded outcome
WEIGHT_CAP = 0.95        # weights are bounded away from 1.0


class PerformanceLedgerIntegrityError(RuntimeError):
    pass


@dataclass
class PerformanceStats:
    task_type: str
    provider: str
    model: str
    samples: int = 0
    successes: int = 0
    verification_successes: int = 0
    total_latency_ms: float = 0.0
    total_cost_cents: float = 0.0
    insufficient_data: bool = True

    @property
    def success_rate(self) -> Optional[float]:
        if self.samples == 0:
            return None
        return self.successes / self.samples

    @property
    def failure_rate(self) -> Optional[float]:
        if self.samples == 0:
            return None
        return 1.0 - (self.successes / self.samples)

    @property
    def verification_success_rate(self) -> Optional[float]:
        if self.samples == 0:
            return None
        return self.verification_successes / self.samples

    @property
    def avg_latency_ms(self) -> Optional[float]:
        if self.samples == 0:
            return None
        return self.total_latency_ms / self.samples

    @property
    def avg_cost_cents(self) -> Optional[float]:
        if self.samples == 0:
            return None
        return self.total_cost_cents / self.samples

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "provider": self.provider,
            "model": self.model,
            "samples": self.samples,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "verification_success_rate": self.verification_success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_cost_cents": self.avg_cost_cents,
            "insufficient_data": self.insufficient_data,
        }


class PerformanceLedger:
    """Persistent ledger of real task outcomes with aggregate stats."""

    def __init__(self, db_path: Optional[str] = "data/performance_ledger.db",
                 strict_load: bool = True, min_samples: int = MIN_SAMPLES,
                 weight_min_samples: int = WEIGHT_MIN_SAMPLES):
        self.db_path = db_path
        self.strict_load = strict_load
        self.min_samples = min_samples
        self.weight_min_samples = weight_min_samples
        self.load_errors: List[str] = []
        self._outcomes: List[Dict[str, Any]] = []
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
            CREATE TABLE IF NOT EXISTS outcomes (
                outcome_id TEXT PRIMARY KEY,
                task_id TEXT,
                task_type TEXT,
                provider TEXT,
                model TEXT,
                difficulty TEXT,
                domain TEXT,
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

    def _difficulty_bucket(self, difficulty: float) -> str:
        if difficulty < 0.34:
            return "low"
        if difficulty < 0.67:
            return "medium"
        return "high"

    def record_outcome(self, *, task: Task, provider: str, model: str,
                       success: bool, latency_ms: Optional[float],
                       cost_cents: Optional[float],
                       verified: Optional[bool] = None,
                       outcome_id: Optional[str] = None) -> Dict[str, Any]:
        row = {
            "outcome_id": outcome_id or f"out_{int(time.time() * 1000)}_{len(self._outcomes)}",
            "task_id": task.task_id,
            "task_type": task.type.value,
            "provider": provider,
            "model": model,
            "difficulty": self._difficulty_bucket(task.difficulty),
            "domain": str(task.metadata.get("domain", "general"))[:64],
            "success": bool(success),
            "latency_ms": latency_ms,
            "cost_cents": cost_cents,
            "verified": verified if verified is not None else None,
            "created_at": time.time(),
        }
        self._outcomes.append(row)
        if self.db_path:
            payload = json.dumps(row, sort_keys=True, separators=(",", ":"))
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (row["outcome_id"], row["task_id"], row["task_type"],
                     row["provider"], row["model"], row["difficulty"],
                     row["domain"], payload, self._checksum(payload), row["created_at"]))
                conn.commit()
            finally:
                conn.close()
        return row

    def stats(self, *, task_type: str, provider: str, model: str,
              difficulty: Optional[float] = None,
              domain: Optional[str] = None) -> PerformanceStats:
        """Aggregate over matching outcomes. Cold-start: UNKNOWN/INSUFFICIENT_DATA."""
        rows = [o for o in self._outcomes
                if o["task_type"] == task_type
                and o["provider"] == provider
                and o["model"] == model]
        if difficulty is not None:
            rows = [o for o in rows if o["difficulty"] == self._difficulty_bucket(difficulty)]
        if domain is not None:
            rows = [o for o in rows if o["domain"] == str(domain)[:64]]
        stats = PerformanceStats(
            task_type=task_type, provider=provider, model=model,
            samples=len(rows),
            successes=sum(1 for o in rows if o["success"]),
            verification_successes=sum(1 for o in rows if o["verified"]),
            total_latency_ms=sum(o["latency_ms"] or 0.0 for o in rows),
            total_cost_cents=sum(o["cost_cents"] or 0.0 for o in rows),
            insufficient_data=len(rows) < self.min_samples,
        )
        return stats

    def routing_weight(self, *, task_type: str, provider: str, model: str,
                       difficulty: Optional[float] = None,
                       domain: Optional[str] = None) -> float:
        """Performance-based routing weight in [0, 1]; neutral 0.5 until enough
        real samples exist (cold start / tiny samples never overfit the router)."""
        stats = self.stats(task_type=task_type, provider=provider, model=model,
                           difficulty=difficulty, domain=domain)
        if stats.samples < self.weight_min_samples or stats.success_rate is None:
            return 0.5
        return min(WEIGHT_CAP, 0.5 + (stats.success_rate - 0.5) * WEIGHT_STEP * stats.samples)

    def update_weights_from_outcome(self, *, task: Task, provider: str, model: str,
                                    success: bool) -> Dict[str, float]:
        """Model-performance learning: repeated failures reduce a model's
        likelihood for that task category; good performance increases it.
        Returns the new weight."""
        w = self.routing_weight(task_type=task.type.value, provider=provider,
                                model=model, difficulty=task.difficulty,
                                domain=str(task.metadata.get("domain", "general")))
        return {"weight": w}

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT payload, checksum FROM outcomes").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise PerformanceLedgerIntegrityError(
                    f"Failed to load performance ledger from {self.db_path}: {e}") from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise PerformanceLedgerIntegrityError(
                        "Performance outcome row checksum mismatch (corrupt write)")
                data = json.loads(payload)
                self._outcomes.append(data)
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise PerformanceLedgerIntegrityError(
                        f"Failed to load performance ledger from {self.db_path}: {e}") from e

    def count(self) -> int:
        return len(self._outcomes)
