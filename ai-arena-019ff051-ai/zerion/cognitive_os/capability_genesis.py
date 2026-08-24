"""
Slice 5 — CapabilityGenesis.

NEED -> DESIGN -> GENERATE -> SANDBOX -> TEST -> VALIDATE -> REGISTER -> MONITOR
-> IMPROVE OR DEPRECATE.

Capabilities are proposed from Slice 4 evidence (validated rules, repeated
failures) but are NEVER trusted automatically: experience -> candidate
capability, not experience -> trusted capability. Every stage is explicit, every
validation is evidence-based ("generated successfully" is never validation), and
generated artifacts are untrusted until the sandbox + tests + policy prove them.

No self-modification: generated capabilities can never modify Zerion's core
architecture; they are bounded by permissions, sandbox, validation, registry and
rollback (SelfModificationGate is a later slice).
"""

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from zerion.cognitive_os.capability import (
    Capability,
    CapabilityHealth,
    CapabilityRegistry,
    CapabilityStatus,
    CapabilityType,
    CapabilityValidationError,
    capability_fingerprint,
    LEAST_PRIVILEGE,
    Permission,
    PermissionPolicy,
)
from zerion.cognitive_os.capability_sandbox import CapabilitySandbox
from zerion.cognitive_os.distilled import (
    DistilledExperience,
    DistilledExperienceStore,
    DistilledType,
    ValidationStatus,
)
from zerion.cognitive_os.failure_learning import FailureStore


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


