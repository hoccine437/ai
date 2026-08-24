# ZERION — Slice 3 Report: Reality Feedback

**Scope:** RealityExperimentEngine, Experiment object, controlled testing, Evidence &
Provenance, Belief object + BeliefRevision, reality-vs-simulation enforcement,
safety gates, the required E2E (experiment → observation → comparison → belief
update), persistence, adversarial handling.
**Date:** 2026-08-12
**Status:** Implemented, tested, wired into the real runtime. Slice 4+ intentionally
NOT started.

---

## 1. Reused Slice 1/2 components (no duplicates created)

| Component | Source | How Slice 3 uses it |
|---|---|---|
| Event Bus | Slice 1 `AsyncEventBus` (single repo bus) | All reality-feedback events flow on it: `EXPERIMENT_PROPOSED/APPROVED/STARTED/BLOCKED/CANCELLED/COMPLETED/FAILED`, `OBSERVATION_RECORDED`, `EVIDENCE_ADDED`, `EVIDENCE_REJECTED`, `BELIEF_UPDATED`, `HYPOTHESIS_SUPPORTED/WEAKENED/CONTRADICTED`. Reused the pre-existing `EXPERIMENT_STARTED/COMPLETED/FAILED`, `OBSERVATION_RECORDED`, `BELIEF_UPDATED` types — no second event system. |
| Question Field | Slice 2 `question.py` / `QuestionStore` | Experiments reference `question_id`; evaluation resolves the question's beliefs. |
| Hypothesis Engine | Slice 2 `hypothesis.py` / `HypothesisStore` | Slice 3 designs one controlled experiment **per competing hypothesis** and scores hypotheses only from evidence. |
| Runtime coordinator | Slice 2 `CognitiveRuntime` | Extended **in place** (additively) with the Experiment / Evidence / Belief fields. Slice 1/2 behavior unchanged. |
| Persistence pattern | SQLite-WAL + SHA-256 checksums (Slices 1/2) | Same pattern for `ExperimentStore` / `EvidenceStore` / `BeliefStore`. |

Duplication documented (not silently created): the legacy engine has
`zerion/evidence/engine.py` (EvidenceEngine, `evidence.db`) and
`zerion/experiments/engine.py` (ExperimentEngine) — separate 25-stage pipeline
components, untouched. Slice 3's evidence store therefore uses
`cognitive_evidence.db` to avoid colliding with the legacy `evidence.db`;
`experiments.db` and `beliefs.db` had no legacy collision.

## 2. Files created

- `zerion/cognitive_os/experiment.py` — `ExperimentType` (CODE_TEST,
  SYSTEM_OBSERVATION, WEB_VERIFICATION, TOOL_EXECUTION, SIMULATION,
  DATA_COMPARISON), `ExperimentLifecycle` (PROPOSED/APPROVED/RUNNING/COMPLETED/
  FAILED/CANCELLED/BLOCKED), `Experiment` (objective, inputs, procedure,
  predictions, expected evidence, success/failure conditions, safety
  constraints, actual_observation, environment, result, confidence, risk, cost,
  evidence_ids, mode, errors, rollback_info, attempts/max_attempts),
  validated `transition()` matrix, `ExperimentStore`.
- `zerion/cognitive_os/evidence.py` — `EvidenceMode` (OBSERVED / SIMULATED /
  TEST / MODEL_GENERATED), `EvidenceVerdict` (SUPPORTS / CONTRADICTS / NEUTRAL /
  MIXED), `MODE_WEIGHT`, `Provenance` (source, timestamps, type,
  content/reference, experiment_id, reliability, mode), `Evidence` (content,
  fingerprint, stale, applied, reject_reason, links to experiments/hypotheses/
  beliefs/predictions), `EvidenceStore`.
- `zerion/cognitive_os/belief.py` — `BeliefLifecycle` (UNKNOWN/HYPOTHESIS/
  PREDICTED/SUPPORTED/WEAKENED/CONTRADICTED/CONFIRMED), `Belief` (confidence,
  supporting/contradicting evidence, predictions, observations,
  contradiction_history, revision_history, related_hypotheses, provenance),
  `BeliefRevision` (explicit deterministic rules), `BeliefStore`.
- `zerion/cognitive_os/experiment_engine.py` — `ExperimentPermissions`
  (allow_code / allow_tools / allow_network, all default False),
  `RealityExperimentEngine` (planner, safety gate, executors, comparator,
  evidence gatekeeping, hypothesis scoring, belief revision),
  `ExperimentExecutionError` / `ResourceUnavailableError` / `ToolExecutionError`
  / `SafetyViolationError`.
- `tests/test_experiment_foundation.py` — 61 tests.
- `ZERION_SLICE_3_REPORT.md` — this report.

## 3. Files modified

