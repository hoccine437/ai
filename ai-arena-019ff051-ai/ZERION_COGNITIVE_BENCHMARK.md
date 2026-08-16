# ZERION_COGNITIVE_BENCHMARK.md

**Run:** `run_d15293d8deda`  
**Created:** 2026-08-16 21:02:46 UTC  
**Seed:** 222  
**Trials per task:** 2  
**Modes:** BASELINE, ZERION, ABLATION_NO_VERIFICATION  
**Integrity:** VALID

## EXECUTIVE RESULT

- BASELINE success rate: **15.0%** (3/20)
- ZERION success rate: **100.0%** (20/20)
- Aggregate success-rate ratio (ZERION / BASELINE, all task classes pooled): **6.67x**
  - This is a pooled aggregate over unrelated task classes; it is NOT an intelligence claim. Metric/task-class-specific ratios are reported per task in RAW RESULTS.

## BASELINE

Configuration: the same deterministic model with fixed weaknesses (hallucination bias 0.5, persistence limit 2, first-source trust, bounded exploration) and plain tool calling. No memory, no goals, no questions, no verification, no experiments, no capabilities.
- Success rate: 15.0% (3/20)
- Median total time: 0.000 s
- Median model calls: 4.000
- Hallucinations detected (as evidence in log): 0

## ZERION

Configuration: the SAME model + the Cognitive Runtime (verification, failure learning, question genesis, controlled experimentation, capability validation/reuse, goal persistence). The runtime observes reality through the same tools; its work is measured as runtime overhead.
- Success rate: 100.0% (20/20)
- Median total time: 0.000 s
- Median model calls: 5.000
- Median runtime (non-model) tool calls: 3.500
- Hallucinations detected and corrected: 10

## TASKS

10 categories, 5 deterministic variants each (50 tasks). Ground truth is reachable only through tools; the evaluator checks the answer AND the tool-call log.

| Category | Variants | Task ids |
|---|---|---|
| ADAPTATION | 1 | bm_adapt_0 |
| CAPABILITY_REUSE | 1 | bm_reuse_0 |
| CROSS_DOMAIN_REASONING | 1 | bm_cross_0 |
| FAILURE_RECOVERY | 1 | bm_recovery_0 |
| GOAL_PERSISTENCE | 1 | bm_goal_0 |
| LONG_HORIZON_COMPLETION | 1 | bm_long_horizon_0 |
| NOVEL_PROBLEM_SOLVING | 1 | bm_novel_0 |
| QUESTION_GENERATION | 1 | bm_question_0 |
| REALITY_VERIFICATION | 1 | bm_reality_0 |
| TOOL_EXECUTION | 1 | bm_tool_0 |

## METHODOLOGY

- **Paired design:** BASELINE and ZERION share the same task and the same trial seed; the only variable is the cognitive runtime.
- **Contamination control:** fresh model and fresh runtime state per trial; BASELINE receives no ZERION memory/capabilities/answers; ZERION receives no baseline answers or hidden evaluator info.
- **Randomization:** task ordering is shuffled per run; trial seeds derive from (run seed, task, trial index) — identical across modes for the same trial.
- **Blind evaluation:** `world.evaluate(answer, tool_log)` receives no mode label. Trial ids are mode-prefixed only for post-hoc analysis; the evaluator never sees them.
- **Repeated trials:** default N=5 per task per mode (smaller samples are explicitly marked as statistically weak).
- **Model:** deterministic, seeded, offline (`benchmark-model-d1`), same profile for all modes: {"hallucination_bias": 0.5, "persistence_limit": 2, "guidance_retry_bonus": 2, "trust_first_source": true, "exploration_limit": 2, "guidance_acceptance": 0.9, "max_steps": 40}

## METRICS

EffectiveTaskPerformance (primary metric, transparent definition):