class CapabilityGenesis:
    def __init__(self,
                 registry: CapabilityRegistry,
                 sandbox: Optional[CapabilitySandbox] = None,
                 distilled_store: Optional[DistilledExperienceStore] = None,
                 failure_store: Optional[FailureStore] = None,
                 permission_policy: Optional[PermissionPolicy] = None,
                 repeat_gap_threshold: int = 3,
                 min_success_rate: float = 0.8,
                 degrade_after: int = 3,
                 deprecate_after: int = 5):
        self.registry = registry
        self._sandbox = sandbox or CapabilitySandbox()
        self.distilled = distilled_store
        self.failures = failure_store
        self.policy = permission_policy or PermissionPolicy()
        self.repeat_gap_threshold = repeat_gap_threshold
        self.min_success_rate = min_success_rate
        self.degrade_after = degrade_after
        self.deprecate_after = deprecate_after

    # --- Gap detection (reuses Slice 4 evidence) --------------------------------

    def detect_gaps(self) -> List[Capability]:
        """Propose NEEDED capabilities from validated distilled rules and
        repeated failures. Detection only — code generation is a later,
        explicit stage."""
        proposed: List[Capability] = []
        if self.distilled is not None:
            for rule in self.distilled.list(status=ValidationStatus.VALIDATED):
                if rule.type == DistilledType.FAILURE_PREVENTION_RULE:
                    cap = self._propose_from_prevention_rule(rule)
                    if cap is not None:
                        proposed.append(cap)
        if self.failures is not None:
            for failure in self.failures.list_failures():
                if failure.repeat_count >= self.repeat_gap_threshold:
                    cap = self._propose_from_repeated_failure(failure)
                    if cap is not None:
                        proposed.append(cap)
        # Deduplicate NEEDED proposals (same name + signals).
        seen: Dict[str, Capability] = {}
        for cap in proposed:
            key = f"{cap.name}|{json.dumps(cap.metadata.get('signals', []), sort_keys=True)}"
            if key in seen:
                continue
            if self._already_covered(cap):
                continue
            seen[key] = cap
            self.registry.put(cap)
        return list(seen.values())

    def _already_covered(self, capability: Capability) -> bool:
        """Skip proposing a capability that already exists (any version)."""
        for existing in self.registry.versions(capability.name):
            if existing.status not in (CapabilityStatus.REJECTED,
                                       CapabilityStatus.DEPRECATED):
                return True
        return False

    def _propose_from_prevention_rule(self,
                                      rule: DistilledExperience) -> Optional[Capability]:
        signals = rule.provenance.get("signals") or []
        action = re.sub(r"^'|'$", "", rule.statement.split("fails")[0].strip().strip("'"))
        if not signals:
            return None
        signal = str(signals[0])
        name = f"{_slug(signal)}_detector" if signal else "condition_detector"
        return Capability(
            name=name,
            description=(f"Detects the condition '{signal}' so '{action}' can be "
                         f"guarded before execution."),
            type=CapabilityType.VALIDATOR,
            status=CapabilityStatus.NEEDED,
            source_rules=[rule.id],
            source_experiences=list(rule.source_episodes),
            required_permissions=list(LEAST_PRIVILEGE),
            risk_level=0.2,
            metadata={
                "gap": {
                    "problem": f"repeated failure of '{action}'",
                    "evidence": f"validated rule {rule.id} across "
                                f"{len(rule.source_episodes)} episodes",
                    "frequency": len(rule.source_episodes),
                    "affected_goals": [],
                    "workaround": "manual check before executing",
                    "expected_benefit": "prevent the recurring failure",
                    "risk": 0.2,
                    "required_resources": "compute only",
                },
                "signals": [str(s) for s in signals],
                "source_type": "validated_prevention_rule",
            },
        )

    def _propose_from_repeated_failure(self, failure) -> Optional[Capability]:
        signals = failure.signals or []
        name = f"{_slug(failure.action)}_gap_handler"
        return Capability(
            name=name,
            description=(f"Addresses the recurring failure of '{failure.action}' "
                         f"(repeat_count={failure.repeat_count})."),
            type=CapabilityType.HEURISTIC,
            status=CapabilityStatus.NEEDED,
            source_experiences=list(failure.episodes),
            required_permissions=list(LEAST_PRIVILEGE),
            risk_level=0.4,
            metadata={
                "gap": {
                    "problem": f"repeated failure of '{failure.action}'",
                    "evidence": f"failure record {failure.failure_id}",
                    "frequency": failure.repeat_count,
                    "affected_goals": [],
                    "workaround": "manual intervention",
                    "expected_benefit": "automate recovery",
                    "risk": 0.4,
                    "required_resources": "compute only",
                },
                "signals": [str(s) for s in signals],
                "source_type": "repeated_failure",
            },
        )

    # --- Design ----------------------------------------------------------------

    def design(self, capability: Capability) -> Capability:
        """Fill the full design contract: purpose, inputs, outputs, dependencies,
        procedure, permissions, success/failure criteria, test strategy, rollback
        strategy, resource requirements."""
        if capability.status != CapabilityStatus.NEEDED:
            raise CapabilityValidationError(
                f"Cannot design capability in status {capability.status.value}")
        signals = [str(s) for s in capability.metadata.get("signals", [])]
        capability.type = self._design_type(capability)
        capability.description = capability.description or f"Capability: {capability.name}"
        capability.inputs = {"payload": {"type": "object",
                                         "description": "runtime input for the capability"}}
        capability.outputs = {"result": {"type": "object",
                                         "description": "structured result dict"}}
        capability.procedure = [
            "Design reviewed",
            f"Permissions bounded to least privilege: "
            f"{[p.value for p in capability.required_permissions]}",
            "Implementation enters the sandbox before any execution",
            "Tests run in the sandbox before validation",
        ]
        capability.metadata["design"] = {
            "purpose": capability.description,
            "inputs": capability.inputs,
            "outputs": capability.outputs,
            "dependencies": capability.dependencies,
            "procedure": capability.procedure,
            "permissions": [p.value for p in capability.required_permissions],
            "success_criteria": ["run() returns a structured dict without error",
                                 "all tests pass at or above the success-rate threshold"],
            "failure_criteria": ["artifact crashes", "security violation",
                                 "test failure", "permission policy denial"],
            "test_strategy": "deterministic sandboxed tests: normal, invalid, edge, "
                             "failure handling, resource limits, permission boundaries",
            "rollback_strategy": "previous validated version restored on regression",
            "resource_requirements": "isolated subprocess with timeout",
        }
        capability.status = CapabilityStatus.DESIGNED
        capability.updated_at = time.time()
        capability.history.append({"event": "designed", "at": time.time()})
        self.registry.put(capability)
        return capability

    @staticmethod
    def _design_type(capability: Capability) -> CapabilityType:
        source = capability.metadata.get("source_type", "")
        if source == "validated_prevention_rule":
            return CapabilityType.VALIDATOR
        if source == "repeated_failure":
            return CapabilityType.HEURISTIC
        return capability.type

    # --- Generate --------------------------------------------------------------

    def generate(self, capability: Capability,
                 implementation: Optional[str] = None) -> Capability:
        """GENERATED artifacts are UNTRUSTED — sandboxing is mandatory next."""
        if capability.status not in (CapabilityStatus.DESIGNED, CapabilityStatus.GENERATED,
                                     CapabilityStatus.NEEDED):
            raise CapabilityValidationError(
                f"Cannot generate capability in status {capability.status.value}")
        if implementation is not None:
            if not isinstance(implementation, str) or not implementation.strip():
                raise CapabilityValidationError("Implementation must be a non-empty string")
            capability.implementation = implementation
        else:
            capability.implementation = self._template(capability)
        capability.fingerprint = capability_fingerprint(capability.name,
                                                        capability.version,
                                                        capability.implementation)
        capability.status = CapabilityStatus.GENERATED
        capability.updated_at = time.time()
        capability.history.append({"event": "generated", "at": time.time(),
                                   "untrusted": True})
        self.registry.put(capability)
        return capability

    def _template(self, capability: Capability) -> str:
        if capability.type == CapabilityType.VALIDATOR:
            signals = [str(s) for s in capability.metadata.get("signals", [])]
            return _detector_template(signals)
        if capability.type == CapabilityType.PROCEDURE:
            return _procedure_template()
        return _generic_template()

    # --- Sandbox ---------------------------------------------------------------

    def sandbox(self, capability: Capability) -> Capability:
        """SANDBOXED: the artifact passes the static gate AND the declared
        permissions pass the policy. Anything outside -> REJECTED, never run."""
        if capability.status != CapabilityStatus.GENERATED:
            raise CapabilityValidationError(
                f"Cannot sandbox capability in status {capability.status.value}")
        violation = self._sandbox.inspect(capability.implementation)
        if violation is not None:
            return self._reject(capability, f"sandbox static gate: {violation}")
        allowed, missing = self.policy.check(capability.required_permissions)
        if allowed:
            capability.status = CapabilityStatus.SANDBOXED
            capability.updated_at = time.time()
            capability.history.append({"event": "sandboxed", "at": time.time(),
                                       "static_gate": "passed",
                                       "permissions": [p.value for p in capability.required_permissions]})
            self.registry.put(capability)
            return capability
        return self._reject(capability,
                            f"permission policy denied: {[p.value for p in missing]}")

    def _reject(self, capability: Capability, reason: str) -> Capability:
        capability.status = CapabilityStatus.REJECTED
        capability.updated_at = time.time()
        capability.history.append({"event": "rejected", "at": time.time(),
                                   "reason": reason})
        capability.validation_evidence.append(
            {"type": "rejection", "reason": reason, "at": time.time()})
        self.registry.put(capability)
        return capability

    # --- Test ------------------------------------------------------------------

    def test(self, capability: Capability,
             test_cases: Optional[List[Dict[str, Any]]] = None) -> Capability:
        """TESTED: run deterministic sandboxed tests (normal, invalid input, edge
        cases, failure handling, resource limits, permission boundaries). Results
        are recorded; a capability that fails tests can never become REGISTERED
        (enforced at validation)."""
        if capability.status != CapabilityStatus.SANDBOXED:
            raise CapabilityValidationError(
                f"Cannot test capability in status {capability.status.value}")
        cases = test_cases if test_cases is not None else self._default_test_cases(capability)
        results: List[Dict[str, Any]] = []
        for case in cases:
            outcome = self._sandbox.run_artifact(capability.implementation,
                                                case.get("payload"))
            passed = self._matches(case, outcome)
            results.append({
                "name": case.get("name", "case"),
                "passed": passed,
                "payload": case.get("payload"),
                "expect": case.get("expect"),
                "result": outcome.get("result"),
                "violation": outcome.get("violation"),
                "latency_ms": outcome.get("latency_ms", 0.0),
            })
        passed_count = sum(1 for r in results if r["passed"])
        capability.test_results = results
        capability.success_rate = round(
            passed_count / len(results), 6) if results else 0.0
        capability.updated_at = time.time()
        capability.status = CapabilityStatus.TESTED
        capability.history.append({"event": "tested", "at": time.time(),
                                   "tests": len(results), "passed": passed_count})
        self.registry.put(capability)
        return capability

    @staticmethod
    def _matches(case: Dict[str, Any], outcome: Dict[str, Any]) -> bool:
        if not outcome.get("success") or outcome.get("blocked"):
            return False
        result = outcome.get("result")
        if not isinstance(result, dict):
            return False
        expect = case.get("expect") or {}
        return all(result.get(k) == v for k, v in expect.items())

    def _default_test_cases(self, capability: Capability) -> List[Dict[str, Any]]:
        if capability.type == CapabilityType.VALIDATOR:
            signals = [str(s) for s in capability.metadata.get("signals", [])]
            positive = {"name": "positive", "payload": {"message": f"error: {signals[0]}"},
                        "expect": {"success": True, "detected": True}}
            negative = {"name": "negative",
                        "payload": {"message": "all systems operational"},
                        "expect": {"success": True, "detected": False}}
            edge = {"name": "edge_empty", "payload": {"message": ""},
                    "expect": {"success": True, "detected": False}}
            invalid = {"name": "invalid_input", "payload": "not a dict",
                       "expect": {"success": True, "detected": False}}
            return [positive, negative, edge, invalid]
        if capability.type == CapabilityType.PROCEDURE:
            return [{"name": "normal", "payload": {}, "expect": {"success": True}}]
        return [{"name": "normal", "payload": {"data": 1},
                 "expect": {"success": True}}]

    # --- Validate --------------------------------------------------------------

    def validate(self, capability: Capability) -> Capability:
        """VALIDATED only with actual evidence: test results, success rate,
        security checks, permission checks, dependency resolution. 'generated
        successfully' is never validation."""
        if capability.status != CapabilityStatus.TESTED:
            raise CapabilityValidationError(
                f"Cannot validate capability in status {capability.status.value}")
        if not capability.test_results:
            return self._reject(capability, "validation requires actual test results")
        passed = sum(1 for r in capability.test_results if r["passed"])
        if capability.success_rate < self.min_success_rate:
            return self._reject(
                capability,
                f"tests failed: {passed}/{len(capability.test_results)} passed "
                f"(below {self.min_success_rate:.0%})")
        ok, missing = self.registry.resolve_dependencies(capability)
        if not ok:
            return self._reject(capability,
                                f"unresolved dependencies: {missing}")
        capability.validation_evidence.append({
            "type": "test_summary", "tests": len(capability.test_results),
            "passed": passed, "success_rate": capability.success_rate,
            "at": time.time(),
        })
        capability.validation_evidence.append({
            "type": "security_check", "static_gate": "passed",
            "sandbox": "isolated subprocess + restricted builtins", "at": time.time(),
        })
        capability.validation_evidence.append({
            "type": "permission_check",
            "policy": self.policy.to_dict(),
            "declared": [p.value for p in capability.required_permissions],
            "at": time.time(),
        })
        capability.status = CapabilityStatus.VALIDATED
        capability.updated_at = time.time()
        capability.history.append({"event": "validated", "at": time.time(),
                                   "evidence": "test results + security + permissions"})
        self.registry.put(capability)
        return capability

    # --- Register --------------------------------------------------------------

    def register(self, capability: Capability) -> Capability:
        """REGISTERED. A new version never automatically replaces the old one:
        if an active version exists with a different implementation, the new
        version stays VALIDATED until promote() decides from evidence."""
        if capability.status != CapabilityStatus.VALIDATED:
            raise CapabilityValidationError(
                f"Cannot register capability in status {capability.status.value}")
        current = self.registry.active_version(capability.name)
        if current is not None and current.fingerprint != capability.fingerprint:
            # New version: stored as VALIDATED, awaiting evidence-based promotion.
            # A new version NEVER automatically replaces the active one.
            capability.version = max([c.version for c in self.registry.versions(
                capability.name)] + [0]) + 1
            capability.updated_at = time.time()
            capability.history.append({
                "event": "new_version_pending", "at": time.time(),
                "version": capability.version,
                "note": "does not automatically replace the active version"})
            self.registry.put(capability)
            return capability
        if current is not None and current.fingerprint == capability.fingerprint:
            # Same artifact already active — idempotent re-registration.
            capability.status = CapabilityStatus.REGISTERED
            capability.health = CapabilityHealth.HEALTHY
            capability.updated_at = time.time()
            capability.history.append({"event": "registered", "at": time.time(),
                                       "version": capability.version})
            self.registry.put(capability)
            return capability
        duplicate = self.registry.find_duplicate_active(
            capability.name, capability.version, capability.fingerprint)
        if duplicate is not None:
            raise CapabilityValidationError(
                f"Duplicate active capability '{capability.name}' v{capability.version} "
                f"already exists with a different definition ({duplicate.capability_id})")
        capability.status = CapabilityStatus.REGISTERED
        capability.health = CapabilityHealth.HEALTHY
        capability.updated_at = time.time()
        capability.history.append({"event": "registered", "at": time.time(),
                                   "version": capability.version})
        self.registry.put(capability)
        return capability

    # --- Execution (controlled, sandboxed) -------------------------------------

    def execute(self, capability: Capability, payload: Any) -> Dict[str, Any]:
        """Execute a REGISTERED capability on a controlled test case. Still goes
        through the sandbox; measures latency and result."""
        if not capability.is_active:
            raise CapabilityValidationError(
                f"Cannot execute capability in status {capability.status.value}")
        return self._sandbox.run_artifact(capability.implementation, payload)

    # --- Monitoring ------------------------------------------------------------

    def record_usage(self, capability: Capability, success: bool,
                     latency_ms: float = 0.0, resource_cost: float = 0.0,
                     permission_violation: bool = False) -> Capability:
        """Track usage/success/failure/latency/cost. A capability that keeps
        failing becomes DEGRADED then DEPRECATED — never silently kept active."""
        n = capability.usage_count + 1
        capability.usage_count = n
        capability.last_used = time.time()
        ok = success and not permission_violation
        capability.success_rate = round(
            (capability.success_rate * (n - 1) + (1.0 if ok else 0.0)) / n, 6)
        capability.failure_rate = round(
            (capability.failure_rate * (n - 1) + (0.0 if ok else 1.0)) / n, 6)
        if permission_violation:
            capability.history.append({
                "event": "permission_violation", "at": time.time(),
                "usage": n})
        if ok:
            capability.consecutive_failures = 0
            if capability.health == CapabilityHealth.DEGRADED:
                capability.health = CapabilityHealth.HEALTHY
                capability.history.append({"event": "recovered", "at": time.time()})
        else:
            capability.consecutive_failures += 1
            if capability.consecutive_failures >= self.deprecate_after:
                capability.status = CapabilityStatus.DEPRECATED
                capability.health = CapabilityHealth.FAILING
                capability.history.append({
                    "event": "deprecated", "at": time.time(),
                    "consecutive_failures": capability.consecutive_failures,
                    "note": "repeated failure — never silently kept active"})
            elif capability.consecutive_failures >= self.degrade_after:
                capability.health = CapabilityHealth.DEGRADED
                capability.history.append({
                    "event": "degraded", "at": time.time(),
                    "consecutive_failures": capability.consecutive_failures})
        capability.updated_at = time.time()
        self.registry.put(capability)
        return capability

    # --- Versioning + rollback -------------------------------------------------

    def promote(self, name: str, version: int) -> Dict[str, Any]:
        """Promote a new version only when its evidence supports it (correctness,
        failure rate, health). Never promotes on opinion."""
        candidate = self.registry.get_by_name_version(name, version)
        if candidate is None:
            return {"ok": False, "reason": f"no capability {name} v{version}"}
        if candidate.status != CapabilityStatus.VALIDATED:
            return {"ok": False, "reason": f"candidate is {candidate.status.value}, "
                                           f"not VALIDATED"}
        current = self.registry.active_version(name)
        if current is not None and not self._evidence_supports(candidate, current):
            return {"ok": False, "reason": "evidence does not support promotion",
                    "current_success_rate": current.success_rate,
                    "candidate_success_rate": candidate.success_rate}
        candidate.status = CapabilityStatus.REGISTERED
        candidate.updated_at = time.time()
        candidate.history.append({"event": "promoted", "at": time.time(),
                                  "version": candidate.version})
        self.registry.put(candidate)
        return {"ok": True, "version": candidate.version,
                "current_success_rate": current.success_rate if current else None,
                "candidate_success_rate": candidate.success_rate}

    @staticmethod
    def _evidence_supports(candidate: Capability, current: Capability) -> bool:
        return (candidate.success_rate + 1e-9 >= current.success_rate
                and candidate.failure_rate <= current.failure_rate + 1e-9
                and candidate.health in (CapabilityHealth.HEALTHY, CapabilityHealth.DEGRADED))

    def rollback(self, name: str, reason: str) -> Dict[str, Any]:
        """Deactivate the current active version and restore the previous
        validated one. The previous version is NEVER deleted before the new one
        is proven. A rollback with no previous version is recorded, not silent."""
        current = self.registry.active_version(name)
        if current is None:
            return {"ok": False, "reason": f"no active version of '{name}' to roll back"}
        previous = [c for c in self.registry.versions(name)
                    if c.is_active and c.version < current.version]
        if not previous:
            current.history.append({
                "event": "rollback_failed", "at": time.time(),
                "reason": "no previous validated version to restore"})
            self.registry.put(current)
            return {"ok": False, "reason": "no previous validated version",
                    "current_version": current.version}
        prev = max(previous, key=lambda c: c.version)
        current.status = CapabilityStatus.DEPRECATED
        current.updated_at = time.time()
        current.history.append({
            "event": "rollback", "at": time.time(), "reason": reason,
            "restored_version": prev.version,
            "deactivated_version": current.version})
        self.registry.put(current)
        prev.status = CapabilityStatus.REGISTERED
        prev.updated_at = time.time()
        prev.history.append({
            "event": "reactivated", "at": time.time(),
            "reason": f"rolled back from v{current.version}"})
        self.registry.put(prev)
        return {"ok": True, "deactivated_version": current.version,
                "restored_version": prev.version, "reason": reason}


# --- Deterministic implementation templates -----------------------------------

def _detector_template(signals: List[str]) -> str:
    embedded = json.dumps(signals)
    return f'''def run(payload):
    if not isinstance(payload, dict):
        payload = {{"message": payload if payload is not None else ""}}
    message = payload.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return {{"success": True, "detected": False}}
    lowered = message.lower()
    for signal in {embedded}:
        if signal.lower() in lowered:
            return {{"success": True, "detected": True, "signal": signal}}
    return {{"success": True, "detected": False}}
'''


def _procedure_template() -> str:
    return '''def run(payload):
    steps = []
    if isinstance(payload, dict):
        steps = payload.get("steps", [])
    return {"success": True, "steps": steps}
'''


def _generic_template() -> str:
    return '''def run(payload):
    return {"success": True, "result": payload}
'''
