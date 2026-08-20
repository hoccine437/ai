# ZERION — Slice 4 Report: Experience → Distillation → Validation → Reuse

**Scope:** ExperienceEpisode, ExperienceDistillation, DistilledExperience,
FailureLearning (recurrence + root-cause lifecycle), validation rules,
ExperienceReuse, event/attention integration, persistence, the required E2E.
**Date:** 2026-08-12
**Status:** Implemented, tested, wired into the real runtime. Slice 5+
intentionally NOT started.

---

## 1. Reused Slice 1–3 components (no duplicates created)

| Component | Source | How Slice 4 uses it |
|---|---|---|
| Event Bus | Slice 1 `AsyncEventBus` (single repo bus) | All Slice 4 events flow on it: `EPISODE_STARTED/COMPLETED`, `EXPERIENCE_DISTILLATION_STARTED`, `EXPERIENCE_DISTILLED`, `FAILURE_RECORDED`, `FAILURE_REPEATED`, `ROOT_CAUSE_PROPOSED`, `LESSON_VALIDATED`, `LESSON_WEAKENED`, `PREVENTION_RULE_CREATED`. |
| Question Field + Attention | Slice 2 genesis + Slice 1 `CognitivePriority` | Repeated failure publishes the existing `REPEATED_FAILURE_DETECTED` trigger → Slice 2 genesis produces a high-urgency question → Slice 1 attention SELECTs it (verified: question reaches INVESTIGATING, focus updates). No second attention system. |
| Evidence field | Slice 3 `EvidenceStore` / `EvidenceMode` | Causal promotion (`CONFIRMED_CAUSAL`) requires Slice 3 **OBSERVED** experimental evidence; SIMULATED evidence is never enough. |
| Runtime coordinator | Slice 3 `CognitiveRuntime` | Extended **in place** (additively) with the Episode / Distilled / Failure stores and the distillation + failure + reuse components. Slice 1–3 behavior unchanged. |
| Persistence pattern | SQLite-WAL + SHA-256 checksums (Slices 1–3) | Same pattern for `EpisodeStore` / `DistilledExperienceStore` / `FailureStore`. |

Duplication documented (not silently created): the legacy engine has
`zerion/memory/developmental_store.py` (one generic `memory.db`),
`zerion/intelligence_forge/cognitive_episode/store.py` (`cognitive_episodes.db`)
and `zerion/cognitive_os/learning_controller.py`. The Slice 4 spec explicitly
requires separating episodic / procedural / failure / validated-rule knowledge —
the legacy single generic store is the opposite, so Slice 4 creates the four
separate corruption-safe stores in `zerion/cognitive_os/` (the same pattern
Slices 1–3 used) and leaves the legacy pipeline untouched. Slice 4's episode DB
is `experience_episodes.db` to avoid colliding with the legacy
`cognitive_episodes.db`.

## 2. Files created

- `zerion/cognitive_os/episode.py` — `ExperienceEpisode` (context, goal/event/
  question/hypothesis/experiment/observation references, actions, outcomes,
  failures, success, lessons, capabilities, resources, provenance, status, mode
  OBSERVED/SIMULATED/TEST, fingerprint), `EpisodeStatus`, `EpisodeStore`.
- `zerion/cognitive_os/distilled.py` — `DistilledExperience` (7 types:
  INVARIANT / PROCEDURE / WARNING / DECISION_RULE / CAUSAL_PATTERN /
  FAILURE_PREVENTION_RULE / REUSABLE_STRATEGY; conditions, action,
  expected_outcome, evidence, confidence, source_episodes, counterexamples,
  validation_status, causality_status, provenance, revision_history,
  times_used/times_successful), `ValidationStatus`, `CausalityStatus`,
  `DistilledExperienceStore`.
- `zerion/cognitive_os/failure_learning.py` — `FailureRecord` (8 classifications,
  root_cause_hypothesis_id, recovery_attempt/result, lesson, prevention_rule,
  evidence, confidence, repeat_count, episodes, fingerprint),
  `RootCauseHypothesis` (PROPOSED/UNCONFIRMED/CONFIRMED/REJECTED lifecycle),
  `FailureStore` (two tables: failures + root causes), `FailureLearning`.
- `zerion/cognitive_os/experience_distillation.py` — `ExperienceDistillation`:
  deterministic distillation (prevention rules from failures, procedures from
  success, causal patterns from analysis), fingerprint dedup + episode merging,
  explicit confidence formula, validation state machine, causal promotion gate,
  deprecation, counterexample recording.
