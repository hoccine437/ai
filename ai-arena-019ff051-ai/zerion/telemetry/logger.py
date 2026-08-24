"""
Structured Cognitive Telemetry Logger
Records auditable execution traces without logging secrets or unpermitted user data.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class CognitiveTelemetryRecord:
    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:8]}")
    goal_id: Optional[str] = None
    mission_id: Optional[str] = None
    program_id: Optional[str] = None
    strategy_id: Optional[str] = None
    genome_version: int = 1
    model_id: str = "deterministic_local"
    experiment_id: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    cost_cents: float = 0.0
    result_status: str = "SUCCESS"  # "SUCCESS", "FAILURE", "ROLLED_BACK"
    confidence: float = 1.0
    failure_class: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "goal_id": self.goal_id,
            "mission_id": self.mission_id,
            "program_id": self.program_id,
            "strategy_id": self.strategy_id,
            "genome_version": self.genome_version,
            "model_id": self.model_id,
            "experiment_id": self.experiment_id,
            "evidence_ids": self.evidence_ids,
            "latency_ms": round(self.latency_ms, 2),
            "cost_cents": round(self.cost_cents, 4),
            "result_status": self.result_status,
            "confidence": round(self.confidence, 3),
            "failure_class": self.failure_class,
            "timestamp": self.timestamp,
            "metadata": self._sanitize_metadata(self.metadata)
        }

    def _sanitize_metadata(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Strips potential secrets / credentials."""
        sanitized = {}
        for k, v in data.items():
            if any(s in k.lower() for s in ["key", "secret", "token", "password", "auth"]):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = v
        return sanitized


class CognitiveTelemetryLogger:
    def __init__(self, log_path: Optional[str] = "data/cognitive_telemetry.jsonl"):
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._in_memory_records: List[CognitiveTelemetryRecord] = []

    def record(self, entry: CognitiveTelemetryRecord):
        self._in_memory_records.append(entry)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")

    def get_recent_traces(self, limit: int = 50) -> List[CognitiveTelemetryRecord]:
        return self._in_memory_records[-limit:]
