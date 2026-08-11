"""
Security Boundary, Permission Matrix, and Audit Engine
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set


class PermissionLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    INTERNAL_EXECUTE = "INTERNAL_EXECUTE"
    WORKSPACE_WRITE = "WORKSPACE_WRITE"
    NETWORK_ACCESS = "NETWORK_ACCESS"
    SYSTEM_MUTATE = "SYSTEM_MUTATE"


@dataclass
class AuditEntry:
    timestamp: float
    action: str
    target: str
    permission_requested: PermissionLevel
    granted: bool
    reason: str
    caller: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class SecurityBoundary:
    def __init__(self, workspace_root: str = "/home/user/ai", allow_network: bool = True):
        self.workspace_root = Path(workspace_root).resolve()
        self.allow_network = allow_network
        self._granted_permissions: Set[PermissionLevel] = {
            PermissionLevel.READ_ONLY,
            PermissionLevel.INTERNAL_EXECUTE,
            PermissionLevel.WORKSPACE_WRITE,
        }
        if allow_network:
            self._granted_permissions.add(PermissionLevel.NETWORK_ACCESS)
            
        self._audit_log: List[AuditEntry] = []
        self._forbidden_paths = [
            Path("/etc/shadow"),
            Path("/etc/sudoers"),
            Path("/root"),
        ]

    def authorize(
        self,
        action: str,
        target: str,
        required_permission: PermissionLevel,
        caller: str = "system",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        granted = True
        reason = "Authorized"

        if required_permission not in self._granted_permissions:
            granted = False
            reason = f"Permission {required_permission.value} not held"

        # Check path boundary if target looks like a path
        if granted and (target.startswith("/") or target.startswith(".")):
            try:
                p = Path(target).resolve()
                for forbidden in self._forbidden_paths:
                    if str(p).startswith(str(forbidden)):
                        granted = False
                        reason = f"Path {target} is in forbidden security scope"
                        break
            except Exception:
                pass

        entry = AuditEntry(
            timestamp=time.time(),
            action=action,
            target=target,
            permission_requested=required_permission,
            granted=granted,
            reason=reason,
            caller=caller,
            metadata=metadata or {}
        )
        self._audit_log.append(entry)
        return granted

    def get_audit_trail(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [
            {
                "timestamp": e.timestamp,
                "action": e.action,
                "target": e.target,
                "permission": e.permission_requested.value,
                "granted": e.granted,
                "reason": e.reason,
                "caller": e.caller,
                "metadata": e.metadata
            }
            for e in self._audit_log[-limit:]
        ]
