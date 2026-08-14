# ZERION-X ARCHITECTURAL FREEZE

**Status of this document:** Canonical architecture contract for ZERION-X.
**Scope:** The repository as it exists at this commit — runtime behavior is the
source of truth, not documentation.
**Rule:** After this freeze, no Slice, feature, agent, model, UI, voice, or
evolution work may bypass the contracts defined here. Historical Zerion /
Genesis / Omega / Singularity / Cognitive Species / Ascendant material is
**historical material only** — reusable only where it does not violate a
contract below.

---

## 1. Current architecture reality

### 1.1 Entrypoints

| Entrypoint | File | What it runs |
|---|---|---|
| CLI | `main.py` → `zerion/cli.py` | `AscendantEngine`; flags: `--status`, `--cycles`, `--ui`, `--voice`, `--models`, `--reality-audit`, `--scoreboard`, `--cognitive-benchmark`, `--experiment`, `--benchmark`, `--introspect`, `--architecture`, `--level 1..7`, etc. |
| Web UI server | `zerion/ui/server.py` (started by `--ui`) | HTTP server; GET endpoints read state through `VisualizationStateAdapter` / `CognitiveRuntime.snapshot()`; POST endpoints execute validated `CommandAPI` commands |
| Voice service | `zerion/voice/perception_service.py` (engine-scoped) | Microphone monitor → VAD → wake word → STT → emits `VOICE_*` events on the single bus |
| Flywheel | `AscendantEngine.run_developmental_cycle()` (`zerion/engine.py`) | Legacy 25-stage developmental cycle (perception → pressure → questions → strategy → program → evidence → memory → foundry → organism → telemetry) |
| Cognitive runtime | `zerion/cognitive_os/cognitive_runtime.py` | Slice 1–8 canonical runtime: state, goals, attention, questions, hypotheses, experiments, evidence/belief, episodes, capabilities, routing, pulse, monitoring |

### 1.2 What is actually wired into the live runtime (`AscendantEngine`)

| System | Canonical implementation (wired) | Legacy/duplicate implementation (also live) |
|---|---|---|
| Event bus | `zerion/runtime/event_bus.py` `AsyncEventBus` — single instance shared by engine, cognitive runtime, UI adapter, voice | none (one bus) |
| State | `zerion/cognitive_os/state.py` `CognitiveState` + `StateStore` | `zerion/entity/state.py` `CognitiveEntityStateStore` (`entity_state.db`) — engine instantiates and snapshots it in the flywheel |
| Identity | `zerion/identity/persistence.py` `IdentityCore` ("ZERION-X ASCENDANT") | `zerion/entity/identity.py` `CognitiveEntityIdentity` ("ZERION-X SINGULARITY") — constructed inside `CognitiveEntityStateStore` |
| Goals | `zerion/cognitive_os/objective_manager.py` `ObjectiveContinuityManager` (one instance, shared engine ↔ runtime) | `zerion/identity/persistence.py` objectives (`LongTermObjective`), `zerion/missions/`, `zerion/cognitive_species/goal_field.py` `GoalField` |
| Memory | `zerion/cognitive_os/` episode / distilled / failure stores | `zerion/memory/` `DevelopmentalMemoryStore` (`memory.db`) |
| Evidence | `zerion/cognitive_os/evidence.py` `EvidenceStore` | `zerion/evidence/` `EvidenceEngine` (`evidence.db`); `zerion/runtime/evidence.py` is a shared *vocabulary* (not a store) |
| Providers | `zerion/cognitive_os/provider_interface.py` protocol + `provider_adapters.py` + `cognitive_router.py` | `zerion/model_providers/` legacy providers/routers — still used by `zerion/cognitive_species/cognitive_pulse.py:12,68` |
| Pulse / orchestrator | `zerion/cognitive_os/pulse.py` `CognitivePulse` | `zerion/cognitive_species/cognitive_pulse.py` `CognitiveSpeciesRuntime` (engine instantiates; `run_species_pulse`) |
| Genome | `zerion/cognitive_os/genome.py` `GenomeManager` | `zerion/cognitive_genome/` `GenomeManager` (22-dim genome, engine) |
| Evolution | `zerion/cognitive_os/self_modification_gate.py` `SelfModificationGate` | `zerion/evolution/self_modification.py` `ControlledSelfModificationEngine` + `AscensionEngine` (engine) |
| Permissions | `zerion/cognitive_os/experiment_engine.py` `ExperimentPermissions`, `zerion/cognitive_os/capability.py` `PermissionPolicy`, `SelfModificationGate` risk policy | `zerion/runtime/security.py` `SecurityBoundary` — **instantiated (engine.py:204) but `authorize()` is never called anywhere** |

### 1.3 One-line verdict

ZERION-X has one canonical Slice 1–8 core (state, bus, goals, evidence,
routing, pulse, gate) that is **real, typed, persisted, and honest**, wrapped by
a legacy `AscendantEngine` flywheel that still drives several parallel
implementations (entity state, species pulse, legacy memory/evidence/genome/
evolution) which are **alive in the runtime but not part of the canonical core**.

---

## 2. Canonical architecture

