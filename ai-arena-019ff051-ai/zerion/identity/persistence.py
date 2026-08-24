"""
Durable Identity Store that Survives Restarts and Failures
"""

import hashlib
import json
from pathlib import Path
import time
from typing import Dict, List, Optional
from zerion.identity.contract import UserContract
from zerion.identity.invariants import CORE_INVARIANTS, Invariant
from zerion.identity.objectives import LongTermObjective, ObjectiveStatus


# Canonical ZERION-X identity constants. There is exactly ONE identity in the
# runtime; every other component (entity snapshots, provider adapters, voice,
# UI telemetry) must derive its identity from this source. "ZERION-X
# SINGULARITY" / "zerion-singularity-core-v1" was a legacy generation's name
# and is no longer a live identity (see ZERION_X_ARCHITECTURAL_FREEZE.md V1).
CANONICAL_SYSTEM_NAME = "ZERION-X ASCENDANT"
CANONICAL_SYSTEM_ID = "ascendant-core-v1"


class IdentityCore:
    def __init__(self, storage_path: str = "data/identity.json"):
        self.storage_path = Path(storage_path)
        self.system_name: str = CANONICAL_SYSTEM_NAME
        self.system_id: str = CANONICAL_SYSTEM_ID
        self.user_contract: UserContract = UserContract()
        self.invariants: List[Invariant] = list(CORE_INVARIANTS)
        self._objectives: Dict[str, LongTermObjective] = {}
        self.created_at: float = time.time()
        self.last_persisted_at: float = 0.0
        self.load()

    def add_objective(self, objective: LongTermObjective) -> str:
        objective.updated_at = time.time()
        self._objectives[objective.id] = objective
        self.save()
        return objective.id

    def get_objective(self, objective_id: str) -> Optional[LongTermObjective]:
        return self._objectives.get(objective_id)

    def list_objectives(self, active_only: bool = False) -> List[LongTermObjective]:
        objs = list(self._objectives.values())
        if active_only:
            objs = [o for o in objs if o.status == ObjectiveStatus.ACTIVE]
        return sorted(objs, key=lambda x: x.priority, reverse=True)

    def update_objective_progress(self, objective_id: str, progress: float, evidence_id: Optional[str] = None):
        if objective_id in self._objectives:
            obj = self._objectives[objective_id]
            obj.progress = max(0.0, min(1.0, progress))
            if progress >= 1.0:
                obj.status = ObjectiveStatus.COMPLETED
            if evidence_id and evidence_id not in obj.evidence_ids:
                obj.evidence_ids.append(evidence_id)
            obj.updated_at = time.time()
            self.save()

    def get_identity_hash(self) -> str:
        """Computes cryptographic digest of core invariant configuration."""
        data_str = f"{self.system_name}:{self.system_id}:{[inv.id for inv in self.invariants]}"
        return hashlib.sha256(data_str.encode()).hexdigest()

    def get_identity_digest(self) -> str:
        """Canonical identity digest used by derived components (entity state,
        snapshots, telemetry). All derived components MUST read identity from
        the canonical IdentityCore — never from a competing identity class."""
        return self.get_identity_hash()

    def save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "system_name": self.system_name,
            "system_id": self.system_id,
            "created_at": self.created_at,
            "user_contract": self.user_contract.to_dict(),
            "objectives": {k: v.to_dict() for k, v in self._objectives.items()},
            "identity_hash": self.get_identity_hash(),
            "last_persisted_at": time.time()
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        self.last_persisted_at = time.time()

    def load(self):
        if not self.storage_path.exists():
            # Create default primary developmental objectives
            self.add_objective(LongTermObjective(
                id="OBJ_DISCOVER_INEFFICIENCIES",
                title="Continuous Anomaly and Inefficiency Discovery",
                description="Detect environmental bottlenecks and unprompted problems before explicit user requests.",
                priority=90
            ))
            self.add_objective(LongTermObjective(
                id="OBJ_EMPIRICAL_LEARNING",
                title="Empirical Capability Ascension",
                description="Develop missing capabilities through sandbox experimentation and verified benchmark improvements.",
                priority=85
            ))
            self.save()
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.system_name = payload.get("system_name", self.system_name)
            self.system_id = payload.get("system_id", self.system_id)
            self.created_at = payload.get("created_at", self.created_at)
            if "user_contract" in payload:
                self.user_contract = UserContract.from_dict(payload["user_contract"])
            if "objectives" in payload:
                self._objectives = {
                    k: LongTermObjective.from_dict(v) for k, v in payload["objectives"].items()
                }
        except Exception:
            pass
