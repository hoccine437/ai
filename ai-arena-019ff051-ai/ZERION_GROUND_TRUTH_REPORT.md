# ZERION_GROUND_TRUTH_REPORT.md

Scope: Phase 0 only. Evidence-based. No fixes applied. No new architecture proposed.

---

## 1. Repository Reality

The uploaded archive contains:
- One top-level `zerion/` package (39 subpackages, ~200 `.py` files) — this is the **current, merged
  codebase**.
- One `tests/` directory (24 files, 101 test functions).
- One `main.py` entrypoint, `ui/` folder, `docs/`.
- ~90 markdown report files at the repo root (`GENESIS_*`, `GENESIS_INFINITY_*`, `GENESIS_X10_*`,
  `ASCENDANT_*`, `ZERION_OMEGA_*`, `SINGULARITY_*`) — these are **self-authored status reports**, not
  code, and are treated below as claims, not evidence.
- Seven additional zip files at repo root (`zerion_genesis.zip`, `zerion_genesis_infinity.zip`,
  `zerion_genesis_x10.zip`, `zerion_genesis_voice_first.zip`, `zerion_omega.zip`,
  `zerion_singularity.zip`, `zerion_cognitive_species.zip`) — confirmed by extraction to be **earlier,
  self-contained snapshots**, each with its own `zerion/` package tree. Diffing `zerion_omega.zip`
  against the current top-level `zerion/` shows heavy overlap plus renamed/reorganized subpackages
  (e.g. omega's `attention/` and `capability/` don't exist by those names in the current tree). This
  confirms a **linear history of successive full-package regenerations**, not seven independent
  products. The current `zerion/` is the most recent merge point — it imports modules named after
  nearly every generation (`cognitive_species`, `intelligence_forge`, `cognitive_autopoiesis`,
  `cognitive_genome`, etc. all coexist in one `engine.py`).

## 2. Runtime Reality

Verified by actually running it:

```
python3 main.py --status --data-dir /tmp/x     # works, exits cleanly
python3 main.py --cycle  --data-dir /tmp/x2    # works, exits cleanly
python3 -m pytest tests/ -q                    # 101 passed, 0 failed, 6.55s
```

`main.py` → `load_dotenv()` → `zerion.cli.main()` → `asyncio.run(run_cli())` → constructs
`AscendantEngine(data_dir=...)` → `await engine.start()` → dispatches on CLI flags → `await engine.stop()`.

This path is **RUNTIME_VERIFIED**. It is not theatrical — `AscendantEngine.__init__` really
constructs ~50 subsystem objects, `engine.start()` really initializes them, and `run_developmental_cycle()`
really executes a multi-step pipeline (signal generation → problem candidates → question ranking →
strategy selection → program execution → adversarial attack → telemetry → maturity assessment) using
real Python logic, not stubs that just `return True`.

## 3. Entrypoints

- **`main.py` is the sole, authoritative entrypoint.** No competing `bootstrap.py` or `api_server.py`
  was found at the root. `zerion/ui/server.py` (`GenesisWebServer`) is a secondary entrypoint reached
  only via `main.py --ui`, and it wraps the same `AscendantEngine` instance — not a separate runtime.
- No evidence of duplicate daemons or duplicate event loops being started from the same process in the
  paths exercised (`--status`, `--cycle`).

## 4. Model / Provider Reality

`zerion/model_providers/` contains a real `CognitiveRouter` with four providers:

| Provider | Verdict | Evidence |
|---|---|---|
| `OpenAIProvider` | **RUNTIME_VERIFIED (conditional)** | Genuinely calls `https://api.openai.com/v1/chat/completions` via `httpx` when `OPENAI_API_KEY` is set and valid. Confirmed by reading the code — this is not a stub. |
| `OpenAIProvider` fallback path | **STUB, disguised as output** | When no key is present (the case in this sandbox, and likely in most runs), it returns a hard-coded string `f"Synthesized structured cognitive resolution for prompt: '{prompt[:40]}'"` with **fabricated** `prompt_tokens=20, completion_tokens=30, cost_cents=0.0`. Nothing marks this response as synthetic to downstream consumers except the `is_fallback` flag, which the CLI/UI paths inspected do not surface to the user. |
| `GeminiProvider` | **UNVERIFIED in this pass** | Same pattern expected (real HTTP call gated on API key) but not individually re-verified line-by-line this pass; structurally identical to OpenAIProvider. |
| `LocalGGUFProvider`, `DeterministicFallbackProvider` | **STUB** | Deterministic canned text, explicitly labeled as local/deterministic — this one is honest about what it is. |

