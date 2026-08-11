"""
ZERION-X Singularity Architecture — Entity Lifecycle & State Persistence
Coordinates persistent entity lifecycle states across sessions and hardware environments.
"""

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.entity.identity import CognitiveEntityIdentity


class EntityLifecycleState(str, Enum):
    STANDBY = "STANDBY"
    BOOTING = "BOOTING"
    PERCEIVING = "PERCEIVING"
    DELIBERATING = "DELIBERATING"
    ACTING = "ACTING"
    EVOLVING = "EVOLVING"
    CONSOLIDATING = "CONSOLIDATING"
    RECOVERING = "RECOVERING"


@dataclass
class EntityStateSnapshot:
    snapshot_id: str
    lifecycle_state: EntityLifecycleState
    identity_digest: str
    active_objectives_count: int
    active_strategies_count: int
    active_capabilities_count: int
    memory_episodes_count: int
    brier_score: float
    learning_acceleration: float
    maturity_level: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "lifecycle_state": self.lifecycle_state.value,
            "identity_digest": self.identity_digest,
            "active_objectives_count": self.active_objectives_count,
            "active_strategies_count": self.active_strategies_count,
            "active_capabilities_count": self.active_capabilities_count,
            "memory_episodes_count": self.memory_episodes_count,
            "brier_score": round(self.brier_score, 4),
            "learning_acceleration": round(self.learning_acceleration, 3),
            "maturity_level": self.maturity_level,
            "timestamp": self.timestamp
        }


class CognitiveEntityStateStore:
    def __init__(self, db_path: Optional[str] = "data/entity_state.db"):
        self.db_path = db_path
        self.identity = CognitiveEntityIdentity()
        self.current_state = EntityLifecycleState.STANDBY
        self._init_db()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    lifecycle_state TEXT,
                    identity_digest TEXT,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.commit()
            conn.close()

    def transition_state(self, new_state: EntityLifecycleState) -> EntityLifecycleState:
        self.current_state = new_state
        return self.current_state

    def capture_snapshot(
        self,
        objectives_count: int = 1,
        strategies_count: int = 3,
        capabilities_count: int = 8,
        episodes_count: int = 10,
        brier_score: float = 0.02,
        learning_acceleration: float = 2.57,
        maturity_level: str = "L7_COGNITIVE_GENERATIVE"
    ) -> EntityStateSnapshot:
        snap = EntityStateSnapshot(
            snapshot_id=f"snap_{int(time.time()*1000)%1000000}",
            lifecycle_state=self.current_state,
            identity_digest=self.identity.get_identity_digest(),
            active_objectives_count=objectives_count,
            active_strategies_count=strategies_count,
            active_capabilities_count=capabilities_count,
            memory_episodes_count=episodes_count,
            brier_score=brier_score,
            learning_acceleration=learning_acceleration,
            maturity_level=maturity_level
        )
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO entity_snapshots VALUES (?, ?, ?, ?, ?)",
                (snap.snapshot_id, snap.lifecycle_state.value, snap.identity_digest, json.dumps(snap.to_dict()), snap.timestamp)
            )
            conn.commit()
            conn.close()
        return snap