```
INTERFACES (protocols: CognitiveModelProvider, Event bus types, contracts)
    ↓
RUNTIME API (CommandAPI, CognitiveRuntime public methods, Pulse lifecycle)
    ↓
COGNITIVE KERNEL (CognitiveRuntime + CognitiveState + CognitivePulse +
                  SelfModificationGate + single AsyncEventBus)
    ↓
COGNITIVE SERVICES (goals, attention, questions, hypotheses, experiments,
                    evidence/belief, episodes, capabilities, routing, monitor)
    ↓
INFRASTRUCTURE (SQLite-WAL stores, resources, watchdog, scheduler,
                provider adapters, voice/UI adapters)
```

Dependency direction is enforced downward. The Kernel owns lifecycle, canonical
state, event sequencing, state transitions, policy enforcement, resource
governance, identity continuity, transaction boundaries and recovery
coordination. The Kernel does **not** own UI, provider SDKs, voice drivers,
individual tools, domain logic, or database-specific details.

**Forbidden mutation paths (enforced by invariant tests I002–I004):**
UI → direct state mutation · MODEL → direct state mutation · TOOL → direct
state mutation · VOICE → direct cognition mutation · PROVIDER → direct
cognition mutation. Every mutation passes through the runtime contract.

---

## 3. Kernel contract

**Owner:** `CognitiveRuntime` (`zerion/cognitive_os/cognitive_runtime.py`).

| Responsibility | Implementation | Verified by |
|---|---|---|
| Lifecycle | `start()` / `stop()` publish `RUNTIME_STARTED` / `RUNTIME_STOPPED`, persist state | I009, I018 |
| Canonical cognitive state | `CognitiveState` owned here; single `StateStore` | I007, I016 |
| Event sequencing | Consumes the single `AsyncEventBus`; per-type vocabulary `_COGNITIVE_EVENT_TYPES` | I008, I021 |
| State transitions | Runtime status machine `INITIALIZING → RUNNING → STOPPED`, `RECOVERING` on corruption | I016, I018 |
| Policy enforcement | `SelfModificationGate`, `ExperimentPermissions`, `PermissionPolicy`; proposals never auto-promote HIGH/CRITICAL | I010, I012, I015, I020 |
| Resource governance | Attention economy budgets, `ResourceBudgetView`, pulse budgets | — |
| Identity continuity | Provider switching never touches `state_id`, goals, or `IdentityCore` digest | I011, I023 |
| Transaction boundaries | SQLite-WAL single-write transactions + SHA-256 checksums everywhere | I009, I016 |
| Recovery coordination | Corruption → `RECOVERING`; pulse RUNNING work requeued on load; DEGRADED preserved | I016, I018, I019 |

---

## 4. Canonical state contract

**Exactly ONE authoritative cognitive state: `CognitiveState`**
(`zerion/cognitive_os/state.py`, schema version 1, `StateStore` with WAL +
SHA-256 checksum). Engine wires it into the runtime; nothing else owns it.

| Field | Owner | Writer | Persisted | Consistency |
|---|---|---|---|---|
| `runtime_status` | Kernel | Kernel lifecycle | yes | — |
| `perception` | Kernel (`ingest_perception`) | Kernel only | yes | last observation wins |
| `attention` | Kernel (from `AttentionEconomy`) | Kernel only | yes | DERIVED view of attention field |
| `goals` | Kernel (`count_goals()`) | Kernel only | yes | DERIVED view of goal store |
| `resources` | Kernel (budget) | Kernel only | yes | DERIVED view of budget |
| `current_focus` / `last_event` | Kernel | Kernel only | yes | DERIVED from bus/attention |
| `recovery_error`, `stale_events_discarded` | Kernel | Kernel only | yes | — |
| `state_id` | Kernel | Kernel only | yes | immutable per identity |

Rules:
- **Goal status canonical = `ObjectiveContinuityManager`** (one instance shared
  by engine and runtime). UI goal status (I007) is DERIVED; entity-state
  snapshot counts are DERIVED telemetry.
- **UI state (`zerion/ui/state_bridge.py`) is presentation state, explicitly
  NOT canonical.** The authoritative read path is `CognitiveRuntime.snapshot()`
  and `VisualizationStateAdapter` (I002).
- **No subsystem may create a competing source of truth.** The entity state
  store (`zerion/entity/state.py`) is currently a *competing* state machine —
  see §17 V2.
- Corrupted persisted state raises `StateIntegrityError` and the runtime enters
  `RECOVERING` with `recovery_error` set — never silently empty, never corrupt
  (I016).

---

## 5. Event contract

**Exactly ONE event bus: `AsyncEventBus` (`zerion/runtime/event_bus.py`).**
Verified by I021: engine, cognitive runtime, UI adapter and voice service all
share the same instance. No second bus exists in the live runtime.

Canonical `Event` schema (`zerion/runtime/events.py`): `event_id`,
`event_type`, `payload`, `correlation_id`, `timestamp`, `source`, `priority`,
`sequence`, `schema_version`.

| Property | Behavior | Evidence |
|---|---|---|
| Ordering | Monotonic `sequence` assigned on publish; persisted with the event | event_bus.py |
| Idempotency | Duplicate `event_id` rejected (`EventValidationError`) | I008 |
| Deduplication | Pulse-level fingerprint dedup window aggregates equivalent events; `_goal_candidates_seen` prevents goal re-event duplication | I017 |
| Replay | `replay_events()` from SQLite log (crash recovery / audit) | event_bus.py |
| Late events | `CognitiveRuntime._is_stale()` discards events older than window, counted in `stale_events_discarded` (never silently lost) | cognitive_runtime.py |
| Invalid events | Publish-time validation (type, payload dict, priority 0–100, duplicate id) raises | I008 |
| Corrupted events | Unknown `EventType` decodes to `OBSERVATION_RECORDED` fallback on replay; handler failures route to DLQ (`dispatch_errors`) | event_bus.py |

