# ZERION — Slice 2 Report: Self-Questioning Layer

**Scope:** Question Object, QuestionGenesis, Question Priority (via Slice 1 attention),
Hypothesis Object, HypothesisEngine, event/attention/goal integration, persistence.
**Date:** 2026-08-12
**Status:** Implemented, tested, wired into the real runtime. Slice 3+ intentionally NOT started.

---

## 1. Reused Slice 1 components (no duplicates created)

| Component | Slice 1 source | How Slice 2 uses it |
|---|---|---|
| Event Bus | `zerion/runtime/event_bus.py` → `AsyncEventBus` (validation, sequencing, deterministic dispatch, replay, DLQ) | **The same single bus.** Internal triggers flow in; `QUESTION_GENERATED`/`QUESTION_SELECTED`/`HYPOTHESES_GENERATED` flow out. No second bus. |
| Attention Field | `zerion/cognitive_os/attention.py` → `AttentionEconomy` + `CognitivePriority` | **The single priority system.** Questions are mapped to `AttentionItem`s (`question_to_attention_item`) and compete through `CognitivePriority` SELECT/DEFER/DISCARD. Question.priority is written from the attention field's score — no second priority formula. |
| Goal Field | `zerion/cognitive_os/objective_manager.py` → `ObjectiveContinuityManager` | Goal-related triggers look up the goal; an active related goal boosts `goal_relevance` to 1.0. |
| Runtime coordinator | `zerion/cognitive_os/cognitive_runtime.py` → `CognitiveRuntime` | Extended **in place** (additively) to own the Question Field + Hypothesis Engine and to consume the new event flow. Slice 1 behavior unchanged. |
| Persistence pattern | SQLite-WAL + SHA-256 checksum (`state.py` `StateStore`) | Same pattern for `QuestionStore` / `HypothesisStore`. |
| Event vocabulary | `zerion/runtime/events.py` | Reused `CONTRADICTION_FOUND`, `ANOMALY_DETECTED`, `PREDICTION_ERROR`, `CAPABILITY_GAP`, `USER_INTERACTION`; added the remaining triggers + flow events. |

Duplication documented (not silently created): the repository's legacy `zerion/questions/`
(`QuestionGraph`/`QuestionGenesis`, `questions.db`) belongs to the 25-stage engine's
problem-candidate pipeline with a different Question shape/status set. It is **untouched**;
Slice 2's `zerion/cognitive_os/question.py` is authoritative for the new architecture
(its DB was renamed `question_field.db` to avoid colliding with the legacy `questions.db`).
Consolidation is a later-slice cleanup, exactly as Slice 1 did with the goal stores.

## 2. Files created

- `zerion/cognitive_os/question.py` — `Question` (structured, never a plain string),
  `QuestionLifecycle` (GENERATED/QUEUED/SELECTED/INVESTIGATING/ANSWERED/PARTIALLY_ANSWERED/
  REJECTED/DEFERRED/EXPIRED), `QuestionSource` (USER_REQUESTED vs ZERION_GENERATED),
  `question_to_attention_item()`, `score_question()`, `QuestionStore` (SQLite WAL +
  SHA-256 checksums, `strict_load`/`load_errors`).
- `zerion/cognitive_os/hypothesis.py` — `Hypothesis` (statement + assumptions +
  predictions + expected_evidence + failure_conditions + status + evidence + score +
  revision_history), `HypothesisLifecycle` (PROPOSED/ACTIVE/SUPPORTED/WEAKENED/CONTRADICTED/
  REJECTED/CONFIRMED), `HypothesisStore` (same corruption-safe pattern).
- `zerion/cognitive_os/question_genesis.py` — `QuestionGenesis`: deterministic templates
  for UNCERTAINTY / CONTRADICTION / ANOMALY / GOAL_GAP / MISSING_DEPENDENCY /
  PREDICTION_FAILURE / REPEATED_FAILURE / CAPABILITY_GAP / USER_REQUEST, dedup by
  fingerprint, goal-relevance boosting, metric sanitization.
- `zerion/cognitive_os/hypothesis_engine.py` — `HypothesisEngine`: >= 2 competing,
  falsifiable hypotheses per question (no experiments — that is Slice 3).
