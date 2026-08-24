# ZERION_RUNTIME_OWNERSHIP.md

Scope: identifies, with evidence, which implementation is authoritative for each
major subsystem in the current merged `zerion/` package, and flags genuine
duplication/disconnection found during the correction phase. No deletions were
made based on this map — per instruction, legacy code is preserved unless proven
unreachable and safe to remove, and even then only in a later phase.

---

## Model / Cognition Execution

| | |
|---|---|
| Authoritative implementation | `zerion.model_providers.router.CognitiveRouter` |
| Entrypoint | Instantiated once at `AscendantEngine.__init__` (not directly observed in this pass — confirm exact line before further work) |
| Consumers | Any subsystem needing model output routes through `CognitiveRouter.route_and_execute()` |
| Legacy implementations | None found — this is the only provider abstraction |
| Reason | Single, coherent abstraction over OpenAI/Gemini/local-GGUF/deterministic providers; correctly the sole path |
| Correction-phase change | All four providers now report `execution_mode` honestly (see ZERION_CORRECTION_REPORT.md) |

## Memory — GENUINE DUPLICATION FOUND

| | |
|---|---|
| Authoritative implementation | `zerion.memory.developmental_store.DevelopmentalMemoryStore`, held as `engine.memory` |
| Entrypoint | `engine.memory._episodes`, `engine.memory._procedural_rules` — read by `--status`, `--memory`, `RuntimeEvidence`, maturity, scoreboard |
| Secondary/parallel implementation | `zerion.intelligence_forge.cognitive_episode.store` (an `EpisodeStore`), held as `engine.foundry.episode_store` |
| Consumers | `engine.memory` is read by every reporting path fixed in this phase. `engine.foundry.episode_store` is read separately by `ui/server.py`'s `/api/episodes` endpoint (`self.engine.foundry.episode_store.list_episodes()`) |
| Conflict evidence | Directly confirmed by instantiation: `engine.memory = DevelopmentalMemoryStore(...)` (line ~220) and `engine.foundry = IntelligenceFoundry(...)` (line ~246) are two separate objects with two separate SQLite-backed episode collections. Both are written to during `run_developmental_cycle()` (via `self.foundry.execute_foundry_cycle(...)` and direct `self.memory` writes), and in a single-process test they stayed in sync (1 episode each after one cycle) — but nothing in the code guarantees they can't diverge, since they are two independently-owned stores with no cross-reference. |
| Recommendation | Not resolved in this phase, per instruction to avoid consolidation without dependency evidence. Flagged as the clearest concrete duplication risk for the next phase: either make `engine.foundry.episode_store` a view over `engine.memory`, or make `/api/episodes` read `engine.memory` directly. |

## Orchestration — Three parallel "cycle" abstractions, not fully unified

| | |
|---|---|
| Authoritative top-level entrypoint | `AscendantEngine.run_developmental_cycle()` — this IS called by every user-facing path (`--cycle`, `--cycles N`) |
| Sub-orchestrators invoked inside it | `engine.foundry.execute_foundry_cycle(...)` and `engine.organism.execute_organism_cycle(...)` — both confirmed called from within `run_developmental_cycle()` |
| Disconnected sibling | `engine.species_runtime` (`CognitiveSpeciesRuntime`) — has its own `execute_pulse_cycle()`, wrapped by `AscendantEngine.run_species_pulse()`. **Confirmed via grep: no CLI flag and no UI endpoint calls `run_species_pulse()` or references `species_runtime` at all.** It is real, connected to live engine state (reads `self.resources.sample()`), fully implemented, and completely unreachable by any user path. Classified `IMPLEMENTED_BUT_DISCONNECTED`. |
| Also disconnected | `AscendantEngine.ask_ultimate_questions()` — same situation: implemented, not called from any CLI flag or UI endpoint found by search. |
| Recommendation | Either wire a `--species-pulse` CLI flag (cheap, honest fix) or explicitly document these as not-yet-exposed rather than leave them silently unreachable. Not done in this phase — flagged for next step. |