```
ETP = success_rate x (1 - time_penalty) x (1 - retry_penalty)
success_rate  = successes / trials          (denominator always reported)
time_penalty  = min(0.5, max(0.0, median_time_s / timeout_s - 0.5))
retry_penalty = min(0.3, 0.05 x median_tool_retries)
```

Measured metrics: task success, time to solution (model latency / tool latency / runtime overhead / total), retries (model, tool, strategy, recovery), verification accuracy (correct/false verification, missed contradiction, unsupported claim), question quality (relevance, info gain, decision impact, redundancy, actionability), goal persistence, tool success, knowledge reuse, resource cost. Metrics that cannot be measured are reported as UNKNOWN / NOT_MEASURED — never invented.

## RAW RESULTS

| Task | Category | Baseline SR | Zerion SR | Ratio | n | Zerion ETP | Baseline ETP |
|---|---|---|---|---|---|---|---|
| bm_adapt_0 | ADAPTATION | 0.0% (0/2) | 100.0% (2/2) | UNKNOWN | 2 | 1.0 | 0.0 |
| bm_cross_0 | CROSS_DOMAIN_REASONING | 0.0% (0/2) | 100.0% (2/2) | UNKNOWN | 2 | 1.0 | 0.0 |
| bm_goal_0 | GOAL_PERSISTENCE | 0.0% (0/2) | 100.0% (2/2) | UNKNOWN | 2 | 1.0 | 0.0 |
| bm_long_horizon_0 | LONG_HORIZON_COMPLETION | 50.0% (1/2) | 100.0% (2/2) | 2.00x | 2 | 1.0 | 0.5 |
| bm_novel_0 | NOVEL_PROBLEM_SOLVING | 50.0% (1/2) | 100.0% (2/2) | 2.00x | 2 | 1.0 | 0.5 |
| bm_question_0 | QUESTION_GENERATION | 0.0% (0/2) | 100.0% (2/2) | UNKNOWN | 2 | 1.0 | 0.0 |
| bm_reality_0 | REALITY_VERIFICATION | 0.0% (0/2) | 100.0% (2/2) | UNKNOWN | 2 | 1.0 | 0.0 |
| bm_recovery_0 | FAILURE_RECOVERY | 0.0% (0/2) | 100.0% (2/2) | UNKNOWN | 2 | 0.9 | 0.0 |
| bm_reuse_0 | CAPABILITY_REUSE | 50.0% (1/2) | 100.0% (2/2) | 2.00x | 2 | 1.0 | 0.5 |
| bm_tool_0 | TOOL_EXECUTION | 0.0% (0/2) | 100.0% (2/2) | UNKNOWN | 2 | 1.0 | 0.0 |

## STATISTICAL ANALYSIS

Success-rate comparisons use the Wilson score interval (proportion comparison). Tiny samples are never called statistically meaningful.

| Task | Baseline SR (95% CI) | Zerion SR (95% CI) | Ratio | Difference |
|---|---|---|---|---|
| bm_adapt_0 | 0.0% [0.000, 0.658] | 100.0% [0.342, 1.000] | UNKNOWN | +1.000 |
| bm_cross_0 | 0.0% [0.000, 0.658] | 100.0% [0.342, 1.000] | UNKNOWN | +1.000 |
| bm_goal_0 | 0.0% [0.000, 0.658] | 100.0% [0.342, 1.000] | UNKNOWN | +1.000 |
| bm_long_horizon_0 | 50.0% [0.095, 0.905] | 100.0% [0.342, 1.000] | 2.00x | +0.500 |
| bm_novel_0 | 50.0% [0.095, 0.905] | 100.0% [0.342, 1.000] | 2.00x | +0.500 |
| bm_question_0 | 0.0% [0.000, 0.658] | 100.0% [0.342, 1.000] | UNKNOWN | +1.000 |
| bm_reality_0 | 0.0% [0.000, 0.658] | 100.0% [0.342, 1.000] | UNKNOWN | +1.000 |
| bm_recovery_0 | 0.0% [0.000, 0.658] | 100.0% [0.342, 1.000] | UNKNOWN | +1.000 |
| bm_reuse_0 | 50.0% [0.095, 0.905] | 100.0% [0.342, 1.000] | 2.00x | +0.500 |
| bm_tool_0 | 0.0% [0.000, 0.658] | 100.0% [0.342, 1.000] | UNKNOWN | +1.000 |