Without an API key (this sandbox's condition, and plausibly the person's default local condition),
**every "cognitive" response the system produces is a template string, not an LLM output.** This is a
critical finding: the system can run end-to-end and *look* functional while never having called a real
model.

## 5. Memory Reality

`DevelopmentalMemoryStore` (`zerion/memory/developmental_store.py`) is real, in-process Python state
(`_episodes`, `_procedural_rules` lists/dicts) constructed fresh per `AscendantEngine` instantiation.
Confirmed via `--status` twice with different `--data-dir` values and one `--cycle` run in between:
episode count went from `0` → `1` correctly, showing writes are real, not fabricated. Not independently
verified in this pass: whether it actually persists to disk and survives a process restart with the
same `--data-dir` (the CLI flag exists and is respected for path construction, but restart-persistence
was not tested).

## 6. Agent / Orchestration Reality

There is no literal multi-agent framework with separate agent processes; "agents" as described in the
directive appear better characterized as the ~50 subsystem objects composed inside `AscendantEngine`
(pressure field, question genesis, strategy registry, evidence engine, capability registry, etc.),
invoked in sequence within `run_developmental_cycle()`. This single method is the closest thing to an
orchestrator. It is **RUNTIME_VERIFIED** — it executes, in order, and returns a real trace object with
per-field data (not all fields independently checked for authenticity — see Section 11).

## 7. Evolution / Self-Modification Reality

`ControlledSelfModificationEngine` (`zerion/evolution/self_modification.py`, 156 lines) is
**RUNTIME_VERIFIED and the most solid subsystem found in this pass.** Its own unit test
(`tests/test_evolution.py::test_self_modification_safety_guardrails_and_rejection`) submits a
`ModificationProposal` containing `os.system(...)` and confirms the pipeline rejects it
(`promoted=False`, `rolled_back=True`, reason contains "Invariant violation"), then submits a benign
proposal and confirms it is promoted. This test passed when run directly. The gating mechanism itself
is a **string-based blocklist** (`forbidden_calls = ["os.system", "shutil.rmtree", "subprocess.Popen",
"__import__('os').system"]`) — real, but a blocklist of this kind is a weak security boundary in
general (trivially bypassable via indirection, e.g. `getattr(__import__('os'), 'sys'+'tem')`), a caveat
worth flagging even though within the scope tested it behaved correctly.

## 8. Voice Reality

Not executed this pass (would require audio hardware/mocking not attempted). Code exists
(`zerion/voice/pipeline.py`, `session.py`, `vad.py`, `wake_word.py`) and imports cleanly as part of
`engine.py`'s successful import. Classified **UNVERIFIED** — code exists and is connected (imported and
instantiated in `engine.py`), but no execution evidence was gathered.

## 9. UI Reality

`zerion/ui/server.py` is reachable only via `main.py --ui` and wraps the same `AscendantEngine`,
calling `self.engine.maturity_evaluator.evaluate()` with **zero arguments** at both call sites (lines
106, 138) — same bug as the CLI (see Section 11). Not run this pass (would bind a port); classified
**IMPLEMENTED_BUT_NOT_EXECUTED**, structurally connected to the real engine, not a mockup.

## 10. Version / Archive Analysis

`GENESIS → GENESIS_INFINITY → GENESIS_X10 → GENESIS_VOICE_FIRST → OMEGA → SINGULARITY →
COGNITIVE_SPECIES` are **successive regenerations of the same project**, each apparently produced in a
separate session, each shipped as a full zip snapshot, each accompanied by its own "reality audit,"
"benchmark," and "final report" markdown files that declare the *previous* iteration verified before a
new one appears. The current top-level `zerion/` package is not any single one of these zips — it is a
**merge** that imports subpackages named after almost every generation simultaneously in one
`engine.py`. This explains the file count and the density of self-referential audit documents: each
generation cycle produced its own audit trail without a hard external checkpoint confirming the prior
cycle's claims before starting the next.

## 11. Verified vs Claimed — Explicit Findings