- `zerion/cognitive_os/knowledge_retrieval.py` — `ExperienceReuse`: scored,
  bounded retrieval (relevance/confidence/usefulness weights), use tracking.
- `tests/test_experience_foundation.py` — 43 tests.
- `ZERION_SLICE_4_REPORT.md` — this report.

## 3. Files modified

- `zerion/runtime/events.py` — added `EPISODE_STARTED`, `EPISODE_COMPLETED`,
  `EXPERIENCE_DISTILLATION_STARTED`, `EXPERIENCE_DISTILLED`, `FAILURE_RECORDED`,
  `FAILURE_REPEATED`, `ROOT_CAUSE_PROPOSED`, `LESSON_VALIDATED`,
  `LESSON_WEAKENED`, `PREVENTION_RULE_CREATED`.
- `zerion/cognitive_os/cognitive_runtime.py` — owns the three Slice 4 stores and
  components; `EPISODE_COMPLETED` events are consumed by a real runtime
  component that distills + revalidates; new methods `start_episode` /
  `complete_episode` / `record_failure` / `retrieve_experiences`.
- `zerion/cognitive_os/__init__.py` — exports for the new types.

## 4. ExperienceEpisode design

Structured, never a plain transcript: context, goal/event/question/hypothesis/
experiment/observation relationships, actions and outcomes as structured entries,
failure references, success flag, lessons, capabilities used, resources,
provenance, status (IN_PROGRESS/COMPLETED), mode (OBSERVED/SIMULATED/TEST).
Validation rejects empty contexts, impossible timestamps and control characters.
Deterministic fingerprint (context + actions + outcome) flags duplicate episodes
— duplicates are detectable but never silently dropped.

## 5. Distillation system

`distill_episode()` extracts candidate items per episode:
- failures → `FAILURE_PREVENTION_RULE` (statement/action derived generically from
  the action + the environment-observed signals; the conclusion is never
  hard-coded to any specific cause)
- success → `PROCEDURE`
- questions/hypotheses/experiments present → `CAUSAL_PATTERN` (causality starts
  at CAUSAL_HYPOTHESIS)
Simulated episodes never produce rules. Every item references its source episodes
and evidence (provenance carries failure_id + signals). Duplicate lessons merge
their source episodes instead of being stored twice.

## 6. FailureLearning system

- First occurrence creates a `FailureRecord` (repeat_count=1) + a
  `RootCauseHypothesis` in **UNCONFIRMED** status — a root cause is never assumed
  or fabricated; the hypothesis statement generically names the observed signals.
- Repeated identical failures (fingerprint on action+error) increment
  repeat_count, append episodes, publish `FAILURE_REPEATED`, and strengthen the
  root cause. At the escalation threshold (≥3) `REPEATED_FAILURE_DETECTED` is
  published → Slice 2 question → Slice 1 attention selection → competing
  hypotheses: the system investigates instead of endlessly repeating the same
  strategy.
- Counterexamples (same action + signal, success) weaken and can REJECT the root
  cause. Recurrence with no counterexamples can CONFIRM it — evidence decides.
- Failure knowledge (incl. recovery attempt/result, prevention rule, lesson,
  confidence, repeat_count) is stored separately from episodic and procedural
  knowledge.

## 7. Validation rules

Explicit, inspectable confidence formula (evidence counts only):

```
confidence = 0.3 + min(0.4, support * 0.1) + min(0.15, recurrence_bonus)
             - min(0.5, counterexamples * 0.25)
```

Statuses: CANDIDATE (insufficient evidence — one episode is never universal) →
VALIDATING (repeatable, ≥2) → VALIDATED (≥3 source episodes, confidence ≥ 0.7,
no counterexamples) or WEAKENED / REJECTED (counterexamples) / DEPRECATED
(explicit). Model-generated lessons are stored as data but can never be
validated. CAUSAL_PATTERN items stay CAUSAL_HYPOTHESIS unless Slice 3 OBSERVED
experimental evidence supports them (correlation is never converted into
causation automatically).

## 8. Retrieval / reuse

`retrieve(goal, problem, context, failure_pattern, top_k, min_score)`:

```
score = 0.5 * relevance + 0.3 * confidence + 0.2 * usefulness
```

Deterministic, top-K bounded, score floor — never retrieves everything.
`record_use(id, success)` tracks historical usefulness so retrieval learns which
rules actually get used. Episodes, procedural knowledge, failure knowledge and
validated rules live in separate stores (never one generic memory dump).

## 9. Required E2E (verified in tests AND through the real engine)