- `zerion/runtime/events.py` — added `EXPERIMENT_PROPOSED`, `EXPERIMENT_APPROVED`,
  `EXPERIMENT_BLOCKED`, `EXPERIMENT_CANCELLED`, `EVIDENCE_ADDED`,
  `EVIDENCE_REJECTED`, `HYPOTHESIS_SUPPORTED`, `HYPOTHESIS_WEAKENED`,
  `HYPOTHESIS_CONTRADICTED` (reused `EXPERIMENT_STARTED/COMPLETED/FAILED`,
  `OBSERVATION_RECORDED`, `BELIEF_UPDATED`).
- `zerion/cognitive_os/cognitive_runtime.py` — owns `experiment_store`,
  `evidence_store`, `belief_store`, `reality_experiments`; `HYPOTHESES_GENERATED`
  now plans PROPOSED experiments automatically; contradiction triggers with
  `payload['beliefs']` materialize the named rule belief (linked to the question);
  hypothesis generation materializes one Belief per hypothesis; new runtime
  methods `approve_experiment` / `run_experiment` / `record_observation` /
  `evaluate_question` publish the full feedback trail.
- `zerion/cognitive_os/__init__.py` — exports for the new types.

## 4. Experiment engine

- **Controlled testing:** every experiment defines hypothesis, predictions,
  expected evidence, success conditions, failure conditions and safety
  constraints BEFORE execution (validation rejects experiments without them).
  The hypothesis is never rewritten after the result.
- **Planning:** `plan_for_question()` designs one experiment per competing
  hypothesis (deterministic type selection; duplicates skipped while the
  experiment is unresolved).
- **Execution:** `approve()` gates safety — SIMULATION / DATA_COMPARISON /
  SYSTEM_OBSERVATION need no permission; CODE_TEST needs `allow_code`,
  TOOL_EXECUTION needs `allow_tools`, WEB_VERIFICATION needs `allow_network`.
  Without the gate the experiment becomes **BLOCKED and is never executed**
  (running a BLOCKED experiment raises `ExperimentTransitionError`).
- **Executors are deterministic and safe:** whitelisted pure simulators only
  (`correlation`, `rule_check`); DATA_COMPARISON compares expected vs observed;
  SYSTEM_OBSERVATION reads a trusted observation channel; CODE_TEST runs in a
  restricted namespace (whitelisted builtins, no imports/IO/network — an
  `import os` attempt is a recorded `SafetyViolationError`); tools run only via
  explicitly registered handlers; web verification never performs network.
- **Failure is data:** a failed experiment records failure type, error,
  environment, hypothesis, rollback info and bounded attempts (`max_attempts`,
  default 2) — no endless retries, and failure is never converted into
  confirmation.

## 5. Evidence & provenance

Every evidence item identifies source, observed_at/recorded_at timestamps, type,
content/reference, experiment_id, reliability and mode. Gatekeeping rejects or
flags: fabricated experiment/hypothesis/belief references, duplicate evidence
(fingerprint), stale evidence (observed long before recorded), and **mode-lying**
(recording a SIMULATION experiment's result as OBSERVED). MODEL_GENERATED
evidence is stored for provenance but never applied to belief.

## 6. Belief system & revision rules

`BeliefRevision` is explicit, inspectable and deterministic:

```
weight        = reliability * MODE_WEIGHT[mode]      (OBSERVED 1.0 / TEST 0.4 /
                                                       SIMULATED 0.2 / MODEL_GENERATED 0.0)
supporting    : conf += (1 - conf) * weight * 0.5
contradicting : conf -= conf * weight * 0.6
strong contradiction (weight >= 0.75)  -> CONTRADICTED
conf >= 0.85 + OBSERVED support       -> CONFIRMED
conf >= 0.6                            -> SUPPORTED
conf <= 0.2                            -> WEAKENED
```

Every revision records previous/new confidence and status, evidence id, verdict,
weight, reason, timestamp and source — appended to `revision_history`, never
overwriting old beliefs. Contradictions are also recorded in
`contradiction_history`. SIMULATED/TEST evidence can inform but can never confirm.

## 7. Reality vs simulation enforcement

- Experiment results carry a `mode` derived from the experiment type; a caller
  cannot claim an OBSERVED result from a SIMULATED experiment (rejected).
- SIMULATED evidence moves confidence by weight 0.2 and can never reach
  CONFIRMED; TEST (mock) evidence is explicitly marked; MODEL_GENERATED is never
  applied.

## 8. Safety behavior

- Default `ExperimentPermissions` locks everything: CODE_TEST / TOOL_EXECUTION /
  WEB_VERIFICATION become BLOCKED in the default runtime — verified at the
  `AscendantEngine` level (planned experiments never auto-execute).
- No OS commands, no filesystem writes, no network, no credential access.
- CODE_TEST executes in a restricted builtins namespace; violations are recorded
  failures.
- A failed experiment's `rollback_info` documents that no side effects occurred.

## 9. Required E2E (verified in tests AND through the real engine)

Known: A normally precedes B. Observed: B occurred without A.

1. `CONTRADICTION_FOUND` → bus → rule belief "A normally precedes B"
   materialized (PREDICTED, conf 0.7) → question "What alternative variable
   could explain B?" → competing hypotheses H1 (hidden cause) / H2 (observation
   inaccurate).