| Claim | Source | Verdict | Evidence |
|---|---|---|---|
| "67 automated tests passing" (`--reality-audit` flag) | `zerion/cli.py` line ~for reality_audit | **FALSE / HARD-CODED** | The flag's handler is a literal `print()` statement with no test execution: `print("Subsystems Verified: Real & Operational (67 automated tests passing).")`. It runs no tests. |
| System reaches "Maturity Level L7 (Level 7/7)" on `--status`, even cold-start with 0 episodes | `zerion/cli.py`, `zerion/self_model/maturity.py` | **FALSE, root cause identified** | `CognitiveMaturityEvaluator.evaluate()` has hard-coded defaults (`episodes_count=1, procedural_rules_count=1, born_capabilities_count=1, learning_acceleration=1.5`, etc.) that all satisfy the L7 criteria. Both real call sites that matter for user-facing output (`cli.py` `--status`, `ui/server.py` x2) call `evaluate()` with **no arguments**, so they always report L7 regardless of actual state. Only the internal `run_developmental_cycle()` call site (`engine.py:495`) passes real counters, and it correctly produced `L3_ADAPTIVE` after one real cycle — proving the evaluator's logic itself is fine; the bug is exclusively in the two/three call sites that forgot to pass arguments. |
| "Effective Intelligence: 0.8800", "Prediction Accuracy: 94.0%", "Self-Correction Rate: 96.0%" on scoreboard after one cycle | `zerion/benchmarks/scoreboard.py` | **FALSE / HARD-CODED** | These are literal default parameter values (`effective_intelligence: float = 0.88`, etc.) on the snapshot constructor, not values computed from the single real episode that had just been recorded. |
| OpenAI/Gemini-backed cognition | `zerion/model_providers/openai_provider.py` | **PARTIALLY VERIFIED** | Real HTTP integration exists and is correct when an API key is configured. Without a key (default/sandbox condition), all output is a fixed template string, with fabricated token/cost metadata, and this is not surfaced to the caller distinctly from a real response in the paths inspected. |
| Self-modification is safety-gated | `zerion/evolution/self_modification.py` | **VERIFIED** | Real blocklist-based rejection pipeline, exercised by a real passing test with a genuine malicious payload. Caveat: blocklist approach is weak in general, not defense-in-depth. |
| 101 unit tests passing | `tests/` | **VERIFIED** | Ran directly: `101 passed, 1 warning in 6.55s`. Sampled tests (self_model, evolution) are substantive — they assert real behavioral properties (Brier score bounds, rollback version numbers, rejection of dangerous code), not just "does it instantiate." |
| Package imports cleanly, engine constructs and runs end-to-end | `zerion/engine.py` | **VERIFIED** | Direct import and two full CLI invocations succeeded with no exceptions. |
| Memory persists across a cycle within one process | `zerion/memory/developmental_store.py` | **VERIFIED (in-process only)** | Episode count moved 0→1 correctly across a real cycle. Restart-survival not tested. |
| Seven "generations" are independent products | Root-level zips/reports | **FALSE** | Confirmed via diff: `zerion_omega.zip`'s package tree overlaps substantially with, and is structurally ancestral to, the current merged `zerion/` package. |

## 12. Critical Findings

1. **Self-reported status metrics are decoupled from real state at the two user-facing surfaces that
   matter most** (`--status` CLI flag, UI server maturity display). This is a narrow, specific,
   fixable bug (missing arguments at two/three call sites) — not evidence that the underlying
   evaluator or engine is fake. The evaluator logic itself is sound and was proven correct when fed
   real data via the internal cycle path.
2. **`--reality-audit` is fabricated output** — a literal print statement claiming a specific test count
   without executing anything. This is the single clearest example of exactly the failure mode the
   directive was written to catch.
3. **Scoreboard numbers are defaults, not computations**, and will misrepresent system state to anyone
   reading `--cycle` output, since the scoreboard renders immediately after a cycle using its
   constructor defaults rather than cycle-derived values.
4. **Without an API key, the entire system runs on template-string cognition** with fabricated
   token/cost accounting, indistinguishable from real model output in the surfaces checked. This is the
   most consequential finding for anyone evaluating the system's actual capability level today.
5. **The self-modification safety gate is real and tested**, and is the strongest-evidenced subsystem in
   this audit — worth explicitly preserving as-is in any future work, with the blocklist caveat noted.
6. **The repository's ~90 root-level markdown reports and 7 snapshot zips are the artifacts of repeated
   full-regeneration cycles**, each self-certifying the last. They should be treated as historical
   record, not as current architecture documentation, until claims in them are individually re-verified
   against code the way this report did for a sample.

## 13. Recommended Direction (per instructions: not implemented)

Evidence supports a narrow, high-confidence characterization: **"The core engine and memory/evolution
subsystems are substantially real and exercised by genuine passing tests; but the small set of
user-facing status/scoreboard surfaces fabricate or misreport system state, and the system's
'cognition' silently degrades to templated text without a configured model API key."** This is closer
to *"substantially functional but with specific, identifiable misrepresentation bugs at the reporting
layer"* than to *"mostly disconnected/generated."* A full recommendation (correct vs. consolidate vs.
extract vs. delete) would require repeating this evidence-based process across the remaining ~45
subsystems not touched in this pass (voice, UI execution, world model, capability birth, learning
engines, the 6 archived snapshot zips) before making an architecture-wide call.