Episode 1: tool succeeds. Episodes 2–5: tool fails when authentication expired.

1. All 5 episodes recorded (structured, persisted).
2. Recurrence detected: one failure record with repeat_count=4, episodes linked.
3. `FAILURE_REPEATED` ×3 + `REPEATED_FAILURE_DETECTED` → investigation question
   (source REPEATED_FAILURE, urgency 0.8) → Slice 1 attention SELECT → question
   INVESTIGATING, focus updated, competing hypotheses generated.
4. Root-cause hypothesis generated from the observed signals; UNCONFIRMED at
   first occurrence, CONFIRMED after recurrence with no counterexamples
   (4 revision records preserved).
5. Candidate prevention rule distilled (PREVENTION_RULE_CREATED event), CANDIDATE.
6. Validated from evidence: VALIDATED, confidence ≥ 0.7, 4 source episodes, no
   counterexamples (LESSON_VALIDATED event).
7. Stored with provenance (source, failure_id, signals) and episode relationships.
8. `retrieve_experiences("execute tool auth expired deploy")` returns the
   validated rule first, bounded top-K.

No cause was hard-coded: the signal ("authentication expired") is
environment-observed fixture data, the statement is a generic template over
observed signals, and validation is pure evidence counting — the same mechanism
validates any repeated signal.

## 10. Persistence

- `experience_episodes.db`, `distilled_experiences.db`, `failures.db` (SQLite
  WAL, per-row SHA-256 checksums, strict_load raises on corruption, load_errors
  otherwise — never silent empty state).
- Episodes, failures, root causes, distilled items, validation/revision history
  and relationships (episode→failure, failure→root cause, lesson→episodes)
  survive restarts (verified by restart tests).

## 11. Adversarial tests (all passing)

one successful episode falsely generalized; repeated identical failure;
contradictory experiences; false root cause; stale lesson (deprecation); corrupt
episode (strict + non-strict); duplicate episode; duplicate lesson (merge); low
confidence rule; causal claim without evidence (SIMULATED cannot promote);
malicious model-generated lesson (stored as data, never validated); conflicting
prevention rules (both stored, no silent overwrite).

## 12. Exact test results

Commands actually run (from the repo root, `cd ai-arena-019ff051-ai`):

```
python3 -m unittest tests.test_experience_foundation -v
python3 -m unittest discover -s tests -p "test_*.py"
python3 -m pytest tests/test_cognitive_foundation.py tests/test_question_foundation.py tests/test_experiment_foundation.py tests/test_experience_foundation.py -q --no-header
```

- Slice 4 suite (`tests/test_experience_foundation.py`): **43 passed, 0 failed**
  (0.93s).
- Full repository suite (`unittest discover`): **Ran 343 tests — OK** (0 failures,
  0 errors) in 17.22s (was 300 before Slice 4; legacy + Slice 1/2/3 all pass).
- Slices 1–4 under pytest: **218 passed in 4.94s**.
- Real-engine smoke (`AscendantEngine`): full E2E above; exit 0, assertions
  verified. No LLM involved anywhere.

## 13. Limitations

- Distillation is template-based and deterministic (by design, model-independent);
  richer lesson phrasing is a later-slice concern.
- Retrieval relevance is keyword-overlap based; semantic/embedding retrieval
  would require a model provider (explicitly out of scope).
- No conflict resolution between competing prevention rules — both are stored and
  both retrievable; arbitration is deferred.
- The legacy memory/episode pipeline remains parallel (documented above);
  consolidation is deferred.

## 14. What is NOT implemented (Slice 5 boundary)

CapabilityGenesis, CapabilityRegistry, CognitiveRouter, ModelProvider
abstraction, BottleneckDetector, SelfModificationGate, CognitivePulse, Benchmark,
UI redesign, Offline GGUF runtime, Offline voice/STT/TTS, Wake-word redesign.

## 15. Slice 5 prerequisites

The foundation now provides: persisted structured episodes, failure records with
root-cause hypotheses and recurrence data, distilled items with validation
status/confidence/provenance, bounded reuse retrieval, and the full
event/attention escalation trail. A future local model system can consume the
validated distilled knowledge as-is (provenance + confidence included) without
Slice 4 depending on it, and future slices can build capability genesis on top of
the failure/lesson evidence.

No claim of remembering more text is made. This slice demonstrates, through real
tests: EXPERIENCE → FAILURE/SUCCESS → EVIDENCE → DISTILLATION → VALIDATION →
REUSABLE KNOWLEDGE → FUTURE BETTER DECISION. Work stops here.
