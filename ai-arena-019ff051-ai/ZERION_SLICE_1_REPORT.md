# ZERION — Slice 1 Report: Cognitive Foundation

**Scope:** Cognitive State, Cognitive Event Bus, Goal Field, Attention Economy.
**Date:** 2026-08-12
**Status:** Implemented, tested, wired into the real runtime. Slice 2+ intentionally NOT started.

---

## 1. Existing components reused

Per the audit (baseline) and the rule "do not create duplicate implementations if equivalent
functionality already exists", Slice 1 extends the repository's authoritative implementations
instead of adding parallel ones:

| Slice 1 component | Authoritative existing implementation | How it was reused |
|---|---|---|
| Event Bus | `zerion/runtime/event_bus.py` → `AsyncEventBus` (SQLite WAL event log, priority queue, DLQ, replay) | Extended **in place** with cognitive event types, validation, sequencing, deterministic synchronous dispatch. This is the single repo-wide bus; the engine keeps one instance, shared by legacy subsystems and the foundation. |
| Goal Field | `zerion/cognitive_os/objective_manager.py` → `ObjectiveContinuityManager` / `ContinuousObjective` (SQLite WAL, dependencies, blockers, history, next_action) | Extended **in place** with a full lifecycle state machine, structured trajectory/evidence, and strict corruption-safe loading. The engine's organism already owned an instance of this store — the foundation shares it. |
| Attention | `zerion/cognitive_os/attention.py` → `AttentionEconomy` / `AttentionItem` | Extended **in place** with the missing candidate fields, the `CognitivePriority` scorer, resource budget awareness, and SELECT/DEFER/DISCARD. The legacy organism path keeps working unchanged. |
| Persistence | Repository-wide SQLite-WAL pattern (`events.db`, `evidence.db`, `world_model.db`, `continuous_objectives.db`, ...) | Reused for the new `CognitiveState` store (atomic transactions + added SHA-256 checksum per document). |

Duplication found in the baseline (documented, not silently re-created):
- **Goal-like systems:** the repo already has three: `identity/objectives.py` (`LongTermObjective`/`IdentityCore`, JSON store), `cognitive_os/objective_manager.py` (`ContinuousObjective`, SQLite WAL), and `zerion/missions/` (mission DAGs). Slice 1 chose `ObjectiveContinuityManager` as the authoritative Goal Field because it is the only one with SQLite-WAL atomic persistence plus dependencies/blockers/history — and it is what the engine's organism already constructs. The other two were **not removed**: the legacy engine's `identity.list_objectives()` and `missions` lifecycle are still used by working legacy code; removal is not yet safe.
- **Attention:** one authoritative implementation existed (`cognitive_os/attention.py`). The legacy multiplicative `compute_priority()` (scale 0–1000) remains solely for the legacy organism path; the foundation uses `CognitivePriority` (weighted additive, scale 0–1, configurable + inspectable). Both live in the same class file; the new scorer is authoritative for the new architecture.
- **State:** `entity/state.py` (per-entity lifecycle), `ui/state_bridge.py` (UI presentation state) and the new `CognitiveState` (authoritative runtime cognitive state) are three distinct domains, not duplicates.

## 2. Files created

- `zerion/cognitive_os/state.py` — `CognitiveState` (typed, versioned, serializable) + `StateStore` (SQLite WAL + SHA-256 checksums).
- `zerion/cognitive_os/cognitive_runtime.py` — `CognitiveRuntime` coordinator wiring state → bus → goal field → attention field.
- `tests/test_cognitive_foundation.py` — 63 tests (state, bus, goals, attention, integration, acceptance incl. the `SYSTEM_RESOURCE_DEGRADATION_DETECTED` demo and goal restart demo, voice vocabulary, adversarial).
- `ZERION_SLICE_1_REPORT.md` — this report.

## 3. Files modified

