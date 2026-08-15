# ZERION X — ASCENDANT ∞ REALITY REPORT

**Method:** repository-first. Every claim below was traced to executable code,
call sites, and test results. The ASCENDANT ∞ documents were treated as claims
to verify, never as evidence. All work is in the working tree (uncommitted).

**Verdict: PARTIAL — REAL BUT INCOMPLETE.** All four focus systems are
genuinely constructed by the canonical `AscendantEngine` and exercised in the
real flywheel/CLI paths, but several claimed measurements were fabricated in
code (now removed and replaced with honest NOT_MEASURED/UNAVAILABLE), and
none of the headline numbers in the ASCENDANT reports are reproducible as
*measured* results.

---

## 1. Security reality — VERIFIED (with wiring added this pass)

| Claim | Code | Runtime path | Test | Result |
|---|---|---|---|---|
| `SecurityBoundary.authorize()` is a real boundary | `zerion/runtime/security.py` | `engine.security` → `ExecutionSandbox._authorized` → every `run_python_code`; `SelfModificationGate.approve` | `test_ascendant_integrity.py`, existing security suite | **VERIFIED** |
| Deny by default (SYSTEM_MUTATE never held) | `security.py:_granted_permissions` | same | `TestSecurityReality::test_security_boundary_denies_system_mutate_by_default` | **VERIFIED** |
| Forbidden-path blocking (`/etc/shadow`, `/root`) | `security.py` component-aware check | same | existing tests | **VERIFIED** |
| Sandbox enforces the boundary | `experiments/sandbox.py:_authorized` | engine.sandbox used by 9+ subsystems (counterfactual, capability birth, genesis, immune, self-mod, autopoiesis, baselines) | `test_sandbox_enforces_security_boundary` | **VERIFIED** |
| INV-001..INV-010 enforced, not just defined | `identity/invariants.py` had **zero call sites** | — | — | **FIXED**: wired into `SelfModificationGate.approve()` (real enforcement on the canonical self-modification path; `modify_benchmark_evaluator` → INV-010 denial) |
| Anti-gaming detector on the execution path | `benchmarks/anti_gaming.py::audit_code_payload` had **zero call sites** | — | — | **FIXED**: wired into `CognitiveGenesisPipeline` stage 4 — hard-coded score patterns reject synthesized strategies before registration |
| Process-group isolation / timeouts | `sandbox.run_python_code` subprocess + `asyncio.wait_for` timeout | real subprocess execution | existing sandbox tests | **VERIFIED** (timeout+kill; process-group isolation not implemented — documented limitation) |

## 2. Self-experiment reality — FIXED (was fabricated)

**Root cause of "+0.084":** `SelfExperimentationEngine.run_architecture_experiment`
hard-coded `control_score = 0.85`, `treatment_score = control_score + 0.08`,
`latency_delta = 3.5`, and printed "Statistically verified global gain (+8.0%)"
with `sample_size` ignored. Both live call sites (`--experiment`, UI
`/api/experiment`) pass **no eval_fn**, so these fabricated numbers were the
actual output. `ASCENDANT_INFINITY_SELF_EXPERIMENTS.md:25` (treatment 0.934,
effect +0.084) traces exactly to `0.85 + 0.08`.

**Fix:** scores now come ONLY from a caller-supplied `eval_fn` (real trials,
`sample_size` honored, mean + measured wall-clock latency). Without an
evaluator the report is `decision="NOT_MEASURED"` with `None` scores — no
effect size, no acceptance. Verified live:
```
Effect Size: UNAVAILABLE (not measured — no eval_fn supplied)
Decision:    NOT_MEASURED
```
The canonical runtime's own experiment authority
(`CognitiveRuntime.reality_experiments`: plan → approve → run → evaluate) is
separate and remains the in-runtime path.

## 3. Strategy evolution reality — VERIFIED with one fix

- `record_lineage(strategy_id, parent_id, derivation_type, gain)` — real,
  persisted (SQLite, WAL); the engine records honest `gain=0.0` (unmeasured)
  for genesis-created strategies. **VERIFIED.**
