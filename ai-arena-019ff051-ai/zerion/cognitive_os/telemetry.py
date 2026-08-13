"""
Slice 7 — ArchitectureTelemetry.

Real measurements only. Every metric is a counted (successes, failures, total)
with optional latency sums and raw values. Rates are only reported once a
minimum sample count is reached; below that the metric is UNKNOWN /
INSUFFICIENT_DATA — metrics are never invented.

Metrics tracked per component (with a success outcome when applicable):
  latency, failure_rate, timeout_rate, tool_success, verification_success,
  memory_retrieval_success, knowledge_retrieval_success, planning_success,
  model_success, routing_success, capability_success, resource_usage,
  recovery_rate, generic task_success.

Persisted with the SQLite-WAL + SHA-256 checksum pattern (Slices 1–6).
"""

import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional

MIN_SAMPLES = 3  # below this, rates are INSUFFICIENT_DATA

# Success-counted metrics: (name, description)
SUCCESS_METRICS = {
    "tool_success", "verification_success", "memory_retrieval_success",
    "knowledge_retrieval_success", "planning_success", "model_success",
    "routing_success", "capability_success", "recovery_rate", "task_success",
}
VALUE_METRICS = {"latency", "resource_usage", "failure_rate", "timeout_rate"}


class TelemetryIntegrityError(RuntimeError):
    pass


class ComponentMetric:
    def __init__(self, component: str, metric: str):
        self.component = component
        self.metric = metric
        self.total = 0
        self.successes = 0
        self.latency_sum_ms = 0.0
        self.value_sum = 0.0

    def record(self, *, success: Optional[bool] = None,
               latency_ms: Optional[float] = None,
               value: Optional[float] = None) -> None:
        self.total += 1
        if success is not None:
            self.successes += int(bool(success))
        if latency_ms is not None:
            self.latency_sum_ms += float(latency_ms)
        if value is not None:
            self.value_sum += float(value)

    def rate(self) -> Optional[float]:
        """Success rate for success metrics; UNKNOWN (None) below min samples."""
        if self.total < MIN_SAMPLES:
            return None
        return self.successes / self.total

    def failure_rate(self) -> Optional[float]:
        r = self.rate()
        return None if r is None else (1.0 - r)

    def avg_latency_ms(self) -> Optional[float]:
        if self.total < MIN_SAMPLES:
            return None
        return round(self.latency_sum_ms / self.total, 6)

    def avg_value(self) -> Optional[float]:
        if self.total < MIN_SAMPLES:
            return None
        return round(self.value_sum / self.total, 6)

    def to_dict(self) -> Dict[str, Any]:
        r = self.rate()
        return {
            "component": self.component,
            "metric": self.metric,
            "total": self.total,
            "successes": self.successes,
            "rate": r,
            "failure_rate": (None if r is None else 1.0 - r),
            "avg_latency_ms": self.avg_latency_ms(),
            "avg_value": self.avg_value(),
            "sufficient_data": self.total >= MIN_SAMPLES,
        }


class ArchitectureTelemetry:
    """Persisted per-component metric collector."""

    def __init__(self, db_path: Optional[str] = "data/telemetry.db",
                 strict_load: bool = True, min_samples: int = MIN_SAMPLES):
        self.db_path = db_path
        self.strict_load = strict_load
        self.min_samples = min_samples
        self.load_errors: List[str] = []
        self._metrics: Dict[tuple, ComponentMetric] = {}
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
            CREATE TABLE IF NOT EXISTS metrics (
                component TEXT,
                metric TEXT,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                updated_at REAL,
                PRIMARY KEY (component, metric)
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # -- recording ----------------------------------------------------------

    def record(self, component: str, metric: str, *,
               success: Optional[bool] = None,
               latency_ms: Optional[float] = None,
               value: Optional[float] = None) -> None:
        if not component or not metric:
            raise ValueError("component and metric are required")
        key = (component, metric)
        m = self._metrics.get(key)
        if m is None:
            m = ComponentMetric(component, metric)
            self._metrics[key] = m
        m.record(success=success, latency_ms=latency_ms, value=value)
        self._persist(key, m)

    def _persist(self, key: tuple, m: ComponentMetric):
        if not self.db_path:
            return
        payload = json.dumps(m.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO metrics VALUES (?, ?, ?, ?, ?)",
                (key[0], key[1], payload, self._checksum(payload), time.time()))
            conn.commit()
        finally:
            conn.close()

    # -- queries ------------------------------------------------------------

    def get(self, component: str, metric: str) -> Optional[ComponentMetric]:
        return self._metrics.get((component, metric))

    def rate(self, component: str, metric: str) -> Optional[float]:
        m = self.get(component, metric)
        return None if m is None else m.rate()

    def failure_rate(self, component: str, metric: str) -> Optional[float]:
        m = self.get(component, metric)
        return None if m is None else m.failure_rate()

    def avg_latency_ms(self, component: str, metric: str) -> Optional[float]:
        m = self.get(component, metric)
        return None if m is None else m.avg_latency_ms()

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for (component, metric), m in sorted(self._metrics.items()):
            out.setdefault(component, {})[metric] = m.to_dict()
        return out

    # -- persistence --------------------------------------------------------

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT component, metric, payload, checksum "
                                "FROM metrics").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise TelemetryIntegrityError(
                    f"Failed to load telemetry from {self.db_path}: {e}") from e
            return
        for component, metric, payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise TelemetryIntegrityError(
                        "telemetry row checksum mismatch (corrupt write)")
                data = json.loads(payload)
                m = ComponentMetric(component, metric)
                m.total = data.get("total", 0)
                m.successes = data.get("successes", 0)
                m.latency_sum_ms = data.get("avg_latency_ms", 0.0) * m.total
                m.value_sum = (data.get("avg_value") or 0.0) * m.total
                self._metrics[(component, metric)] = m
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise TelemetryIntegrityError(
                        f"Failed to load telemetry from {self.db_path}: {e}") from e