Categories covered by `EventType`: PERCEPTION, ATTENTION, GOAL, QUESTION,
HYPOTHESIS, EXPERIMENT, OBSERVATION, EVIDENCE, BELIEF, MEMORY (episode/
distill/failure), FAILURE, CAPABILITY, MODEL, VERIFICATION (routing),
EVOLUTION (gate/genome), SYSTEM, VOICE, RESOURCE.

---

## 6. Memory / evidence contract

**Separate: MEMORY · WORLD MODEL · EVIDENCE · BELIEF.** Never merged.

| Store | File | Mode/provenance | Belief influence |
|---|---|---|---|
| Episodic | `cognitive_os/episode.py` | — | — |
| Distilled (procedural) | `cognitive_os/distilled.py` | — | — |
| Failure | `cognitive_os/failure_learning.py` | — | — |
| Evidence | `cognitive_os/evidence.py` `EvidenceStore` | `OBSERVED` / `SIMULATED` / `TEST` / `MODEL_GENERATED` | `MODE_WEIGHT`: 1.0 / 0.2 / 0.4 / **0.0** |
| Belief | `cognitive_os/belief.py` `BeliefStore` | `BeliefLifecycle` + full `revision_history` | explicit revision rules |

**Critical rule (I001):** MODEL OUTPUT ≠ FACT. `MODEL_GENERATED` evidence is
recorded for provenance but **never applied** to belief (`MODE_WEIGHT = 0.0`);
belief revision records `applied=False` with reason. Only `OBSERVED` evidence
can reach `CONFIRMED`. Promotion path:
`UNTRUSTED CLAIM → HYPOTHESIS → PREDICTION → EXPERIMENT → OBSERVATION →
EVIDENCE → BELIEF UPDATE`.

**SIMULATED ≠ OBSERVED (I006):** `MeasurementStatus.SIMULATED` is distinct;
`SIMULATED` evidence carries weight 0.2 and can never confirm a belief; mode is
preserved through persistence.

Every important belief carries: statement, source, evidence, confidence,
prediction, observation, contradictions, `revision_history`, `created_at`,
`updated_at`, validity (status), freshness (updated_at).

---

## 7. State machine

### 7.1 Cognitive state machine (Kernel)

`INITIALIZING → RUNNING ⇄ STOPPED`; `ERROR/RECOVERING` entered from corruption
or store load failure; recovery is explicit and recorded (`STATE_RECOVERED`).
**Forbidden:** claiming RUNNING while `RECOVERING`; silently resuming from a
failed state.

### 7.2 Pulse lifecycle machine (`zerion/cognitive_os/pulse.py`)

`INITIALIZING → RUNNING ⇄ PAUSED`; `DEGRADED`; `STOPPED`. Persisted; restored
across restarts. **I019 (fixed this freeze):** a pulse restored from `DEGRADED`
stays `DEGRADED` (never silently resumed/declared healthy); `PAUSED` requires
explicit `resume()`.

### 7.3 Voice state machine (`zerion/voice/state_machine.py`)

Explicit `_TRANSITIONS` map; invalid transitions raise `InvalidVoiceTransition`
(I025). Distinguishes `INTERRUPTED` from `ERROR` from `IDLE`.

### 7.4 Terminal semantics

`CANCELLED / FAILED / INTERRUPTED / PAUSED / RECOVERING` are distinct:
- Proposal: `REJECTED` / `ROLLED_BACK` terminal (I024).
- Genome: `REJECTED` terminal, never promoted (I010).
- Work item: `FAILED` (with bounded retry policy) vs `DEFERRED` (offline/budget,
  requeued later — never fabricated) vs `CANCELLED`.

---

## 8. Permission model

**Capability-based, centralized at the gates** (not in the UI, not in tools):

| Gate | Grants | Default |
|---|---|---|
| `ExperimentPermissions` (experiment_engine.py:69) | `allow_code`, `allow_tools`, `allow_network` | all **False**; CODE_TEST / TOOL_EXECUTION / WEB_VERIFICATION blocked otherwise |
| `PermissionPolicy` (capability.py:265) | `READ/EXECUTE` least privilege; `FINANCIAL/SYSTEM_CONTROL/SELF_MODIFICATION` are `HIGH_RISK` | high-risk denied unless pre-approved |
| `SelfModificationGate` risk policy | LOW auto only when configured; MEDIUM explicit; HIGH/CRITICAL never auto | `allow_low_auto=True`, `allow_medium_auto=False` |

Pipeline: `MODEL INTENT → POLICY → PERMISSION → RISK → ACTION GATE →
EXECUTION`. The model never implicitly grants itself permission (I005).

**Finding:** `zerion/runtime/security.py` `SecurityBoundary` is instantiated in
the engine but `authorize()` has **zero call sites** — a permission layer that
exists but is not enforced (see §17 V8). Enforcement today is real only through
the three gates above and the `SecurityBoundary` unit behavior itself.

---

## 9. Provider contract

**Canonical interface: `CognitiveModelProvider`** (`cognitive_os/provider_interface.py`)
— a `Protocol` (`generate`, `stream`, `health_check`, `capabilities`,
`list_models`, `model_info`) with typed `ProviderCall` and `RawProviderResponse`.
The Kernel never imports provider SDKs; provider-specific code lives only in
`provider_adapters.py` (which wraps the legacy `zerion.model_providers`
implementations — reuse, not duplication).