## Evolution / Self-Modification

| | |
|---|---|
| Authoritative implementation | `zerion.evolution.self_modification.ControlledSelfModificationEngine` (gate) + `zerion.evolution.plasticity.CognitivePlasticityManager` (versioned config state) |
| Entrypoint | `engine.self_mod`, `engine.plasticity` |
| Consumers | Tested directly by `tests/test_evolution.py` and the new `tests/test_correction_phase_regressions.py::TestSelfModificationBypassResistance` |
| Legacy implementations | None found |
| Correction-phase change | Static analysis stage rewritten from a bypassable blocklist to an allowlist (see ZERION_CORRECTION_REPORT.md). **Important scope note preserved from the fix itself:** `ControlledSelfModificationEngine` never applies a proposal to live system state before evaluating it — it only runs code in an ephemeral sandbox subprocess. `ModificationResult.rolled_back` therefore means "rejected", not "a live change was reverted." The only component in the codebase that performs a genuine apply-then-revert on real state is `CognitivePlasticityManager.rollback_to_previous()`, which is tested and confirmed real. |
| Sandbox isolation | `zerion.experiments.sandbox.ExecutionSandbox` is a plain OS subprocess with the same permissions as the host process — no container, seccomp, or VM isolation. The allowlist in stage 2 is therefore the actual safety boundary today, not the sandbox. This is stated explicitly in the module docstring rather than left implicit. |

## Health / Monitoring

| | |
|---|---|
| Authoritative implementation | `zerion.runtime.watchdog.Watchdog` (`engine.watchdog`) |
| Status | Not exercised in this correction pass beyond confirming a single instance is constructed once in `AscendantEngine.__init__`. No duplicate `Watchdog` construction found via grep. |

## Voice

| | |
|---|---|
| Authoritative implementation | `zerion.voice.pipeline.VoiceFirstInteractionPipeline` (`engine.voice_pipeline`) |
| Status | Not executed in this phase (would require audio I/O). Single instantiation confirmed, constructed with a reference to `ui_bridge`, consistent with the intended `VoiceProvider -> CognitiveRuntime -> VoiceProvider` shape described in the original directive. Not independently verified against that shape line-by-line in this pass. |

## UI

| | |
|---|---|
| Authoritative implementation | `zerion.ui.server.GenesisWebServer`, reachable only via `main.py --ui` |
| Status | Wraps the same live `AscendantEngine` instance — not a separate runtime, confirmed by code inspection. Fixed in this phase: two `/api/status` and `/api/maturity` endpoints previously called `evaluate()` with zero arguments (same bug as the CLI); now use `evaluate_from_evidence()`. **Not yet fixed:** `/api/episodes` reads `engine.foundry.episode_store` while every other reporting path reads `engine.memory` — see Memory section above. |

## Configuration

| | |
|---|---|
| Authoritative implementation | `main.py`'s `load_dotenv()` (a small, dependency-free `.env` loader) plus `os.environ` reads scattered in provider files (`OPENAI_API_KEY`, `GEMINI_API_KEY`) and CLI flags (`--data-dir`, `--port`) |
| Status | Not audited for fragmentation in this phase — flagged as out of scope for this pass (Section 20 of the original directive was not reached). No secrets were observed being logged in any code path touched during this phase. |

---

## Summary of Genuine Duplications Found This Phase

1. **Memory: `engine.memory` vs `engine.foundry.episode_store`** — real, unresolved duplication. Not consolidated this phase.
2. **Orchestration: `species_runtime`/`run_species_pulse()` and `ask_ultimate_questions()` are implemented but unreachable from any entrypoint.** Not wired this phase.

Everything else instantiated in `AscendantEngine.__init__` (50 subsystems) was spot-checked for single-instantiation (no duplicate constructors found via grep across `engine.py`) but not individually traced for internal duplication within each subsystem's own submodule tree — that would require repeating this process ~48 more times and is out of scope for this pass.