- `zerion/runtime/events.py` — added the Slice 1 cognitive `EventType`s (`RUNTIME_*`, `STATE_RECOVERED`, `PERCEPTION_RECEIVED`, `GOAL_*`, `ATTENTION_*`, `RESOURCE_WARNING`, `SYSTEM_RESOURCE_DEGRADATION_DETECTED`, `TASK_*`); added `Event.sequence` and `Event.schema_version`. Also added the voice lifecycle vocabulary (`VOICE_STARTED`, `VOICE_TRANSCRIPT_PARTIAL`, `VOICE_TRANSCRIPT_FINAL`, `VOICE_INTERRUPTED`, `VOICE_ENDED`) as valid bus events so the architecture can eventually consume them — the cognitive foundation deliberately does **not** subscribe to them (cognition stays decoupled from voice).
- `zerion/runtime/event_bus.py` — strict event validation (`EventValidationError`), monotonic `sequence` assignment, `publish(..., dispatch_immediately=True)`, `drain_now()` for deterministic testing, `pending_count`, `dispatch_errors`, SQLite schema migration for pre-existing 7-column `events_log` tables.
- `zerion/cognitive_os/attention.py` — `AttentionItem` gains `expected_utility`, `risk`, `api_cost`, `estimated_latency_ms`, `goal_id`, `priority`; new `CognitivePriority`, `ResourceBudgetState`, `AttentionDecision`, `AttentionFieldValidationError`; `AttentionEconomy` gains `submit`, `submit_candidate_fields`, `evaluate()` (SELECT/DEFER/DISCARD), `set_budget`, `fits_budget`, `reconsider_deferred`, `stats()`. Legacy `submit_candidate`/`get_focused_attention`/`clear` unchanged.
- `zerion/cognitive_os/objective_manager.py` — `ObjectiveLifecycle` (PROPOSED/ACTIVE/BLOCKED/PAUSED/COMPLETED/ABANDONED) with validated transition matrix; `purpose`, `progress_evidence`, `abandonment_criteria`, `blockers`, structured `trajectory`; `create_goal`, `set_status`, `activate` (dependency-gated), `block`/`unblock`, `pause`/`resume`, `complete`, `abandon`, `set_progress`, `set_next_action`, `list_goals`, `count_goals`; priority/progress validation; `strict_load` + `load_errors` (corruption is raised or recorded, never silent). Legacy API (`register_objective`, `update_progress`, `list_active_objectives`) unchanged.
- `zerion/cognitive_os/__init__.py` — exports for the new/`extended types.
- `zerion/engine.py` — `AscendantEngine` now owns `cognitive_runtime` (sharing the engine's `event_bus` and the organism's objective store); `start()`/`stop()` drive the foundation; each developmental cycle feeds real perception into it.

## 4. Files deprecated

None removed. Deprecating `AsyncEventBus`, `AttentionEconomy` legacy scoring, or `IdentityCore` objectives would break working legacy code (the 25-stage engine, organism, voice pipeline, existing tests), so they remain. The report above documents the authoritative choice for each domain; removal is deferred until a later slice makes it safe.

## 5. Cognitive State design

`CognitiveState` (`zerion/cognitive_os/state.py`), one authoritative typed document:
- `schema_version` (validated on load; mismatches raise `StateVersionError`), `state_id`, `updated_at`.
- `runtime_status` (`RuntimeStatus`: INITIALIZING / RUNNING / PAUSED / STOPPED / ERROR / RECOVERING).
- `perception` (`PerceptionSnapshot`: cpu, memory, compute tier, source, timestamp).
- `attention` (`AttentionStateView`: current focus, selected/deferred/discarded/pending counters).
- `goals` (`GoalStateView`: counts per lifecycle status; the Goal Field store remains the source of truth).
- `pending_events`, `resources` (`ResourceBudgetView`), `current_focus`, `last_event`, `recovery_error`, `stale_events_discarded`.

No LLM-generated prose: every field is structured, real runtime state.

## 6. Event Bus design

The existing `AsyncEventBus` now supports the Slice 1 vocabulary and deterministic behavior:
- `Event` carries `event_id`, `event_type`, `timestamp`, `source`, `priority` (0–100), `payload`, `correlation_id`, `schema_version`, and a bus-assigned monotonic `sequence`.
- Validation rejects unknown types, non-dict payloads, out-of-range priorities, and duplicate event ids (`EventValidationError`).
- Delivery is deterministic: `publish(dispatch_immediately=True)` delivers synchronously; queued events drain in priority order (desc), FIFO within equal priority (`drain_now`).
- Events are persisted (SQLite WAL) before dispatch and can be replayed; handler failures are recorded in `dispatch_errors` / DLQ without crashing the bus.
- Events are consumed by real runtime components: the foundation's attention field subscribes and turns `PERCEPTION_RECEIVED`, `RESOURCE_WARNING`, `SYSTEM_RESOURCE_DEGRADATION_DETECTED` (equivalent resource-degradation signal), `GOAL_*` and `TASK_*` events into attention candidates. No fake UI-only event streams.

## 7. Goal Field design

`ContinuousObjective` + `ObjectiveContinuityManager` (extended) with:
- Rich goal model: `objective_id`, `objective` (title), `purpose`, `priority`, `status`, `created_at`, `updated_at`, `deadline_ts`, `dependencies`, `progress`, `progress_evidence`, `blockers`, `next_action`, `success_condition`, `failure_condition`, `abandonment_criteria`, structured `trajectory` history.
- Lifecycle `PROPOSED → ACTIVE → (BLOCKED | PAUSED | COMPLETED | ABANDONED)` with a validated transition matrix; impossible transitions raise `GoalTransitionError`. `ACTIVE` requires dependencies COMPLETED (`GoalDependencyError` otherwise).
- Every mutation persists immediately to SQLite WAL before any event is published. Goals survive process restart, conversation termination, and provider failure by construction (they never depend on an LLM).
- Corruption-safe loading: `strict_load=True` raises `ObjectiveStoreIntegrityError`; otherwise load errors are recorded in `load_errors` — never silently empty.

## 8. Attention scoring design

`CognitivePriority` — explicit, inspectable, configurable, deterministic:

```
score = Σ wᵢ·factorᵢ  −  Σ pⱼ·penaltyⱼ        (clamped to [0, 1])
factors: urgency 0.20, importance 0.20, uncertainty 0.10, novelty 0.05,
         goal_relevance 0.20, expected_information_gain 0.10, expected_utility 0.15