**Result honesty (I014):** `RawProviderResponse` defaults `success=False`,
`output=None`; `usage`/`latency_ms`/`confidence` stay `None` (NOT_REPORTED)
when unmeasured; `GeminiAdapter` returns a structured `PROVIDER_UNAVAILABLE`
rather than its legacy canned fallback; `OFFLINE_ONLY` with no local model
returns `ROUTING_FAILED` with `output=None` — never fake model text.

**Routing:** deterministic `CognitiveRouter` (`cognitive_os/cognitive_router.py`):
`Task → ModelSelection → execute` with health ledger, capability matching,
explicit fallback chain, bounded attempts, and `emit()` events on the single
bus. `OFFLINE_ONLY` excludes non-local providers (I022).

**Provider switch preserves cognitive identity (I011):** swapping providers
never touches `CognitiveState.state_id`, goals, or the `IdentityCore` digest.

**Finding:** the legacy `zerion/model_providers/router.py` `CognitiveRouter`
(with its own D0–D6 depth ladder) is still used by
`cognitive_species/cognitive_pulse.py` — a second routing implementation in the
live runtime (see §17 V5).

---

## 10. Persistence contract

Everything that must survive restart is persisted with the SQLite-WAL +
SHA-256-checksum pattern: `CognitiveState`, goals, questions, hypotheses,
experiments, evidence, beliefs, episodes, distilled experiences, failures,
capabilities, performance ledger, proposals, genomes, snapshots, policies,
pulse store, monitor store, telemetry, events log, identity, world model,
memory, capabilities, missions, timeline.

| Guarantee | Implementation | Verified by |
|---|---|---|
| Atomic writes | single INSERT/REPLACE in one transaction | — |
| Versioning | `schema_version` on state; genome versions; policy versions | I016 |
| Schema migration | events log `sequence` column ALTER | event_bus.py |
| Corruption recovery | checksum mismatch → `StateIntegrityError` → `RECOVERING`, never silent | I016 |
| Rollback | snapshot-before-mutation + `rollback()` | I020 |
| Never silently lose state | strict-load stores raise; `load_errors` surfaced; recovery_error recorded | I016 |
| Persistence failure | `RECOVERING` state; never reports success on failed persist | I016 |

**Identity continuity (I023):** `IdentityCore` (identity hash, objectives,
contract) survives restart unchanged.

---

## 11. Evolution contract

**Canonical: `SelfModificationGate`** (`cognitive_os/self_modification_gate.py`).

Pipeline: `BOTTLENECK → EVIDENCE → IMPROVEMENT HYPOTHESIS → CANDIDATE →
SANDBOX → TEST → BENCHMARK → REGRESSION → POLICY CHECK → PROMOTION →
MONITORING`. Promotion is atomic (snapshot persisted **before** mutation),
LOW-only auto (config), MEDIUM requires explicit approval, HIGH/CRITICAL never
auto; code/architecture changes are approval-only (never applied to source).
Rollback restores the pre-change snapshot (I020).

Genome: `G0` never mutated in place; candidates are clones; `REJECTED` genomes
can never become current (I010).

**Outside normal autonomous evolution (immutable):** security policy,
permission model, audit system, benchmark integrity, rollback mechanism,
secret isolation, identity continuity, the self-modification gate itself
(I012: a proposal targeting the gate escalates to CRITICAL and cannot be
auto-approved).

---

## 12. Testing invariants (executable)

`tests/test_architectural_invariants.py` — 58 tests, all passing.

| ID | Contract | Enforced |
|---|---|---|
| I001 | MODEL_OUTPUT_CANNOT_BECOME_VERIFIED_FACT_WITHOUT_EVIDENCE | YES |
| I002 | UI_CANNOT_MUTATE_CANONICAL_STATE_DIRECTLY | YES |
| I003 | PROVIDER_CANNOT_MUTATE_COGNITIVE_STATE_DIRECTLY | YES |
| I004 | VOICE_CANNOT_BYPASS_POLICY | YES |
| I005 | TOOL_CANNOT_SELF_GRANT_PERMISSION | YES |
| I006 | SIMULATION_CANNOT_BE_STORED_AS_OBSERVED_FACT | YES |
| I007 | GOAL_STATE_HAS_ONE_CANONICAL_OWNER | YES |
| I008 | EVENTS_ARE_IDEMPOTENT | YES |
| I009 | CRITICAL_STATE_SURVIVES_RESTART | YES |
| I010 | FAILED_EVOLUTION_CANNOT_REPLACE_KNOWN_GOOD_VERSION | YES |
| I011 | MODEL_PROVIDER_SWITCH_PRESERVES_COGNITIVE_IDENTITY | YES |
| I012 | SELF_MODIFICATION_CANNOT_DISABLE_ITS_OWN_GATE | YES |
| I013 | FABRICATED_TELEMETRY_IS_REJECTED | YES |
| I014 | UNKNOWN_METRICS_ARE_NOT_REPORTED_AS_SUCCESS | YES |
| I015 | PERMISSION_ESCALATION_IS_REJECTED | YES |
| I016 | CORRUPTED_MEMORY_DOES_NOT_CORRUPT_CANONICAL_STATE | YES |
| I017 | DUPLICATE_EVENTS_DO_NOT_DUPLICATE_EFFECTS | YES |
| I018 | INTERRUPTED_OPERATIONS_CAN_RECOVER | YES |
| I019 | DEGRADED_MODE_DOES_NOT_FABRICATE_HEALTH | YES (code fixed this freeze) |
| I020 | ROLLBACK_RESTORES_KNOWN_GOOD_STATE | YES |
| I021 | SINGLE_EVENT_BUS (repo-discovered) | YES |
| I022 | OFFLINE_ONLY_NEVER_TOUCHES_CLOUD_PROVIDERS (repo-discovered) | YES |
| I023 | IDENTITY_IS_IMMUTABLE_ACROSS_RESTART (repo-discovered) | YES |
| I024 | PROPOSAL_LIFECYCLE_TRANSITIONS_ARE_ENFORCED (repo-discovered) | YES |
| I025 | VOICE_STATE_MACHINE_ENFORCES_TRANSITIONS (repo-discovered) | YES |

