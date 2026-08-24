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
            # NOTE (Termux/Android bug fix): the previous check compared
            # str(p).startswith(str(forbidden)) after calling Path.resolve().
            # Path.resolve() does not require the path to exist and its behavior
            # for non-existent absolute paths is platform-dependent (confirmed:
            # on Termux/Android, where /etc/shadow does not exist as a real file,
            # this comparison silently failed to match, so
            # authorize("write_file", "/etc/shadow", WORKSPACE_WRITE) incorrectly
            # returned True). String-prefix comparison is also unsound in general
            # -- it would wrongly flag "/etc/shadowbackup" as forbidden while
            # being fragile to any resolve() discrepancy for the real path.
            # Fixed to use an existence-independent, platform-consistent check:
            # compare resolved path components directly against each forbidden
            # path's own components, and also check the raw (unresolved) target
            # string as a fallback so a missing/virtualized filesystem can't
            # cause the check to silently pass through.
            try:
                p = Path(target).resolve()
            except Exception:
                p = Path(target)
            raw = Path(target)
            for forbidden in self._forbidden_paths:
                is_match = False
                for candidate in (p, raw):
                    try:
                        if candidate == forbidden or forbidden in candidate.parents:
                            is_match = True
                            break
                    except Exception:
                        pass
                    # Fallback string check against BOTH resolved and raw forms,
                    # anchored so "/etc/shadowbackup" cannot match "/etc/shadow".
                    cstr = str(candidate)
                    fstr = str(forbidden)
                    if cstr == fstr or cstr.startswith(fstr + os.sep):
                        is_match = True
                        break
                if is_match:
                    granted = False
                    reason = f"Path {target} is in forbidden security scope"
                    break

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
