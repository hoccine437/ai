# ZERION — PARADIGM-X · STAGE 0
## REPOSITORY TRUTH (forensics, not design)

**Date:** 2026-08-13
**Method:** static import-graph scan of all 228 `zerion/` modules, wiring map of
the two runtime hubs, live CLI/engine verification, and the 667-test regression
suite as the breakage oracle.
**Rule honored:** nothing was deleted. Every verdict below is KEEP / MERGE /
REDIRECT / STAGE-DELETE with the evidence that justifies it.

---

## 1. What the repository actually is

One Python package (`zerion/`, 228 modules), 668 test methods, one real event
bus, and **two runtime hubs** plus a small third cycle engine:

| Hub | Module | What it is | Verdict |
|---|---|---|---|
| **Hub A — AscendantEngine** | `zerion/engine.py` | The "25-stage flywheel": world model, pressure field, question genesis 3.0, cognitive genesis, meta-prediction, evolution/ascension, `zerion/memory/`, `zerion/evidence/`, `zerion/capabilities/`, `zerion/benchmarks/`, daemon, voice, UI bridge | **LEGACY — keep as orchestrator for now, redirect its subsystem calls to Hub B over Stages 1–7** |
| **Hub B — CognitiveRuntime** | `zerion/cognitive_os/cognitive_runtime.py` | The Slice 1–8 canonical event-driven runtime: Goal Field, Attention Economy, Question Field, Hypothesis Engine, Belief Field, Experiment/Evidence, Experience→Capability, CognitiveRouter, SelfModificationGate, CognitivePulse, Monitor | **CANONICAL — this is the "One CognitiveRuntime" of the directive** |
| **Hub C — CognitiveSpeciesRuntime** | `zerion/cognitive_species/cognitive_pulse.py` | Own mini goal field + hypothesis engine + pulse, started only via `engine.run_species_pulse()` | **REDIRECT/ABSORB — duplicate goal/hypothesis/pulse machinery; tests pin it (`test_cognitive_species.py`), so absorb its real behaviors, then alias, then delete last** |

The directive's §32 target — "One CognitiveRuntime. One EventBus. One GoalField.
One AttentionField. One Memory. One CapabilityRegistry. One Model abstraction.
One Voice abstraction. One UI boundary" — is **partially true already** and the
remaining gaps are enumerated below.

### Already single (no duplication found)

- **EventBus** — `zerion/runtime/event_bus.py`. Both hubs share the same bus
  (`engine.event_bus` is passed into `CognitiveRuntime`). One bus. ✔
- **Attention** — `zerion/cognitive_os/attention.py` (`AttentionEconomy`); no
  legacy duplicate anywhere. ✔
- **Model providers** — `zerion/model_providers/` is the canonical provider
  layer; `cognitive_os/provider_adapters.py` wraps it (`LegacyOpenAIAdapter`,
  `LegacyGeminiAdapter`, `LegacyGGUFAdapter`) for the router. Already merged. ✔
  (The `Legacy*` names should be dropped to `OpenAIAdapter` etc. — cosmetic.)
- **Voice** — `zerion/voice/`, single implementation, engine-scoped. ✔
- **UI boundary** — `zerion/ui/` (Python server + `index.html` + adapter) is the
  only wired UI; `ui/*.kt` is a design contract folder, never imported. ✔
- **Identity/invariants** — `zerion/identity/`, single. ✔

### Duplicated families (the §31 inventory)

