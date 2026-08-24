# ZERION — Slice 8 Report: CognitivePulse (Persistent, Event-Driven, Resource-Aware Cognitive Runtime)

**Scope:** the CognitivePulse — the coordinator of the cognitive lifecycle on
the REAL Slice 1–7 runtime. It connects the existing subsystems on the single
Slice 1 event bus without replacing any engine: perception → attention →
goals → questions → hypotheses → experiments → reality feedback → belief
update → experience → capabilities → bottlenecks → controlled improvement →
next cycle. It is NOT another agent and NOT another reasoning engine. It is
capable of doing nothing when computation has low expected value.

**Date:** 2026-08-13
**Status:** Implemented, tested, wired into `CognitiveRuntime`. Slice 9+
intentionally NOT started.

> **Repository note (two bodies of work both labeled "Slice 8").** Earlier in
> this slice, this repo also implemented the Slice 7 report's three monitoring
> prerequisites (live `TelemetryFeed` from Slice 6 task outcomes, the
> `MonitorScheduler` background cadence, and the gated policy-store promotion
> path for non-configuration modification types). Those remain part of Slice 8
> and are summarized in §4. The CognitivePulse itself is the current focus and
> consumes all of them.

---

## 1. Reused Slice 1–7 components (no duplicates created)

| Component | Source | How the Pulse uses it |
|---|---|---|
| Event Bus | Slice 1 `AsyncEventBus` (single repo bus) | The Pulse reacts to real bus events and publishes `PULSE_*` / `WORK_*` / `UNFINISHED_TASK_DETECTED` on the SAME bus. No second bus. |
| Attention field | Slice 1 `AttentionEconomy` + `CognitivePriority` (`attention.py`) | Every event is scored into an `AttentionItem` through the real `CognitivePriority` scorer — no second priority formula. Blocked goals publish `ATTENTION_CANDIDATE_CREATED`; `ATTENTION_REVIEW` reconsiders deferred candidates through the field. |
| Goal field | Slice 1 `ObjectiveContinuityManager` | `GOAL_REVIEW` reads `list_active_objectives()`; blocked goals → high-priority attention candidates; staleness is recorded, never silently deleted. |
| Question engine | Slice 2 `question_genesis.py` + `question_store` | `QUESTION_GENERATION` re-publishes the original trigger on the bus so the Slice 2 engine (not the Pulse) generates questions. `HYPOTHESIS_INVESTIGATION` only re-publishes `QUESTION_SELECTED` for questions that won attention. |
| Experiment engine | Slice 3 `RealityExperimentEngine` | `EXPERIMENT` work executes only APPROVED experiments via `runtime.run_experiment` (the explicit approval gate); reality-vs-simulation modes stay in the Slice 3 engine. `BELIEF_UPDATE` calls the real `evaluate_question`. |
| Experience distillation | Slice 4 `experience_distillation` + `episode_store` | `EPISODE_COMPLETED` → `EXPERIENCE_DISTILLATION` work, gated on importance/failure thresholds; distillation runs through the existing engine. |
| Capability registry | Slice 5 `capability_registry` | `CAPABILITY_HEALTH` is monitoring-only; the Pulse never generates/modifies capabilities outside Slice 5 gates. |
| Router / providers | Slice 6 `cognitive_router`, `provider_health` | Offline enforcement reads the REAL `ProviderHealthTracker`; `record_task_outcome` feeds telemetry via the `TelemetryFeed`. Depth `D1/D2/D3` maps to Slice 6's cognitive-depth levels (FAST_FIELD for routine, DEEP_FIELD only where justified). |
| Telemetry / bottlenecks / gate | Slice 7 `telemetry.py`, `bottlenecks.py`, `improvement.py`, `self_modification_gate.py`, `genome.py`, `snapshots.py` | `BOTTLENECK_ANALYSIS` calls the SAME `bottleneck_detector.detect()` and surfaces evidence-backed reports. `IMPROVEMENT_EVALUATION` only schedules; the Slice 7 gate decides. Genome health is monitored read-only. |
| Monitor / policy store | Slice 8 (earlier in this slice) `monitor.py`, `policy_store.py`, `telemetry_feed.py` | The Pulse's periodic telemetry scan and the monitor cadence both read the same stores; no duplicate detector/gate. |

No duplicate engines were created. `zerion/cognitive_species/cognitive_pulse.py`
(`CognitiveSpeciesRuntime`) is a legacy species-runner class, untouched.