- Retirement is non-destructive: `retire_strategy` deactivates + persists
  full snapshot with reason/superseded_by/rollback provenance. **VERIFIED.**
- `compose_strategies` previously recorded `benchmark_gain=0.05` — fabricated.
  **FIXED → 0.0 (unmeasured)** per INV-003. `StrategyCompatibilityEdge` graph
  is defined but never populated — documented, low impact (not on a live path).
- No parallel strategy authority: one `StrategyRegistry` + one
  `StrategyEvolutionEngine` owned by the engine. **VERIFIED.**

## 4. Cognitive genesis reality — VERIFIED (stages real; one wiring added)

10-stage pipeline (`CognitiveGenesisPipeline.synthesize_strategy`):
1_GAP_ANALYSIS, 2_FORMALIZATION, 3_COMPILATION, 4_STATIC_ANALYSIS (AST +
**anti-gaming now wired**), 5_SANDBOX_TESTS (real sandbox execution),
7_ADVERSARIAL_TEST (real sandbox), 8_BLIND_BENCHMARK (**honestly
NOT_MEASURED** — no blind benchmark executed, explicit in the stage log),
10_REGISTRATION. Stages 1-2 are constructive (not independently falsifiable);
5/7 genuinely execute code. Stage count = 8 (property tests bundled into 5;
no separate 9_CANARY stage — documented). Called live from
`run_developmental_cycle` when no strategy exists for the domain.

## 5. Genome/phenotype reality — PARTIALLY VERIFIED

- 22 dimensions with bounds, SHA-256 digest, clone, rollback mutation
  (`CognitiveGenome`, `GenomeManager` persistence): **VERIFIED.**
- **ACTIVE dimensions:** `reasoning_depth`, `parallel_reasoning_width`
  (→ phenotype → `AdaptiveCognitiveController.allocate_cognition` —
  verified changing parallel paths/depth), plus phenotype fields consumed by
  the controller (`verification_ratio` etc. are carried but not yet consumed
  by a runtime consumer — PARTIALLY ACTIVE).
- **CONFIG-ONLY / DEAD:** `GenomeManager.propose_and_apply_mutation` has zero
  call sites; most dimensions (`question_generation_rate`, `experiment_rate`,
  `counterfactual_rate`, `adversarial_check_rate`, budgets, biases) are not
  read by any runtime path. Documented, not fabricated.
- 8+1 phenotypes derive real config from the genome; `get_phenotype(domain)`
  is called every flywheel cycle. Verified: CodingPhenotype → higher
  verification, Creative vs Mathematical → different allocation widths.

## 6. Failure recovery reality — VERIFIED (canonical path)

12-class taxonomy lives in `capabilities/detector.py::CapabilityGapDetector`
(DETECTION → CLASSIFICATION → RECOVERY → RESULT → LEARNING SIGNAL through
`birth_pipeline`); the canonical recovery path is `CognitiveRuntime` +
`SelfModificationGate` (proposal → static analysis → security → tests →
benchmark → approval → promotion/rollback, all wired at
`cognitive_runtime.py:1730-1930`). Pulse failure analysis + `TASK_FAILED` /
`PREDICTION_ERROR` events feed it. This pass verified the gate's approve()
enforces INV-001..010 and SYSTEM_MUTATE (tests added).

## 7. Validation reality — UNVERIFIED AS MEASURED

- "58 tests, 100% passing" (`ASCENDANT_INFINITY_VALIDATION.md`) is not
  reproducible from the ASCENDANT test modules (11 + 4 + 5 = 20 tests there);
  the claim is **STALE**. Current suite: 865 passed / 2 skipped.
- The comparative table (Scripted / Linear ReAct / Ablated / Full) came from
  `AdversarialEvaluator`, whose Full-ASCENDANT arm hard-coded 0.96/0.94/0.98/
  0.92/0.90 per category. **FIXED:** full arm now measures real sandbox
  pass/fail on the 3 executable categories (coding/debugging/tool_use), all
  other categories NOT_MEASURED, and comparisons are restricted to the
  measured subset (heuristic baseline scores can no longer contaminate the
  ratios).

## 8. Benchmark reproducibility — FIXED (was fabricated)

