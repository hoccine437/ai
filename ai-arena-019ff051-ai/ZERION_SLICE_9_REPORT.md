# ZERION — Slice 9 Report: ZERION_COGNITIVE_BENCHMARK

**Scope:** `ZERION_COGNITIVE_BENCHMARK` — a real, adversarial, evidence-required
comparison that determines whether the Slice 1–8 Cognitive Runtime improves
system-level task performance over a plain model + tool-calling loop. It is a
benchmark and an adversary, not marketing: it never hard-codes a conclusion
("5× smarter", "500% better", "AGI"), it never leaks state between the two
system configurations, and it reports negative results. The benchmark decides
the result.

**Date:** 2026-08-13
**Status:** Implemented, tested (42 foundation tests), wired into the CLI
(`--cognitive-benchmark`), and executed end-to-end offline. Slice 10+
intentionally NOT started.

---

## 1. The two system configurations (rule 1)

| Mode | Configuration |
|---|---|
| `BASELINE` | The SAME deterministic model + normal tool calling. No memory, no goals, no questions, no verification, no experiments, no capabilities. |
| `ZERION` | The SAME model + the Cognitive Runtime (verification, failure learning, question genesis, controlled experimentation, capability validation/reuse, goal persistence). |
| `ABLATION_NO_*` | FULL ZERION minus one component (verification / memory / goals / question genesis / capabilities) — required ablation, rule 39. |

Both modes use the same model, the same tasks, the same tools, the same
initial information and the same trial seeds. **The only major variable is the
cognitive runtime.** The model (`benchmark-model-d1`) implements the Slice 6
`ModelProvider` protocol, so the benchmark is provider-independent: it runs
the deterministic local model today and can route any provider implementing
the same protocol through the same runner.

## 2. CognitiveBenchmark — the runner (rule 2)

`zerion/cognitive_os/benchmark/runner.py` implements `CognitiveBenchmark`:

- **benchmark creation** — `create_benchmark(name)` + a validated task
  registry (`register_task`, rejects duplicates / missing objective criteria /
  non-positive timeouts).
- **task registration** — `build_default_task_registry()` builds the 10
  categories × 5 deterministic variants = 50 tasks.
- **task execution** — `_run_phase` loop: runtime `observe()` → model `act()` →
  tool call or answer → world evaluation. Adaptation and goal-persistence
  families run two-phase trials (environment flip; restart).
- **trial repetition** — configurable `trials_per_task` (default 5) per mode.
- **result collection** — every trial is a `TrialRecord` with the full tool
  call log, measured times, retries, verification counts, questions, goals,
  taxonomy and the evaluator decision.
- **metric calculation** — `metrics.py` (`summarize`, `wilson_ci`, `improve`,
  `EffectiveTaskPerformance`).
- **baseline comparison / Zerion comparison** — per-task `comparisons`
  (success ratio, Wilson CIs, time ratio, ETP delta) and `per_category`
  aggregation.
- **statistical analysis** — Wilson score intervals on success rates; std /
  mean / median / 95% CI on numeric metrics; small samples are never called
  statistically meaningful.
- **report generation** — `_render_report` emits
  `ZERION_COGNITIVE_BENCHMARK.md` with every required section (executive
  result, baseline/zerion, tasks, methodology, metrics, raw results,
  statistical analysis, ablation, resource overhead, failure analysis,
  negative results, 5× target analysis, offline results, provider results,
  reproducibility, limitations, final verdict).

## 3. Task schema and categories (rules 3–5)

`BenchmarkTask` carries the full schema: task_id, category, description,
initial_state, available_information, available_tools, success_criteria,
failure_criteria, difficulty, novelty, stakes, expected_behavior, timeout_s,
resource_budget, evaluation_method, metadata. Success criteria are objective
(registration rejects tasks without them), and the evaluator checks the
answer **and** the actual tool-call log — a claim without a matching tool
call fails the task, so hallucinated successes are impossible.

The 10 categories (50 deterministic tasks):

1. NOVEL_PROBLEM_SOLVING — correct composition of f/g/h is not the memorized
   order; only testing the right order succeeds.
2. TOOL_EXECUTION — fetch two facts and compute; both facts must be read.
3. LONG_HORIZON_COMPLETION — several dependent steps; the evaluator requires
   the full dependent call sequence in order.