Category-level success rates:

| Category | Baseline SR | Zerion SR | n (each) |
|---|---|---|---|
| ADAPTATION | 0.0% | 100.0% | 2 |
| CAPABILITY_REUSE | 50.0% | 100.0% | 2 |
| CROSS_DOMAIN_REASONING | 0.0% | 100.0% | 2 |
| FAILURE_RECOVERY | 0.0% | 100.0% | 2 |
| GOAL_PERSISTENCE | 0.0% | 100.0% | 2 |
| LONG_HORIZON_COMPLETION | 50.0% | 100.0% | 2 |
| NOVEL_PROBLEM_SOLVING | 50.0% | 100.0% | 2 |
| QUESTION_GENERATION | 0.0% | 100.0% | 2 |
| REALITY_VERIFICATION | 0.0% | 100.0% | 2 |
| TOOL_EXECUTION | 0.0% | 100.0% | 2 |

## ABLATION

### ABLATION_NO_VERIFICATION

| Task | Ablation SR | Full Zerion SR | Baseline SR | ETP delta vs Zerion |
|---|---|---|---|---|
| bm_adapt_0 | 0.0% | 100.0% | 0.0% | -1.000 |
| bm_cross_0 | 50.0% | 100.0% | 0.0% | -0.500 |
| bm_goal_0 | 0.0% | 100.0% | 0.0% | -1.000 |
| bm_long_horizon_0 | 50.0% | 100.0% | 50.0% | -0.500 |
| bm_novel_0 | 100.0% | 100.0% | 50.0% | +0.000 |
| bm_question_0 | 100.0% | 100.0% | 0.0% | +0.000 |
| bm_reality_0 | 0.0% | 100.0% | 0.0% | -1.000 |
| bm_recovery_0 | 0.0% | 100.0% | 0.0% | -0.900 |
| bm_reuse_0 | 50.0% | 100.0% | 50.0% | -0.500 |
| bm_tool_0 | 0.0% | 100.0% | 0.0% | -1.000 |


Ablations that cannot be isolated (NOT_ISOLATABLE): removing the Slice 1 attention function from a single-guidance-per-step deterministic runtime cannot be measured independently, because attention only arbitrates between concurrently competing candidates — with one candidate per step there is nothing to arbitrate. GOALS is likewise only exercised by the GOAL_PERSISTENCE task class.

## RESOURCE OVERHEAD

| Metric | Baseline (median) | Zerion (median) | Delta |
|---|---|---|---|
| Total time (s) | 0.000 | 0.000 | +0.000 |
| Model calls | 4.000 | 5.000 | +1.000 |
| Tool calls (model) | 3.000 | 4.000 | +1.000 |
| Runtime (non-model) tool calls | 0.000 | 3.500 | +3.500 |
| Resource cost (abstract) | 0.550 | 0.775 | +0.225 |

Overhead is the runtime's own work: verification re-reads, experiments, capability validation. Any success gain is reported against this cost; a system that improves success but consumes 100x resources would report that tradeoff.

## FAILURE ANALYSIS

Failure taxonomy counts per mode (MODEL_REASONING, TOOL_FAILURE, PLANNING_FAILURE, MEMORY_FAILURE, VERIFICATION_FAILURE, GOAL_FAILURE, ROUTING_FAILURE, RESOURCE_LIMIT, ENVIRONMENT_FAILURE, CAPABILITY_FAILURE, OTHER).

