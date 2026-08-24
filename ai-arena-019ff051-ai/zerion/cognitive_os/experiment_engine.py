"""
Slice 3 — RealityExperimentEngine.

Turns QUESTION -> HYPOTHESES into
QUESTION -> HYPOTHESES -> EXPERIMENT -> OBSERVATION -> COMPARISON -> BELIEF UPDATE.

Design rules honored here:

- Controlled testing: every experiment defines its predictions, expected
  evidence, success conditions, failure conditions and safety constraints BEFORE
  execution. The hypothesis is never rewritten after the result is seen.
- Safety: experiments respect explicit permissions. CODE_TEST requires
  ``allow_code``, TOOL_EXECUTION requires ``allow_tools``, WEB_VERIFICATION
  requires ``allow_network``. Anything outside permissions becomes BLOCKED and is
  never executed. No OS commands, no filesystem writes, no network.
- Reality vs simulation: every observation carries a mode. SIMULATED / TEST /
  MODEL_GENERATED evidence can never be recorded as real-world confirmation.
- Evidence must have provenance; fabricated, duplicate and stale evidence is
  rejected or flagged before it can influence belief.
- A failed experiment is data: failure, error, environment, hypothesis and
  rollback info are recorded. Repeated failure is bounded by max_attempts.
- Hypotheses are scored by evidence, never by opinion; a generated hypothesis is
  never automatically knowledge.
"""

import math
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from zerion.cognitive_os.belief import Belief, BeliefLifecycle, BeliefRevision, BeliefStore
from zerion.cognitive_os.evidence import (
    Evidence,
    EvidenceMode,
    EvidenceStore,
    EvidenceValidationError,
    EvidenceVerdict,
    MODE_WEIGHT,
    Provenance,
)
from zerion.cognitive_os.experiment import (
    Experiment,
    ExperimentLifecycle,
    ExperimentStore,
    ExperimentTransitionError,
    ExperimentType,
    ExperimentValidationError,
    transition,
)
from zerion.cognitive_os.hypothesis import Hypothesis, HypothesisLifecycle, HypothesisStore
from zerion.cognitive_os.question import Question, QuestionStore


class ExperimentExecutionError(RuntimeError):
    """Base error for experiment execution failures."""


class ResourceUnavailableError(ExperimentExecutionError):
    """A resource needed by the experiment was unavailable."""


class ToolExecutionError(ExperimentExecutionError):
    """A tool failed during execution."""


class SafetyViolationError(ExperimentExecutionError):
    """The experiment attempted something outside its safety constraints."""


class ExperimentPermissions:
    """Explicit permission gates. All default to False: experiments that need
    code execution, tools or network are BLOCKED unless permission is granted."""

    def __init__(self, allow_code: bool = False, allow_tools: bool = False,
                 allow_network: bool = False):
        self.allow_code = allow_code
        self.allow_tools = allow_tools
        self.allow_network = allow_network

    def required_for(self, etype: ExperimentType) -> Optional[str]:
        if etype == ExperimentType.CODE_TEST:
            return "allow_code" if not self.allow_code else None
        if etype == ExperimentType.TOOL_EXECUTION:
            return "allow_tools" if not self.allow_tools else None
        if etype == ExperimentType.WEB_VERIFICATION:
            return "allow_network" if not self.allow_network else None
        return None  # SIMULATION / DATA_COMPARISON / SYSTEM_OBSERVATION need no gate


# Deterministic, pure, whitelisted simulators. Only these names can be invoked —
# there is no arbitrary code execution path for SIMULATION experiments.
def _sim_correlation(params: Dict[str, Any]) -> Dict[str, Any]:
    xs = [float(x) for x in params.get("x", [])]
    ys = [float(y) for y in params.get("y", [])]
    n = min(len(xs), len(ys))
    if n == 0:
        return {"correlation": 0.0, "samples": 0}
    agreements = sum(1 for i in range(n) if (xs[i] > 0.0) == (ys[i] > 0.0))
    r = round((agreements / n) * 2.0 - 1.0, 6)
    return {"correlation": r, "samples": n}


