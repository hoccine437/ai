"""
Slice 7 — SelfModificationGate.

NO unrestricted autonomous source modification. Every proposed change must pass:
PROPOSAL -> STATIC ANALYSIS -> SECURITY CHECK -> TESTS -> SANDBOX -> BENCHMARK
-> REGRESSION COMPARISON -> POLICY CHECK -> PROMOTION OR REJECTION.

Rules honored here:
- A proposal is NOT an improvement because an LLM suggested it, code was
  generated, or tests passed. It requires BASELINE vs CANDIDATE measurement,
  sufficient evidence, and no regression. INCONCLUSIVE != SUCCESS.
- HIGH / CRITICAL changes are never auto-approved.
- Promotion is atomic: the previous state is snapshotted (and verified) BEFORE
  the change is applied; rollback restores the previous snapshot.
- Static analysis is AST-based (reuses the Slice 5 CapabilitySandbox gate),
  not a naive string blacklist.
- The gate is provider-independent: it protects the runtime regardless of the
  cognitive provider (OpenAI / Gemini / GGUF are irrelevant here).
"""

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from zerion.cognitive_os.capability_sandbox import CapabilitySandbox
from zerion.cognitive_os.genome import GenomeManager
from zerion.cognitive_os.improvement import (
    BASE_RISK,
    ImprovementProposal,
    ModificationType,
    ProposalStatus,
    RiskLevel,
)
from zerion.cognitive_os.policy_store import PolicyStore
from zerion.cognitive_os.snapshots import RuntimeSnapshot, SnapshotStore
from zerion.cognitive_os.telemetry import ArchitectureTelemetry

_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1,
               RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}

# Roles that, when a proposal touches them, escalate risk.
_HIGH_PERMISSION_HINTS = ("system_control", "financial", "self_modification",
                          "network", "write")

# Non-CONFIGURATION modification types with a REAL promotion path: they are
# applied to the versioned runtime PolicyStore (never to source code). The
# proposed_change must be {"policy": <name>, "value": <value>}.
_POLICY_APPLIED_TYPES = {
    ModificationType.STRATEGY_CHANGE,
    ModificationType.PROMPT_CHANGE,
    ModificationType.ROUTING_CHANGE,
    ModificationType.MEMORY_POLICY_CHANGE,
    ModificationType.CAPABILITY_CHANGE,
}


class GatePolicy:
    """Approval policy. LOW changes may auto-promote only when this explicitly
    permits it; everything else requires explicit approval."""

    def __init__(self, *, allow_low_auto: bool = True,
                 allow_medium_auto: bool = False,
                 require_rollback: bool = True):
        self.allow_low_auto = allow_low_auto
        self.allow_medium_auto = allow_medium_auto
        self.require_rollback = require_rollback

    def auto_allowed(self, risk: RiskLevel) -> bool:
        if risk == RiskLevel.LOW:
            return self.allow_low_auto
        if risk == RiskLevel.MEDIUM:
            return self.allow_medium_auto
        return False


class AnalysisResult:
    def __init__(self, passed: bool, violations: List[str],
                 risk: RiskLevel, reasons: List[str]):
        self.passed = passed
        self.violations = list(violations)
        self.risk = risk
        self.reasons = list(reasons)

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "violations": list(self.violations),
                "risk": self.risk.value, "reasons": list(self.reasons)}


class TestOutcome:
    def __init__(self, passed: bool, results: List[Dict[str, Any]]):
        self.passed = passed
        self.results = list(results)

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "results": list(self.results)}


