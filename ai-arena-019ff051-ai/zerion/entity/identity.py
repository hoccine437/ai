"""
Entity identity adapter (DEPRECATED class, canonical source is IdentityCore).

ZERION-X has exactly ONE canonical identity: ``zerion.identity.persistence``
``IdentityCore`` (\"ZERION-X ASCENDANT\" / ``ascendant-core-v1``). This class is
kept only as a thin adapter so legacy entity snapshots and tests can read the
canonical identity without constructing a second, competing identity.

- Standalone construction (no ``identity_core``) resolves to the canonical
  constants — it can never invent a different self-name.
- When an ``IdentityCore`` is passed (the engine does this), name, id and
  digest all come from that canonical core.
"""

from dataclasses import dataclass, field
import hashlib
from typing import Any, Dict, List, Optional
import time

from zerion.identity.persistence import (
    CANONICAL_SYSTEM_ID,
    CANONICAL_SYSTEM_NAME,
    IdentityCore,
)


@dataclass
class EntityCommitment:
    commitment_id: str
    statement: str
    priority: int = 1
    is_immutable: bool = True
    created_at: float = field(default_factory=time.time)


_DEFAULT_COMMITMENTS: List[EntityCommitment] = [
    EntityCommitment("COM-01", "Preserve epistemic integrity; declare unknowns explicitly", 1),
    EntityCommitment("COM-02", "Maintain persistent long-term objectives across sessions and failures", 2),
    EntityCommitment("COM-03", "Require empirical reality evidence before promoting self-modifications", 3),
    EntityCommitment("COM-04", "Enforce strict security boundaries and least-privilege permissions", 4),
    EntityCommitment("COM-05", "Continuously accelerate learning velocity through proceduralization", 5),
]


class CognitiveEntityIdentity:
    """Adapter over the canonical ``IdentityCore`` (or canonical constants).

    Never a competing identity: ``entity_name``/``entity_id``/digest are either
    read from the passed canonical core or fall back to the canonical constants.
    """

    def __init__(self, identity_core: Optional[IdentityCore] = None):
        self._core = identity_core
        if identity_core is not None:
            self.entity_name: str = identity_core.system_name
            self.entity_id: str = identity_core.system_id
            # Commitments mirror the canonical core's immutable invariants.
            self.commitments: List[EntityCommitment] = [
                EntityCommitment(inv.id, inv.name, priority=idx + 1)
                for idx, inv in enumerate(identity_core.invariants)
            ]
        else:
            self.entity_name = CANONICAL_SYSTEM_NAME
            self.entity_id = CANONICAL_SYSTEM_ID
            self.commitments = list(_DEFAULT_COMMITMENTS)
        self.created_at = time.time()

    def get_identity_digest(self) -> str:
        """Digest always derives from the canonical identity source."""
        if self._core is not None:
            return self._core.get_identity_digest()
        data = f"{self.entity_name}:{self.entity_id}:{[c.commitment_id for c in self.commitments]}"
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_name": self.entity_name,
            "entity_id": self.entity_id,
            "commitments": [{"id": c.commitment_id, "statement": c.statement, "priority": c.priority} for c in self.commitments],
            "identity_digest": self.get_identity_digest(),
            "created_at": self.created_at
        }
