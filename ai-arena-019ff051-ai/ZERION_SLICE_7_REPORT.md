# ZERION — Slice 7 Report: Self-Improvement Gate (Measurable, Bounded)

**Scope:** real ArchitectureTelemetry (INSUFFICIENT_DATA, never invented),
evidence-required BottleneckDetector (11 limitation types, configurable
thresholds), bottleneck → Slice 2 self-question integration, ImprovementProposal
(with the rule that a proposal is NOT an improvement without baseline
comparison), the full SelfModificationGate (static analysis / security check /
sandbox / tests / benchmark / policy / promotion / rollback), modification
types + risk levels, versioned CognitiveGenome candidate evaluation, atomic
RuntimeSnapshot + rollback, post-promotion monitoring, the required E2E
(reject / promote / rollback / bottleneck), security + adversarial tests,
persistence across restart.
**Date:** 2026-08-12
**Status:** Implemented, tested, wired into the real runtime. Slice 8+
intentionally NOT started.

---

## 1. Reused Slice 1–6 components (no duplicates created)

| Component | Source | How Slice 7 uses it |
|---|---|---|
| Event Bus | Slice 1 `AsyncEventBus` (single repo bus) | Slice 7 emits `BOTTLENECK_DETECTED`, `IMPROVEMENT_PROPOSED`, `MODIFICATION_ANALYSIS_STARTED/REJECTED/SANDBOXED/TESTED/BENCHMARKED/APPROVED/PROMOTED/ROLLED_BACK`, `GENOME_CREATED/EVALUATED/PROMOTED/REJECTED` on the one bus. No second event system. |
| Question Genesis | Slice 2 `question_genesis.py` | `BOTTLENECK_DETECTED` is a **pre-existing genesis trigger type**; a significant bottleneck generates the internal self-question ("what component is limiting performance, and what evidence supports this?") through the existing Slice 2 engine — no second question engine was created. Verified in the E2E: bottleneck → `BOTTLENECK_DETECTED` → `QUESTION_GENERATED` on the bus. |
| Capability Sandbox | Slice 5 `CapabilitySandbox` (which reuses the legacy `ExecutionSandbox` outer subprocess) | **Reused unchanged** as the gate's static-analysis AST inspector AND its sandboxed test runner for code changes. No second sandbox was created. |
| Telemetry consumers | Slice 6 provider health + performance ledger | Post-promotion regression monitoring reads REAL telemetry only; the gate never fabricates improvement. The Slice 6 ledger remains the routing-performance evidence source; Slice 7 adds architecture-level telemetry on top. |
| Runtime coordinator | Slice 5 `CognitiveRuntime` | Extended **in place** (additively) with telemetry, bottleneck store/detector, proposal store, genome store/manager, snapshot store and the gate. Slices 1–6 behavior unchanged. |
| Persistence pattern | SQLite-WAL + SHA-256 checksums (Slices 1–6) | Every Slice 7 store (`architecture_telemetry.db`, `bottlenecks.db`, `proposals.db`, `genomes.db`, `snapshots.db`) follows the same corruption-safe pattern; `strict_load=True` raises the store's integrity error on corruption (same convention as Slices 1–6). |

Duplication documented (not silently created): the legacy pipeline already has
`zerion/cognitive_genome/` (22-dimension genome for the legacy 25-stage
engine), `zerion/self_experimentation/` (A/B trials) and `zerion/learning_to_learn/`
(bottleneck analysis) — all untouched. The Slice 7 policy genome
(`cognitive_os/genome.py`) is the Slice 1–7 runtime's configuration genome and
uses its own `genomes.db`; the legacy stores keep their own DBs.

## 2. Files created

- `zerion/cognitive_os/telemetry.py` — `ArchitectureTelemetry` + `ComponentMetric`:
  real per-component measurements (latency, failure_rate, timeout_rate,
  tool/verification/memory/knowledge/planning/model/routing/capability success,
  resource_usage, recovery_rate, task_success). Rates are only reported after
  `MIN_SAMPLES` — below that the metric is UNKNOWN / INSUFFICIENT_DATA,
  never invented. Persisted with the SQLite-WAL + SHA-256 pattern.
