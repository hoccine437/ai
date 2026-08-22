"""
Slice 7 — BottleneckDetector.

Identifies which component is actually limiting system performance, from
REAL telemetry only. A bottleneck is never declared merely because a component
exists — the detector requires sufficient evidence (min samples) and a metric
beyond a configurable threshold. Output is a structured BottleneckReport with
evidence, frequency, severity, confidence, affected tasks and a recommended
investigation.

Possible outputs: MODEL_LIMITATION, MEMORY_LIMITATION, TOOL_LIMITATION,
PLANNING_LIMITATION, VERIFICATION_LIMITATION, KNOWLEDGE_LIMITATION,
RESOURCE_LIMITATION, ROUTING_LIMITATION, CAPABILITY_LIMITATION,
ARCHITECTURAL_LIMITATION, UNKNOWN.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set

from zerion.cognitive_os.telemetry import ArchitectureTelemetry

# Metric -> (bottleneck type, "low rate is bad" | "high rate is bad").
_DETECTOR_MAP = {
    "verification_success": ("VERIFICATION_LIMITATION", "low"),
    "model_success": ("MODEL_LIMITATION", "low"),
    "memory_retrieval_success": ("MEMORY_LIMITATION", "low"),
    "knowledge_retrieval_success": ("KNOWLEDGE_LIMITATION", "low"),
    "tool_success": ("TOOL_LIMITATION", "low"),
    "planning_success": ("PLANNING_LIMITATION", "low"),
    "routing_success": ("ROUTING_LIMITATION", "low"),
    "capability_success": ("CAPABILITY_LIMITATION", "low"),
    "recovery_rate": ("ARCHITECTURAL_LIMITATION", "low"),
}

DEFAULT_THRESHOLDS = {
    "verification_success": 0.5,
    "model_success": 0.5,
    "memory_retrieval_success": 0.5,
    "knowledge_retrieval_success": 0.5,
    "tool_success": 0.5,
    "planning_success": 0.5,
    "routing_success": 0.5,
    "capability_success": 0.5,
    "recovery_rate": 0.5,
    # Value-based signals:
    "latency_ms": 1000.0,          # avg latency above this -> RESOURCE_LIMITATION
    "resource_usage": 0.85,        # avg utilization above this -> RESOURCE_LIMITATION
    "failure_rate": 0.5,           # generic failure rate above this
    "timeout_rate": 0.3,           # timeout rate above this
}

MIN_SAMPLES = 5  # stricter than raw telemetry: bottlenecks need real evidence


class BottleneckType(str):
    pass


BOTTLENECK_TYPES = (
    "MODEL_LIMITATION", "MEMORY_LIMITATION", "TOOL_LIMITATION",
    "PLANNING_LIMITATION", "VERIFICATION_LIMITATION", "KNOWLEDGE_LIMITATION",
    "RESOURCE_LIMITATION", "ROUTING_LIMITATION", "CAPABILITY_LIMITATION",
    "ARCHITECTURAL_LIMITATION", "UNKNOWN",
)


class BottleneckIntegrityError(RuntimeError):
    pass


@dataclass
class BottleneckReport:
    id: str = field(default_factory=lambda: f"bn_{uuid.uuid4().hex[:10]}")
    type: str = "UNKNOWN"
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    affected_component: str = ""
    frequency: float = 0.0
    severity: float = 0.0
    confidence: float = 0.0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    affected_tasks: List[str] = field(default_factory=list)
    estimated_impact: str = ""
    recommended_investigation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "evidence": list(self.evidence),
            "affected_component": self.affected_component,
            "frequency": self.frequency,
            "severity": self.severity,
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "affected_tasks": list(self.affected_tasks),
            "estimated_impact": self.estimated_impact,
            "recommended_investigation": self.recommended_investigation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BottleneckReport":
        known = {k: data.get(k) for k in (
            "id", "type", "evidence", "affected_component", "frequency",
            "severity", "confidence", "first_seen", "last_seen",
            "affected_tasks", "estimated_impact", "recommended_investigation")}
        return cls(**known)


class BottleneckStore:
    """SQLite-WAL + SHA-256 persistence for bottleneck reports."""

    def __init__(self, db_path: Optional[str] = "data/bottlenecks.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._reports: Dict[str, BottleneckReport] = {}
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
            CREATE TABLE IF NOT EXISTS bottlenecks (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                last_seen REAL
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, report: BottleneckReport) -> BottleneckReport:
        self._reports[report.id] = report
        if not self.db_path:
            return report
        payload = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("INSERT OR REPLACE INTO bottlenecks VALUES (?, ?, ?, ?)",
                         (report.id, payload, self._checksum(payload), report.last_seen))
            conn.commit()
        finally:
            conn.close()
        return report

    def get(self, report_id: str) -> Optional[BottleneckReport]:
        return self._reports.get(report_id)

    def list(self) -> List[BottleneckReport]:
        return sorted(self._reports.values(), key=lambda r: r.last_seen)

    def count(self) -> int:
        return len(self._reports)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT payload, checksum FROM bottlenecks").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise BottleneckIntegrityError(
                    f"Failed to load bottlenecks from {self.db_path}: {e}") from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise BottleneckIntegrityError(
                        "bottleneck row checksum mismatch (corrupt write)")
                data = json.loads(payload)
                self._reports[data["id"]] = BottleneckReport.from_dict(data)
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise BottleneckIntegrityError(
                        f"Failed to load bottlenecks from {self.db_path}: {e}") from e


class BottleneckDetector:
    """Evidence-required bottleneck detection over real telemetry."""

    def __init__(self, telemetry: ArchitectureTelemetry,
                 store: Optional[BottleneckStore] = None,
                 thresholds: Optional[Dict[str, float]] = None,
                 min_samples: int = MIN_SAMPLES):
        self.telemetry = telemetry
        self.store = store or BottleneckStore(db_path=None)
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)
        self.min_samples = min_samples

    def detect(self) -> List[BottleneckReport]:
        """Scan telemetry; return NEW significant bottleneck reports (deduped
        by component+type while unresolved — the same bottleneck is not
        re-reported every scan) and persist them to the store."""
        found: List[BottleneckReport] = []
        for component in sorted(self.telemetry.snapshot()):
            report = self._check_component(component)
            if report is None:
                continue
            existing = next((r for r in self.store.list()
                             if r.affected_component == report.affected_component
                             and r.type == report.type), None)
            if existing is not None:
                existing.last_seen = time.time()
                self.store.put(existing)
                continue
            self.store.put(report)
            found.append(report)
        return found

    def _check_component(self, component: str) -> Optional[BottleneckReport]:
        evidence: List[Dict[str, Any]] = []
        severities: List[float] = []
        for metric, (btype, direction) in _DETECTOR_MAP.items():
            m = self.telemetry.get(component, metric)
            if m is None or m.total < self.min_samples:
                continue
            rate = m.rate()
            if rate is None:
                continue
            threshold = self.thresholds.get(metric, 0.5)
            if direction == "low" and rate < threshold:
                evidence.append({"metric": metric, "rate": rate,
                                 "samples": m.total, "threshold": threshold})
                severities.append(1.0 - rate)
        # Value-based signals.
        lat = self.telemetry.get(component, "latency")
        if lat is not None and lat.total >= self.min_samples:
            avg = lat.avg_latency_ms()
            if avg is not None and avg > self.thresholds.get("latency_ms", 1000.0):
                evidence.append({"metric": "latency_ms", "avg_ms": avg,
                                 "samples": lat.total,
                                 "threshold": self.thresholds.get("latency_ms", 1000.0)})
                severities.append(min(1.0, avg / (2 * self.thresholds.get("latency_ms", 1000.0))))
        res = self.telemetry.get(component, "resource_usage")
        if res is not None and res.total >= self.min_samples:
            avg = res.avg_value()
            if avg is not None and avg > self.thresholds.get("resource_usage", 0.85):
                evidence.append({"metric": "resource_usage", "avg": avg,
                                 "samples": res.total,
                                 "threshold": self.thresholds.get("resource_usage", 0.85)})
                severities.append(min(1.0, avg - 0.8))
        fail = self.telemetry.get(component, "failure_rate")
        if fail is not None and fail.total >= self.min_samples:
            v = fail.avg_value() if fail.avg_value() is not None else None
            if v is None and fail.total >= self.min_samples:
                v = fail.failure_rate()
            if v is not None and v > self.thresholds.get("failure_rate", 0.5):
                evidence.append({"metric": "failure_rate", "rate": v,
                                 "samples": fail.total})
                severities.append(min(1.0, v))

        if not evidence:
            return None

        # Pick the dominant bottleneck type for this component.
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for e in evidence:
            btype = self._type_for_metric(e["metric"])
            by_type.setdefault(btype, []).append(e)
        dominant = max(by_type.items(), key=lambda kv: len(kv[1]))
        btype, ev = dominant

        severity = round(max(severities, default=0.0), 4)
        samples = max(e.get("samples", 0) for e in evidence)
        confidence = round(min(1.0, 0.5 + 0.08 * samples + severity * 0.4), 4)
        frequency = round(len(evidence) / len(_DETECTOR_MAP), 4)

        report = BottleneckReport(
            type=btype,
            evidence=ev,
            affected_component=component,
            frequency=frequency,
            severity=severity,
            confidence=confidence,
            affected_tasks=[component],
            estimated_impact=(f"Component '{component}' is at or beyond its "
                              f"configured threshold for {', '.join(e['metric'] for e in ev)}"),
            recommended_investigation=(f"Investigate '{component}': measure, form a "
                                       f"hypothesis, propose an evidence-based "
                                       f"improvement, and compare against baseline."),
        )
        return report

    @staticmethod
    def _type_for_metric(metric: str) -> str:
        for m, (btype, _dir) in _DETECTOR_MAP.items():
            if metric == m:
                return btype
        if metric in ("latency_ms", "resource_usage"):
            return "RESOURCE_LIMITATION"
        return "UNKNOWN"

    def has_unresolved(self) -> bool:
        return self.store.count() > 0