| Family | Canonical (Hub B) | Legacy/parallel | Verdict |
|---|---|---|---|
| Goals | `cognitive_os/objective_manager.py` (`ObjectiveContinuityManager`) | `identity/objectives.py` (engine), `cognitive_species/goal_field.py` | MERGE → B; `identity` keeps objectives for INV-004 durability |
| Questions | `cognitive_os/question*.py` (Store + Genesis) | `questions/` (graph/genesis/scorer, engine flywheel) | MERGE → B over Stage 3 |
| Hypotheses | `cognitive_os/hypothesis*.py` | `world/causal.py` (causal hyps — keep, different role), `cognitive_species/hypothesis_engine.py` | MERGE species → B |
| Evidence | `cognitive_os/evidence.py` (Belief-field evidence) | `evidence/` (claim/engine/verifier, engine), `runtime/evidence.py` (reporting provenance) | THREE different roles — KEEP all, document boundary; do not merge blindly |
| Memory | `cognitive_os/` episode/distilled/failure stores (epistemic-tagged) | `memory/` (7-domain store + distillation, engine flywheel) | MERGE → B over Stage 6; `memory/` keeps procedural distillation for the flywheel until B covers it |
| Capabilities | `cognitive_os/capability*.py` (genesis+registry+sandbox) | `capabilities/` (detector/birth/registry) | MERGE → B over Stage 6 |
| Genome | `cognitive_os/genome.py` (versioned, self-modification) | `cognitive_genome/` (22-dim genome + phenotypes, engine) | MERGE → B over Stage 12 |
| Evolution/self-mod | `cognitive_os/self_modification_gate.py` + `improvement.py` | `evolution/` (ascension/plasticity/self_modification) | MERGE → B over Stage 12 |
| Pulse | `cognitive_os/pulse.py` (event-driven, budget-aware) | `cognitive_species/cognitive_pulse.py` | MERGE → B |
| Benchmarks | `cognitive_os/benchmark/` (Slice 9 BASELINE vs ZERION — the directive's judge) | `benchmarks/` (14-category + scoreboard + integrity) | **KEEP BOTH** — different jobs; one line of the report will say why |
| Meta-prediction/learning-to-learn | — | `meta_prediction/`, `learning_to_learn/` (engine) | KEEP (no B counterpart) |

### Module-level liveness (import-graph evidence)

- 228 modules scanned; **no dead modules at package level** — every module is
  imported by another `zerion/` module or is an `__init__`/entry (`cli.py`,
  `setup.py`). Only 3 are imported exclusively by tests:
  `benchmarks.adversarial_evaluator`, `experiments.developmental_ab_test`,
  `experiments.long_horizon_100` (all wired to their tests, so still KEEP).
- The "generations" (GENESIS / ASCENDANT / INFINITY / X10 / OMEGA / Ω) exist as
  **documentation markdown only** — there are no code snapshots to delete, and
  the historical reports are preserved as-is. Consolidation is about the two
  live hubs above, not about removing generations.

---

## 2. Hard-coded claims / fake telemetry found in wired code (fixed this stage)

| # | Finding | Location | Fix |
|---|---|---|---|
| 1 | `os.environ` used with no `import os` — a **latent NameError** every time a `.env` file exists in cwd/package-root/home | `engine.py` `__init__` inline loader | Extracted `load_dotenv_files(environ=None, extra_dirs=None)`; added `import os`; loader is injectable + never overrides existing env. Pinned by `TestDotEnvLoader` |
| 2 | `ask_ultimate_questions()` answer_4 fabricated **"Yes. Verified via in-memory sandbox and invariant checks."** even when no capability was born | `engine.py` | Reports real state: BORN (name + benchmark score) / NOT BORN (reason) / NOT REQUIRED; adds `capability_born` + `capability_name` fields. Pinned by `test_ultimate_answer4_reports_real_born_state` |
| 3 | `answer_hierarchy_level(4)` hard-coded `distributed_consensus_quorum_strategy` as the missing strategy regardless of registry | `engine.py` | Gap computed from the real registry against a canonical domain list; returns `domains_covered` + `missing_reason`. Pinned by level-4 tests |
| 4 | `answer_hierarchy_level(1)` used zero-arg `maturity_evaluator.evaluate()` → **always reported L7** (the bug class fixed repo-wide in the correction phase, missed here) | `engine.py` | Uses `evaluate_from_evidence(collect_runtime_evidence(self))`; cold start now reports `L0_STATIC`. Pinned by `test_level1_maturity_uses_real_evidence` |
| 5 | `GenesisCycleTrace.perceptions_ingested` hard-coded to `2` | `engine.py` | Real counter incremented at each perception call (runtime ingest + world observations). Pinned by `test_cycle_perception_telemetry_is_measured` |

Fixes verified live (cold engine, real CLI):
```
L1 maturity: L0_STATIC | evidence score: 0.375
L4 missing:  general_cognition_strategy (no registered strategy for domain 'general_cognition') | covered: 3
A4:          No new capability was required ... capability_born: False | name: None
cycle:       perceptions_ingested: 3
```

### Known remaining fabrication risk (documented, not fixed this stage)

- The **historical generation reports** (`GENESIS_X10_FINAL_REPORT.md`,
  `ASCENDANT_DEVELOPMENT_CURVE.md`, etc.) contain benchmark tables (e.g.
  "96.4% / 2.62×", "97.0% prediction accuracy"). These are prior-generation
  documents, not live code — they must be treated as **unverified claims** until
  re-measured by the Slice 9 cognitive benchmark (which already refuses to
  hard-code conclusions). The 500%-question (§28) is already enforced there.
- `run_developmental_cycle()` still executes many engine-family steps with
  synthetic inputs (fixed `uncertainty=0.6`, `difficulty=0.5` etc.). Honest
  (they are explicit parameters, not presented as measurements), but Stage 1
  work should drive them from real runtime telemetry.

---

## 3. Consolidation plan (vertical stages, no generation #8)

The directive's stage ladder maps to concrete repo actions. Each stage = code +
tests + evidence; **no stage advances while the previous one is red.**

| Stage | Directive | Concrete action | Safe-now? |
|---|---|---|---|
| 0 | Repository truth | This report + 7 honesty regression tests (667 → 674) | ✅ done this turn |
| 1 | Cognitive state | Make Hub A's flywheel read/write Hub B's `CognitiveState` as the single state source; engine state fields become views | Next |
| 2 | Problem discovery + attention | Route engine pressure signals into Hub B's Attention Economy as real candidates (already shares the bus) | Next |
| 3 | Question genesis | Merge `questions/` into `cognitive_os/` question field; keep `questions/` API as adapter until flywheel redirected | Next |
| 4 | Hypothesis + experiment | Absorb `cognitive_species/hypothesis_engine.py`; alias `world/causal.py` (different role, stays) | Next |
| 5 | Belief + causal learning | Wire engine evidence/experiment results into Hub B belief field with provenance | Next |
| 6 | Experience → capability | Redirect `memory/` + `capabilities/` calls to Hub B stores; keep procedural distillation as a Hub B module | Next |
| 7 | Model substrate + routing | Drop `Legacy*` names; make `model_providers/` the single provider layer the router consumes (already true structurally) | Next |
| 8 | Persistent CognitivePulse | Engine daemon calls `cognitive_os.cognitive_pulse` as the single pulse; retire `cognitive_species.cognitive_pulse` after behavior absorption | Next |
| 9 | Benchmark | Keep `cognitive_os/benchmark/` (BASELINE vs ZERION) as the judge; run it and report the measured ratio, whatever it is | Next |
| 10 | Voice + UI | Already unified (Slice 10/10.1) | ✅ |
| 11 | Self-observation | Route engine telemetry into Hub B `ArchitectureTelemetry`/`BottleneckDetector` (exists) | Next |
| 12 | Controlled cognitive evolution | Merge `cognitive_genome/` + `evolution/` into Hub B genome + self-modification gate | Last |

**Explicitly NOT deleting (with reasons):** `zerion/benchmarks/` (different role:
14-category developmental scoreboard vs the cognitive benchmark judge),
`zerion/runtime/evidence.py` (reporting provenance layer, imported by CLI/UI/
providers/scoreboard), the generation markdown reports (historical record).

---

## 4. Evidence (this stage)

| Command (from `ai-arena-019ff051-ai/`) | Result |
|---|---|
| `python3 -m unittest tests.test_paradigm_x_forensics -v` | **7 tests — OK** |
| `python3 -m unittest discover -s tests -p "test_*.py"` | **674 tests — OK** (667 baseline + 7 new; see below) |

Files changed this stage: `zerion/engine.py` (5 fixes), `tests/test_paradigm_x_forensics.py` (new),
`ZERION_PARADIGM_X_FORENSICS.md` (this report).

## 5. Final note

The five questions (Q1–Q5) are already *architecturally present* in Hub B
(problem discovery → attention → questions → hypotheses → experiments → belief
revision → experience → capability, all on one bus, provider-independent). What
Stage 0 established is that the repository truth matches that claim at the code
level and that the remaining work is **de-duplication of the legacy hub into the
canonical one**, not a rewrite. The benchmark decides whether it works.