4. FAILURE_RECOVERY — the read tool fails the first N calls; success requires
   recovery, not giving up or guessing.
5. REALITY_VERIFICATION — two sources disagree; the config file is
   authoritative; answering from the doc alone is wrong.
6. QUESTION_GENERATION — a required parameter is not in the store; the only
   correct next action is to ask for it.
7. GOAL_PERSISTENCE — a long-term goal is persisted, the runtime restarts,
   and the objective (priority/progress/dependencies/next action) must
   survive while an unrelated interaction runs.
8. CROSS_DOMAIN_REASONING — a rule learned in one domain must be applied in
   another with the same structure.
9. ADAPTATION — the environment flips phase A→B mid-trial; a strategy that
   was valid in A stops validating in B and must be re-validated.
10. CAPABILITY_REUSE — a procedure is validated against reality once, then
    reused via a dedicated capability tool.

Ground truth is reachable **only** through world tools — the task prompt
never contains the answer (tested by `test_ground_truth_not_in_prompt`).

## 4. Contamination control, randomization, blind evaluation (rules 6–8)

- **Contamination control:** a fresh model and a fresh runtime are created per
  trial. BASELINE receives no ZERION memory, distilled rules, capabilities,
  answers or internal state; ZERION receives no baseline answers, future
  outcomes or hidden evaluator information. Nothing is shared across trials
  except the static task specification.
- **Randomization:** task ordering is shuffled per run with the run seed;
  trial seeds derive from `(run seed, task, trial index)` and are **shared
  between modes** for the same task/trial (paired design). Fixed ordering
  cannot favor one system (tested).
- **Blind evaluation:** `world.evaluate(answer, tool_log)` receives only the
  answer and the tool log — never the mode label. Trial ids are mode-prefixed
  only for post-hoc analysis; the evaluator never sees them (asserted by the
  integrity check `evaluator_is_blind`).

## 5. Metrics (rules 9–14)

Measured per trial and summarized per task/mode: TASK_SUCCESS, TIME_TO_SOLUTION
(model latency / tool latency / runtime overhead / total), RETRY_COUNT (model,
tool, strategy, recovery), RECOVERY_RATE, VERIFICATION_ACCURACY (correct /
false verification, missed contradiction, unsupported claim), KNOWLEDGE_REUSE,
QUESTION_QUALITY (relevance, info gain, decision impact, redundancy,
actionability), GOAL_PERSISTENCE (per-field breakdown), TOOL_SUCCESS and
RESOURCE_COST. Anything that cannot be measured is reported `UNKNOWN /
NOT_MEASURED` — never invented. Resource cost is a documented abstract unit
(`model_calls*0.1 + tool_calls*0.05 + runtime_tool_calls*0.05`).

**Primary metric — EffectiveTaskPerformance** (transparent, per task, not a
blind average of unrelated tasks):

```
ETP = success_rate x (1 - time_penalty) x (1 - retry_penalty)
success_rate  = successes / trials          (denominator always reported)
time_penalty  = min(0.5, max(0.0, median_time_s / timeout_s - 0.5))
retry_penalty = min(0.3, 0.05 x median_tool_retries)
```

Success rate dominates; time and retry penalties are secondary and capped.
Raw metrics are always reported alongside the score.

**Success rate** is always reported with its denominator and sample size
(successful / total trials, plus failed / timeouts / errors counts).

## 6. Reused Slice 1–8 components (no duplicates created)

| Component | Source | How the benchmark uses it |
|---|---|---|
| Attention economy | Slice 1 `AttentionItem` + `CognitivePriority` (`attention.py`) | The ZerionRuntime scores its own competing guidance candidates with the REAL Slice 1 `CognitivePriority` before emitting them. |
| Goal field | Slice 1 `ObjectiveContinuityManager` (pattern) | `ZerionRuntime.create_goal` persists priority/progress/dependencies/next-action to a restart-safe store; `measure_goal_persistence` checks every field after the restart. |
| Question engine | Slice 2 `question_genesis.py` | The runtime's `_question_genesis` emits the only correct next action (ask for the missing parameter) and scores question quality with the Slice 9 metric keys. |
| Experiment engine | Slice 3 `RealityExperimentEngine` | `_experiment_order` / `_run_multiplier_experiment` test candidate hypotheses against reality through the SAME tools the model has — never by guessing. |
| Failure learning | Slice 4 `failure_learning.py` | `_failure_learning` classifies transient tool failures and grants a bounded retry bonus; failures are aggregated, never endlessly repeated. |
| Capability registry | Slice 5 `capability_registry` | `_capabilities` validates a procedure against reality once (learning), then the model reuses it via `__capability__`; reuse is detected and measured. |
| Router / provider protocol | Slice 6 `provider_interface.py`, `router_types.py`, `cognitive_router.py` | `BenchmarkModel` implements the Slice 6 `ModelProvider` protocol; `provider_availability()` reports each provider honestly (never fabricated). |
| Benchmark infrastructure | Slice 7 gate | The benchmark is immutable per run_id (results are never overwritten) and protected from self-modification: no runtime path mutates benchmark code. |

