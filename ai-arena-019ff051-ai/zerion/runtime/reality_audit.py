"""
Reality Audit

Replaces the previous hard-coded "--reality-audit" output
(a literal print claiming "67 automated tests passing" that never ran anything)
with an implementation that actually discovers and executes the test suite and
reports real results.

This module never fabricates a pass/fail count. If tests cannot be discovered
or executed, that failure is reported explicitly rather than papered over.
"""

from dataclasses import dataclass, field
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional


@dataclass
class RealityAuditResult:
    tests_discovered: int
    tests_executed: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration_seconds: float
    exit_code: int
    ran_successfully: bool
    raw_summary_line: str
    failure_details: List[str] = field(default_factory=list)
    command: str = ""

    @property
    def all_passed(self) -> bool:
        return self.ran_successfully and self.failed == 0 and self.errors == 0 and self.tests_executed > 0

    def render_text(self) -> str:
        lines = [
            "=== REAL-TIME REALITY AUDIT ===",
            f"Command:            {self.command}",
            f"Ran successfully:   {self.ran_successfully}",
            f"Tests discovered:   {self.tests_discovered}",
            f"Tests executed:     {self.tests_executed}",
            f"Passed:             {self.passed}",
            f"Failed:             {self.failed}",
            f"Errors:             {self.errors}",
            f"Skipped:            {self.skipped}",
            f"Duration:           {self.duration_seconds:.2f}s",
            f"Exit code:          {self.exit_code}",
        ]
        if self.failure_details:
            lines.append("Failures/Errors:")
            for f in self.failure_details[:20]:
                lines.append(f"  - {f}")
        if not self.ran_successfully:
            lines.append("NOTE: audit could not execute the test suite; see failure_details above.")
        return "\n".join(lines)


def _find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk upward from this file to find the directory containing tests/."""
    here = start or Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "tests").is_dir():
            return candidate
    # Fall back to the package's grandparent (zerion/runtime/../..)
    return Path(__file__).resolve().parents[2]


def run_reality_audit(target: Optional[str] = None, timeout_seconds: float = 120.0) -> RealityAuditResult:
    """
    Actually runs pytest against the real test suite (or a targeted subset)
    and parses genuine results. Never invents a count.

    target: optional pytest target (e.g. "tests/test_evolution.py") for a
            cheaper, documented targeted audit instead of the full suite.
    """
    repo_root = _find_repo_root()
    tests_path = target or "tests"
    cmd = [sys.executable, "-m", "pytest", tests_path, "-q", "--no-header"]
    command_str = " ".join(cmd)

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration = time.perf_counter() - t0
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except FileNotFoundError as exc:
        return RealityAuditResult(
            tests_discovered=0, tests_executed=0, passed=0, failed=0, skipped=0, errors=0,
            duration_seconds=time.perf_counter() - t0, exit_code=-1, ran_successfully=False,
            raw_summary_line="", command=command_str,
            failure_details=[f"pytest not available: {exc}"],
        )
    except subprocess.TimeoutExpired as exc:
        return RealityAuditResult(
            tests_discovered=0, tests_executed=0, passed=0, failed=0, skipped=0, errors=0,
            duration_seconds=timeout_seconds, exit_code=-1, ran_successfully=False,
            raw_summary_line="", command=command_str,
            failure_details=[f"pytest timed out after {timeout_seconds}s"],
        )

    passed = failed = skipped = errors = 0
    summary_line = ""
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.endswith("s") and (" passed" in stripped or " failed" in stripped or " error" in stripped
                                        or "no tests ran" in stripped):
            summary_line = stripped

    import re
    if summary_line:
        for pattern, group_name in [
            (r"(\d+) passed", "passed"),
            (r"(\d+) failed", "failed"),
            (r"(\d+) skipped", "skipped"),
            (r"(\d+) error", "errors"),
        ]:
            m = re.search(pattern, summary_line)
            if m:
                val = int(m.group(1))
                if group_name == "passed":
                    passed = val
                elif group_name == "failed":
                    failed = val
                elif group_name == "skipped":
                    skipped = val
                elif group_name == "errors":
                    errors = val

    tests_executed = passed + failed + skipped + errors
    failure_lines = [l for l in stdout.splitlines() if l.startswith("FAILED") or l.startswith("ERROR")]

    ran_successfully = proc.returncode in (0, 1) and (tests_executed > 0 or "no tests ran" in stdout.lower())
    if not ran_successfully and not failure_lines:
        failure_lines = [f"pytest exit code {proc.returncode}", stderr.strip()[:500]] if stderr.strip() else \
                         [f"pytest exit code {proc.returncode}"]

    return RealityAuditResult(
        tests_discovered=tests_executed,
        tests_executed=tests_executed,
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        duration_seconds=duration,
        exit_code=proc.returncode,
        ran_successfully=ran_successfully,
        raw_summary_line=summary_line,
        failure_details=failure_lines,
        command=command_str,
    )
