# ZERION_CORRECTION_REPORT.md

Scope: correction phase only, following ZERION_GROUND_TRUTH_REPORT.md. Every fix below
was applied following: ground-truth finding → root cause → minimal fix → test →
regression check. No new architecture, no new cognitive subsystems, no deletion of
the seven generation snapshots.

---

## 1. Findings Corrected

### 1.1 `--reality-audit` fabricated its result

- **Finding**: `zerion/cli.py`'s `--reality-audit` handler was a literal `print()` statement
  claiming `"Subsystems Verified: Real & Operational (67 automated tests passing)"` with no
  test execution whatsoever.
- **Root cause**: the handler never called pytest or any other verification mechanism; the
  string was static.
- **Files modified**: new `zerion/runtime/reality_audit.py`; `zerion/cli.py` (handler + new
  `--audit-target` flag).
- **Behavior before**: identical hard-coded output regardless of actual repo/test state.
- **Behavior after**: genuinely invokes `python3 -m pytest <target> -q --no-header` as a
  subprocess, parses real pass/fail/skip/error counts from pytest's own summary line, and
  exits non-zero when the suite fails.
- **Test proving correction**: `tests/test_correction_phase_regressions.py::TestRealityAuditExecutesRealTests`
  (2 tests). Also manually verified live: planted a deliberately failing test file, ran
  `--reality-audit --audit-target <file>`, confirmed it correctly reported `1 passed, 1 failed`
  and exited with code 1, then removed the planted file. Full-suite run reported the true
  count (121, not a fabricated 67).

### 1.2 `--status` / `/api/status` / `/api/maturity` / `--maturity` always reported L7

