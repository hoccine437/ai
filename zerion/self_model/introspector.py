"""
Self-Model Engine and Introspection Interface
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.self_model.capabilities import CapabilityRecord
from zerion.self_model.limitations import LimitationRecord, DEFAULT_LIMITATIONS
from zerion.self_model.calibration import ConfidenceCalibrator


class SelfModel:
    def __init__(self, db_path: Optional[str] = "data/self_model.db"):
        self.db_path = db_path
        self._capabilities: Dict[str, CapabilityRecord] = {}
        self._limitations: Dict[str, LimitationRecord] = {l.id: l for l in DEFAULT_LIMITATIONS}
        self.calibrator = ConfidenceCalibrator()
        self._init_db()
        self._bootstrap_native_capabilities()
        self.load()

    def _bootstrap_native_capabilities(self):
        core_caps = [
            ("observe_reality", "perception", "Sample environment states and compute reality deltas"),
            ("causal_inference", "reasoning", "Deduce causal mechanisms from empirical observations"),
            ("adversarial_verification", "verification", "Critique conclusions and attempt falsification"),
            ("cognitive_compilation", "reasoning", "Synthesize customized execution DAGs for novel problems"),
            ("experiment_sandbox", "experiment", "Execute controlled code experiments safely in sandbox"),
            ("experience_distillation", "memory", "Extract procedural rules from repeated episodic events"),
            ("capability_genesis", "evolution", "Synthesize and test missing capability code components"),
            ("transfer_evaluation", "learning", "Assess cross-domain generalization of acquired strategies"),
        ]
        for name, cat, desc in core_caps:
            if name not in self._capabilities:
                self._capabilities[name] = CapabilityRecord(name=name, category=cat, description=desc, is_native=True)

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_capabilities (
                    name TEXT PRIMARY KEY,
                    data_json TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_limitations (
                    id TEXT PRIMARY KEY,
                    data_json TEXT,
                    discovered_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def register_capability(self, cap: CapabilityRecord):
        self._capabilities[cap.name] = cap
        self._persist_cap(cap)

    def get_capability(self, name: str) -> Optional[CapabilityRecord]:
        return self._capabilities.get(name)

    def record_capability_result(self, name: str, success: bool, latency_ms: float, evidence_id: Optional[str] = None):
        if name in self._capabilities:
            self._capabilities[name].record_execution(success, latency_ms, evidence_id)
            self._persist_cap(self._capabilities[name])

    # Introspection API
    def what_can_i_do(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in sorted(self._capabilities.values(), key=lambda x: x.reliability, reverse=True)]

    def what_can_i_not_do(self) -> List[Dict[str, Any]]:
        active_limits = [l.to_dict() for l in self._limitations.values() if l.is_active]
        unreliable_caps = [c.to_dict() for c in self._capabilities.values() if c.invocations > 2 and c.reliability < 0.5]
        return active_limits + unreliable_caps

    def how_reliable_am_i_at(self, capability_name: str) -> Dict[str, Any]:
        cap = self._capabilities.get(capability_name)
        if not cap:
            return {
                "capability": capability_name,
                "known": False,
                "reliability": 0.0,
                "invocations": 0,
                "evidence_ids": [],
                "statement": f"Capability '{capability_name}' is not in my self-catalog."
            }
        return {
            "capability": capability_name,
            "known": True,
            "reliability": cap.reliability,
            "invocations": cap.invocations,
            "successes": cap.successes,
            "failures": cap.failures,
            "avg_latency_ms": cap.avg_latency_ms,
            "evidence_ids": cap.evidence_ids,
            "statement": f"Reliability is {cap.reliability * 100:.1f}% based on {cap.invocations} empirical executions."
        }

    def what_capability_am_i_missing(self, task_description: str) -> Optional[str]:
        """
        Analyzes a task description to determine if an existing capability satisfies it.
        """
        task_lower = task_description.lower()
        matched = False
        for name, cap in self._capabilities.items():
            if name.replace("_", " ") in task_lower or any(word in task_lower for word in cap.description.lower().split()):
                matched = True
                break
        if not matched:
            return f"missing_capability_for_{task_lower.replace(' ', '_')[:30]}"
        return None

    def _persist_cap(self, cap: CapabilityRecord):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO self_capabilities VALUES (?, ?, ?)",
            (cap.name, json.dumps(cap.to_dict()), cap.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT data_json FROM self_capabilities")
            for row in cursor.fetchall():
                cap = CapabilityRecord.from_dict(json.loads(row[0]))
                self._capabilities[cap.name] = cap
            conn.close()
        except Exception:
            pass
