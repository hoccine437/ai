"""
Slice 5 — CapabilitySandbox.

Generated capability artifacts are UNTRUSTED. They can never run directly in the
main runtime: they enter this sandbox first, which enforces at minimum:

- restricted filesystem   (no open/IO builtins, temp cwd, no pathlib/shutil)
- restricted network     (no socket/urllib/http modules reachable)
- execution timeout      (outer subprocess kill via reused ExecutionSandbox)
- resource limits        (timeout bound; no subprocess spawning to exhaust CPU)
- no access to secrets   (subprocess environment is cleared before artifact exec)
- no privilege escalation(no setuid/chmod, no os module at all)
- no unrestricted subprocess execution (imports are impossible)

The repository's existing ``ExecutionSandbox`` (zerion/experiments/sandbox.py)
is REUSED as the outer process-isolation/timeout layer; this module adds the
static gate + restricted-builtins isolation that the legacy sandbox lacks (the
legacy one runs plain python with full env and full stdlib, so os.system /
socket / secrets would all be reachable). No second unrelated sandbox is created.
"""

import ast
import asyncio
import concurrent.futures
import json
import re
import time
from typing import Any, Dict, List, Optional

from zerion.experiments.sandbox import ExecutionSandbox


class SecurityViolationError(RuntimeError):
    """Raised when a generated artifact attempts something outside its bounds."""


# Restricted builtins: no imports, no IO, no eval/exec/compile, no introspection.
_SAFE_BUILTINS: Dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "sum": sum, "len": len, "range": range,
    "round": round, "sorted": sorted, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple,
    "enumerate": enumerate, "zip": zip, "any": any, "all": all,
    "isinstance": isinstance, "frozenset": frozenset,
    "True": True, "False": False, "None": None,
}

_FORBIDDEN_MODULES = {
    "os", "subprocess", "socket", "sys", "shutil", "pathlib", "ctypes",
    "pickle", "multiprocessing", "threading", "importlib", "http", "urllib",
    "requests", "ftplib", "smtplib", "telnetlib", "pty", "signal", "resource",
}
_FORBIDDEN_ATTRS = {
    "__subclasses__", "__class__", "__bases__", "__globals__", "__builtins__",
    "__import__", "__getattribute__", "__setattr__", "__delattr__",
    "system", "popen", "Popen", "call", "run", "setuid", "setgid", "chmod",
    "chown", "unlink", "remove", "rmdir", "makedirs", "mkdir", "symlink",
    "link", "rename", "open", "read", "write",
}
_FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "open", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "input", "breakpoint", "__import__",
    "execfile", "memoryview", "help",
}
_DANGEROUS_STRINGS = (
    "rm -rf", "sudo ", "chmod 777", "mkfs", "dd if=", ">/etc/",
    "chown root", "passwd", "/proc/", "/dev/",
)


class CapabilitySandbox:
    def __init__(self, default_timeout_s: float = 4.0):
        self.outer = ExecutionSandbox(default_timeout_seconds=default_timeout_s)
        self.default_timeout_s = default_timeout_s

    # --- Static gate (AST-based, deterministic, not a naive string blacklist) --

    def inspect(self, code: str) -> Optional[str]:
        """Return a violation reason if the artifact must be blocked, else None.

        This is defense in depth on top of the restricted-execution layer (where
        imports genuinely fail). It catches obvious attacks fast and blocks
        introspection-based sandbox escapes."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"artifact is not valid python: {e}"
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return f"imports are not allowed in capability artifacts ({node.lineno})"
            if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
                return f"forbidden attribute access: .{node.attr} (line {node.lineno})"
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in _FORBIDDEN_CALLS:
                    return f"forbidden call: {name}() (line {node.lineno})"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lowered = node.value.lower()
                if any(bad in lowered for bad in _DANGEROUS_STRINGS):
                    return "artifact contains a dangerous command string"
        return None

    # --- Execution -------------------------------------------------------------

    def run_artifact(self, code: str, payload: Any,
                     timeout_s: Optional[float] = None) -> Dict[str, Any]:
        """Execute a generated artifact's ``run(payload)`` in the sandbox.
        Returns a structured result; security violations and timeouts are
        reported, never executed."""
        violation = self.inspect(code)
        if violation is not None:
            return {"success": False, "blocked": True, "violation": violation,
                    "result": None, "latency_ms": 0.0}
        harness = self._harness(code, payload)
        start = time.perf_counter()
        outer = self._run_sync(harness, timeout_s or self.default_timeout_s)
        latency_ms = round((time.perf_counter() - start) * 1000.0, 3)
        if outer.timed_out:
            return {"success": False, "blocked": True,
                    "violation": f"execution timed out after {outer.duration_ms}ms",
                    "result": None, "latency_ms": latency_ms}
        if not outer.success:
            return {"success": False, "blocked": True,
                    "violation": f"artifact crashed: {outer.stderr[:300]}",
                    "result": None, "latency_ms": latency_ms}
        marker = "CAPABILITY_RESULT:"
        line = next((ln for ln in outer.stdout.splitlines()
                     if ln.startswith(marker)), None)
        if line is None:
            return {"success": False, "blocked": True,
                    "violation": "artifact produced no result", "result": None,
                    "latency_ms": latency_ms}
        try:
            body = json.loads(line[len(marker):])
        except json.JSONDecodeError as e:
            return {"success": False, "blocked": True,
                    "violation": f"artifact result not serializable: {e}",
                    "result": None, "latency_ms": latency_ms}
        if not body.get("ok"):
            return {"success": False, "blocked": True,
                    "violation": body.get("error", "artifact failed"),
                    "result": None, "latency_ms": latency_ms}
        return {"success": True, "blocked": False, "violation": None,
                "result": body.get("result"), "latency_ms": latency_ms}

    def _run_sync(self, harness: str, timeout_s: float):
        """Synchronous bridge over the reused (async) ExecutionSandbox: run it on
        a worker thread with its own event loop. ExecutionSandbox itself enforces
        the subprocess timeout, so the future resolves promptly."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                self.outer.run_python_code(harness, timeout_seconds=timeout_s))
            return future.result(timeout=timeout_s + 10.0)

    @staticmethod
    def _harness(code: str, payload: Any) -> str:
        """Restricted-exec harness. Runs inside the legacy ExecutionSandbox
        subprocess: the environment is cleared BEFORE the artifact executes, so
        no secrets are reachable even if an escape were attempted."""
        names = json.dumps(sorted(_SAFE_BUILTINS.keys()))
        return f'''
import json, os
os.environ.clear()
import builtins as _b
_SAFE_NAMES = {names}
_SB = {{name: getattr(_b, name) for name in _SAFE_NAMES
        if name not in ("True", "False", "None")}}
_SB["True"] = True
_SB["False"] = False
_SB["None"] = None
ARTIFACT = {code!r}
PAYLOAD = {payload!r}
ns = {{"__builtins__": _SB}}
try:
    exec(compile(ARTIFACT, "<capability>", "exec"), ns)
    fn = ns.get("run")
    if fn is None:
        raise RuntimeError("artifact must define run(payload)")
    result = fn(PAYLOAD)
    print("CAPABILITY_RESULT:" + json.dumps({{"ok": True, "result": result}}))
except Exception as e:
    print("CAPABILITY_RESULT:" + json.dumps({{"ok": False, "error": type(e).__name__ + ": " + str(e)}}))
'''