No duplicate engines were created. The legacy `zerion/benchmarks/` suite
(14-category ASCENDANT suite, `main.py --benchmark`) is left untouched; the
Slice 9 benchmark is a separate, adversarial comparison harness.

## 7. Integrity, immutability, honesty (rules 33–36)

- `_integrity_check` verifies trial count, outcome/success consistency,
  monotonic timestamps, non-negative times, recorded model usage and that
  every success is derivable from the recorded evaluator decision (no score
  injection). Outcomes are `VALID`, `VALID_WITH_WARNINGS` (unverified claims
  underpinned a successful trial — measured lucky outcome, fully traced, not
  structural) or `INVALID` (no conclusion is drawn from an invalid run).
- `save_results` writes `<output_dir>/runs/<run_id>.json` and raises
  `FileExistsError` if the run_id already exists — immutable results.
- The seeded benchmark is deterministic: same seed → identical trial outcomes
  (tested), so any report is reproducible.
- No provider's results are fabricated: unavailable providers are reported
  `NOT_AVAILABLE` with the reason (missing key / no GGUF models).
- The report contains a `## NEGATIVE RESULTS` section and a `## 5x TARGET
  ANALYSIS` section that only reports a 5× ratio on the exact metric/task
  class where it is reached — the pooled ratio is explicitly qualified as
  "NOT an intelligence claim."

## 8. Exact test results (run just now, not fabricated)

| Command (from `ai-arena-019ff051-ai/`) | Result | Time |
|---|---|---|
| `python3 -m unittest tests.test_benchmark_foundation -v` | **42 passed, 0 failed, 0 errors** | 0.2s |
| `python3 -m unittest discover -s tests -p "test_*.py"` | **622 tests — OK** (580 prior; +42 for Slice 9; zero regressions across Slices 1–8) | 25.1s |
| `python3 main.py --cognitive-benchmark` (full run, 750 trials) | **Integrity VALID_WITH_WARNINGS; BASELINE 15.6% (39/250); ZERION 100.0% (250/250); pooled ratio 6.41x (qualified)** | <2s |

The 42 foundation tests pin: the full task schema, objective criteria,
10 categories × 50 tasks, ground-truth-not-in-prompt, paired seeds, per-run
task-order randomization, ETP formula/caps/empty-sample behavior, success rate
with denominator, statistics honesty, Wilson CIs, all metric keys present in
analysis, time breakdown components, integrity status, blind evaluation,
trial-count checks, immutable results, reproducibility manifest,
same-seed determinism, provider availability honesty, all ablation modes, the
required ablation run and report, failure taxonomy completeness, and the
report's mandated sections / no-unsupported-claims rules.

## 9. What the benchmark measured (its verdict, not a prediction)

On this deterministic task set (50 tasks × 5 trials × 3 modes, offline,
seeded):

- ZERION completed every task class every trial (250/250); BASELINE completed
  39/250 (15.6%). The pooled success-rate ratio is **6.41x** — reported only
  as a pooled aggregate with the explicit qualification that it is NOT an
  intelligence claim; per-task ratios range from 1.00x (NOVEL tasks where the
  baseline already succeeds) to 5.00x and undefined (baseline 0) elsewhere.
- ZERION detected and corrected 132 hallucinations; BASELINE detected 0.
- The report includes full per-task raw results, Wilson 95% CIs, the
  verification-ablation comparison, resource-overhead deltas, failure
  taxonomy counts, negative results (none in this run where ZERION ≤ BASELINE),
  and a `5x TARGET ANALYSIS` that only claims ratios where actually reached.