- **Finding**: `CognitiveMaturityEvaluator.evaluate()` has hard-coded default parameters
  (`episodes_count=1, procedural_rules_count=1, born_capabilities_count=1,
  learning_acceleration=1.5, flywheel_cycles=10`, etc.) that satisfy every maturity
  criterion. Every user-facing reporting call site (`cli.py` `--status` and `--maturity`,
  `ui/server.py`'s `/api/status` and `/api/maturity`) called `evaluate()` with **zero
  arguments**, so they always reported `L7_COGNITIVE_GENERATIVE` regardless of true system
  state, even on a cold start with 0 episodes.
- **Root cause**: missing arguments at four call sites; the evaluator logic itself was
  correct (proven by the one call site inside `run_developmental_cycle()` that did pass real
  arguments and correctly produced lower levels).
- **Files modified**: new `zerion/runtime/evidence.py` (shared `RuntimeEvidence` /
  `collect_runtime_evidence()`); `zerion/self_model/maturity.py` (added
  `evaluate_from_evidence()`, and fixed a second, related bug below); `zerion/cli.py` (2 call
  sites); `zerion/ui/server.py` (2 call sites).
- **Second bug found and fixed in the same file**: the level-assignment logic
  (`active_idx = min(len(met) - 1, 7)`) indexed by **how many** criteria were met, not
  **which specific consecutive levels** were met. A system satisfying L0 and L3 but not
  L1/L2 would be reported as "L1_MEMORY" (2 criteria met → index 1) despite not actually
  meeting L1's own criterion. Replaced with a proper ladder: the reported level is the
  highest level for which that level and every level below it are genuinely met.
- **Behavior before**: `--status` on a brand-new `--data-dir` with 0 episodes printed
  `Maturity Level: L7_COGNITIVE_GENERATIVE (Level 7/7)`.
- **Behavior after**: cold start correctly prints `L0_STATIC (Level 0/7)`. After one real
  developmental cycle, correctly prints `L4_SELF_DIAGNOSTIC` (episodes=1, rules=1,
  brier calibrated, but born_capabilities=0 breaks the ladder at L5). After three cycles in
  a fresh run, correctly showed episodes=3, rules=2, `L4_SELF_DIAGNOSTIC`.
- **Test proving correction**: `TestMaturityUsesRealEvidence` (2 tests) plus manual CLI runs
  shown above, cross-checked against the pre-existing (unmodified) internal call site in
  `run_developmental_cycle()` to confirm consistency.

### 1.3 Scoreboard reported hard-coded defaults as observed performance

- **Finding**: `DevelopmentalScoreboard.capture_snapshot()` accepted defaults
  (`effective_intelligence=0.88, prediction_accuracy=0.94, self_correction_rate=0.96,
  mission_reliability=0.98`, etc.) and was **never called anywhere in the codebase with
  real arguments** — `render_summary_text()` always fell through to a zero-arg
  `capture_snapshot()` call, meaning every rendered scoreboard was 100% defaults, permanently,
  regardless of how many cycles had run.
- **Root cause**: no caller ever computed or supplied real values; the defaults were
  effectively the only values that ever existed.
- **Files modified**: `zerion/benchmarks/scoreboard.py` (rewritten around the new
  `Metric`/`MeasurementStatus` provenance contract from `zerion/runtime/evidence.py`);
  `zerion/cli.py` (`--scoreboard` and end-of-cycle summary now call
  `capture_snapshot_from_evidence()` with a live `RuntimeEvidence`); `tests/test_benchmarks.py`
  (updated the one test that exercised the old fabricated API).
- **Behavior before**: `Effective Intelligence: 0.8800`, `Prediction Accuracy: 94.0%`,
  `Self-Correction Rate: 96.0%` printed unconditionally.
- **Behavior after**: capability counts (genuinely measured) show as `OBSERVED`; brier score
  (when the calibrator has predictions) shows as `CALCULATED_FROM_OBSERVED_DATA`; the
  initiative tracker's seed numbers show as `CONFIGURED_DEFAULT` rather than being presented
  as measured precision; effective intelligence, prediction accuracy, self-correction rate,
  mission reliability, and resource efficiency — which have no real measurement pipeline
  anywhere in the codebase — now correctly print `UNAVAILABLE (<reason>)` instead of a
  fabricated number. A fresh scoreboard with no captured snapshot now says
  `"No snapshot captured yet"` instead of silently rendering fabricated defaults.
- **Test proving correction**: `TestScoreboardProvenance` (2 tests) plus
  `tests/test_benchmarks.py::test_scoreboard_rendering` (updated) and
  `test_scoreboard_has_no_default_snapshot` (new). Manually verified via `--scoreboard` and
  `--cycle` CLI output shown in section 6.

### 1.4 Model provider fallback output was indistinguishable from real model output

- **Finding**: `OpenAIProvider`, without an API key, returned a canned string
  (`"Synthesized structured cognitive resolution for..."`) with fabricated
  `prompt_tokens=20, completion_tokens=30, cost_cents=0.0`. `GeminiProvider` **always**
  returned canned text regardless of API key presence (no real HTTP integration existed at
  all, despite a comment claiming "Real HTTP call if configured"), with a flat
  `cost_cents=0.005` reported unconditionally. `LocalGGUFProvider` correctly checked for a
  real `.gguf` file in `is_available()` but never actually loaded or ran one, and reported
  `is_fallback=False` even when doing nothing but returning template text.
- **Root cause**: no `execution_mode` concept existed; `is_fallback` was either not checked
  by callers or, in `LocalGGUFProvider`'s case, was simply set incorrectly.
- **Files modified**: `zerion/model_providers/provider.py` (added `execution_mode: ExecutionMode`
  field to `ModelResponse`; changed `prompt_tokens`/`completion_tokens`/`cost_cents` to
  `Optional`, meaning "unmeasured" is now representable instead of defaulting to a
  plausible-looking number); `zerion/model_providers/openai_provider.py`;
  `zerion/model_providers/gemini_provider.py`.
- **Behavior before**: fallback/template content looked structurally identical to a real
  model response except for an internal boolean most callers never inspected.
- **Behavior after**: every non-real response's `content` field is explicitly prefixed
  `[FALLBACK - NOT A MODEL RESPONSE]`; `execution_mode` is `FALLBACK_RESPONSE` for
  OpenAI (no key)/Gemini/LocalGGUF, `SIMULATION` for the intentionally-deterministic
  provider, and `REAL_MODEL_RESPONSE` only when a genuine HTTP 200 came back from OpenAI's
  API with real usage data; token counts and cost are `None` (not a fake number) whenever
  not actually measured.
- **Test proving correction**: `TestProviderFallbackHonesty` (4 tests) plus direct manual
  verification (shown in the previous turn) confirming all three no-credential providers
  report `FALLBACK_RESPONSE` with `None` tokens/cost.
- **Note**: `OpenAIProvider`'s real-call path (with a valid key) was not re-tested live in
  this phase (no API key available in this environment) — its correctness rests on the
  ground-truth phase's code review plus the fact that the response-construction code for
  that path was left structurally unchanged except for the token/cost-null-safety fix.

## 2. Measurement Integrity

| Metric | Status now |
|---|---|
| Test pass/fail/skip counts (`--reality-audit`) | OBSERVED (subprocess pytest run, parsed) |
| Maturity level (`--status`, `--maturity`, UI) | CALCULATED_FROM_OBSERVED_DATA (via `RuntimeEvidence`) |
| Episode count, procedural rule count, capability counts | OBSERVED |
| Brier score (scoreboard) | CALCULATED_FROM_OBSERVED_DATA when calibrator has predictions, else UNAVAILABLE |
| Learning velocity (scoreboard) | CALCULATED_FROM_OBSERVED_DATA when >1 cycle has run, else UNAVAILABLE |
| Effective intelligence, prediction accuracy, self-correction rate, mission reliability | UNAVAILABLE (no measurement pipeline exists anywhere in the codebase for these — not invented) |
| Initiative precision / false-initiative rate | CONFIGURED_DEFAULT (explicitly labeled as seed data, not observed initiatives) |
| Model provider token counts / cost | OBSERVED when a real API call succeeds and returns usage data; otherwise `None`/UNAVAILABLE, never a fabricated number |

## 3. Model Execution Integrity

- **Real provider execution**: `OpenAIProvider` genuinely calls
  `https://api.openai.com/v1/chat/completions` via `httpx` when `OPENAI_API_KEY` is set and
  the request succeeds; response is tagged `REAL_MODEL_RESPONSE`.
- **Fallback execution**: confirmed live for all three no-credential paths (OpenAI without
  key, Gemini always, LocalGGUF without a model file) — all now correctly tagged
  `FALLBACK_RESPONSE` with explicit `[FALLBACK - NOT A MODEL RESPONSE]` content prefix and
  `None` telemetry.
- **Failure**: an OpenAI call that raises an exception (network error, timeout, non-200) falls
  through to the same honestly-labeled fallback path; not separately distinguished as `ERROR`
  in this pass (a real follow-up: distinguish "never attempted" from "attempted and failed"
  in `execution_mode`, currently both collapse to `FALLBACK_RESPONSE`).
- **Telemetry behavior**: `total_invocations`/`failed_invocations` counters on each provider
  were left unchanged and not audited for correctness in this pass.

## 4. Self-Modification Safety

- **Gate**: static-analysis stage rewritten from a textual blocklist to an allowlist. Only
  imports of `math, statistics, itertools, functools, collections, dataclasses, typing, re,
  json, time, datetime` are permitted; any reference (identifier, attribute, or string
  literal) to `os, sys, subprocess, shutil, socket, ctypes, importlib, eval, exec, compile,
  __import__, getattr, setattr, delattr, globals, locals, vars, open, input, exit, quit`, or
  process-control-sounding names (`system, popen, execv, ..., remove, unlink, rmtree, ...`)
  is rejected outright.
- **Adversarial tests — before the fix** (executed live against the original blocklist code,
  transcript preserved here since the original blocklist code no longer exists to re-run):

  | Bypass technique | Result against original blocklist |
  |---|---|
  | `getattr(os, 'sy'+'stem')` indirection | **BYPASSED — promoted=True** |
  | `subprocess.run(...)` (not `Popen`) | **BYPASSED — promoted=True** |
  | `os.popen(...)` | **BYPASSED — promoted=True** |
  | `eval(compile("__import__('os').system(...)"))` | **BYPASSED — promoted=True** |
  | `os.execv(...)` | Blocked (failed at sandbox stage — payload executed inside the sandbox, but the sandbox happened to error) |
  | `os.remove(...)` | Blocked (same — happened to error inside sandbox) |
  | `__import__('o'+'s')` then `getattr(...,'system')` | **BYPASSED — promoted=True** |

  **5 of 7 realistic bypass techniques were promoted** by the original gate. Two "blocked"
  cases were not blocked by the guardrail logic at all — they happened to error inside the
  sandbox subprocess for unrelated reasons, meaning the actual security boundary was even
  weaker than 5/7 suggests.

- **Adversarial tests — after the fix**: same 7 techniques re-run against the allowlist
  implementation. **0 of 7 bypassed.** All rejected at stage `2_STATIC_ANALYSIS` with a
  specific reason (disallowed import / identifier / attribute / string literal). The original
  legitimate test case (direct `os.system`) remains blocked. A legitimate benign proposal
  (`def fast_add(a, b): return a + b`) still promotes correctly, confirming the allowlist
  didn't break real usage.
- **Permanent regression tests**: `tests/test_correction_phase_regressions.py::TestSelfModificationBypassResistance`
  (7 tests, one per technique plus the legitimate-code control).
- **Remaining limitations (stated explicitly, not hidden)**:
  1. The sandbox (`ExecutionSandbox`) is a plain OS subprocess — no container, seccomp, or VM
     isolation. The allowlist in stage 2 is the actual safety boundary today, not the sandbox.
     Anything that both passes the allowlist and is genuinely benign will still run with full
     host-process OS permissions inside the "sandbox."
  2. The string-literal check in the allowlist (rejecting any string constant containing a
     forbidden substring) is deliberately conservative and will produce false positives on
     legitimate code that happens to contain a forbidden word in a comment-like string —
     this tradeoff was chosen deliberately (reject-more is safer for a self-modification
     gate) but is worth knowing about.
  3. `ControlledSelfModificationEngine.execute_modification_pipeline()` **never applies a
     proposal to live running system state** — everything is evaluated in the ephemeral
     sandbox subprocess only. `ModificationResult.rolled_back` means "the proposal was
     rejected before promotion," not "a live change was reverted." This is now stated
     explicitly in the dataclass docstring. No code path in the current repository performs
     apply-then-revert against live production state.

## 5. Rollback

- **Genuinely verified real apply-then-revert**: `CognitivePlasticityManager.rollback_to_previous()`.
  Test: apply a mutation (version 1→2, reasoning_depth 3→9), call rollback, confirm state is
  restored to exactly version 1 / reasoning_depth 3. Also tested the empty-history edge case
  (rollback with nothing to roll back to returns `None` rather than erroring or fabricating a
  result). Both pass: `tests/test_correction_phase_regressions.py::TestPlasticityRollbackRestoresState`.
- **Not verified, and explicitly not claimed as verified**: rollback of the
  `ControlledSelfModificationEngine`'s "promoted" changes against live system state — no such
  apply step exists in the current codebase for there to be a rollback of, as documented in
  section 4 above.

## 6. Runtime Ownership

See `ZERION_RUNTIME_OWNERSHIP.md` for the full subsystem-by-subsystem map. Headline findings:

- **Model/cognition execution**: single coherent `CognitiveRouter` abstraction, no duplication.
- **Memory: genuine duplication found and left unresolved this phase.** `engine.memory`
  (`DevelopmentalMemoryStore`) is the store read by every reporting path fixed in this
  correction phase. `engine.foundry.episode_store` is a **separate** episode store, read
  independently by the UI's `/api/episodes` endpoint. Both are written to during a
  developmental cycle and happened to agree (1 episode each) in a live single-process test,
  but nothing in the code guarantees they can't diverge. Flagged, not merged, per the
  instruction not to consolidate without further dependency evidence.
- **Orchestration: two genuinely disconnected features found.** `engine.species_runtime`
  (`CognitiveSpeciesRuntime`, via `AscendantEngine.run_species_pulse()`) and
  `AscendantEngine.ask_ultimate_questions()` are both fully implemented, wired to live engine
  state, and **confirmed via search to be unreachable from any CLI flag or UI endpoint.**
  Classified `IMPLEMENTED_BUT_DISCONNECTED`. Not wired into an entrypoint this phase — flagged
  as a candidate next step (either expose them or explicitly document them as inactive).
- **Self-modification/evolution, health monitor, voice, UI**: each spot-checked for
  single-instantiation (no duplicate constructors found in `engine.py`); not individually
  traced for internal duplication within their own submodule trees, which is out of scope
  for this pass.

## 7. Regression Results

Full suite, run directly, not estimated:

```
$ python3 -m pytest tests/ -q --no-header
121 passed in 8.21s
```

Breakdown: 101 tests present before this phase (all still passing) + 1 test split into 2
(`test_scoreboard_rendering` updated, `test_scoreboard_has_no_default_snapshot` added) + 19
new tests in `tests/test_correction_phase_regressions.py` = 121 total, all passing, 0 failed,
0 skipped, 0 errors.

Also independently confirmed via the corrected `--reality-audit` command itself:
```
$ python3 main.py --reality-audit
Tests discovered: 121, executed: 121, passed: 121, failed: 0, errors: 0, skipped: 0
Duration: ~8s, exit code: 0
```

## 8. Remaining Problems

Listed honestly, not hidden:

1. **Memory duplication** (`engine.memory` vs `engine.foundry.episode_store`) is unresolved.
2. **`species_runtime`/`run_species_pulse()` and `ask_ultimate_questions()` remain unreachable**
   from any entrypoint — implemented but dead from the user's perspective.
3. **Self-modification sandbox provides no real OS-level isolation.** The allowlist is the
   only safety boundary; this is a meaningfully weaker guarantee than "sandboxed execution"
   implies, and is now stated explicitly rather than implied away.
4. **`ControlledSelfModificationEngine` never applies changes to live state**, so its
   "rollback" claim is really "rejection," not "reversion." No apply-then-revert path exists
   for self-modification proposals anywhere in the current codebase.
5. **GeminiProvider has no real API integration at all** (this was true before this phase too,
   but is now at least honestly labeled instead of silently returning plausible-looking text).
6. **Only ~4 of ~50 subsystems constructed in `AscendantEngine.__init__`** were individually
   audited for internal fabrication/duplication in this phase (maturity, scoreboard, model
   providers, self-modification). The remaining ~46 (world model, capability birth, learning
   engines, voice pipeline internals, the six archived generation zips, etc.) were not
   re-audited and may contain similar fabrication patterns not yet found.
7. **UI execution path** (`main.py --ui`) was not run live in this phase (would bind a port);
   its two fixed call sites were verified by code inspection and by the identical fix pattern
   working correctly in the CLI, but not independently smoke-tested via an actual HTTP request.
8. **OpenAIProvider's real-API-key path** was not re-tested live in this phase (no key
   available in this environment); only the fallback path was exercised end-to-end.

