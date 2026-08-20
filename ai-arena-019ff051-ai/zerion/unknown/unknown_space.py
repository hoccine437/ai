"""
Unknown Space & Knowledge Frontier Substrate for GENESIS ∞
Models:
- KNOWN (Measured / Observed / Proven)
- KNOWN_UNKNOWN (Explicitly Identified Epistemic Voids)
- UNKNOWN_UNKNOWN_CANDIDATE (Suspected Unobserved Variables / Latent Factors)
- CONTRADICTION (Conflicting Empirical Observations)
- BLIND_SPOT (Domains with Low Sampling Density & High Uncertainty)
"""

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set
import uuid


class EpistemicVoidType(str, Enum):
    KNOWN = "KNOWN"
    KNOWN_UNKNOWN = "KNOWN_UNKNOWN"
    UNKNOWN_UNKNOWN_CANDIDATE = "UNKNOWN_UNKNOWN_CANDIDATE"
    CONTRADICTION = "CONTRADICTION"
    BLIND_SPOT = "BLIND_SPOT"


@dataclass
class EpistemicVoidItem:
    void_id: str = field(default_factory=lambda: f"void_{uuid.uuid4().hex[:8]}")
    target_entity: str = ""
    target_property: str = ""
    void_type: EpistemicVoidType = EpistemicVoidType.KNOWN_UNKNOWN
    description: str = ""
    entropy_score: float = 0.8         # [0.0, 1.0] (high entropy = high uncertainty)
    investigation_priority: float = 0.7# [0.0, 1.0]
    candidate_hypotheses: List[str] = field(default_factory=list)
    discovered_at: float = field(default_factory=time.time)
    resolved: bool = False
    resolution_evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "void_id": self.void_id,
            "target_entity": self.target_entity,
            "target_property": self.target_property,
            "void_type": self.void_type.value if isinstance(self.void_type, EpistemicVoidType) else str(self.void_type),
            "description": self.description,
            "entropy_score": round(self.entropy_score, 3),
            "investigation_priority": round(self.investigation_priority, 3),
            "candidate_hypotheses": self.candidate_hypotheses,
            "discovered_at": self.discovered_at,
            "resolved": self.resolved,
            "resolution_evidence_id": self.resolution_evidence_id
        }


class UnknownSpaceEngine:
    def __init__(self, db_path: Optional[str] = "data/unknown_space.db"):
        self.db_path = db_path
        self._voids: Dict[str, EpistemicVoidItem] = {}
        self._contradictions: List[Dict[str, Any]] = []
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS epistemic_voids (
                    void_id TEXT PRIMARY KEY,
                    target_entity TEXT,
                    target_property TEXT,
                    void_type TEXT,
                    entropy_score REAL,
                    investigation_priority REAL,
                    data_json TEXT,
                    resolved INTEGER,
                    timestamp REAL
                )
            """)
            conn.commit()
            conn.close()

    def register_void(
        self,
        target_entity: str,
        target_property: str,
        void_type: EpistemicVoidType = EpistemicVoidType.KNOWN_UNKNOWN,
        description: str = "",
        entropy: float = 0.8
    ) -> EpistemicVoidItem:
        void = EpistemicVoidItem(
            target_entity=target_entity,
            target_property=target_property,
            void_type=void_type,
            description=description or f"Unmeasured state for {target_entity}.{target_property}",
            entropy_score=entropy,
            investigation_priority=min(1.0, entropy * 1.2)
        )
        self._voids[void.void_id] = void
        self._persist(void)
        return void

    def register_contradiction(
        self,
        claim_statement: str,
        counter_evidence_source: str,
        delta: float
    ):
        record = {
            "contradiction_id": f"contra_{uuid.uuid4().hex[:8]}",
            "claim": claim_statement,
            "counter_source": counter_evidence_source,
            "delta": round(delta, 4),
            "timestamp": time.time()
        }
        self._contradictions.append(record)
        # Also create a high-priority contradiction void
        self.register_void(
            target_entity="belief_ledger",
            target_property=claim_statement[:30],
            void_type=EpistemicVoidType.CONTRADICTION,
            description=f"Direct empirical contradiction in '{claim_statement[:40]}'",
            entropy=1.0
        )

    def scan_for_blind_spots(self, world_nodes: List[Any]) -> List[EpistemicVoidItem]:
        """Identifies entities with low attribute sampling frequency."""
        blind_spots = []
        for node in world_nodes:
            attrs = getattr(node, "attributes", {})
            if len(attrs) < 2:
                bs = self.register_void(
                    target_entity=getattr(node, "id", "node"),
                    target_property="full_state_space",
                    void_type=EpistemicVoidType.BLIND_SPOT,
                    description=f"Sparse property representation on node '{getattr(node, 'name', 'unnamed')}'",
                    entropy=0.75
                )
                blind_spots.append(bs)
        return blind_spots

    def get_highest_priority_voids(self, limit: int = 5) -> List[EpistemicVoidItem]:
        unresolved = [v for v in self._voids.values() if not v.resolved]
        return sorted(unresolved, key=lambda v: v.investigation_priority, reverse=True)[:limit]

    def resolve_void(self, void_id: str, evidence_id: str):
        if void_id in self._voids:
            v = self._voids[void_id]
            v.resolved = True
            v.resolution_evidence_id = evidence_id
            self._persist(v)

    def _persist(self, void: EpistemicVoidItem):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO epistemic_voids VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (void.void_id, void.target_entity, void.target_property, void.void_type.value, void.entropy_score, void.investigation_priority, json.dumps(void.to_dict()), 1 if void.resolved else 0, void.discovered_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT data_json FROM epistemic_voids").fetchall():
                d = json.loads(row[0])
                void = EpistemicVoidItem(
                    void_id=d["void_id"],
                    target_entity=d["target_entity"],
                    target_property=d["target_property"],
                    void_type=EpistemicVoidType(d.get("void_type", EpistemicVoidType.KNOWN_UNKNOWN.value)),
                    description=d.get("description", ""),
                    entropy_score=d.get("entropy_score", 0.8),
                    investigation_priority=d.get("investigation_priority", 0.7),
                    candidate_hypotheses=d.get("candidate_hypotheses", []),
                    discovered_at=d.get("discovered_at", time.time()),
                    resolved=bool(d.get("resolved", False)),
                    resolution_evidence_id=d.get("resolution_evidence_id")
                )
                self._voids[void.void_id] = void
            conn.close()
        except Exception:
            pass