class BenchmarkComparison:
    """Baseline vs candidate, with statistical discipline (min trials) and
    regression detection across correctness AND latency AND extra metrics.
    INCONCLUSIVE != SUCCESS."""

    VERDICTS = ("SUPPORTED", "REGRESSION", "INCONCLUSIVE", "UNSUPPORTED")

    def __init__(self, baseline: Dict[str, Any], candidate: Dict[str, Any],
                 verdict: str, samples: int, regressions: List[str],
                 deltas: Dict[str, float]):
        self.baseline = baseline
        self.candidate = candidate
        self.verdict = verdict
        self.samples = samples
        self.regressions = list(regressions)
        self.deltas = dict(deltas)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline": dict(self.baseline),
            "candidate": dict(self.candidate),
            "verdict": self.verdict,
            "samples": self.samples,
            "regressions": list(self.regressions),
            "deltas": dict(self.deltas),
            "improvement_observed": self.verdict == "SUPPORTED",
        }

    @staticmethod
    def compare(baseline_results: List[Dict[str, Any]],
                candidate_results: List[Dict[str, Any]],
                min_trials: int = 5,
                success_effect: float = 0.1,
                latency_factor: float = 1.5,
                latency_abs_ms: float = 50.0) -> "BenchmarkComparison":
        """Deterministic comparison of per-trial result dicts. Each trial:
        {"correct": bool, "latency_ms": float, "extra": {name: value}}."""
        samples = min(len(baseline_results), len(candidate_results))
        if samples < min_trials:
            return BenchmarkComparison(
                baseline={"samples": len(baseline_results)},
                candidate={"samples": len(candidate_results)},
                verdict="INCONCLUSIVE", samples=samples,
                regressions=[], deltas={})

        b_success = sum(1 for r in baseline_results[:samples] if r.get("correct")) / samples
        c_success = sum(1 for r in candidate_results[:samples] if r.get("correct")) / samples
        b_lat = sum(r.get("latency_ms", 0.0) for r in baseline_results[:samples]) / samples
        c_lat = sum(r.get("latency_ms", 0.0) for r in candidate_results[:samples]) / samples
        delta_success = round(c_success - b_success, 4)
        delta_latency = round(c_lat - b_lat, 4)

        regressions: List[str] = []
        if c_success < b_success - 0.001:
            regressions.append(f"correctness: {b_success:.3f} -> {c_success:.3f}")
        if c_lat > max(b_lat * latency_factor, b_lat + latency_abs_ms):
            regressions.append(f"latency: {b_lat:.2f}ms -> {c_lat:.2f}ms")
        # Extra metrics: candidate must not be worse on any named dimension.
        for r_b, r_c in zip(baseline_results[:samples], candidate_results[:samples]):
            for name, b_val in (r_b.get("extra") or {}).items():
                c_val = (r_c.get("extra") or {}).get(name)
                if c_val is None:
                    continue
                if c_val < b_val - 1e-9:
                    regressions.append(f"extra.{name}: {b_val} -> {c_val}")
                    break
        deltas = {"success": delta_success, "latency_ms": delta_latency}
        if regressions:
            verdict = "REGRESSION"
        elif delta_success >= success_effect:
            verdict = "SUPPORTED"
        elif delta_success <= -0.001:
            verdict = "REGRESSION"
        else:
            verdict = "UNSUPPORTED"
        return BenchmarkComparison(
            baseline={"samples": samples, "success_rate": round(b_success, 4),
                      "avg_latency_ms": round(b_lat, 2)},
            candidate={"samples": samples, "success_rate": round(c_success, 4),
                       "avg_latency_ms": round(c_lat, 2)},
            verdict=verdict, samples=samples, regressions=regressions,
            deltas=deltas)


class PromotionResult:
    def __init__(self, ok: bool, snapshot_version: Optional[int],
                 message: str, applied: bool):
        self.ok = ok
        self.snapshot_version = snapshot_version
        self.message = message
        self.applied = applied

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "snapshot_version": self.snapshot_version,
                "message": self.message, "applied": self.applied}


class RollbackResult:
    def __init__(self, ok: bool, restored_version: Optional[int],
                 message: str):
        self.ok = ok
        self.restored_version = restored_version
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "restored_version": self.restored_version,
                "message": self.message}