---

## 13. Architectural ownership table

| Resource | Canonical owner | Readers | Writers | Persisted? | Mutation method | Failure mode |
|---|---|---|---|---|---|---|
| identity | `IdentityCore` | Kernel, CLI | `IdentityCore` | yes (`identity.json`) | API | load fallback to defaults |
| goals | `ObjectiveContinuityManager` | Kernel, UI (derived) | Kernel (`create_goal`, …) | yes | runtime API | strict-load error → RECOVERING |
| beliefs | `BeliefStore` | Kernel, evidence pipeline | `BeliefRevision` only | yes | revision rules | strict-load error surfaced |
| world model | `WorldModel` (`zerion/world/`) | engine flywheel | engine trackers | yes | API | — |
| memory | `cognitive_os` episode/distilled/failure stores | Kernel | Kernel (episode/distill/failure paths) | yes | API | strict-load error surfaced |
| attention | `AttentionEconomy` | Kernel | Kernel (event-driven) | view only | via state view | budget cap |
| questions | `QuestionStore` | Kernel | `QuestionGenesis` | yes | API | — |
| hypotheses | `HypothesisStore` | Kernel | `HypothesisEngine` | yes | API | — |
| experiments | `ExperimentStore` | Kernel | `RealityExperimentEngine` (gated) | yes | approve/run API | BLOCKED without permissions |
| capabilities | `CapabilityRegistry` | Kernel, pulse | `CapabilityGenesis` (gated) | yes | genesis pipeline | policy-gated |
| self-model | `SelfModel` (`zerion/self_model/`) | engine, CLI | engine | yes | API | — |
| resources | `ResourceManager` | Kernel, engine | OS sampling | no (telemetry only) | sample() | sample failure → INSUFFICIENT_DATA |
| provider state | `ProviderHealthTracker` + `PerformanceLedger` | Kernel router | router outcomes | yes | record_success/failure | cold start = INSUFFICIENT_DATA |
| genome | `cognitive_os` `GenomeManager` | Kernel, gate | gate (candidate/promote/rollback) | yes | gate pipeline | promote requires evidence |
| evolution state | `ProposalStore` + `SnapshotStore` | Kernel, monitor | gate | yes | gate pipeline | rollback restores snapshot |
| permissions | gates (`ExperimentPermissions`, `PermissionPolicy`, gate risk) | Kernel | configuration (operator) | config | policy check | deny by default |
| events | single `AsyncEventBus` | all | any via publish (validated) | yes | publish | duplicate id rejected |
| telemetry | `ArchitectureTelemetry` | Kernel, monitor | Kernel components | yes | record() | < MIN_SAMPLES → None |

---

## 14. Dependency matrix (canonical core)

Component × Component (ALLOWED = A, FORBIDDEN = F, ADAPTER_ONLY = AO,
EVENT_ONLY = EO, READ_ONLY = RO).

| | Kernel | State | Bus | Evidence | Router | Pulse | Gate | UI | Voice |
|---|---|---|---|---|---|---|---|---|---|
| Kernel | — | A | A | A | A | A | A | RO (snapshot) | EO (events) |
| State | A | — | EO | — | — | RO | RO | RO | F |
| Bus | A | EO | — | EO | EO | A | EO | EO | EO |
| Evidence | A | F | EO | — | F | EO | RO | F | F |
| Router | A | F | EO | F | — | EO | F | F | F |
| Pulse | A | RO | A | EO | EO | — | EO | F | F |
| Gate | A | F | EO | RO | F | EO | — | F | F |
| UI | A (via CommandAPI) | F | EO | F | F | EO (commands) | F | — | EO (commands) |
| Voice | A (via runtime API) | F | EO | F | F | EO | F | EO | — |

Circularity check: no cycle exists in the canonical core (UI→Kernel→Bus→UI is
event-only; Voice→Kernel→Bus→Voice is event-only). **Violations:** legacy
flywheel and species runtime read/write systems outside this matrix (§17).

---

## 15. Trust boundary matrix

| Input | Trust level | Validation |
|---|---|---|
| user input | LOW-MEDIUM | CommandAPI schema validation, length caps |
| voice transcript | LOW | state machine validation; events only; never cognition mutation |
| LLM output | UNTRUSTED | `MODEL_GENERATED` evidence weight 0.0; never direct fact/tool execution |
| web result | UNTRUSTED | not currently consumed by canonical core |
| tool output | LOW | sandbox gates; `ExperimentPermissions` (code/tools/network off by default) |
| filesystem content | UNTRUSTED | GGUF discovery: magic validation + `_is_within` path containment |
| plugin output | UNTRUSTED | capability sandbox inspection (AST-based) |
| sensor output | LOW | resource sampler; sample failure → INSUFFICIENT_DATA |
| events | MEDIUM (validated) | publish-time validation + idempotency + staleness |