def _sim_rule_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic counterfactual check: does the rule hold on the given cases?"""
    cases = params.get("cases", [])
    if not cases:
        return {"rule_holds": False, "checked": 0}
    held = sum(1 for c in cases if bool(c.get("preceded", False)))
    return {"rule_holds": held == len(cases), "checked": len(cases)}


_SIMULATORS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "correlation": _sim_correlation,
    "rule_check": _sim_rule_check,
}

# Restricted builtins for CODE_TEST: no imports, no IO, no eval/exec/compile.
_SAFE_BUILTINS: Dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "sum": sum, "len": len, "range": range,
    "round": round, "sorted": sorted, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple,
    "enumerate": enumerate, "zip": zip, "any": any, "all": all,
    "isinstance": isinstance, "True": True, "False": False, "None": None,
}


class RealityExperimentEngine:
    def __init__(self,
                 experiment_store: ExperimentStore,
                 evidence_store: EvidenceStore,
                 belief_store: BeliefStore,
                 hypothesis_store: HypothesisStore,
                 question_store: Optional[QuestionStore] = None,
                 permissions: Optional[ExperimentPermissions] = None,
                 staleness_threshold_s: float = 3600.0,
                 max_attempts: int = 2,
                 revision: Optional[BeliefRevision] = None):
        self.experiments = experiment_store
        self.evidence = evidence_store
        self.beliefs = belief_store
        self.hypotheses = hypothesis_store
        self.question_store = question_store
        self.permissions = permissions or ExperimentPermissions()
        self.staleness_threshold_s = staleness_threshold_s
        self.max_attempts = max_attempts
        self.revision = revision or BeliefRevision()
        self.tool_handlers: Dict[str, Callable[..., Any]] = {}

    # --- Planning --------------------------------------------------------------

    def plan_for_question(self, question_id: str) -> List[Experiment]:
        """Design one controlled experiment per competing hypothesis. All
        predictions / expected evidence / success / failure / safety are fixed
        BEFORE any execution. Returns new PROPOSED experiments (duplicates skipped)."""
        hyps = self.hypotheses.list_by_question(question_id)
        planned: List[Experiment] = []
        for hyp in hyps:
            existing = [e for e in self.experiments.list_by_question(question_id)
                        if hyp.hypothesis_id in e.hypothesis_ids and e.status
                        in (ExperimentLifecycle.PROPOSED, ExperimentLifecycle.APPROVED,
                            ExperimentLifecycle.RUNNING, ExperimentLifecycle.FAILED)]
            if existing:
                continue  # already planned / unresolved — no duplicate experiments
            exp = self._design_experiment(hyp)
            self.experiments.put(exp)
            planned.append(exp)
        return planned

    def _design_experiment(self, hyp: Hypothesis) -> Experiment:
        if not hyp.predictions:
            raise ExperimentValidationError(
                f"Hypothesis {hyp.hypothesis_id} has no predictions — cannot design an experiment")
        if not hyp.failure_conditions:
            raise ExperimentValidationError(
                f"Hypothesis {hyp.hypothesis_id} has no failure conditions — cannot design an experiment")
        question = self.question_store.get(hyp.question_id) if self.question_store else None
        source = question.source if question else "UNCERTAINTY"

        if "observation" in hyp.statement.lower() and "inaccurate" in hyp.statement.lower():
            etype = ExperimentType.SYSTEM_OBSERVATION
        elif source in ("GOAL_GAP", "MISSING_DEPENDENCY"):
            etype = ExperimentType.DATA_COMPARISON
        elif "rule" in hyp.statement.lower() and "incorrect" in hyp.statement.lower():
            etype = ExperimentType.SIMULATION
        else:
            etype = ExperimentType.DATA_COMPARISON

        safety = self._safety_constraints(etype)
        objective = f"Test: {hyp.statement}"
        return Experiment(
            question_id=hyp.question_id,
            hypothesis_ids=[hyp.hypothesis_id],
            objective=objective,
            type=etype,
            procedure=[f"Run a controlled {etype.value.lower()} for hypothesis {hyp.hypothesis_id}"],
            predictions=list(hyp.predictions),
            expected_evidence=list(hyp.expected_evidence),
            success_conditions=[f"All predictions for {hyp.hypothesis_id} are supported by observation"],
            failure_conditions=list(hyp.failure_conditions),
            safety_constraints=safety,
            environment={"sandbox": "restricted", "network": "denied",
                         "filesystem_writes": "denied", "os_commands": "denied"},
            risk=0.3,
            cost=1.0,
            confidence=hyp.confidence,
            mode=self._mode_for(etype),
            max_attempts=self.max_attempts,
        )

    @staticmethod
    def _mode_for(etype: ExperimentType) -> str:
        if etype == ExperimentType.SIMULATION:
            return EvidenceMode.SIMULATED.value
        if etype == ExperimentType.CODE_TEST:
            return EvidenceMode.TEST.value
        return EvidenceMode.OBSERVED.value

    @staticmethod
    def _safety_constraints(etype: ExperimentType) -> List[str]:
        if etype == ExperimentType.WEB_VERIFICATION:
            return ["network access only with explicit permission",
                    "no credential access", "read-only requests"]
        if etype == ExperimentType.TOOL_EXECUTION:
            return ["tool execution only with explicit permission",
                    "no privileged tools", "no state mutation beyond tool contract"]
        if etype == ExperimentType.CODE_TEST:
            return ["restricted builtins only", "no imports", "no IO",
                    "no filesystem access", "no network"]
        if etype == ExperimentType.SIMULATION:
            return ["whitelisted simulators only", "pure computation",
                    "no external effects"]
        return ["read-only comparison of recorded data", "no external effects"]

    # --- Approval (safety gate) ------------------------------------------------

    def approve(self, experiment: Experiment,
                inputs: Optional[Dict[str, Any]] = None) -> Experiment:
        """PROPOSED -> APPROVED (or -> BLOCKED when the type needs a permission
        that is not granted). Inputs are attached at approval time and may not be
        changed afterwards. BLOCKED experiments are never executed."""
        if inputs is not None:
            if not isinstance(inputs, dict):
                raise ExperimentValidationError("Experiment inputs must be a dict")
            experiment.inputs = dict(inputs)
            experiment.updated_at = time.time()
            self.experiments.put(experiment)
        missing = self.permissions.required_for(experiment.type)
        if missing is not None:
            transition(experiment, ExperimentLifecycle.BLOCKED)
            experiment.rollback_info = (
                f"Not executed: experiment type {experiment.type.value} requires "
                f"permission '{missing}' which is not granted")
            experiment.errors = [experiment.rollback_info]
            experiment.result = {"blocked": True, "missing_permission": missing}
            self.experiments.put(experiment)
            return experiment
        transition(experiment, ExperimentLifecycle.APPROVED)
        experiment.rollback_info = "No side effects performed yet; safe to cancel."
        self.experiments.put(experiment)
        return experiment

    # --- Execution -------------------------------------------------------------

    def run(self, experiment: Experiment) -> Tuple[Experiment, Optional[Evidence]]:
        """APPROVED -> RUNNING -> (COMPLETED | FAILED). A BLOCKED or CANCELLED
        experiment can never run. Execution produces one Observation which is
        immediately compared against the experiment's predictions and stored as
        Evidence with full provenance. Failure is recorded as data and never
        converted into confirmation."""
        if experiment.status in (ExperimentLifecycle.BLOCKED,
                                 ExperimentLifecycle.CANCELLED,
                                 ExperimentLifecycle.COMPLETED):
            raise ExperimentTransitionError(
                f"Cannot run experiment {experiment.experiment_id} in status {experiment.status.value}")
        transition(experiment, ExperimentLifecycle.RUNNING)
        experiment.started_at = time.time()
        experiment.attempts += 1
        experiment.rollback_info = "Executor aborted before any side effect; no rollback needed."
        self.experiments.put(experiment)

        try:
            observation = self._execute(experiment)
        except (ResourceUnavailableError, ToolExecutionError,
                SafetyViolationError) as e:
            transition(experiment, ExperimentLifecycle.FAILED)
            experiment.completed_at = time.time()
            experiment.errors.append(f"{type(e).__name__}: {e}")
            experiment.result = {
                "failure": type(e).__name__,
                "error": str(e),
                "attempt": experiment.attempts,
                "max_attempts": experiment.max_attempts,
            }
            experiment.rollback_info = "No state mutated; recorded failure is data, not confirmation."
            self.experiments.put(experiment)
            return experiment, None
        except Exception as e:  # noqa: BLE001
            transition(experiment, ExperimentLifecycle.FAILED)
            experiment.completed_at = time.time()
            experiment.errors.append(f"{type(e).__name__}: {e}")
            experiment.result = {"failure": "UNEXPECTED", "error": str(e)}
            self.experiments.put(experiment)
            return experiment, None

        # OBSERVATION -> COMPARISON
        content = observation
        experiment.actual_observation = content
        evidence = self._compare_and_record(experiment, content)
        if evidence is not None:
            experiment.evidence_ids.append(evidence.evidence_id)

        transition(experiment, ExperimentLifecycle.COMPLETED)
        experiment.completed_at = time.time()
        experiment.result = {"completed": True, "attempt": experiment.attempts,
                             "evidence_id": evidence.evidence_id if evidence else None}
        experiment.rollback_info = "Experiment completed; only read-only evidence was recorded."
        self.experiments.put(experiment)
        return experiment, evidence

    # --- Executors (all deterministic, all safe) -------------------------------

    def _execute(self, experiment: Experiment) -> Dict[str, Any]:
        etype = experiment.type
        if etype == ExperimentType.SIMULATION:
            return self._simulate(experiment)
        if etype == ExperimentType.DATA_COMPARISON:
            return self._data_compare(experiment)
        if etype == ExperimentType.SYSTEM_OBSERVATION:
            return self._system_observe(experiment)
        if etype == ExperimentType.CODE_TEST:
            return self._code_test(experiment)
        if etype == ExperimentType.TOOL_EXECUTION:
            return self._tool_execute(experiment)
        if etype == ExperimentType.WEB_VERIFICATION:
            return self._web_verify(experiment)
        raise ExperimentExecutionError(f"Unknown experiment type: {etype}")

    def _simulate(self, experiment: Experiment) -> Dict[str, Any]:
        spec = experiment.inputs.get("simulation")
        if not isinstance(spec, dict) or not spec.get("name"):
            raise ExperimentExecutionError(
                "SIMULATION experiment requires inputs['simulation'] = {name, params}")
        name = str(spec["name"])
        simulator = _SIMULATORS.get(name)
        if simulator is None:
            raise ExperimentExecutionError(
                f"Unknown simulator '{name}' — only whitelisted pure simulators are allowed")
        params = dict(spec.get("params", {}))
        result = simulator(params)
        content = {"mode": EvidenceMode.SIMULATED.value, "result": result}
        prediction = experiment.predictions[0] if experiment.predictions else ""
        threshold = float(experiment.inputs.get("threshold", 0.5))
        correlated = "correlation" in result and abs(float(result["correlation"])) >= threshold
        rule_holds = "rule_holds" in result and bool(result["rule_holds"])
        if "correlation" in result:
            if correlated:
                content["matches"] = [prediction]
            else:
                content["contradicts"] = [prediction]
        if "rule_holds" in result:
            # The observation channel reports what it saw in the prediction's terms:
            # a prediction like "further B-without-A cases will recur" is matched by
            # observing rule violations (rule_holds=False).
            if rule_holds:
                content["contradicts"] = [prediction]
            else:
                content["matches"] = [prediction]
        return content

    def _data_compare(self, experiment: Experiment) -> Dict[str, Any]:
        expected = experiment.inputs.get("expected")
        observed = experiment.inputs.get("observed")
        if expected is None or observed is None:
            raise ExperimentExecutionError(
                "DATA_COMPARISON experiment requires inputs['expected'] and inputs['observed']")
        match = self._compare_values(expected, observed)
        prediction = experiment.predictions[0] if experiment.predictions else ""
        content: Dict[str, Any] = {
            "mode": EvidenceMode.OBSERVED.value,
            "expected": expected,
            "observed": observed,
            "match": match,
        }
        if match:
            content["matches"] = [prediction]
        else:
            content["contradicts"] = [prediction]
        return content

    @staticmethod
    def _compare_values(expected: Any, observed: Any) -> bool:
        if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
            return math.isclose(float(expected), float(observed), rel_tol=1e-9, abs_tol=1e-9)
        if isinstance(expected, list) and isinstance(observed, list):
            return [str(x) for x in expected] == [str(x) for x in observed]
        if isinstance(expected, dict) and isinstance(observed, dict):
            return {str(k): str(v) for k, v in expected.items()} == \
                   {str(k): str(v) for k, v in observed.items()}
        return str(expected) == str(observed)

    def _system_observe(self, experiment: Experiment) -> Dict[str, Any]:
        # Read-only observation channel. ``inputs['observations']`` carries the
        # trusted observer's readout (e.g. sensor/telemetry); the observation
        # channel decides what was seen (matches/contradicts), never the model.
        obs = dict(experiment.inputs.get("observations", {}))
        matches = [str(x) for x in experiment.inputs.get("matches", [])]
        contradicts = [str(x) for x in experiment.inputs.get("contradicts", [])]
        if not obs:
            raise ResourceUnavailableError(
                "SYSTEM_OBSERVATION channel returned no readout (resource unavailable)")
        content: Dict[str, Any] = {
            "mode": EvidenceMode.OBSERVED.value,
            "observations": obs,
            "observed_at": time.time(),
        }
        if matches:
            content["matches"] = matches
        if contradicts:
            content["contradicts"] = contradicts
        return content

    def _code_test(self, experiment: Experiment) -> Dict[str, Any]:
        code = experiment.inputs.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ExperimentExecutionError(
                "CODE_TEST experiment requires inputs['code']")
        # Restricted sandbox: whitelisted builtins only, no imports, no IO.
        namespace: Dict[str, Any] = {"__builtins__": dict(_SAFE_BUILTINS)}
        try:
            exec(compile(code, "<experiment>", "exec"), namespace)  # noqa: S102 — restricted
        except (NameError, ImportError, AttributeError) as e:
            raise SafetyViolationError(f"CODE_TEST attempted an unsafe operation: {e}") from e
        result = namespace.get("result", {})
        passed = bool(result.get("passed", False)) if isinstance(result, dict) else False
        prediction = experiment.predictions[0] if experiment.predictions else ""
        content: Dict[str, Any] = {
            "mode": EvidenceMode.TEST.value,
            "result": result,
        }
        if passed:
            content["matches"] = [prediction]
        else:
            content["contradicts"] = [prediction]
        return content

    def _tool_execute(self, experiment: Experiment) -> Dict[str, Any]:
        tool = str(experiment.inputs.get("tool", ""))
        handler = self.tool_handlers.get(tool)
        if handler is None:
            raise ToolExecutionError(
                f"Tool '{tool}' has no registered handler and cannot run")
        params = dict(experiment.inputs.get("params", {}))
        outcome = handler(**params)
        prediction = experiment.predictions[0] if experiment.predictions else ""
        content: Dict[str, Any] = {
            "mode": EvidenceMode.OBSERVED.value,
            "tool": tool,
            "outcome": outcome,
        }
        if isinstance(outcome, dict) and outcome.get("matches"):
            content["matches"] = [str(x) for x in outcome["matches"]]
        if isinstance(outcome, dict) and outcome.get("contradicts"):
            content["contradicts"] = [str(x) for x in outcome["contradicts"]]
        return content

    def _web_verify(self, experiment: Experiment) -> Dict[str, Any]:
        raise ToolExecutionError(
            "WEB_VERIFICATION unavailable: no network permission is granted in this runtime")

    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        self.tool_handlers[name] = handler

    # --- Comparison ------------------------------------------------------------

    def _compare_and_record(self, experiment: Experiment,
                            content: Dict[str, Any]) -> Optional[Evidence]:
        """COMPARISON: deterministic per-prediction verdicts from the observation,
        then store the Evidence with full provenance."""
        matches = [str(x) for x in content.get("matches", [])]
        contradicts = [str(x) for x in content.get("contradicts", [])]
        verdicts: List[EvidenceVerdict] = []
        for pred in experiment.predictions:
            if any(pred == m or pred in m or m in pred for m in matches):
                verdicts.append(EvidenceVerdict.SUPPORTS)
            elif any(pred == c or pred in c or c in pred for c in contradicts):
                verdicts.append(EvidenceVerdict.CONTRADICTS)
            else:
                verdicts.append(EvidenceVerdict.NEUTRAL)
        has_support = EvidenceVerdict.SUPPORTS in verdicts
        has_contradict = EvidenceVerdict.CONTRADICTS in verdicts
        if has_support and has_contradict:
            verdict = EvidenceVerdict.MIXED
        elif has_contradict:
            verdict = EvidenceVerdict.CONTRADICTS
        elif has_support:
            verdict = EvidenceVerdict.SUPPORTS
        else:
            verdict = EvidenceVerdict.NEUTRAL

        prov = Provenance(
            source="experiment_engine",
            observed_at=time.time(),
            evidence_type=f"experiment:{experiment.type.value}",
            content_reference=experiment.experiment_id,
            reliability=float(experiment.inputs.get("reliability", 0.9)),
            mode=EvidenceMode(experiment.mode),
            recorded_at=time.time(),
            experiment_id=experiment.experiment_id,
        )
        return self._store_evidence(
            content=content,
            provenance=prov,
            verdict=verdict,
            experiment_id=experiment.experiment_id,
            hypothesis_ids=list(experiment.hypothesis_ids),
            belief_ids=[],
            related_predictions=list(experiment.predictions),
            observed_at=prov.observed_at,
        )

    def record_external_observation(self, *, content: Dict[str, Any],
                                    source: str, reliability: float = 0.9,
                                    mode: EvidenceMode = EvidenceMode.OBSERVED,
                                    evidence_type: str = "observation",
                                    verdict: EvidenceVerdict = EvidenceVerdict.NEUTRAL,
                                    experiment_id: Optional[str] = None,
                                    hypothesis_ids: Optional[List[str]] = None,
                                    belief_ids: Optional[List[str]] = None,
                                    observed_at: Optional[float] = None,
                                    related_predictions: Optional[List[str]] = None,
                                    allow_stale: bool = False) -> Evidence:
        """Record an external observation (e.g. from perception) as Evidence.
        Fabricated references, mode-lying (claiming a simulation is reality),
        duplicate and stale evidence are rejected or flagged."""
        if mode == EvidenceMode.MODEL_GENERATED:
            # Model output is provenance data only; it is recorded but never
            # applied to belief (enforced by BeliefRevision).
            pass
        prov = Provenance(
            source=source,
            observed_at=observed_at if observed_at is not None else time.time(),
            evidence_type=evidence_type,
            content_reference=str(content),
            reliability=reliability,
            mode=mode,
            recorded_at=time.time(),
            experiment_id=experiment_id,
        )
        return self._store_evidence(
            content=content,
            provenance=prov,
            verdict=verdict,
            experiment_id=experiment_id,
            hypothesis_ids=hypothesis_ids or [],
            belief_ids=belief_ids or [],
            related_predictions=related_predictions or [],
            observed_at=prov.observed_at,
            allow_stale=allow_stale,
        )

    def _store_evidence(self, *, content: Dict[str, Any], provenance: Provenance,
                        verdict: EvidenceVerdict, experiment_id: Optional[str],
                        hypothesis_ids: List[str], belief_ids: List[str],
                        related_predictions: List[str], observed_at: float,
                        allow_stale: bool = False) -> Evidence:
        # Mode honesty: the evidence mode must match its experiment's mode.
        if experiment_id is not None:
            exp = self.experiments.get(experiment_id)
            if exp is None:
                raise EvidenceValidationError(
                    f"Fabricated evidence: unknown experiment reference {experiment_id}")
            if provenance.mode.value != exp.mode:
                raise EvidenceValidationError(
                    f"Mode-lying evidence rejected: experiment {experiment_id} is "
                    f"{exp.mode} but evidence claims {provenance.mode.value}")
        # Fabricated hypothesis / belief references.
        for hid in hypothesis_ids:
            if self.hypotheses.get(hid) is None:
                raise EvidenceValidationError(
                    f"Fabricated evidence: unknown hypothesis reference {hid}")
        for bid in belief_ids:
            if self.beliefs.get(bid) is None:
                raise EvidenceValidationError(
                    f"Fabricated evidence: unknown belief reference {bid}")

        stale = (provenance.recorded_at - observed_at) > self.staleness_threshold_s \
            and not allow_stale

        evidence = Evidence(
            content=content,
            provenance=provenance,
            verdict=verdict,
            experiment_id=experiment_id,
            hypothesis_ids=hypothesis_ids,
            belief_ids=belief_ids,
            related_predictions=related_predictions,
            stale=stale,
        )
        # Duplicate evidence is rejected, never double-applied.
        existing = self.evidence.get_by_fingerprint(evidence.fingerprint)
        if existing is not None:
            raise EvidenceValidationError(
                f"Duplicate evidence rejected (fingerprint {evidence.fingerprint[:12]}…) "
                f"matches evidence {existing.evidence_id}")
        self.evidence.put(evidence)
        return evidence

    # --- Evaluation: hypothesis competition + belief revision -------------------

    def evaluate_question(self, question_id: str) -> Dict[str, Any]:
        """After observations are in: compare evidence, score each competing
        hypothesis using ONLY evidence, then revise related beliefs. No model
        opinion selects a winner — the evidence does."""
        hyps = self.hypotheses.list_by_question(question_id)
        changed: List[Dict[str, Any]] = []
        for hyp in hyps:
            before_status = hyp.status
            self._apply_evidence_to_hypothesis(hyp)
            if hyp.status != before_status or hyp.score > 0.0:
                changed.append({
                    "hypothesis_id": hyp.hypothesis_id,
                    "question_id": question_id,
                    "status_before": before_status.value,
                    "status_after": hyp.status.value,
                    "score": round(hyp.score, 6),
                })
            self.hypotheses.put(hyp)

        # Belief revision for every belief tied to the question (directly or via
        # its hypotheses), in deterministic evidence order.
        revisions: List[Dict[str, Any]] = []
        beliefs = self._beliefs_for_question(question_id)
        for belief in beliefs:
            for evidence in self._evidence_for_belief(belief):
                if evidence.applied:
                    continue
                belief, record = self.revision.apply(belief, evidence)
                self.evidence.put(evidence)  # persist applied/reject flags
                self.beliefs.put(belief)
                revisions.append(record)
        return {"question_id": question_id, "hypotheses": changed,
                "revisions": revisions}

    def _apply_evidence_to_hypothesis(self, hyp: Hypothesis) -> None:
        evidence_items = self.evidence.list_for_hypothesis(hyp.hypothesis_id)
        supports = 0.0
        contradicts = 0.0
        observed_support_count = 0
        for ev in evidence_items:
            weight = ev.provenance.reliability * MODE_WEIGHT[ev.provenance.mode]
            if ev.verdict == EvidenceVerdict.SUPPORTS:
                supports += weight
                if ev.provenance.mode == EvidenceMode.OBSERVED:
                    observed_support_count += 1
                if ev.evidence_id not in hyp.supporting_evidence:
                    hyp.supporting_evidence.append(ev.evidence_id)
            elif ev.verdict == EvidenceVerdict.CONTRADICTS:
                contradicts += weight
                if ev.evidence_id not in hyp.contradicting_evidence:
                    hyp.contradicting_evidence.append(ev.evidence_id)
        score = min(1.0, max(0.0, 0.5 + 0.5 * (supports - contradicts)))
        hyp.score = round(score, 6)
        hyp.updated_at = time.time()

        # Evidence-determined status transitions (never opinion).
        if contradicts > 0.0 and supports == 0.0 and contradicts >= 0.7:
            hyp.status = HypothesisLifecycle.CONTRADICTED
        elif supports > contradicts and supports > 0.0:
            if score >= 0.85 and observed_support_count >= 2:
                hyp.status = HypothesisLifecycle.CONFIRMED
            elif score >= 0.6:
                hyp.status = HypothesisLifecycle.SUPPORTED
        elif contradicts > supports and contradicts > 0.0:
            hyp.status = HypothesisLifecycle.WEAKENED
        hyp.revision_history.append({
            "event": "evidence_evaluated", "at": time.time(),
            "support_weight": round(supports, 6),
            "contradict_weight": round(contradicts, 6),
            "score": round(score, 6),
        })

    def _beliefs_for_question(self, question_id: str) -> List[Belief]:
        q = self.question_store.get(question_id) if self.question_store else None
        ids: List[str] = list(q.related_beliefs) if q else []
        for hyp in self.hypotheses.list_by_question(question_id):
            for b in self.beliefs.list_for_hypothesis(hyp.hypothesis_id):
                if b.belief_id not in ids:
                    ids.append(b.belief_id)
        beliefs = [self.beliefs.get(bid) for bid in ids]
        return sorted([b for b in beliefs if b is not None], key=lambda b: b.created_at)

    def _evidence_for_belief(self, belief: Belief) -> List[Evidence]:
        direct = {e.evidence_id: e for e in self.evidence.list_for_belief(belief.belief_id)}
        for hid in belief.related_hypotheses:
            for e in self.evidence.list_for_hypothesis(hid):
                direct.setdefault(e.evidence_id, e)
        return sorted(direct.values(), key=lambda e: e.created_at)