class SelfModificationGate:
    """The full gate. Provider-independent, evidence-required."""

    def __init__(self, sandbox: Optional[CapabilitySandbox] = None,
                 policy: Optional[GatePolicy] = None,
                 allowed_components: Optional[List[str]] = None,
                 security: Optional[Any] = None):
        self.sandbox = sandbox or CapabilitySandbox()
        self.policy = policy or GatePolicy()
        self.allowed_components = list(allowed_components or [])
        # Optional canonical SecurityBoundary. When present, self-modification
        # approval requires SYSTEM_MUTATE authorization — the model can never
        # bypass the boundary, and a boundary that does not hold SYSTEM_MUTATE
        # (the default) denies every self-modification at the approval gate.
        self.security = security

    # -- 1. static analysis + security check --------------------------------

    def static_analysis(self, proposal: ImprovementProposal) -> AnalysisResult:
        violations: List[str] = []
        reasons: List[str] = []

        # Scope: the target must be within the allowed modification scope.
        if proposal.scope and proposal.target_component not in proposal.scope:
            violations.append(
                f"target '{proposal.target_component}' outside allowed scope "
                f"{sorted(proposal.scope)}")
        if self.allowed_components and proposal.target_component not in self.allowed_components:
            violations.append(
                f"target '{proposal.target_component}' not in gate allowed components")

        # Files: any declared file paths must stay inside the scope.
        files = proposal.proposed_change.get("files") if isinstance(
            proposal.proposed_change, dict) else None
        if isinstance(files, list):
            for f in files:
                fs = str(f)
                if not fs.startswith(("zerion/cognitive_os/",
                                      "zerion/cognitive_os")):
                    if not any(fs.startswith(c) for c in proposal.scope):
                        violations.append(f"file '{fs}' outside allowed scope")

        # Code: AST-based inspection via the Slice 5 sandbox gate.
        if proposal.modification_type in (ModificationType.CODE_CHANGE,
                                          ModificationType.CAPABILITY_CHANGE):
            code = proposal.proposed_change
            if not isinstance(code, str) or not code.strip():
                violations.append("code change has no implementation")
            else:
                violation = self.sandbox.inspect(code)
                if violation is not None:
                    violations.append(f"static analysis: {violation}")

        # Unbounded resource usage / destructive / secret patterns in strings.
        if isinstance(proposal.proposed_change, dict):
            blob = str(proposal.proposed_change).lower()
            for bad in ("rm -rf", "os.system", "subprocess.popen",
                        "chmod 777", "sudo "):
                if bad in blob:
                    violations.append(f"forbidden pattern in change: {bad}")

        risk = self.risk_assessment(proposal)
        return AnalysisResult(passed=not violations, violations=violations,
                              risk=risk, reasons=reasons)

    # -- 2. risk assessment -------------------------------------------------

    def risk_assessment(self, proposal: ImprovementProposal) -> RiskLevel:
        risk = BASE_RISK.get(proposal.modification_type, RiskLevel.MEDIUM)
        idx = _RISK_ORDER[risk]

        rollback = (proposal.rollback_plan or "").strip().lower()
        if not rollback or rollback in ("none", "n/a", "not needed"):
            idx = min(3, idx + 1)  # no rollback path -> escalate

        joined = " ".join(proposal.dependencies +
                          proposal.affected_capabilities).lower()
        if any(hint in joined for hint in _HIGH_PERMISSION_HINTS):
            idx = min(3, idx + 1)

        if proposal.modification_type == ModificationType.ARCHITECTURE_CHANGE:
            idx = 3
        if proposal.risk == RiskLevel.CRITICAL:
            idx = 3  # explicit critical never downgrades

        return list(RiskLevel)[idx]

    # -- 3. tests (sandboxed for code) --------------------------------------

    def run_tests(self, proposal: ImprovementProposal,
                  tests: Optional[List[Dict[str, Any]]] = None) -> TestOutcome:
        tests = tests if tests is not None else proposal.test_plan
        results: List[Dict[str, Any]] = []
        all_passed = True
        for t in tests:
            name = t.get("name", "unnamed")
            kind = t.get("kind", "code" if proposal.modification_type in (
                ModificationType.CODE_CHANGE,
                ModificationType.CAPABILITY_CHANGE) else "config")
            try:
                if kind == "code":
                    code = proposal.proposed_change
                    out = self.sandbox.run_artifact(
                        code, t.get("inputs", {}),
                        timeout_s=t.get("timeout_s", 4.0))
                    passed = bool(out.get("success")
                                  and out.get("result") == t.get("expected"))
                    results.append({"name": name, "passed": passed,
                                    "result": out.get("result"),
                                    "violation": out.get("violation")})
                elif kind == "config":
                    value = self._config_lookup(proposal.proposed_change,
                                                t.get("config_path", []))
                    passed = value == t.get("expected_value")
                    results.append({"name": name, "passed": passed,
                                    "value": value,
                                    "expected": t.get("expected_value")})
                elif kind == "unit" and callable(t.get("check")):
                    passed = bool(t["check"](proposal.proposed_change))
                    results.append({"name": name, "passed": passed})
                else:
                    passed = False
                    results.append({"name": name, "passed": False,
                                    "violation": "unsupported test kind"})
            except Exception as e:  # noqa: BLE001
                passed = False
                results.append({"name": name, "passed": False,
                                "violation": f"{type(e).__name__}: {e}"})
            all_passed = all_passed and passed
        return TestOutcome(passed=all_passed, results=results)

    @staticmethod
    def _config_lookup(config: Any, path: List[str]) -> Any:
        cur = config
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
        return cur

    # -- 4. benchmark (baseline vs candidate) -------------------------------

    def benchmark(self, proposal: ImprovementProposal,
                  baseline_runner: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
                  candidate_runner: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
                  trials: int = 10,
                  min_trials: int = 5) -> BenchmarkComparison:
        """Runners take a config and return per-trial result dicts. The gate
        only compares; it never fabricates improvement."""
        baseline_config = proposal.analysis.get("baseline_config")
        candidate_config = proposal.analysis.get("candidate_config")
        if baseline_config is None or candidate_config is None:
            raise ValueError(
                "benchmark requires baseline_config and candidate_config in "
                "proposal.analysis (from the runtime orchestration)")
        b_results = list(baseline_runner(baseline_config))[:trials]
        c_results = list(candidate_runner(candidate_config))[:trials]
        return BenchmarkComparison.compare(b_results, c_results,
                                           min_trials=min_trials)

    # -- 5. policy check + approval -----------------------------------------

    def approve(self, proposal: ImprovementProposal,
                approval: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        # INV-001..INV-010 are enforced here as a real call site: the
        # immutable invariant root gate rejects proposals that would present
        # unverified claims as facts, bypass evaluator isolation, or fabricate
        # memory provenance. Denials carry the exact invariant id.
        try:
            from zerion.identity.invariants import check_invariants
            # proposed_change may be a code string (CODE_CHANGE) or a config
            # dict; only dict payloads can carry invariant-flag fields.
            proposed = (proposal.proposed_change
                        if isinstance(proposal.proposed_change, dict) else {})
            payload: Dict[str, Any] = {
                "unverified_claim_as_fact": bool(
                    (proposal.analysis or {}).get("claims_measured") is False),
                "manipulate_memory_provenance": bool(
                    proposal.modification_type == ModificationType.MEMORY_POLICY_CHANGE
                    and proposed.get("rewrite_provenance")),
                "bypass_evaluator_isolation": bool(
                    proposed.get("modify_benchmark_evaluator")),
            }
            ok, reason = check_invariants("self_modification", payload)
            if not ok:
                return False, reason
        except Exception:  # noqa: BLE001 — invariant gate failure must deny
            return False, "invariant gate unavailable: self-modification denied"

        # Security boundary next: SELF_MODIFICATION/SYSTEM_MUTATE is a
        # high-risk permission that is never held by default. If a boundary is
        # wired, it MUST authorize the operation or the gate refuses — policy
        # checks below never run for an unauthorized change.
        if self.security is not None:
            from zerion.runtime.security import PermissionLevel
            authorized = False
            try:
                authorized = self.security.authorize(
                    action="self_modification",
                    target=proposal.target_component,
                    required_permission=PermissionLevel.SYSTEM_MUTATE,
                    caller="self_modification_gate",
                    metadata={"proposal_id": proposal.proposal_id,
                              "modification_type": proposal.modification_type.value},
                )
            except Exception:  # noqa: BLE001 — authorization failure must deny
                authorized = False
            if not authorized:
                return False, (
                    "self-modification denied by security boundary "
                    "(SYSTEM_MUTATE not held)")
        analysis = proposal.analysis or {}
        if not analysis.get("passed"):
            return False, "static analysis failed"
        if not analysis.get("tests_passed"):
            return False, "tests failed"
        bench = proposal.benchmark or {}
        if bench.get("verdict") != "SUPPORTED":
            return False, (f"benchmark not supported: "
                           f"{bench.get('verdict', 'no benchmark')}")
        risk = RiskLevel(analysis.get("risk", "MEDIUM"))
        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            # Never AUTO-approved. An explicit human/operator approval can
            # unlock them (Slice 8 promotion path), still bounded by the gate.
            if not (approval or {}).get("explicit"):
                return False, f"{risk.value} risk changes require explicit approval"
            if risk == RiskLevel.CRITICAL and not (approval or {}).get("approver"):
                return False, "CRITICAL changes require a named approver"
        elif risk == RiskLevel.MEDIUM and not self.policy.auto_allowed(risk):
            if not (approval or {}).get("explicit"):
                return False, "MEDIUM risk requires explicit approval"
        if risk == RiskLevel.LOW and not self.policy.auto_allowed(risk):
            if not (approval or {}).get("explicit"):
                return False, "policy does not permit LOW auto-promotion"
        if self.policy.require_rollback and not (proposal.rollback_plan or "").strip():
            return False, "rollback plan required"
        return True, "approved"

    # -- 6. atomic promotion ------------------------------------------------

    # Modification types with a REAL promotion target: the versioned runtime
    # policy store (Slice 8). These promote to runtime policies — never to
    # source code — so the no-unrestricted-self-modification rule holds while
    # the promotion is real and the runtime can consume it.
    _POLICY_PROMOTABLE = {
        ModificationType.STRATEGY_CHANGE,
        ModificationType.PROMPT_CHANGE,
        ModificationType.ROUTING_CHANGE,
        ModificationType.MEMORY_POLICY_CHANGE,
        ModificationType.CAPABILITY_CHANGE,
    }
    # Modification types that are approval-only (never applied anywhere):
    _APPROVAL_ONLY = {
        ModificationType.CODE_CHANGE,
        ModificationType.ARCHITECTURE_CHANGE,
    }

    def promote(self, proposal: ImprovementProposal,
                genome_manager: GenomeManager,
                snapshot_store: SnapshotStore,
                *, approval: Optional[Dict[str, Any]] = None,
                policy_store=None) -> PromotionResult:
        ok, reason = self.approve(proposal, approval=approval)
        if not ok:
            return PromotionResult(ok=False, snapshot_version=None,
                                   message=reason, applied=False)

        current = genome_manager.current()
        snapshot = RuntimeSnapshot(
            version=snapshot_store.next_version(),
            timestamp=time.time(),
            changed_components=[proposal.target_component],
            configuration=dict(current.configuration),
            tests=list(proposal.test_results),
            benchmark_results=proposal.benchmark,
            approval_state={"proposal_id": proposal.proposal_id,
                            "risk": proposal.risk.value,
                            "modification_type": proposal.modification_type.value},
            rollback_reference=current.genome_id,
            label=f"pre-{proposal.proposal_id}",
        )
        # Atomic: snapshot is persisted BEFORE any mutation.
        snapshot_store.put(snapshot)
        proposal.snapshot_version = snapshot.version

        applied = False
        if proposal.modification_type == ModificationType.CONFIGURATION_CHANGE:
            changes = proposal.proposed_change
            if isinstance(changes, dict):
                candidate = genome_manager.propose_variation(
                    changes, allow_new_keys=True)
                genome_manager.record_evaluation(candidate.genome_id, {
                    "benchmark": proposal.benchmark,
                    "tests": proposal.test_results,
                    "snapshot_version": snapshot.version,
                })
                genome_manager.promote(candidate.genome_id)
                proposal.promoted_version = candidate.version
                applied = True
        elif (proposal.modification_type in self._POLICY_PROMOTABLE
              and policy_store is not None
              and isinstance(proposal.proposed_change, dict)):
            # Real promotion into the versioned runtime policy store. The
            # store deactivates the parent version (its history is preserved)
            # and records the parent so rollback can restore it.
            policy = policy_store.apply(
                proposal.target_component, proposal.proposed_change,
                applied_by=proposal.proposal_id,
                snapshot_version=snapshot.version)
            proposal.promoted_version = policy.version
            proposal.policy_version = policy.version
            applied = True
        # CODE_CHANGE / ARCHITECTURE_CHANGE (and any type without a promotion
        # target) are APPROVED with evidence + snapshot but never applied — no
        # unrestricted source modification. Their approval state is preserved.
        proposal.promoted_at = time.time()
        return PromotionResult(ok=True, snapshot_version=snapshot.version,
                               message=("promoted" if applied else
                                        "approved (evidence recorded; not "
                                        "applied to production)"),
                               applied=applied)

    # -- 7. post-promotion monitoring ---------------------------------------

    def monitor_regression(self, proposal: ImprovementProposal,
                           telemetry: ArchitectureTelemetry,
                           thresholds: Optional[Dict[str, float]] = None) -> bool:
        """Detect post-promotion regression via REAL telemetry on the affected
        component. Thresholds mirror the bottleneck detector's."""
        if proposal.status != ProposalStatus.APPROVED:
            return False
        th = thresholds or {
            "verification_success": 0.5, "tool_success": 0.5,
            "model_success": 0.5, "routing_success": 0.5,
            "capability_success": 0.5, "recovery_rate": 0.5,
        }
        component = proposal.target_component
        degraded = False
        for metric, threshold in th.items():
            rate = telemetry.rate(component, metric)
            if rate is not None and rate < threshold:
                degraded = True
        return degraded

    # -- 8. rollback --------------------------------------------------------

    def rollback(self, proposal: ImprovementProposal,
                 genome_manager: GenomeManager,
                 snapshot_store: SnapshotStore,
                 reason: str = "",
                 policy_store=None) -> RollbackResult:
        if proposal.snapshot_version is None:
            return RollbackResult(ok=False, restored_version=None,
                                  message="no snapshot to restore")
        snapshot = snapshot_store.get(proposal.snapshot_version)
        if snapshot is None:
            return RollbackResult(ok=False, restored_version=None,
                                  message="snapshot missing — cannot rollback")
        # Policy-store promotions are rolled back by restoring the parent
        # version as active (the value is never destroyed, only deactivated).
        if (proposal.modification_type in self._POLICY_PROMOTABLE
                and policy_store is not None
                and getattr(proposal, "policy_version", None) is not None):
            policy_store.rollback(proposal.target_component,
                                  reason=reason or "post-promotion regression")
            proposal.rollback_reason = reason or "post-promotion regression"
            proposal.status = ProposalStatus.ROLLED_BACK
            return RollbackResult(ok=True,
                                  restored_version=snapshot.version,
                                  message=(f"restored snapshot v{snapshot.version} "
                                           f"and policy {proposal.target_component}"))
        # Restore the pre-change configuration as the promoted genome.
        current = genome_manager.current()
        restored = current.clone()
        restored.configuration = dict(snapshot.configuration)
        genome_manager.rollback_to(restored)
        proposal.rollback_reason = reason or "post-promotion regression"
        proposal.status = ProposalStatus.ROLLED_BACK
        return RollbackResult(ok=True,
                              restored_version=snapshot.version,
                              message=f"restored snapshot v{snapshot.version}")