## 2. CognitivePulse architecture

```
EVENT (bus) ──▶ attention score (Slice 1 CognitivePriority)
     │                 │
     ├─ dedup (window, fingerprint, related events)
     ├─ cooldown (per work type, persisted)
     ├─ budgets (CPU / RAM / API / network / model-inference / concurrency)
     └─ priority queue (CognitiveWorkItem, atomic status transitions)
              │
              ▼
     COGNITIVE WORK (handler) ──▶ REAL subsystem call (Slices 1–7 engine)
              │
              ▼
     WORK_COMPLETED / WORK_FAILED ──▶ cooldown set, budget spent, cycle recorded
              │
              ▼
     IDLE when nothing has expected value (no model calls)
```

Lifecycle: `START → INITIALIZE (recovery + state restore) → RUN → PAUSE →
RESUME → SHUTDOWN`, with `DEGRADED` as an honest degraded state. All
lifecycle transitions persist to the store (`pulse_state`), so a paused or
degraded pulse recovers in that state after a restart.

## 3. Event-driven activation (rule 3)

`_EVENT_ACTION_MAP` maps bus events to work types; no expensive reasoning
happens inline:

- `GOAL_BLOCKED` / `GOAL_CREATED` / `GOAL_UPDATED` → `GOAL_REVIEW`
- `TASK_FAILED` / `REPEATED_FAILURE_DETECTED` / `EXPERIMENT_FAILED` → `FAILURE_ANALYSIS`
- `PROVIDER_FAILED` → `BOTTLENECK_ANALYSIS`
- `BOTTLENECK_DETECTED` → `IMPROVEMENT_EVALUATION`
- `CAPABILITY_DEGRADED` / `CAPABILITY_DEPRECATED` → `CAPABILITY_HEALTH`
- `EXPERIMENT_COMPLETED` → `BELIEF_UPDATE`
- `ANOMALY_DETECTED` / `CONTRADICTION_FOUND` / `PREDICTION_ERROR` /
  `UNCERTAINTY_DETECTED` / `GOAL_GAP_DETECTED` / `CAPABILITY_GAP` →
  `QUESTION_GENERATION`
- `USER_INTERACTION` / `ATTENTION_DEFERRED` / `OBSERVATION_RECORDED` →
  `ATTENTION_REVIEW` (routine observations are pinned to low priority)
- `EPISODE_COMPLETED` → `EXPERIENCE_DISTILLATION`
- `RESOURCE_WARNING` / `SYSTEM_RESOURCE_DEGRADATION_DETECTED` →
  `ENVIRONMENT_HEALTH` (closed this pass — the priority-shaping branch for
  these types existed but the events were never mapped to work)

Voice events (`VOICE_*`) are recorded as an external perception source and
never turned into cognition (rule 34). The Pulse never reacts to its own
published events (`source == "cognitive_pulse"`), preventing self-trigger
loops.

## 4. The earlier-in-slice monitoring layer (brief)

- `TelemetryFeed` translates REAL Slice 6 `record_task_outcome` results into
  Slice 7 architecture telemetry (routing/model/verification success, latency,
  resource usage). Below `MIN_SAMPLES` everything stays INSUFFICIENT_DATA.
- `MonitorScheduler` runs a background cadence: OBSERVE → DETECT → sight
  persistent bottlenecks only after consecutive-cycle evidence → opt-in
  proposal (never auto-proposes by default) → post-promotion regression
  monitoring → `REGRESSION_DETECTED` → auto-rollback to the pre-change
  snapshot (bounded, safe).
- `PolicyStore` gives STRATEGY / PROMPT / ROUTING / MEMORY_POLICY /
  CAPABILITY promotions a real, versioned target, still through the FULL
  Slice 7 gate. CODE / ARCHITECTURE changes remain approval-with-evidence
  only — never applied.

## 5. Scheduler (rule 4)

Periodic activation runs per-area on its own configurable interval, with
last-run timestamps persisted per task (`periodic` table) so cadences survive
restarts and one activity never resets another's timer:

goal health (30s), telemetry scan (30s), deep cycle (300s), memory maintenance
(120s), capability health (60s), stale-task scan (30s), environment health
(60s). Nothing fires before its interval elapses — no aggressive polling.

## 6. Attention economy (rule 5)