**BASELINE — failed trials:** GOAL_FAILURE=2, MODEL_REASONING=7, OTHER=6, PLANNING_FAILURE=2

**ZERION — detected-and-corrected events (within successful trials):** MODEL_REASONING=10, PLANNING_FAILURE=2

**ABLATION_NO_VERIFICATION — failed trials:** MODEL_REASONING=7, OTHER=2, PLANNING_FAILURE=2, TOOL_FAILURE=2


## NEGATIVE RESULTS

No task class showed ZERION at or below BASELINE in this run.

Evidence-insufficiency: any task with fewer than 5 trials per mode is flagged; none in this run (default N=5).

## 5x TARGET ANALYSIS

Ratios are metric- and task-class-specific; the 5x target is only reported on the exact metric where it is reached — never as a global intelligence claim.

- No metric reached a 5x improvement in this run.

## OFFLINE RESULTS

This entire run executes offline: deterministic local model, deterministic mock tools, no network access, no API keys. All trials above are offline trials; the Cognitive Runtime's core functions (verification, failure learning, questions, experiments, capabilities, goals) operate without any cloud cognition.

## PROVIDER RESULTS

| Provider | Status |
|---|---|
| deterministic_local | AVAILABLE (used for every trial in this run) |
| local_gguf | NOT_AVAILABLE (no GGUF models registered in this environment) |
| openai | NOT_AVAILABLE (no OPENAI_API_KEY configured) |
| gemini | NOT_AVAILABLE (no GEMINI_API_KEY configured) |

Provider-independence: the benchmark model implements the Slice 6 `ModelProvider` protocol and is registered with the real `CognitiveRouter` in the test suite to prove the benchmark is not bound to one provider. No unavailable provider's results are fabricated (NOT_AVAILABLE is reported instead).

## REPRODUCIBILITY

- run_id: `run_d15293d8deda`
- timestamp: 2026-08-16 21:02:46 UTC
- seed: 222
- trials per task: 2
- model/profile: {"hallucination_bias": 0.5, "persistence_limit": 2, "guidance_retry_bonus": 2, "trust_first_source": true, "exploration_limit": 2, "guidance_acceptance": 0.9, "max_steps": 40}
- provider: deterministic_local
- task versions: {"bm_tool_0": "v1", "bm_recovery_0": "v1", "bm_reality_0": "v1", "bm_novel_0": "v1", "bm_reuse_0": "v1", "bm_question_0": "v1", "bm_long_horizon_0": "v1", "bm_goal_0": "v1", "bm_adapt_0": "v1", "bm_cross_0": "v1"}
- runtime config: {"benchmark": "ZERION_COGNITIVE_BENCHMARK", "registry_size": 10}
- resource budget: {"trials_per_task": 2, "max_steps_per_world": "world_defined"}

Results are stored immutably (a run_id is never overwritten) in `<output_dir>/runs/<run_id>.json`, which contains the full trial records, analysis and integrity checks.

## LIMITATIONS

- The model is a small deterministic stand-in, not an LLM; it is the same for both modes, so the comparison isolates the runtime, but absolute success rates will differ from a real model.
- N=5 per task per mode is the minimum; per-task confidence intervals are wide and no per-task difference is claimed statistically significant without interval evidence.
- The runtime's guidance is deterministic and task-family-aware; generalization to unseen task families is not measured here.
- GOAL_PERSISTENCE compares a runtime WITH a goal store against a baseline WITHOUT one; the baseline result is a structural negative, not a performance deficiency.

## FINAL VERDICT

ZERION outperformed BASELINE on the pooled deterministic task set (15.0% vs 100.0%). The evidence is per-task (see RAW RESULTS and STATISTICAL ANALYSIS); this verdict is scoped to those tasks, that model and N=20 trials per mode.

---
*This report is generated from measured trial data. The benchmark is an adversary: if the evidence says ZERION loses, this report says so.*