## 9. Next Safe Step

Resolve the memory duplication (`engine.memory` vs `engine.foundry.episode_store`) first,
since it's the one finding in this phase with a concrete risk of silently divergent numbers
being shown to users depending on which surface (CLI vs UI) they're looking at — and it's a
narrow, well-understood fix (make one the source of truth, have the other either alias it or
be removed) rather than a redesign. After that, either wire or explicitly retire
`species_runtime`/`ask_ultimate_questions`. Only after those two are resolved would it make
sense to widen the audit to the remaining ~46 unaudited subsystems.

---

# ZERION CORRECTION RESULT

Measurement Integrity:
FIXED (for the 4 surfaces audited this phase: reality-audit, maturity, scoreboard, provider
telemetry. NOT verified for the ~46 subsystems not yet audited.)

Runtime Truthfulness:
PARTIAL (the audited surfaces now tell the truth and were proven to do so with live evidence
in this environment; two genuine disconnections — species_runtime, ask_ultimate_questions —
and one genuine duplication — memory — remain, and are documented rather than hidden)

Model Execution Integrity:
PARTIAL (fallback paths are now honestly labeled and verified live; the real-API-key path was
not re-tested live in this environment; Gemini still has no real API integration at all)

Self-Modification Safety:
IMPROVED (blocklist replaced with allowlist; 5/7 previously-successful bypasses now blocked,
0/7 succeed against the new gate, verified by direct adversarial execution; sandbox itself
still provides no real OS-level isolation, stated explicitly as a known limitation)

Rollback:
VERIFIED (for `CognitivePlasticityManager`, the one component that actually performs a live
apply-then-revert cycle) / UNVERIFIED (for `ControlledSelfModificationEngine`, because no
apply-to-live-state path exists for it to roll back from — documented, not glossed over)

Regression:
121 passed
0 failed
0 skipped

Critical Remaining Issues:
1. Memory duplication (engine.memory vs engine.foundry.episode_store) unresolved.
2. species_runtime and ask_ultimate_questions remain fully unreachable from any entrypoint.
3. Self-modification sandbox has no real OS-level isolation; allowlist is the sole boundary.
4. ~46 of ~50 engine subsystems not yet individually audited for similar fabrication patterns.

Next Safe Step:
Resolve the engine.memory / engine.foundry.episode_store duplication (narrow, well-understood
fix), then decide whether to wire or retire species_runtime and ask_ultimate_questions. Widen
the fabrication audit to the remaining unaudited subsystems only after those two are closed.

This phase did not implement the Cognitive Species Protocol, did not claim intelligence
improvement, and did not claim superiority over any baseline. Its only claim is that the
specific surfaces listed above now report what the running system actually measured, and that
claim is backed by live, reproducible test output rather than assertion.
