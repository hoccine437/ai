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
    def __init__(self, default_timeout_seconds: float = 5.0):
        self.default_timeout = default_timeout_seconds

    async def run_python_code(self, code: str, timeout_seconds: Optional[float] = None) -> SandboxResult:
        timeout = timeout_seconds or self.default_timeout
        start_time = time.perf_counter()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name

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
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