Every event is scored through `AttentionItem` → `CognitivePriority` (Slice 1),
producing a `CognitivePriority`-derived score with urgency/importance/
uncertainty/novelty/goal-relevance/information-gain/utility/risk/cost. The
priority queue is authoritative: highest score first, ties by creation time.
Blocked goals and persistent failures are surfaced as attention candidates;
deferred attention is reconsidered by `ATTENTION_REVIEW` work.

## 7. Budgets (rule 6)

Checked BEFORE expensive work; exhaustion means DEFER (reason persisted), never
a silent overrun and never fake completion:

- CPU units per hour, API cost per day, network requests per hour,
  model-inference ms per hour (spent only by provider-required work),
  concurrent tasks (atomic slot accounting).
- RAM floor (`ram_available_mb`, closed this pass): when a real resource
  sampler reports available memory below the configured floor, work is
  deferred. Without a sampler (or on a failed sample) the check is skipped —
  INSUFFICIENT_DATA is never invented. Samples are cached 5s so the budget
  check never becomes a hot sampler.

## 8. Cooldowns (rule 9), dedup (rule 10), fast-vs-deep (rule 8)

- Every expensive work type has a cooldown (last_run / next_allowed_run /
  trigger_reason persisted). An escalated repeated-failure investigation is a
  NEW deeper item and is not blocked by the routine cooldown — but there is
  only ONE of them, never ten identical investigations.
- Equivalent events within the dedup window are aggregated by fingerprint with
  occurrence_count, first/last seen and related_events retained — evidence is
  never lost. A more urgent event for the same target upgrades the queued item
  instead of being silently dropped.
- Depth: D1 (FAST_FIELD) for routine work; D2 for bottleneck/question
  analysis; D3 for improvement evaluation and deep cycles. Deep Field is never
  used continuously.

## 9. Offline-first (rules 7, 35)

`OFFLINE_ONLY` never activates cloud cognition: provider-required work is
deferred with the reason persisted (`"offline mode (OFFLINE_ONLY)"` /
`"no provider available"`), and `_recover_deferred()` requeues it the moment
the mode/provider situation unblocks — deferred work is never lost and never
fabricated. Local deterministic work types (goal review, bottleneck analysis,
question genesis via the deterministic Slice 2 engine, experiment sandbox,
deep cycle, …) continue normally offline. Provider availability comes from the
REAL Slice 6 health tracker; UNKNOWN counts as routable, health is only proven
by real call outcomes.

## 10. Failure escalation, retry policy, crash recovery (rules 20, 28, 29)

- Failure 1 → normal recovery; repeated failures → aggregated, attention
  escalated (`REPEATED_FAILURE_DETECTED` → deeper investigation); persistent
  failure → capability-gap/bottleneck candidate via Slice 7. The same strategy
  is never endlessly repeated.
- Retries are bounded and classified: TRANSIENT (limited retry + exponential
  backoff), PERMANENT (never retried), UNKNOWN (small bounded retry then
  escalation). Attempts are incremented before the retry decision so the bound
  terminates.
- A crashing work item is isolated: failure recorded, other safe work
  continues, `RUNNING` items are requeued on store load after a crash (never
  silently completed or duplicated).

## 11. Goal field, unfinished work, problem discovery (rules 13–15)

`GOAL_REVIEW` periodically asks "what currently matters most?" — progress/
blockers are read from the real goal store; blocked goals create attention
candidates; staleness is recorded as a state transition, never deleted.
`STALE_TASK_SCAN` surfaces queued work past the configurable staleness
threshold as `UNFINISHED_TASK_DETECTED` with real age/attempts — distinct
from `USER_REQUESTED`/`ZERION_DISCOVERED` problems, and never fabricating
problems just to show autonomy. Anomaly/contradiction/resource signals feed
the existing perception → question path only when real evidence crosses
thresholds.

## 12. Self-improvement integration (rules 21–23, 33)

The Pulse schedules `BOTTLENECK_ANALYSIS` and `IMPROVEMENT_EVALUATION` but
NEVER approves, promotes, or mutates anything. All modification still passes
the Slice 7 `SelfModificationGate` (static analysis → risk → sandbox → tests →
baseline-vs-candidate benchmark → policy → snapshot → promotion/rollback);
HIGH/CRITICAL are never auto-approved. Capability health is monitoring-only;
genome health is read-only. No unrestricted self-modification, no permission
bypass, no secret exposure, no untrusted code execution outside the approved
sandbox. Autonomy is bounded autonomy.

## 13. Health, idle, deep cycle (rules 25–27)