- `zerion/cognitive_os/bottlenecks.py` — `BottleneckReport` (id, type, evidence,
  affected_component, frequency, severity, confidence, first/last_seen,
  affected_tasks, estimated_impact, recommended_investigation),
  `BottleneckStore`, `BottleneckDetector` with `DEFAULT_THRESHOLDS`
  (configurable per metric) and the 11 limitation types
  (MODEL/MEMORY/TOOL/PLANNING/VERIFICATION/KNOWLEDGE/RESOURCE/ROUTING/
  CAPABILITY/ARCHITECTURAL/UNKNOWN). A bottleneck is only declared from
  sufficient evidence (min samples) beyond a threshold — never because a
  component exists. Same-type same-component reports are deduped while
  unresolved (last_seen refreshed), not re-reported every scan.
- `zerion/cognitive_os/improvement.py` — `ModificationType` (8 types),
  `RiskLevel` (LOW/MEDIUM/HIGH/CRITICAL), `BASE_RISK` per modification type,
  `ProposalStatus` (PROPOSED → ANALYZING → SANDBOXED → TESTING →
  BENCHMARKING → APPROVED | REJECTED | ROLLED_BACK) with a validated
  transition matrix, `ImprovementProposal` (problem, evidence, hypothesis,
  proposed_change, benefit/cost, risk, dependencies, affected capabilities,
  test plan, rollback plan, rejection history, approval/snapshot/promotion
  fields), `ProposalStore`.
- `zerion/cognitive_os/genome.py` — `CognitiveGenome` + `GenomeManager` +
  `GenomeStore`: the runtime's CONFIGURATION genome (not weights), with
  CANDIDATE → VALIDATED → PROMOTED | REJECTED | DEPRECATED. Candidates are
  clones — the production genome is never mutated during experimentation.
  `apply_changes` is a deep-merge that never mutates the input.
- `zerion/cognitive_os/snapshots.py` — `RuntimeSnapshot` + `SnapshotStore`:
  versioned, checksummed snapshots capturing the PREVIOUS known-good
  configuration plus tests, benchmark results, approval state and a rollback
  reference. Snapshot rows are persisted (and verified) BEFORE any production
  mutation — a crash mid-promotion cannot leave a partially-promoted state.
- `zerion/cognitive_os/self_modification_gate.py` — `GatePolicy`,
  `AnalysisResult`, `TestOutcome`, `BenchmarkComparison`, `PromotionResult`,
  `RollbackResult`, `SelfModificationGate` (static_analysis, risk_assessment,
  run_tests, benchmark, approve, promote, monitor_regression, rollback).
- `tests/test_self_improvement_foundation.py` — 44 tests.
- `ZERION_SLICE_7_REPORT.md` — this report.

## 3. Files modified

- `zerion/runtime/events.py` — added `BOTTLENECK_DETECTED`,
  `IMPROVEMENT_PROPOSED`, `MODIFICATION_ANALYSIS_STARTED`,
  `MODIFICATION_REJECTED`, `MODIFICATION_SANDBOXED`, `MODIFICATION_TESTED`,
  `MODIFICATION_BENCHMARKED`, `MODIFICATION_APPROVED`, `MODIFICATION_PROMOTED`,
  `MODIFICATION_ROLLED_BACK`, `GENOME_CREATED`, `GENOME_EVALUATED`,
  `GENOME_PROMOTED`, `GENOME_REJECTED`.
- `zerion/cognitive_os/cognitive_runtime.py` — owns `architecture_telemetry`,
  `bottleneck_store`, `bottleneck_detector`, `proposal_store`,
  `genome_store`/`genome_manager`, `snapshot_store`, `self_modification_gate`;
  `BOTTLENECK_DETECTED` added to the Slice 2 question-trigger set; new methods
  `record_telemetry` / `detect_bottlenecks` / `propose_improvement` /
  `analyze_modification` / `sandbox_modification` / `test_modification` /
  `benchmark_modification` / `approve_modification` / `promote_modification` /
  `rollback_modification` / `current_genome` / `propose_genome_variation` /
  `evaluate_genome` / `promote_genome` / `reject_genome` / `create_snapshot` /
  `monitor_proposal_regression`.
- `zerion/cognitive_os/__init__.py` — exports for the new types.

## 4. Self-observation & bottleneck detection