2. Experiments planned (PROPOSED) with predictions/expected evidence/success/
   failure/safety fixed up front.
3. Safe deterministic experiments approved and executed: H1's DATA_COMPARISON
   finds no correlation (contradicts H1); H2's SYSTEM_OBSERVATION re-observation
   records A present (supports H2); H3's SIMULATION produces SIMULATED evidence
   only.
4. Observations recorded with full provenance (OBSERVED mode).
5. Comparison produced SUPPORTS/CONTRADICTS verdicts deterministically.
6. Hypotheses scored from evidence only: H1 CONTRADICTED (0.050), H2 SUPPORTED
   (0.950). No opinion selected the winner.
7. The rule belief was revised: PREDICTED → CONTRADICTED (anomaly) → SUPPORTED
   (independent verification), 2 revisions, contradiction history recorded,
   confidence 0.7 → 0.364 → 0.650.
8. Complete provenance/history preserved in stores and the bus trail
   (`EXPERIMENT_COMPLETED`, `OBSERVATION_RECORDED`, `EVIDENCE_ADDED`,
   `BELIEF_UPDATED`, `HYPOTHESIS_SUPPORTED`, `HYPOTHESIS_CONTRADICTED`).

## 10. Persistence

- `experiments.db`, `cognitive_evidence.db`, `beliefs.db` (SQLite WAL,
  per-row SHA-256 checksums, `strict_load` raises on corruption, `load_errors`
  otherwise — never silent empty state).
- Unresolved experiments (PROPOSED/APPROVED/RUNNING/FAILED) are never silently
  lost across restarts; belief revision history survives restarts; evidence and
  its provenance survive restarts; question↔hypothesis↔belief↔experiment
  relationships are restored (verified by restart tests).

## 11. Exact test results

Commands actually run (from the repo root, `cd ai-arena-019ff051-ai`):

```
python3 -m unittest tests.test_experiment_foundation -v
python3 -m unittest discover -s tests -p "test_*.py"
python3 -m pytest tests/test_cognitive_foundation.py tests/test_question_foundation.py tests/test_experiment_foundation.py -q --no-header
```

- Slice 3 suite (`tests/test_experiment_foundation.py`): **61 passed, 0 failed**
  (1.44s).
- Full repository suite (`unittest discover`): **Ran 300 tests — OK** (0 failures,
  0 errors) in 9.56s (was 239 before Slice 3; legacy Slice 1/2 suites all pass).
- Slice 1 + 2 + 3 under pytest: **175 passed in 2.95s**.
- Real-engine smoke (`AscendantEngine`): full E2E above; exit 0, assertions
  verified. No LLM involved anywhere.

Coverage: experiment model/validation/transitions/retry bounds; persistence +
restart for all three stores + corruption handling; evidence provenance/mode
weights/dedup/staleness/fabrication/mode-lying; belief revision rules (model
output can't confirm, never overwrite history, strong contradiction, simulation
can't confirm); executors (correlation, data comparison, system observation,
restricted code sandbox, failed tool, unavailable resource); unsafe experiments
BLOCKED and never executed; repeated failure bounded; runtime integration, the
required E2E, the full bus trail, restart recovery, and an experiment result that
contradicts the current belief.

## 12. Failures / limitations

- Evidence sources in tests are deterministic fixtures standing in for a real
  observation channel; real-world sensors/telemetry would supply the content at
  runtime (the SYSTEM_OBSERVATION channel is ready for that).
- `WEB_VERIFICATION` has no executor (always BLOCKED without network permission);
  a real network verification adapter is a later-slice concern.
- Hypothesis scoring uses explicit weight thresholds (0.7/0.6/0.85/0.9) that are
  documented but not yet calibrated against real domains.
- The legacy `zerion/evidence/` + `zerion/experiments/` pipelines remain parallel
  (documented above); consolidation is deferred.

## 13. What is NOT implemented (Slice 4 boundary)

ExperienceDistillation, FailureLearning, CapabilityGenesis, CognitiveRouter,
BottleneckDetector, SelfModificationGate, CognitivePulse, Benchmark, UI redesign,
Voice redesign, wake-word/voice repair.

## 14. Slice 4 prerequisites

The foundation now provides: persisted Experiments with full contracts, Evidence
with provenance and mode honesty, persisted Beliefs with revision history and
contradiction tracking, evidence-determined hypothesis scoring, and the
experiment/observation/comparison/belief-update bus trail. A future slice can
consume failure records + `rollback_info` (FailureLearning), contradiction
patterns (ExperienceDistillation), and belief provenance chains (CapabilityGenesis)
without touching Slice 1–3 internals.

No claim of intelligence is made. This slice makes Zerion structurally capable of:
"I have a question." → "I have competing explanations." → "I made predictions." →
"I tested them." → "Reality produced this observation." → "Therefore my confidence
changed." Work stops here.