- `tests/test_question_foundation.py` — 51 tests.
- `ZERION_SLICE_2_REPORT.md` — this report.

## 3. Files modified

- `zerion/runtime/events.py` — added `UNCERTAINTY_DETECTED`, `GOAL_GAP_DETECTED`,
  `MISSING_DEPENDENCY_DETECTED`, `REPEATED_FAILURE_DETECTED`, `QUESTION_GENERATED`,
  `QUESTION_SELECTED`, `HYPOTHESES_GENERATED`.
- `zerion/cognitive_os/cognitive_runtime.py` — owns `question_store`, `hypothesis_store`,
  `question_genesis`, `hypothesis_engine`; `_QUESTION_TRIGGER_TYPES`; `_on_event` now
  routes triggers → genesis → `QUESTION_GENERATED` → attention candidate (with the
  attention score written back to the question) → `ATTENTION_SELECTED` → `QUESTION_SELECTED`
  → hypotheses → `HYPOTHESES_GENERATED`. `_process_attention`/`_candidate_from_event`
  pass `question_id` through so selections carry the question link.
- `zerion/cognitive_os/__init__.py` — exports for the new types.

## 4. Question architecture

`Question` carries: `question_id`, `question` (text), `source`, `source_kind`
(USER_REQUESTED | ZERION_GENERATED), `created_at`, `status`, `priority` (attention
score), `urgency`, `uncertainty`, `novelty`, `goal_relevance`,
`expected_information_gain`, `expected_decision_impact`, `estimated_cost`, `risk`,
`related_goal`, `related_event`, `related_beliefs`, `related_hypotheses`,
`parent_question`, `resolution`, `fingerprint`, `metadata` (structured genesis
context), `updated_at`. Empty text, out-of-range metrics, and negative costs are
rejected (`QuestionValidationError`); control characters are stripped.

QuestionGenesis is deterministic and source-aware: the same event always produces the
same question. Example (the required scenario): `CONTRADICTION_FOUND` with
observed=B, expected=A → **"What alternative variable could explain B?"**. A user
request (`USER_INTERACTION` transcript) becomes a `USER_REQUESTED` question verbatim;
an empty transcript is ignored. Duplicate generation is prevented via a fingerprint
(any unresolved question with the same source + normalized text + related goal wins).

## 5. Hypothesis architecture

For one question, `HypothesisEngine` generates at least two **competing** explanations
(never random opinions). For a contradiction they are:

1. "An unobserved cause produced B." (hidden cause)
2. "The observation that A did not occur is inaccurate." (observation is wrong)
3. "The rule that A precedes B is incorrect." (the rule is wrong)

Every hypothesis carries `assumptions`, `predictions`, `expected_evidence`,
`failure_conditions`, modest `confidence` (< 1.0), status PROPOSED, empty evidence
lists, and a `revision_history`. Generation never marks anything CONFIRMED and never
performs experiments. Hypotheses are DATA: never executed, never granted permissions.

## 6. Event integration

```
CONTRADICTION_FOUND / ANOMALY_DETECTED / UNCERTAINTY_DETECTED / GOAL_GAP_DETECTED /
MISSING_DEPENDENCY_DETECTED / PREDICTION_ERROR / REPEATED_FAILURE_DETECTED /
CAPABILITY_GAP / USER_INTERACTION
        → AsyncEventBus (Slice 1)
        → QuestionGenesis → QUESTION_GENERATED
        → AttentionField (Slice 1 CognitivePriority)
        → ATTENTION_SELECTED → QUESTION_SELECTED
        → HypothesisEngine → HYPOTHESES_GENERATED
```

The full trail is observable on the real bus (verified by replay in tests). Malformed
payloads are rejected at the bus boundary (`EventValidationError`) or sanitized by
genesis; stale/duplicate events are handled by the existing bus/runtime rules.

## 7. Attention integration

No new priority system. `question_to_attention_item()` maps a Question onto the Slice 1
`AttentionItem` contract (importance held at neutral 0.5; `expected_decision_impact` →
`expected_utility`; `estimated_cost` → `resource_cost`; goal relevance →
`objective_relevance`). Questions compete for compute with everything else, are
SELECT/DEFER/DISCARD'd by `CognitivePriority`, and the authoritative score is written
back into `Question.priority` and persisted.