penalties: resource_cost 0.15, risk 0.15
```

- Not `priority = importance` — shown by tests: an importance-only candidate (score 0.2) loses to a balanced candidate (score 0.65).
- `explain(item)` returns the full weight/factor/contribution breakdown for inspection.
- `AttentionEconomy.evaluate()` orders candidates by score, then: SELECT while within the resource budget (`ResourceBudgetState`: compute units, API/model budget, latency constraint, concurrency) and at/above `select_threshold` (0.55); DEFER those above `discard_threshold` (0.30); DISCARD the rest. Deferred candidates can be reconsidered.
- Intelligence includes what Zerion decides not to process: discards are counted, reasoned, and observable via `ATTENTION_DISCARDED` events.

## 9. Persistence mechanism

Reused the repository's established SQLite-WAL pattern — no new database engine.
- Goal Field: `continuous_objectives.db` (existing store; atomic transactions).
- Event log: `events.db` / per-runtime `cognitive_events.db` (existing `events_log` table; new `sequence` column with auto-migration).
- Cognitive State: `cognitive_state.db` — single-row document table; every write is one atomic `INSERT OR REPLACE`; every read verifies a SHA-256 checksum of the payload, so partial/corrupted writes raise `StateIntegrityError` and the runtime enters RECOVERING (goals still load independently).
- Tested: WRITE → RESTART → LOAD → VERIFY for both state and goals, plus corrupted checksum, malformed JSON, and corrupt goal rows.

## 10. Runtime integration

`CognitiveRuntime` (`zerion/cognitive_os/cognitive_runtime.py`) is wired into the real entrypoint (`AscendantEngine`, `zerion/engine.py`):
- `AscendantEngine.__init__` constructs `self.cognitive_runtime` reusing the engine's `event_bus` and the organism's objective store.
- `engine.start()` → `cognitive_runtime.start()` (publishes `RUNTIME_STARTED`, recovers state, persists).
- `engine.stop()` → `cognitive_runtime.stop()` (publishes `RUNTIME_STOPPED`, persists) before the bus closes.
- Each `run_developmental_cycle()` feeds the real resource snapshot into `ingest_perception(...)` → `PERCEPTION_RECEIVED` (+ `RESOURCE_WARNING` on degradation) → attention candidates → selected focus → state updated.
- The required demo signal `SYSTEM_RESOURCE_DEGRADATION_DETECTED` is a first-class bus event with identical attention semantics to `RESOURCE_WARNING`: an acceptance test publishes it directly and verifies EventBus → AttentionCandidate → `CognitivePriority` evaluation → SELECT over a competing low-value candidate → `CognitiveState` updated (focus, counters, persisted document, full event trail).
- UI observes Slice 1 via `engine.cognitive_runtime.snapshot()` / `.state`; Slice 1 has no dependency on the UI (verified: no UI imports in any new module).

## 11. Tests executed

```
cd ai-arena-019ff051-ai
python3 -m unittest tests.test_cognitive_foundation -v
python3 -m unittest discover -s tests -p "test_*.py"          # full legacy + Slice 1 suite
python3 -m pytest tests -q --no-header                        # project's audit runner
```

Coverage: state create/serialize/deserialize/version validation/persistence/corruption;
bus publish/subscribe/ordering/FIFO/multi-subscriber/unsubscribe/validation/duplicates/
sequence/determinism/replay; goal create/update/priority/dependencies/blockers/progress/
completion/abandonment/transitions/persistence/corruption; attention creation/scoring/
ordering/impact of every factor/select/defer/discard/budget; integration (event → candidate,
goal → attention, state updates, restart); the acceptance scenarios, including the required
`SYSTEM_RESOURCE_DEGRADATION_DETECTED` demo and the goal restart demo (create → restart →
verify → progress update → restart → verify progress + history); voice vocabulary tests
(publishable on the bus, deterministically ordered, and provably **not** consumed by the
cognitive runtime — no candidates, no focus hijack); adversarial cases (corrupt state,
duplicate events, stale events, impossible transitions, invalid priorities, negative budgets,
malformed payloads, corrupted stores).

## 12. Exact pass/fail counts

Commands actually run (from the repo root, `cd ai-arena-019ff051-ai`):

```
python3 -m unittest tests.test_cognitive_foundation -v     # Slice 1 suite
python3 -m unittest discover -s tests -p "test_*.py"         # full legacy + Slice 1 suite
python3 -m pytest tests/test_cognitive_foundation.py -q --no-header
```

- Slice 1 suite (`tests/test_cognitive_foundation.py`): **63 passed, 0 failed** (0.6s).
- Full repository suite (`unittest discover`): **Ran 188 tests — OK** (0 failures, 0 errors) in 7.1s.
- Slice 1 suite under pytest: **63 passed in 0.75s**.
- Counts above include the `SYSTEM_RESOURCE_DEGRADATION_DETECTED` acceptance demo, the voice
  vocabulary tests, and the goal restart demo (previously 59 Slice 1 / 183 total).
- Note: `test_reality_audit_does_not_fake_counts` requires `pytest` (declared in the project's
  `requirements-dev.txt`); with pytest present it passes. This was a missing-dev-dependency
  environment gap, not a Slice 1 regression.

## 13. Known limitations

- Voice: only the **vocabulary** was added (VOICE_STARTED / VOICE_TRANSCRIPT_PARTIAL /
  VOICE_TRANSCRIPT_FINAL / VOICE_INTERRUPTED / VOICE_ENDED are publishable bus events). No
  wake-word/voice repair was implemented in Slice 1 (per scope), and the cognitive runtime
  does not consume voice events — wiring voice into cognition is deferred to a later slice.
- The foundation consumes the shared bus via immediate dispatch; legacy queued events are
  intentionally ignored by the foundation (single bus, two vocabularies — documented in code).
- `CognitiveState` counters are derived views; the Goal Field and event log remain the
  sources of truth. Deferred candidates do not yet age out automatically (reconsideration
  is manual via `reconsider_deferred()`).
- The runtime's candidate metric defaults (per event type) are explicit constants; tuning them
  into a learned policy is out of scope for Slice 1.
- Legacy goal stores (`identity/objectives.py`, `missions/`) remain parallel to the Goal Field
  for legacy compatibility; consolidating them is a later-slice cleanup.

## 14. What is NOT implemented yet

Question Genesis, Hypothesis Engine, Experiment Engine, Belief Revision, Capability Genesis,
Model Routing, Cognitive Genome, Self-Modification, Cognitive Pulse, Benchmarking, UI redesign,
Voice redesign and wake-word/voice repair (the known "Zerion" hearing issue is explicitly out
of scope for Slice 1). The Slice 1 video is UI direction for a later slice and was not used.

Per the Slice 1 stop condition, work stops here. No claim of a "cognitive species", AGI, or
any multiplier is made: this is a small, tested foundation wired into the real runtime.