`BenchmarkRunner._evaluate_task` hard-coded `ascendant_score=0.95`,
`gen_score=0.92`, `verification_passed=True`, `cost=0.01` and a `0.90`
transfer fallback — every "Improvement Ratio" from `--benchmark` was fake.
**FIXED:** real `BlindTaskGenerator(seed=7)` harnesses (deterministic) are
executed in the sandbox for executable categories; measured scores are real
pass/fail (0.0/1.0); the other 11 categories are NOT_MEASURED and excluded
from composites; unmeasured transfer makes "Effective Intelligence"
UNAVAILABLE. Verified live:
```
Tasks Evaluated: 14 (3 measured, 11 NOT_MEASURED)
Average Ascendant Score: 1.000   Improvement Ratio: 2.00x
Effective Intelligence Score: UNAVAILABLE (transfer factor not measured)
```
`evolution/ascension.py` also fabricated `post_intel = base + 0.04` —
**FIXED** to the measured post-benchmark; unmeasured comparisons are
INCONCLUSIVE (never promoted).

## 9. Ablation reproducibility — VERIFIED AS SIMULATED (mismatch with docs)

`ASCENDANT_ABLATION_REPORT.md` numbers (0.690/-26.8%, 0.710/-24.6%,
0.740/-21.4%, 0.765/-18.8%) **reproduce exactly** from
`experiments/ablation_study.py`'s config table — but that table is labeled
`SIMULATED` with `measurement_status="SIMULATED"` in code, and the CLI prints
the same disclaimer. The report presents simulated priors as empirical
findings → **doc/runtime mismatch; the code is honest, the document is
stale/mislabeled**. No real engine configuration is ablated.

## 10. Developmental curve reproducibility — FIXED (was synthetic)

`long_horizon_100.py` fabricated the entire curve:
`acc = min(0.97, 0.72 + 0.0025*c)`, `brier = max(0.02, 0.15 - 0.0013*c)`,
`second_order_gain = 2.0`, `discovery_rate=0.88`, `resource_efficiency=0.93`
— the exact source of the 97.0% / 0.0200 / 2.0× claims. **FIXED:** prediction
accuracy is derived from the real calibration sample set (None when empty),
Brier is the real calibrator output (None when empty), velocity is the real
measured delta between snapshots, second-order gain is the measured ratio of
real capability-birth cycle counts (None when <2 births), and discovery/resource
metrics are None (not instrumented). This pass also fixed the **vacuous Brier**
itself: `ConfidenceCalibrator.calculate_brier_score()` returned 0.0 with zero
samples (its `record_prediction` had no callers) — now returns `None`
(NOT_MEASURED), which also stops unmeasured calibration from inflating
cognitive maturity (engine maps None → worst-case 1.0 for the maturity gate).

## 11. Documentation mismatches

| Claim | Source | Runtime evidence | Status |
|---|---|---|---|
| Effect Size +0.084, treatment 0.934 | SELF_EXPERIMENTS.md | hard-coded 0.85+0.08 line | **FALSE → fixed** (now NOT_MEASURED without evaluator) |
| 2.57×/2.0× learning acceleration | DEVELOPMENT_CURVE.md | synthetic formula / hard-coded 2.0 | **FALSE → fixed** (measured or None) |
| 97.0% accuracy, Brier 0.0200 | DEVELOPMENT_CURVE.md | synthetic formula | **FALSE → fixed** |
| Ablation -26.8%/-24.6%/-21.4%/-18.8% | ABLATION_REPORT.md | SIMULATED config table (code labels it SIMULATED) | **REPRODUCIBLE as simulated**; doc presents as empirical → mismatch |
| 58 tests, 100% passing | VALIDATION.md | 20 ASCENDANT tests; suite 865 | **UNVERIFIED / STALE** |
| "Statistically verified" decisions | SELF_EXPERIMENTS.md | no statistics computed | **FALSE → fixed** |
| Effective Intelligence ~0.88 | FINAL_SCOREBOARD.md | scoreboard reports UNAVAILABLE (no pipeline) | **FALSE → already honest** |
| Initiative Precision 92.3% | FINAL_SCOREBOARD.md | `CONFIGURED_DEFAULT` seed (12/1/2/9.4), labeled as such | **CONFIGURED_DEFAULT** (doc presents as measured) |