- **Telemetry is real:** every metric is a counted (successes, failures,
  total) with optional latency sums and raw values. Below `MIN_SAMPLES` the
  rate is `None` → consumers see INSUFFICIENT_DATA. Nothing is fabricated:
  `test_insufficient_data_is_unknown` and the rate tests assert exact
  thresholds. Persistence round-trips (`record → restart → load → verify`)
  are tested; corrupted rows raise in strict mode.
- **Evidence-required detection:** the detector scans telemetry per component
  and only reports a bottleneck when a metric has ≥ min-samples AND is beyond
  its configurable threshold. All-rate-high components produce no report;
  a component with 2 samples produces no report. Dominant type per component
  is chosen from the evidence; severity/confidence derive from the actual
  rates and sample counts. Same bottleneck is deduped on rescan.
- **Thresholds are configurable** (`thresholds=` dict overrides
  `DEFAULT_THRESHOLDS`) — verified by tests (e.g. raising the
  `verification_success` threshold to 0.9 makes an all-success component
  reportable only when actually below it).

## 5. Self-question (Slice 2 integration)

`BOTTLENECK_DETECTED` is a Slice 2 `QuestionGenesis` trigger (the same
internal-trigger set as Slice 2). When a significant bottleneck is published,
the existing Slice 2 engine generates the internal question — no new question
engine was built. Verified end-to-end: repeated verification failures →
`BOTTLENECK_DETECTED` event → `QUESTION_GENERATED` event on the same bus.

## 6. Improvement proposals, benchmark discipline, gate

- **A proposal is not an improvement.** `ImprovementProposal` carries problem,
  evidence, hypothesis, expected benefit/cost, risk, dependencies, affected
  capabilities, test plan and rollback plan; status moves through the full
  lifecycle with a validated transition matrix (TESTING cannot jump to
  APPROVED, etc.). `BenchmarkComparison.compare` requires `min_trials` (5) —
  fewer samples is **INCONCLUSIVE**, never SUCCESS. It compares BASELINE vs
  CANDIDATE on identical deterministic tasks across correctness AND latency
  AND extra metrics; any regression → REGRESSION; only a real correctness
  effect (≥ `success_effect` 0.1) → SUPPORTED; equal correctness → UNSUPPORTED
  (a pure latency win is not "improvement").