`health()` exposes running / paused / degraded / stopped, last_cycle,
last_success, queue_size, active_work, failed_work, deferred_work,
budget_usage, next_scheduled_cycle, offline_mode, provider_available and
voice_events_seen — never claims READY without evidence. When nothing has
expected value the Pulse enters IDLE and calls no model (`PULSE_IDLE` emitted
once on the transition, not per tick). Deep cycles (budgeted, cooldown-gated)
review goals, attention, capability health, bottlenecks, unresolved questions,
repeated failures and architectural telemetry (closed this pass: the deep
cycle now records `DEEP_QUESTIONS` / `DEEP_FAILURES` / `DEEP_TELEMETRY`
evidence-only cycles; telemetry counts are reported as-is — INSUFFICIENT_DATA
below min samples).

## 14. Event bus additions (rule 30)

`PULSE_STARTED`, `PULSE_CYCLE_STARTED`, `PULSE_CYCLE_COMPLETED`, `PULSE_IDLE`,
`PULSE_PAUSED`, `PULSE_RESUMED`, `PULSE_DEGRADED`, `PULSE_STOPPED`,
`WORK_QUEUED`, `WORK_STARTED`, `WORK_DEFERRED`, `WORK_COMPLETED`, `WORK_FAILED`
were added to the ONE bus (with the earlier-in-slice `REGRESSION_DETECTED`,
`MONITOR_CYCLE_COMPLETED`, `POLICY_APPLIED`, `POLICY_ROLLED_BACK`). Closed
this pass: `PULSE_CYCLE_STARTED` / `PULSE_CYCLE_COMPLETED` were defined but
never emitted — they now bracket every real work execution (cycle start before
`WORK_STARTED`, cycle completed after `WORK_COMPLETED`/`WORK_FAILED`), and idle
ticks do not spam them.

## 15. Persistence, restart recovery, concurrency (rules 31–32)

`PulseStore` (SQLite-WAL + SHA-256 checksums, strict-load integrity errors)
persists: the work queue, cooldowns, dedup state, budget counters, per-area
periodic timestamps, cycle history, failure history and (closed this pass) the
pulse lifecycle state (`pulse_state`). A paused pulse stays paused across a
restart; a degraded pulse restores degraded; completed work is never
re-executed. All status transitions are atomic (QUEUED → RUNNING →
COMPLETED/FAILED/DEFERRED/CANCELLED) under a lock — double execution, double
promotion and queue corruption are structurally prevented.

## 16. Required E2E, resource, idle and failure tests (rules 37–40)

All are implemented as deterministic tests (`TestRequiredE2E`,
`TestPriorityAndBudget.test_required_resource_test`,
`TestSchedulerAndCooldown.test_idle_enters_when_nothing_matters`,
`TestRequiredFailure`): a goal exists → blocked → detected → attention
priority rises → question → hypotheses → experiment (only after approval) →
observation → belief update → episode → distillation → capability-gap
detection → evidence-backed bottleneck to Slice 7 → NO unauthorized
modification (genome stays v1, no APPROVED proposals) → all state persists
across restart. The resource test uses a very small budget and asserts
highest-value executes, low-value DEFERS, no budget violation, no fake
completion. The idle test asserts IDLE and zero work. The failure test drives
a failing provider through bounded retries and asserts the Pulse stays
healthy.

## 17. Exact test results (run just now, not fabricated)

| Command (from `ai-arena-019ff051-ai/`) | Result | Time |
|---|---|---|
| `python3 -m unittest tests.test_pulse_foundation -v` | **57 passed, 0 failed, 0 errors** (48 prior + 9 new this pass) | 5.2s |
| `python3 -m unittest discover -s tests -p "test_*.py"` | **580 tests — OK** (571 prior; +9; zero regressions across Slices 1–7 and the earlier Slice 8 monitoring work) | 24.8s |
| `python3 -m pytest tests/test_cognitive_foundation.py tests/test_question_foundation.py tests/test_experiment_foundation.py tests/test_experience_foundation.py tests/test_capability_foundation.py tests/test_routing_foundation.py tests/test_self_improvement_foundation.py tests/test_monitoring_foundation.py tests/test_pulse_foundation.py -q` | **455 passed** (was 398 + 57 pulse) | 20.8s |
| Module import sanity (`zerion.cognitive_os.pulse`, `pulse_store`) | OK | <1s |

New tests this pass (9):

