"""
Slice 8 — RuntimePolicy store (controlled promotion target).

An explicit promotion path for non-CONFIGURATION modification types
(STRATEGY / PROMPT / ROUTING / MEMORY_POLICY / CAPABILITY). Promotions apply
to a versioned runtime policy store — never to source code — so the
no-unrestricted-self-modification rule holds while the promotion is REAL
(the runtime can consume active policies through RuntimePolicies).

Every apply() bumps the policy version and deactivates the previous one;
rollback() restores the parent version as active. Promotion still goes
through the full Slice 7 gate (analysis -> sandbox -> tests -> benchmark ->
policy -> snapshot -> apply), and the gate snapshots the pre-change state
BEFORE apply() is called.

Persisted with the SQLite-WAL + SHA-256 checksum pattern (Slices 1-7).
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


class PolicyIntegrityError(RuntimeError):
    pass


@dataclass
class RuntimePolicy:
    name: str = ""
    version: int = 1
    value: Any = None
    active: bool = True
    applied_at: float = field(default_factory=time.time)
    applied_by: str = ""                     # proposal_id that applied it
    snapshot_version: Optional[int] = None   # Slice 7 pre-change snapshot
    parent_version: Optional[int] = None     # version this was applied on top of
    rollback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "value": self.value,
            "active": self.active,
            "applied_at": self.applied_at,
            "applied_by": self.applied_by,
            "snapshot_version": self.snapshot_version,
            "parent_version": self.parent_version,
            "rollback_reason": self.rollback_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimePolicy":
        return cls(
            name=data.get("name", ""),
            version=data.get("version", 1),
            value=data.get("value"),
            active=bool(data.get("active", True)),
            applied_at=data.get("applied_at", time.time()),
            applied_by=data.get("applied_by", ""),
            snapshot_version=data.get("snapshot_version"),
            parent_version=data.get("parent_version"),
            rollback_reason=data.get("rollback_reason", ""),
        )


class PolicyStore:
    """Versioned named runtime policies, corruption-safe persistence."""

    def __init__(self, db_path: Optional[str] = "data/runtime_policies.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._policies: Dict[str, RuntimePolicy] = {}  # (name, version) -> policy
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
            CREATE TABLE IF NOT EXISTS policies (
                name TEXT,
                version INTEGER,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                active INTEGER,
                applied_at REAL,
                PRIMARY KEY (name, version)
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _persist(self, policy: RuntimePolicy) -> None:
        if not self.db_path:
            return
        payload = json.dumps(policy.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO policies VALUES (?, ?, ?, ?, ?, ?)",
                (policy.name, policy.version, payload,
                 self._checksum(payload), int(policy.active), policy.applied_at))
            conn.commit()
        finally:
            conn.close()

    # -- queries ------------------------------------------------------------

    def get(self, name: str, version: int) -> Optional[RuntimePolicy]:
        return self._policies.get((name, version))

    def current(self, name: str) -> Optional[RuntimePolicy]:
        """The active version of a policy, if any (else None, never invented)."""
        versions = [p for (n, _v), p in self._policies.items()
                    if n == name and p.active]
        if not versions:
            return None
        return max(versions, key=lambda p: p.version)

    def list_active(self) -> List[RuntimePolicy]:
        return sorted((p for p in self._policies.values() if p.active),
                      key=lambda p: (p.name, p.version))

    def list(self, name: Optional[str] = None) -> List[RuntimePolicy]:
        policies = list(self._policies.values())
        if name is not None:
            policies = [p for p in policies if p.name == name]
        return sorted(policies, key=lambda p: (p.name, p.version))

    def count(self) -> int:
        return len(self._policies)

    # -- mutation (through the gate only) -----------------------------------

    def apply(self, name: str, value: Any, *,
              applied_by: str = "",
              snapshot_version: Optional[int] = None) -> RuntimePolicy:
        """Apply a new policy version. The previous version is deactivated
        (its history is preserved for rollback)."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("policy name is required")
        cur = self.current(name)
        new = RuntimePolicy(
            name=name,
            version=(cur.version + 1) if cur is not None else 1,
            value=value,
            active=True,
            applied_at=time.time(),
            applied_by=applied_by,
            snapshot_version=snapshot_version,
            parent_version=cur.version if cur is not None else None,
        )
        if cur is not None:
            cur.active = False
            self._persist(cur)
        self._policies[(name, new.version)] = new
        self._persist(new)
        return new

    def rollback(self, name: str, *, reason: str = "") -> Optional[RuntimePolicy]:
        """Restore the pre-change state. If the active policy has a parent
        version, that version becomes active again; if it was the FIRST policy
        (no parent), it is deactivated so the runtime reads no policy for that
        name (exactly the pre-change state). Returns the restored policy or
        None when there was nothing active to roll back."""
        cur = self.current(name)
        if cur is None:
            return None
        if cur.parent_version is None:
            # First version: the pre-change state was "no policy".
            cur.active = False
            cur.rollback_reason = reason or "rollback"
            self._persist(cur)
            return None
        parent = self.get(name, cur.parent_version)
        if parent is None:
            return None
        parent.active = True
        parent.rollback_reason = reason or "rollback"
        self._persist(parent)
        cur.active = False
        self._persist(cur)
        return parent

    # -- persistence --------------------------------------------------------

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT name, version, payload, checksum FROM policies").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise PolicyIntegrityError(
                    f"Failed to load policies from {self.db_path}: {e}") from e
            return
        for name, version, payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise PolicyIntegrityError(
                        "policy row checksum mismatch (corrupt write)")
                data = json.loads(payload)
                policy = RuntimePolicy.from_dict(data)
                self._policies[(name, version)] = policy
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise PolicyIntegrityError(
                        f"Failed to load policies from {self.db_path}: {e}") from e


class RuntimePolicies:
    """Consumption view: active policy values the runtime actually reads."""

    def __init__(self, store: PolicyStore):
        self.store = store

    def get(self, name: str, default: Any = None) -> Any:
        policy = self.store.current(name)
        return default if policy is None else policy.value

    def snapshot(self) -> Dict[str, Any]:
        return {p.name: p.value for p in self.store.list_active()}