All external data is untrusted until validated; `OBSERVED` status is only
assigned by system/tool/real-world sources with provenance.

---

## 16. Failure matrix

| Failure | Detection | Degraded mode | Recovery | Data preservation | Escalation |
|---|---|---|---|---|---|
| model unavailable | health tracker, structured provider failure | route fallback / DEFER | next pulse pass / mode change | ledger records failure | REPEATED_FAILURE_DETECTED |
| voice unavailable | mic/VAD/STT honest statuses | UI shows real mic state | watchdog restart with backoff | events logged | VOICE_ERROR |
| network unavailable | OFFLINE_ONLY enforcement | offline mode, DEFER | provider/offline-mode change | nothing fabricated | — |
| memory/store corruption | SHA-256 checksum | `RECOVERING` state | fresh state + recovery_error | corrupt row isolated | STATE_RECOVERED event |
| disk full | persist exception | not persisted → no success claim | operator | prior persisted state | RECOVERING |
| RAM exhausted | resource sampling + budget floors | DEFER expensive work | next pass | budget accounting | resource warnings |
| tool failure | sandbox violation/exception | BLOCKED (permissions) | explicit approval | failure recorded | FAILURE_ANALYSIS |
| corrupted event | bus validation | DLQ + `dispatch_errors` | replay from log | event log | — |
| corrupted memory | strict-load raise | RECOVERING / load_errors | reload or fresh | checksum mismatch surfaced | — |
| provider timeout | `asyncio.wait_for` | failover within budget | next attempt bounded | health record | PROVIDER_FAILED |
| experiment failure | lifecycle status | BLOCKED/FAILED | new proposal | failure store | FAILURE_ANALYSIS |
| evolution failure | benchmark verdict | REJECTED (no promote) | new candidate | snapshot retained | — |
| UI failure | adapter exception isolation | UI state ERROR | reattach | state untouched | — |
| Pulse failure | work crash handling | DEGRADED persisted | explicit recovery (no silent resume) | work requeued | REPEATED_FAILURE_DETECTED |

---

## 17. Repository violations (evidence-backed)