## 12. Canonical runtime integration — VERIFIED

One `AscendantEngine` owns: `security`, `sandbox`, `genome_manager`,
`strategy_registry` + `strategy_genesis` + `strategy_evolution`,
`self_experimentation`, `experiments` (canonical `ExperimentEngine` +
`CognitiveRuntime.reality_experiments`), `benchmarks`, `scoreboard`,
`anti_gaming`. No parallel ASCENDANT runtime is constructed; the legacy
`cognitive_species` generation remains isolated (not constructed).

## 13–15. Files modified / created / isolated

**Modified (this pass):**
`zerion/self_experimentation/engine.py`,
`zerion/benchmarks/runner.py`, `zerion/benchmarks/adversarial_evaluator.py`,
`zerion/benchmarks/baselines.py`, `zerion/benchmarks/scoreboard.py`,
`zerion/evolution/ascension.py`, `zerion/experiments/long_horizon_100.py`,
`zerion/cognitive_genesis/genesis_pipeline.py`,
`zerion/cognitive_os/self_modification_gate.py`,
`zerion/self_model/calibration.py`, `zerion/runtime/evidence.py`,
`zerion/engine.py`, `zerion/cli.py`,
`zerion/strategy_evolution/evolution_engine.py`.

**Created:** `tests/test_ascendant_integrity.py` (8 tests).

**Tests updated:** `tests/test_infinity_subsystems.py` (+2 honest
self-experiment tests, 1 rewritten with a real evaluator),
`tests/test_benchmarks.py`, `tests/test_evolution.py`,
`tests/test_validation_protocols.py` (honest evaluator + curve assertions).

**Isolated/documented (no code change):** `experiments/developmental_ab_test.py`
(test-only, hard-coded scores, never wired into CLI/UI/runtime — STALE);
`AblationStudyRunner` (honest SIMULATED by design).

## 16–17. Tests executed & exact counts

```
python3 -m compileall -q zerion tests main.py        → clean
python3 -m pytest -q                                  → 865 passed, 2 skipped
python3 -m pytest tests/test_architectural_invariants.py → 89 passed
```
Baseline before this pass: 854 passed, 2 skipped → **+11** (8 new integrity
tests + 3 new self-experiment tests). Invariants unchanged: 89/89.

## 18–19. Verified vs unverified capabilities

**Verified:** security boundary + sandbox enforcement + gate invariants +
anti-gaming wiring; real sandbox task execution; honest lineage/retirement;
genome/phenotype → allocation; genesis stage execution; measured-only
self-experiments.

**Unverified/limited:** real engine-config ablation (none exists — only
simulated priors); calibration Brier remains None because no runtime path
records predictions (`record_prediction` still has zero callers — a real
gap); genome mutation/rollback promotion (`GenomeManager.propose_and_apply_mutation`)
not wired to any runtime trigger; process-group isolation; most genome
dimensions CONFIG-ONLY.

## 20. Remaining blockers

1. No runtime path records calibration predictions → Brier/accuracy honestly
   stay UNAVAILABLE until wired.
2. No empirical ablation harness (component disable + same-task re-measure)
   exists.
3. Baseline models still carry heuristic score components (now excluded from
   measured comparisons, but the modules themselves are heuristic by design).
4. Document corpus (ASCENDANT_*.md) still contains the stale/false numbers;
   correcting the corpus itself is a separate documentation pass.

## Final verdict

**PARTIAL — REAL BUT INCOMPLETE.** ASCENDANT ∞ is not "mostly
documentation": the four systems are constructed, persisted, and exercised by
the canonical runtime. But its claimed results (effect sizes, improvement
ratios, ablation drops, developmental curve, 58-test validation) were NOT
measurable from code — several were fabricated at the source. This pass
removed every fabrication it could reach and made the remaining gaps explicit
(NOT_MEASURED / UNAVAILABLE / INCONCLUSIVE) with regression tests proving the
honest behavior.
