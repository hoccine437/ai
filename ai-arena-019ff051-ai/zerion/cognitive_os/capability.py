"""
Slice 5 — Capability model, permissions and registry.

A capability is NOT learned merely because code was generated. A Capability is a
structured, versioned, permission-bounded artifact that only becomes trusted
(REGISTERED) after DESIGN -> GENERATE -> SANDBOX -> TEST -> VALIDATE with actual
evidence. Permissions default to least privilege and can never be gained because
generated code requested them — they come only from the design and are checked
against the PermissionPolicy.
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid


class Permission(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    NETWORK = "NETWORK"
    COMMUNICATION = "COMMUNICATION"
    FINANCIAL = "FINANCIAL"
    SYSTEM_CONTROL = "SYSTEM_CONTROL"
    SELF_MODIFICATION = "SELF_MODIFICATION"


# High-risk permissions require explicit policy approval — never granted by
# generated code, never defaulted.
HIGH_RISK_PERMISSIONS: Set[Permission] = {
    Permission.FINANCIAL,
    Permission.SYSTEM_CONTROL,
    Permission.SELF_MODIFICATION,
}

LEAST_PRIVILEGE: Set[Permission] = {Permission.READ, Permission.EXECUTE}


class CapabilityType(str, Enum):
    PROCEDURE = "PROCEDURE"
    TOOL_CHAIN = "TOOL_CHAIN"
    VALIDATOR = "VALIDATOR"
    HEURISTIC = "HEURISTIC"
    RETRIEVAL_STRATEGY = "RETRIEVAL_STRATEGY"
    PLANNING_STRATEGY = "PLANNING_STRATEGY"
    DETERMINISTIC_MODULE = "DETERMINISTIC_MODULE"
    SPECIALIZED_WORKFLOW = "SPECIALIZED_WORKFLOW"


class CapabilityStatus(str, Enum):
    NEEDED = "NEEDED"
    DESIGNED = "DESIGNED"
    GENERATED = "GENERATED"
    SANDBOXED = "SANDBOXED"
    TESTED = "TESTED"
    VALIDATED = "VALIDATED"
    REGISTERED = "REGISTERED"
    MONITORED = "MONITORED"
    DEPRECATED = "DEPRECATED"
    REJECTED = "REJECTED"


class CapabilityHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILING = "FAILING"


class CapabilityValidationError(ValueError):
    """Raised for structurally invalid capabilities."""


class CapabilityStoreIntegrityError(RuntimeError):
    """Raised when persisted capabilities are corrupt and strict loading is enabled."""


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Any) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def _clean_str_list(values: Any) -> List[str]:
    if not values:
        return []
    return [_clean_text(v) for v in values if _clean_text(v)]


def capability_fingerprint(name: str, version: int, implementation: str) -> str:
    key = f"{name}|v{version}|{implementation}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class Capability:
    capability_id: str = field(default_factory=lambda: f"cap_{uuid.uuid4().hex[:10]}")
    name: str = ""                        # stable identity (unique + versioned)
    description: str = ""
    type: CapabilityType = CapabilityType.PROCEDURE
    version: int = 1
    status: CapabilityStatus = CapabilityStatus.NEEDED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_experiences: List[str] = field(default_factory=list)   # episode_ids
    source_rules: List[str] = field(default_factory=list)         # distilled ids
    dependencies: List[str] = field(default_factory=list)         # capability names
    required_permissions: List[Permission] = field(default_factory=lambda: list(LEAST_PRIVILEGE))
    inputs: Dict[str, Any] = field(default_factory=dict)          # {name: {type, description}}
    outputs: Dict[str, Any] = field(default_factory=dict)         # {name: {type, description}}
    procedure: List[str] = field(default_factory=list)
    implementation: str = ""              # generated artifact (untrusted until validated)
    validation_evidence: List[Dict[str, Any]] = field(default_factory=list)
    test_results: List[Dict[str, Any]] = field(default_factory=list)
    success_rate: float = 0.0             # [0.0, 1.0]
    failure_rate: float = 0.0             # [0.0, 1.0]
    usage_count: int = 0
    last_used: Optional[float] = None
    consecutive_failures: int = 0
    health: CapabilityHealth = CapabilityHealth.HEALTHY
    risk_level: float = 0.1               # [0.0, 1.0]
    metadata: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)   # rollback/deprecation
    fingerprint: str = ""
    supported_tasks: List[str] = field(default_factory=list)
    supported_goal_types: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.name = _clean_text(self.name)
        if not self.name:
            raise CapabilityValidationError("Capability name must not be empty")
        if isinstance(self.type, str):
            self.type = CapabilityType(self.type)
        if isinstance(self.status, str):
            self.status = CapabilityStatus(self.status)
        if isinstance(self.health, str):
            self.health = CapabilityHealth(self.health)
        if not (0.0 <= float(self.risk_level) <= 1.0):
            raise CapabilityValidationError("Capability risk_level must be in [0.0, 1.0]")
        self.source_experiences = _clean_str_list(self.source_experiences)
        self.source_rules = _clean_str_list(self.source_rules)
        self.dependencies = _clean_str_list(self.dependencies)
        self.procedure = _clean_str_list(self.procedure)
        self.supported_tasks = _clean_str_list(self.supported_tasks)
        self.supported_goal_types = _clean_str_list(self.supported_goal_types)
        self.limitations = _clean_str_list(self.limitations)
        perms: List[Permission] = []
        for p in self.required_permissions:
            if isinstance(p, str):
                p = Permission(p)
            if p not in perms:
                perms.append(p)
        # Deterministic ordering (never rely on set iteration order).
        self.required_permissions = sorted(perms, key=lambda p: p.value)
        if not self.fingerprint:
            self.fingerprint = capability_fingerprint(self.name, self.version,
                                                      self.implementation)

    @property
    def is_active(self) -> bool:
        return self.status in (CapabilityStatus.REGISTERED, CapabilityStatus.MONITORED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "version": self.version,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_experiences": self.source_experiences,
            "source_rules": self.source_rules,
            "dependencies": self.dependencies,
            "required_permissions": [p.value for p in self.required_permissions],
            "inputs": self.inputs,
            "outputs": self.outputs,
            "procedure": self.procedure,
            "implementation": self.implementation,
            "validation_evidence": self.validation_evidence,
            "test_results": self.test_results,
            "success_rate": round(self.success_rate, 6),
            "failure_rate": round(self.failure_rate, 6),
            "usage_count": self.usage_count,
            "last_used": self.last_used,
            "consecutive_failures": self.consecutive_failures,
            "health": self.health.value,
            "risk_level": round(self.risk_level, 6),
            "metadata": self.metadata,
            "history": self.history,
            "fingerprint": self.fingerprint,
            "supported_tasks": self.supported_tasks,
            "supported_goal_types": self.supported_goal_types,
            "limitations": self.limitations,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        ctype = data.get("type", CapabilityType.PROCEDURE.value)
        try:
            ctype = CapabilityType(ctype)
        except ValueError:
            ctype = CapabilityType.PROCEDURE
        status = data.get("status", CapabilityStatus.NEEDED.value)
        try:
            status = CapabilityStatus(status)
        except ValueError:
            status = CapabilityStatus.NEEDED
        health = data.get("health", CapabilityHealth.HEALTHY.value)
        try:
            health = CapabilityHealth(health)
        except ValueError:
            health = CapabilityHealth.HEALTHY
        perms = []
        for p in data.get("required_permissions", [Permission.READ.value,
                                                   Permission.EXECUTE.value]):
            try:
                perms.append(Permission(p))
            except ValueError:
                continue
        return cls(
            capability_id=data.get("capability_id", f"cap_{uuid.uuid4().hex[:10]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            type=ctype,
            version=int(data.get("version", 1)),
            status=status,
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            source_experiences=list(data.get("source_experiences", [])),
            source_rules=list(data.get("source_rules", [])),
            dependencies=list(data.get("dependencies", [])),
            required_permissions=perms,
            inputs=dict(data.get("inputs", {})),
            outputs=dict(data.get("outputs", {})),
            procedure=list(data.get("procedure", [])),
            implementation=data.get("implementation", ""),
            validation_evidence=list(data.get("validation_evidence", [])),
            test_results=list(data.get("test_results", [])),
            success_rate=float(data.get("success_rate", 0.0)),
            failure_rate=float(data.get("failure_rate", 0.0)),
            usage_count=int(data.get("usage_count", 0)),
            last_used=data.get("last_used"),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            health=health,
            risk_level=float(data.get("risk_level", 0.1)),
            metadata=dict(data.get("metadata", {})),
            history=list(data.get("history", [])),
            fingerprint=data.get("fingerprint", ""),
            supported_tasks=list(data.get("supported_tasks", [])),
            supported_goal_types=list(data.get("supported_goal_types", [])),
            limitations=list(data.get("limitations", [])),
        )


class PermissionPolicy:
    """Explicit policy gates. High-risk permissions (FINANCIAL, SYSTEM_CONTROL,
    SELF_MODIFICATION) must be pre-approved here — generated code can never gain
    them, and least privilege is the default."""

    def __init__(self, approved: Optional[Set[Permission]] = None):
        self.approved = set(approved or set())

    def check(self, requested: List[Permission]) -> Tuple[bool, List[Permission]]:
        denied = [p for p in requested
                  if p in HIGH_RISK_PERMISSIONS and p not in self.approved]
        return (not denied, denied)

    def to_dict(self) -> Dict[str, Any]:
        return {"approved": sorted(p.value for p in self.approved)}


class CapabilityRegistry:
    """SQLite WAL-backed registry for Capabilities (corruption-safe, same
    pattern as the Slice 1-4 stores). DB ``cognitive_capabilities.db`` — avoids
    the legacy ``capabilities.db`` (zerion/capabilities/registry.py).

    Supports: register, lookup, versioning, enable/disable (status transitions),
    monitor, deprecate, rollback history, dependency inspection. Every
    capability has a unique identity (name + version); duplicate active
    capabilities with conflicting definitions are rejected."""

    def __init__(self, db_path: Optional[str] = "data/cognitive_capabilities.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._capabilities: Dict[str, Capability] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    capability_id TEXT PRIMARY KEY,
                    name TEXT,
                    version INTEGER,
                    status TEXT,
                    payload TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    updated_at REAL
                )
            """)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cap_name_version "
                "ON capabilities (name, version)"
            )
            conn.commit()
            conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, capability: Capability) -> Capability:
        self._capabilities[capability.capability_id] = capability
        if not self.db_path:
            return capability
        payload = json.dumps(capability.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO capabilities VALUES (?, ?, ?, ?, ?, ?, ?)",
                (capability.capability_id, capability.name, capability.version,
                 capability.status.value, payload, self._checksum(payload),
                 capability.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return capability

    def get(self, capability_id: str) -> Optional[Capability]:
        return self._capabilities.get(capability_id)

    def get_by_name_version(self, name: str, version: int) -> Optional[Capability]:
        for c in self._capabilities.values():
            if c.name == name and c.version == version:
                return c
        return None

    def versions(self, name: str) -> List[Capability]:
        return sorted([c for c in self._capabilities.values() if c.name == name],
                      key=lambda c: c.version)

    def active_version(self, name: str) -> Optional[Capability]:
        active = [c for c in self.versions(name) if c.is_active]
        if not active:
            return None
        return max(active, key=lambda c: c.version)

    def list(self, status: Optional[CapabilityStatus] = None,
             ctype: Optional[CapabilityType] = None) -> List[Capability]:
        caps = list(self._capabilities.values())
        if status is not None:
            caps = [c for c in caps if c.status == status]
        if ctype is not None:
            caps = [c for c in caps if c.type == ctype]
        return sorted(caps, key=lambda c: (c.name, c.version))

    def find_duplicate_active(self, name: str, version: int,
                              fingerprint: str) -> Optional[Capability]:
        """A conflicting definition at the same identity (name + version) is a
        duplicate and must be rejected. The same artifact re-registered is not
        a duplicate (identical fingerprint)."""
        same_version = self.get_by_name_version(name, version)
        if same_version is not None and same_version.fingerprint != fingerprint:
            return same_version
        return None

    def resolve_dependencies(self, capability: Capability) -> Tuple[bool, List[str]]:
        """Dependency inspection: every declared dependency must resolve to an
        active (REGISTERED/MONITORED) capability."""
        missing = [d for d in capability.dependencies
                   if self.active_version(d) is None]
        return (not missing, missing)

    def count(self) -> int:
        return len(self._capabilities)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM capabilities").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise CapabilityStoreIntegrityError(
                    f"Failed to load persisted capabilities from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise CapabilityStoreIntegrityError(
                        "Capability row checksum mismatch (corrupt or partial write)")
                data = json.loads(payload)
                cap = Capability.from_dict(data)
                self._capabilities[cap.capability_id] = cap
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise CapabilityStoreIntegrityError(
                        f"Failed to load persisted capabilities from {self.db_path}: {e}"
                    ) from e