### V1 — Two identity implementations, both live
- **Files:** `zerion/identity/persistence.py:22-23` ("ZERION-X ASCENDANT",
  `ascendant-core-v1`) vs `zerion/entity/identity.py:11-16` ("ZERION-X
  SINGULARITY", `zerion-singularity-core-v1`).
- **Lines:** engine.py:118,211,540 (entity store live), engine.py:210 (identity live).
- **Severity:** HIGH — two self-names and two identity digests in one runtime.
- **Root cause:** incremental generations imported side by side.
- **Fix:** `zerion/entity/identity.py` deprecated; `CognitiveEntityIdentity`
  replaced by `IdentityCore`. Entity snapshots become DERIVED telemetry of the
  canonical state.
- **Migration risk:** low (engine passes real values already); tests
  `test_singularity_entity.py` must be migrated.

### V2 — Two state systems, both live
- **Files:** `zerion/cognitive_os/state.py` (canonical) vs
  `zerion/entity/state.py` `EntityLifecycleState` (STANDBY/BOOTING/…/RECOVERING)
  + `CognitiveEntityStateStore` (`entity_state.db`).
- **Lines:** engine.py:118,211; engine.py:540 (flywheel snapshot).
- **Severity:** HIGH — competing state machine with **no enforced transitions**
  (`transition_state` is a bare setter).
- **Fix:** ISOLATE — flywheel snapshot writes move to the canonical state's
  derived telemetry; entity store deprecated.
- **Migration risk:** low; snapshot data is telemetry, not authority.

### V3 — Two pulse/orchestrators, both live
- **Files:** `zerion/cognitive_os/pulse.py` (canonical) vs
  `zerion/cognitive_species/cognitive_pulse.py` `CognitiveSpeciesRuntime`.
- **Lines:** engine.py:122,297,630-633.
- **Severity:** MEDIUM — second orchestrator with its own pulse loop, own
  `GoalField` (`goal_field.db`), and legacy router.
- **Fix:** DEPRECATE `CognitiveSpeciesRuntime`; `run_species_pulse` routes
  through `CognitivePulse` or is removed.
- **Migration risk:** medium — species cycle traces are used by CLI/tests.

### V4 — Two memory systems, both live
- **Files:** `zerion/memory/` `DevelopmentalMemoryStore` (engine.py:258) vs
  `cognitive_os` episode/distilled/failure stores.
- **Severity:** MEDIUM — episodic experience stored in two schemas.
- **Fix:** engine flywheel writes episodes through the canonical episode store
  (adapter), then legacy `zerion/memory/` deprecated.
- **Migration risk:** low-medium (both SQLite; data migration one-time).

### V5 — Two router/provider implementations, both live
- **Files:** `zerion/cognitive_os/cognitive_router.py` (canonical) vs
  `zerion/model_providers/router.py` (legacy D0–D6), used by
  `zerion/cognitive_species/cognitive_pulse.py:12,68`. engine.py:123 imports
  the legacy router but never instantiates it (dead import).
- **Severity:** MEDIUM.
- **Fix:** species runtime adopts the canonical router; remove engine.py:123.
- **Migration risk:** low.

### V6 — Two evidence systems, both live
- **Files:** `zerion/cognitive_os/evidence.py` (canonical, mode-weighted) vs
  `zerion/evidence/` `EvidenceEngine` (engine.py:76-77,261, flywheel writes).
- **Severity:** MEDIUM — two evidence ledgers with different schemas.
- **Fix:** flywheel `EvidenceItem` writes go through the canonical
  `EvidenceStore`; `zerion/evidence/` deprecated (its verifier concepts fold
  into `cognitive_os/evidence.py`).
- **Migration risk:** medium — engine flywheel + experiments + benchmarks read
  legacy evidence.

### V7 — Two genome managers, both live; two evolution systems, both live
- **Files:** `zerion/cognitive_genome/` (engine.py:52) vs
  `zerion/cognitive_os/genome.py`; `zerion/evolution/self_modification.py`
  (engine.py:96,270-274, via `AscensionEngine`) vs
  `zerion/cognitive_os/self_modification_gate.py`.
- **Severity:** MEDIUM.
- **Fix:** the gate is canonical; `AscensionEngine` reuses gate evidence
  pipelines or is deprecated. Genome unification after memory/evidence
  migration.
- **Migration risk:** high for genome (22-dim phenotype coupling) — KEEP with
  ADAPT, isolate from canonical policy genome.

### V8 — Permission boundary exists but is not wired
- **Files:** `zerion/runtime/security.py`; engine.py:204 instantiates
  `SecurityBoundary`; `authorize()` has **zero call sites**; `PermissionLevel`
  import (engine.py:18) unused.
- **Severity:** HIGH — the canonical gates enforce permissions, but the runtime
  boundary itself is dead.
- **Fix:** wire `SecurityBoundary.authorize` into the tool/command execution
  path (or remove it and document the gates as the boundary).
- **Migration risk:** low.

### V9 — Hard-coded metric defaults in entity snapshots
- **File:** `zerion/entity/state.py:62-79` — `capture_snapshot` defaults
  `brier_score=0.02`, `learning_acceleration=2.57`,
  `maturity_level="L7_COGNITIVE_GENERATIVE"`.
- **Severity:** MEDIUM — engine overrides with real values today, but the
  defaults fabricate numbers if called bare.
- **Fix:** remove fabricated defaults (require explicit values); part of V2.

### V10 — Legacy flywheel bypasses the canonical loop
- **File:** `zerion/engine.py` `run_developmental_cycle()` — drives world/
  pressure/questions/evidence/memory/genome directly, outside the canonical
  bus/pulse.
- **Severity:** MEDIUM — it is still the `--cycles` path users run.
- **Fix:** re-route flywheel evidence/memory writes through canonical stores
  (V4/V6); the flywheel becomes an outer loop that *feeds* the canonical core.
- **Migration risk:** medium.

### V11 — Stale documentation vs runtime
- **File:** `zerion/cognitive_os/provider_adapters.py:1-16` docstring still
  claims local GGUF execution is "UNAVAILABLE" although `LocalGGUFProvider`
  now has real llama.cpp backends.
- **Severity:** LOW.
- **Fix:** update docstring.

### V12 — Dead/unused imports in the engine
- **Lines:** engine.py:18 (`PermissionLevel`), engine.py:123 (legacy
  `CognitiveRouter`).
- **Severity:** LOW. Fix: remove.

### Anti-pattern sweep results
- Duplicate engines: V3, V10. Duplicate event buses: **none** (I021).
- Duplicate memory: V4. Duplicate goal managers: V3 (`GoalField`), objectives
  in identity, missions — 3 extra stores vs canonical 1.
- Global mutable state: `CognitiveState` is the only canonical one (V2 entity
  store excluded).
- Provider-specific cognition: none (adapters isolate SDKs; I003).
- Model output directly executing tools / creating facts: **none** (I001,
  I005, gates).
- Fake readiness/telemetry: V9 (defaults), otherwise honest (I013/I014/I019).
- Silent fallbacks: `DeterministicFallbackProvider` is labeled `is_fallback`
  (execution_mode FALLBACK_RESPONSE) — acceptable; legacy Gemini canned text
  now suppressed by the adapter (I014).
- Unbounded retries/queues: bounded (pulse retry policy, max queue 500).
- Self-modification without snapshots/regression: none (gate requires both).
- Cross-layer imports: none in canonical core (I002/I003/I004).

---

## 18. Migration plan

Priority order (do not rewrite; classify and migrate):

1. **Canonical kernel** — KEEP (already canonical): `CognitiveRuntime`,
   `CognitiveState`, single `AsyncEventBus`, `CognitivePulse`,
   `SelfModificationGate`.
2. **Canonical state** — KEEP; migrate V2 (entity store → derived telemetry).
3. **Canonical event bus** — KEEP; no second bus allowed (I021).
4. **Epistemic/evidence model** — KEEP `cognitive_os/evidence.py`; migrate V6.
5. **Permission boundary** — wire V8 or document gates as the boundary.
6. **Provider abstraction** — KEEP canonical router; remove legacy router usage
   (V5) and dead import.
7. **Persistence** — KEEP checksum-WAL pattern everywhere; unify stores after
   migrations.
8. **Evolution gate** — KEEP; reconcile `AscensionEngine` (V7).
9. **Invariant tests** — KEEP and extend (this freeze adds 25).

Per-subsystem classification:
| Subsystem | Class |
|---|---|
| `cognitive_os/*` (state, goals, attention, questions, evidence, belief, episodes, capabilities, router, pulse, gate, monitor, genome, snapshots, telemetry) | KEEP |
| `runtime/*` (bus, events, resources, scheduler, watchdog, security) | KEEP (wire security) |
| `identity/persistence.py` (IdentityCore, objectives, contract) | KEEP |
| `ui/*` (commands, adapter, server, state_bridge) | KEEP (bridge = presentation) |
| `voice/*` | KEEP |
| `entity/*` | DEPRECATE (V2) |
| `cognitive_species/*` | DEPRECATE (V3) |
| `model_providers/*` | ADAPT (providers reused behind adapters; router deprecated) |
| `zerion/evidence/*`, `zerion/memory/*` | ADAPT → DEPRECATE after migration (V4, V6) |
| `cognitive_genome/*`, `evolution/*` | ADAPT → ISOLATE (V7) |
| `missions/*`, `pressure/*`, `questions/*`, `world/*`, `self_model/*`, `cognition/*`, `experiments/*`, `capabilities/*`, `learning/*`, `benchmarks/*`, `telemetry/*` (legacy engine subsystems) | ADAPT (used by flywheel; must feed canonical stores) |
| Docs `GENESIS_*/ASCENDANT_*/OMEGA_*/SINGULARITY_*` + zips | REMOVE or archive (historical material) |

---

## 19. Immutable boundaries

The following may never be modified by autonomous evolution, the model, tools,
or the UI (I012, I005, I015):

1. Security policy & permission model
2. Audit system (event log integrity, DLQ)
3. Benchmark integrity (`AntiGamingDetector`, evaluator isolation)
4. Rollback mechanism (`SnapshotStore` before-mutation rule)
5. Secret isolation (env-only keys, never logged)
6. Identity continuity (`IdentityCore` digest)
7. The self-modification gate itself
8. The single event bus (no second bus)
9. The canonical state ownership (no competing source of truth)

---

## 20. Architectural freeze criteria

| Criterion | Status |
|---|---|
| 10 contracts exist | ✅ (this document, sections 3–12) |
| Canonical ownership defined | ✅ §13 |
| Forbidden dependencies removed or isolated | ⚠️ canonical core clean; legacy duplicates isolated but NOT yet removed (V1–V10) |
| State transitions enforced | ⚠️ canonical + voice enforced; `EntityLifecycleState` (V2) unenforced |
| Permissions enforced | ⚠️ gates enforced (I005/I012/I015); `SecurityBoundary` unwired (V8) |
| Provider abstraction real | ✅ I003/I011/I014 |
| Persistence verified | ✅ I009/I016/I023 |
| Evolution rollback verified | ✅ I010/I020 |
| Invariant tests exist and pass | ✅ 25 invariants / 58 tests, all passing |
| No critical architectural contradiction remains | ⚠️ duplicate identities (V1) and unwired security boundary (V8) remain |

---

## Deliverable accounting

**Files modified (this freeze):**
- `zerion/cognitive_os/pulse.py` — 1-line structural fix: a pulse restored
  from `DEGRADED` stays `DEGRADED` (never silently resumed). Required to make
  invariant I019 true and to honor the code's own documented contract.

**Files added:**
- `tests/test_architectural_invariants.py` — 58 executable invariant tests
  (I001–I025).
- `ZERION_X_ARCHITECTURAL_FREEZE.md` — this document.

**Files deprecated (declared, not yet deleted — migration plan §18):**
- `zerion/entity/` (V2), `zerion/cognitive_species/` (V3),
  `zerion/model_providers/router.py` (V5), `zerion/evidence/` (V6),
  `zerion/memory/` (V4), legacy `zerion/cognitive_genome/` + `zerion/evolution/`
  (V7) — these remain in the tree during migration; they are **not** part of
  the canonical architecture.

**Files removed:** none (no evidence-based justification to delete yet).

**Tests added:** 58 (invariants). **Tests executed:** 762.
**Tests passed:** 762. **Tests failed:** 0. **Skipped:** 2.

---

## ARCHITECTURE STATUS

```
[ ] NOT READY
[X] STRUCTURALLY SOUND WITH REQUIRED FIXES
[ ] FROZEN
```

**NOT FROZEN.** The canonical core (state, bus, evidence/belief, routing,
pulse, gate, persistence) is real, enforced, and invariant-tested — but the
following remain before the architecture may be marked FROZEN:

1. **V1 (HIGH):** two live identity implementations with conflicting
   self-names — resolve to one canonical identity.
2. **V8 (HIGH):** `SecurityBoundary` exists but `authorize()` is never called —
   wire it into the action path or formally replace it with the gates.
3. **V2 (MEDIUM):** entity state machine has no enforced transitions — migrate
   to derived telemetry.
4. **V3–V7, V10 (MEDIUM):** legacy duplicates (species pulse, legacy
   memory/evidence/genome/evolution, flywheel writes) remain live in the
   runtime — isolate/deprecate per §18.
5. **V9 (MEDIUM):** fabricated metric defaults in `entity/state.py` — remove.

When (1)–(5) are closed and the invariant suite still passes with 0 failures,
re-run this gate and mark FROZEN.

---

*No marketing claims. No AGI claims. No fabricated metrics. All statuses above
are measured from the repository at this commit and from the executed test
suite (762 tests, 0 failures).*