- `TestCycleEvents.test_cycle_events_are_published_around_work`
- `TestCycleEvents.test_idle_ticks_do_not_spam_cycle_events`
- `TestResourceDegradationWork.test_resource_warning_triggers_environment_health_work`
- `TestResourceDegradationWork.test_resource_degradation_triggers_environment_health_work`
- `TestRamFloorBudget.test_ram_floor_defers_work_with_real_sampler`
- `TestRamFloorBudget.test_ram_budget_never_fabricated_without_sampler`
- `TestDeepCycleBreadth.test_deep_cycle_reviews_questions_failures_telemetry`
- `TestLifecycleStateRestore.test_paused_state_survives_restart`
- `TestLifecycleStateRestore.test_running_state_still_starts_after_restart`

No cycle counts, API usage, costs, latencies, autonomous discoveries or
success rates are claimed beyond what the tests above actually exercise.

## 18. Files created / modified

**Created earlier in this slice:** `zerion/cognitive_os/telemetry_feed.py`,
`policy_store.py`, `monitor.py`, `pulse.py` (CognitivePulse),
`pulse_store.py` (PulseStore), `tests/test_pulse_foundation.py`,
`tests/test_monitoring_foundation.py`.

**Modified this pass:**

- `zerion/cognitive_os/pulse_store.py` — `pulse_state` table +
  `save_pulse_state` / `load_pulse_state`; `cycle_history(limit)`.
- `zerion/cognitive_os/pulse.py` — lifecycle state persistence + restore
  (PAUSED/DEGRADED survive restart; `start()` no longer force-resumes a
  restored PAUSED pulse); `PULSE_CYCLE_STARTED`/`PULSE_CYCLE_COMPLETED`
  emitted around real work; `RESOURCE_WARNING` /
  `SYSTEM_RESOURCE_DEGRADATION_DETECTED` mapped to `ENVIRONMENT_HEALTH` work;
  RAM floor budget (`_ram_allows`, cached sampler, never fabricated);
  deep-cycle breadth (unresolved questions, failure ledger, telemetry
  summary); removed a duplicate set entry.
- `tests/test_pulse_foundation.py` — 9 new tests (above).

`zerion/runtime/events.py` (Slice 8 event types), `cognitive_runtime.py`
(pulse + monitor wiring), `monitor.py`, `policy_store.py`, `telemetry_feed.py`
were created/modified earlier in this slice and are unchanged by this pass.

## 19. Actual limitations

- The Pulse executes one work item per tick; `run_forever()` is an asyncio
  loop, not a separate OS daemon process.
- The RAM budget only bites when a real resource sampler is attached
  (`runtime.resources`); the stock `CognitiveRuntime` does not attach one, so
  in the default runtime the RAM check reports INSUFFICIENT_DATA and defers to
  the other budgets (honest, but the floor is inert until a sampler exists).
- Deep-cycle reviews are evidence-counting (cycles), not autonomous
  investigations — the engines decide what to act on.
- Static analysis / sandboxing depth is inherited from Slices 5/7 (AST-based
  defense-in-depth + sandboxed subprocess backstop), not a full OS container.
- Benchmarks in the Slice 7 gate remain deterministic fixed-trial
  comparisons; statistical significance testing is a later-slice extension.

## 20. Remaining gaps before Slice 9

- A durable, restart-safe scheduler task (or daemon integration) that actually
  calls `cognitive_pulse.run_forever()` / `monitor.start()` in production,
  plus a watchdog for the Pulse loop itself.
- Regression grace windows for the monitor (N consecutive degraded cycles
  before auto-rollback) to avoid thrash on transient noise.
- An operator-facing review surface for HIGH/CRITICAL approvals.
- Wiring a real resource sampler (`ResourceManager`) into `CognitiveRuntime`
  so the RAM floor and environment health run on live data instead of
  INSUFFICIENT_DATA.

## Final rule

The CognitivePulse is NOT `while True: ask_model(); think(); repeat()`. It is:

```
EVENT → ATTENTION → PRIORITY → BUDGET → COGNITIVE WORK → REALITY/RESULT
→ LEARNING → QUEUE NEXT WORK → IDLE WHEN NOTHING MATTERS
```

Verified by tests: it executes the highest-value work first, defers (never
fakes) when budgets or offline constraints bind, aggregates repeated failures
into one deeper investigation, recovers safely across restarts, never
auto-modifies anything, and enters IDLE — calling no model — when nothing has
expected value.