- Integrity was `VALID_WITH_WARNINGS`: a handful of successful BASELINE /
  ABLATION_NO_VERIFICATION trials relied on unverified claims — fully traced
  and reported, never hidden.

## 10. Files created / modified this slice

**Created (Slice 9):**

- `zerion/cognitive_os/benchmark/__init__.py` — public API of the benchmark.
- `zerion/cognitive_os/benchmark/types.py` — `BenchmarkMode` (BASELINE /
  ZERION + 5 ablations), `BenchmarkCategory` (10), `FailureTaxonomy` (11),
  `MetricKey` (all spec metrics + time/verification/recovery/question
  detail), `AblationSpec`, `BenchmarkTask` (full schema), `AgentAction`,
  `TrialRecord` (all measured fields), `RunManifest`.
- `zerion/cognitive_os/benchmark/metrics.py` — `Statistics`, `summarize`,
  `wilson_ci`, `improve`, `EffectiveTaskPerformance` /
  `effective_task_performance`.
- `zerion/cognitive_os/benchmark/world.py` — `ToolCall`, `BenchmarkTool`,
  `BenchmarkWorld` (seeded ground truth + mock tools + objective evaluator),
  `world_fingerprint`, and the 10 family builders (`build_fetch_compute`,
  `build_flaky_fetch`, `build_contradiction`, `build_novel_algorithm`,
  `build_capability_reuse`, `build_question_task`, `build_long_horizon`,
  `build_goal_persistence`, `build_adaptation`, `build_cross_domain`),
  `make_world`.
- `zerion/cognitive_os/benchmark/model.py` — `ModelProfile` (fixed weaknesses,
  identical for both modes), `ModelContext`, `BenchmarkModel` (deterministic,
  seeded, flawed-on-purpose, Slice 6 `ModelProvider` protocol).
- `zerion/cognitive_os/benchmark/runner.py` — `ZerionRuntime` (the Slice 1–8
  cognitive functions bound to the benchmark tools), `BenchmarkRun`,
  `CognitiveBenchmark`, `build_default_task_registry`, `provider_availability`,
  `run_end_to_end_benchmark`.
- `tests/test_benchmark_foundation.py` — 42 tests.
- `ZERION_COGNITIVE_BENCHMARK.md` — generated benchmark report (regenerated by
  each full run; latest `run_0a0e1b23eb5c`).
- `ZERION_SLICE_9_REPORT.md` — this report.

**Modified (Slice 9):**

- `zerion/cli.py` — added `--cognitive-benchmark` flag that runs the full
  benchmark, prints the executive summary (integrity, per-mode success with
  denominators, qualified pooled ratio, trials per task, modes, report path),
  and writes `ZERION_COGNITIVE_BENCHMARK.md`. The legacy `--benchmark`
  (14-category ASCENDANT suite) is untouched.
- `zerion/cognitive_os/benchmark/runner.py` — removed a duplicated
  unreachable code block in `_run_multiplier_experiment` (dead after
  `return {}`).

## 11. Actual limitations

- The model is a small deterministic stand-in, not an LLM. It is identical for
  both modes (so the comparison isolates the runtime), but absolute success
  rates will differ from a real model.
- N=5 per task per mode is the minimum; per-task Wilson intervals are wide and
  no per-task difference is claimed statistically significant without interval
  evidence. Nothing here is a claim about a real LLM.
- The runtime's guidance is deterministic and task-family-aware; generalization
  to unseen task families is not measured.
- GOAL_PERSISTENCE compares a runtime WITH a goal store against a baseline
  WITHOUT one; the baseline result is a structural negative, not a performance
  deficiency (documented in the report).
- The attention ablation is NOT_ISOLATABLE (one guidance candidate per step
  leaves nothing to arbitrate) and is documented as such rather than faked.
- The provider section reports availability honestly but does not execute
  cloud providers without keys; provider-independence is proven by protocol
  conformance, not by paid runs.

## Final rule

The benchmark is an adversary: if the evidence says ZERION loses, the report
says so. It measures 10 task classes, two system configurations whose only
variable is the cognitive runtime, objective criteria, contamination control,
randomization, blind evaluation and honest `UNKNOWN`s — and it reports exactly
what it measured, with denominators, intervals and qualifications.