- **Static analysis is AST-based** (Slice 5 `CapabilitySandbox.inspect` for
  code changes) plus scope enforcement (target must be inside `proposal.scope`
  and the gate's allowed components), declared-file containment, and
  forbidden-pattern checks — not a naive string blacklist. Verified blocks:
  `os.system`, unrestricted `subprocess.Popen`, secret extraction, destructive
  filesystem writes, `socket` network access, outside-scope targets,
  `sudo rm -rf`-style config strings.
- **Risk:** `RiskLevel` LOW/MEDIUM/HIGH/CRITICAL with `BASE_RISK` per
  modification type (ARCHITECTURE_CHANGE = CRITICAL), escalated by no-rollback
  plans, high-permission dependencies/affected capabilities, and explicit
  CRITICAL. HIGH/CRITICAL are never auto-approved; MEDIUM requires explicit
  approval unless policy allows; LOW auto-promotes only when `GatePolicy`
  permits.
- **Sandbox:** code changes are never executed in the production runtime —
  they are inspected by the static gate and executed only inside the reused
  Slice 5 sandbox during tests. A generated modification that fails tests is
  REJECTED and never reaches the benchmark.
- **Atomic promotion:** a snapshot of the PREVIOUS state is written and
  verified BEFORE any mutation; the change is applied only for
  `CONFIGURATION_CHANGE` (via a new genome candidate that is evaluated and
  promoted with evidence). STRATEGY/PROMPT/ROUTING/MEMORY/CAPABILITY/CODE/
  ARCHITECTURE changes are APPROVED with evidence + snapshot but never
  auto-applied — no unrestricted source modification.
- **Monitoring + rollback:** `monitor_regression` reads REAL post-promotion
  telemetry; a degraded component triggers `rollback`, which restores the
  pre-change snapshot genome, records the reason, and sets status ROLLED_BACK.
  Rollback without a snapshot fails honestly (recorded, not silent).

## 7. Genome versioning

`CognitiveGenome` is the promoted production CONFIGURATION. Candidates are
clones with parent pointers; the production genome is never mutated during
experimentation. Promote requires evaluation evidence (a candidate with no
evaluation raises). Rollback restores the previously-promoted genome exactly.
Persistence across restart is tested.

## 8. Required E2E (verified in tests AND through the real engine)

1. **BOTTLENECK:** repeated verification failures → `VERIFICATION_LIMITATION`
   report with evidence, severity, confidence, affected tasks; event on the
   bus; Slice 2 question generated; rescan is deduped (no duplicate reports).
2. **REJECT:** unsafe CODE_CHANGE (`os.system('rm -rf /')`) → REJECTED at
   static analysis, production genome unchanged.
3. **PROMOTE:** LOW CONFIGURATION_CHANGE passes analysis → sandbox → tests →
   benchmark SUPPORTED (baseline 0.6 vs candidate 1.0 on 10 identical trials)
   → policy approve → atomic promotion: snapshot v1 written, genome
   configuration updated to strictness 0.3.
4. **ROLLBACK:** post-promotion telemetry shows the component degrading →
   `monitor_regression` true → rollback restores snapshot v1 → genome back to
   strictness 0.5, proposal ROLLED_BACK, reason recorded.
5. Security suite: benign code passes; `os.system`, `subprocess.Popen`,
   secret extraction, destructive filesystem, network, outside-scope,
   forbidden string, HIGH/CRITICAL auto-approval and MEDIUM-without-approval
   are all rejected.

Real-engine smoke (`AscendantEngine`'s `CognitiveRuntime`, temp data dir):
telemetry → bottleneck → question (1), dedupe (2), full proposal pipeline →
PROMOTED with snapshot (3), regression → ROLLED_BACK (4), genome candidate →
evaluated → promoted without touching production during experimentation (5),
unsafe code change rejected (6). Exit 0.

## 9. Exact test results (run just now, not fabricated)

| Command | Result | Time |
|---|---|---|
| `python3 -m unittest tests.test_self_improvement_foundation` | **44 passed** | 0.68s |
| `python3 -m unittest discover -s tests -p "test_*.py"` | **505 tests — OK** (was 461; zero regressions across Slices 1–6) | 17.3s |
| `python3 -m pytest tests/test_cognitive_foundation.py tests/test_question_foundation.py tests/test_experiment_foundation.py tests/test_experience_foundation.py tests/test_capability_foundation.py tests/test_routing_foundation.py tests/test_self_improvement_foundation.py -q` | **380 passed** (was 336) | 11.0s |
| Real-engine E2E smoke (bottleneck → question → promote → rollback → genome → reject) | exit 0 | <1s |

## 10. Limitations

- Only `CONFIGURATION_CHANGE` is auto-applied to the production genome (by
  design — no unrestricted source modification). Other modification types are
  fully gated, tested, benchmarked and approved with evidence + snapshot but
  require an explicit promotion path that Slice 7 deliberately does not
  auto-execute.
- Static analysis is AST-based defense-in-depth (reusing the Slice 5 sandbox
  gate), not a full OS container — the same documented threat model as
  Slice 5, with the sandboxed subprocess as the hard backstop.
- Health/telemetry persist; the gate's regression monitor reads persisted
  telemetry, but monitoring cadence (when to scan for bottlenecks/regressions)
  is driven by explicit calls today, not a background scheduler.
- The benchmark discipline is deterministic-fixed-trials; statistical
  significance testing (e.g. bootstrap CI) is a natural extension but was not
  required by the spec.

## 11. Slice 8 prerequisites

- A background loop that periodically runs `detect_bottlenecks()` +
  `monitor_proposal_regression()` on real runtime cadence instead of explicit
  calls (the Slice 1–6 runtime already has the bus; a small scheduler can
  consume the events).
- Feeding routed-task outcomes (Slice 6 `record_task_outcome`) into
  architecture telemetry so MODEL/ROUTING/VERIFICATION bottlenecks are driven
  by live task data, not only explicit `record_telemetry` calls.
- If a later slice adds an explicit promotion path for STRATEGY/PROMPT/
  ROUTING/MEMORY/CAPABILITY changes, it must go through the same gate
  (analysis → sandbox → tests → benchmark → policy → snapshot → rollback).
