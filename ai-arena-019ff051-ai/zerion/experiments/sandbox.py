"""
Safe Execution Sandbox for Reality Experiments
"""

import asyncio
from dataclasses import dataclass
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Optional


@dataclass
class SandboxResult:
    success: bool
    return_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    resource_usage: Optional[Dict[str, Any]] = None


class ExecutionSandbox:
    def __init__(self, default_timeout_seconds: float = 5.0, security: Optional[Any] = None):
        self.default_timeout = default_timeout_seconds
        # Optional canonical SecurityBoundary. When present, every execution is
        # authorized through it before a subprocess is spawned — a denial
        # blocks execution and is audited (never silently bypassed).
        self.security = security

    def _authorized(self, temp_path: str, caller: str = "execution_sandbox") -> bool:
        if self.security is None:
            return True
        try:
            from zerion.runtime.security import PermissionLevel
            return self.security.authorize(
                action="execute_code",
                target=temp_path,
                required_permission=PermissionLevel.INTERNAL_EXECUTE,
                caller=caller,
                metadata={"subsystem": "execution_sandbox"},
            )
        except Exception:  # noqa: BLE001 — authorization failure must deny, never allow
            return False

    async def run_python_code(self, code: str, timeout_seconds: Optional[float] = None) -> SandboxResult:
        timeout = timeout_seconds or self.default_timeout
        start_time = time.perf_counter()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name

        if not self._authorized(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return SandboxResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr="execution denied by security boundary",
                duration_ms=round((time.perf_counter() - start_time) * 1000.0, 2),
                timed_out=False,
            )

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SandboxResult(
                    success=(process.returncode == 0),
                    return_code=process.returncode or 0,
                    stdout=stdout_bytes.decode(errors="replace").strip(),
                    stderr=stderr_bytes.decode(errors="replace").strip(),
                    duration_ms=round(duration_ms, 2),
                    timed_out=False
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SandboxResult(
                    success=False,
                    return_code=-1,
                    stdout="",
                    stderr=f"Execution timed out after {timeout} seconds",
                    duration_ms=round(duration_ms, 2),
                    timed_out=True
                )
        finally:
            # Close the subprocess transport while its event loop is still
            # alive, so its destructor never runs against an already-closed
            # loop at GC time (avoids the "Event loop is closed" warning).
            if process is not None:
                transport = getattr(process, "_transport", None)
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:  # noqa: BLE001 — teardown only
                        pass
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