## 8. Goal integration

Goal-related triggers carry `goal_id`; `QuestionGenesis` queries the Slice 1 Goal Field
(`ObjectiveContinuityManager`) and raises `goal_relevance` to 1.0 for an active related
goal. The spec example works: goal "finish deployment" + missing dependency "the
migration" → question "What is the current state of the migration?" with maximum goal
relevance.

## 9. Persistence

- `QuestionStore` → `question_field.db` (SQLite WAL), `HypothesisStore` → `hypotheses.db`.
- Every row: JSON payload + SHA-256 checksum; atomic `INSERT OR REPLACE`.
- Corruption: checksum mismatch / malformed JSON / invalid structure is recorded in
  `load_errors`; with `strict_load=True` it raises (never silent empty state).
- Relationships survive restarts: questions persist `related_hypotheses` ids and
  hypotheses persist `question_id`; restart tests verify both directions.

## 10. Exact test results

Commands actually run (from the repo root, `cd ai-arena-019ff051-ai`):

```
python3 -m unittest tests.test_question_foundation -v     # Slice 2 suite
python3 -m unittest discover -s tests -p "test_*.py"        # full legacy + Slice 1 + Slice 2
python3 -m pytest tests/test_question_foundation.py tests/test_cognitive_foundation.py -q --no-header
```

- Slice 2 suite (`tests/test_question_foundation.py`): **51 passed, 0 failed** (0.5s).
- Full repository suite (`unittest discover`): **Ran 239 tests — OK** (0 failures,
  0 errors) in 8.05s (was 188 before Slice 2).
- Slice 1 + Slice 2 under pytest: **114 passed in 1.45s**.
- Engine smoke (real `AscendantEngine`): `CONTRADICTION_FOUND` → question
  "What alternative variable could explain B?" (priority 0.665, attention-scored) →
  INVESTIGATING → 3 PROPOSED hypotheses → focus updated. No LLM involved.

Coverage: question generation from every source; user vs Zerion source; priority
(attention-based, ordering); deduplication (questions + hypotheses); persistence +
restart for both; multiple competing hypotheses with assumptions/predictions/expected
evidence/failure conditions; event → question → attention → hypotheses; goal relevance;
restart recovery of relationships; malformed events/payloads; empty questions; invalid
references; corrupted stores (strict + non-strict); hallucinated evidence not promoted
(no auto-SUPPORTED/CONFIRMED); malicious generated text stored as data and never
executed; voice events never generate questions.

## 11. Limitations

- Hypothesis generation is template-based and deterministic; there is no belief
  update, no evidence testing, and no revision beyond creation (all Slice 3+).
- Question confidence/uncertainty are genesis heuristics, not calibrated estimates.
- The legacy `zerion/questions/` pipeline remains parallel (documented above);
  consolidation is deferred.
- `Question.priority` is scored by the standard `CognitivePriority` weights with a
  neutral importance term — documented and deterministic, not yet tuned per domain.

## 12. What is NOT implemented (Slice 3 boundary)

RealityExperimentEngine, BeliefRevision, ExperienceDistillation, FailureLearning,
CapabilityGenesis, CognitiveRouter, BottleneckDetector, SelfModificationGate,
CognitivePulse, Benchmark, UI redesign, Voice redesign, wake-word/voice repair.

## 13. Slice 3 prerequisites

For the next slice the foundation provides: persisted Questions with full metrics and
status, persisted Hypotheses with predictions/expected evidence/failure conditions and
question relationships, the attention-selection trail on the real bus, and the goal
relevance hooks. Slice 3 (RealityExperimentEngine) can consume `expected_evidence` /
`failure_conditions` per hypothesis, write evidence to `supporting_evidence` /
`contradicting_evidence`, and drive lifecycle transitions (SUPPORTED / WEAKENED /
CONTRADICTED / CONFIRMED / REJECTED) without touching Slice 1 or Slice 2 internals.

No claim of intelligence is made. This slice makes Zerion structurally capable of:
"I don't know something important" → "I need to ask a question" → "There are multiple
possible explanations" → "Each explanation makes different predictions." Work stops here.
