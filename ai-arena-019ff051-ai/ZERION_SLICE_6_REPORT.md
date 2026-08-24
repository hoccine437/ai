# ZERION — Slice 6 Report: Cognitive Routing (Provider-Independent Substrate)

**Scope:** provider-independent ModelProvider interface, honest adapters for
the repository's existing OpenAI / Gemini / Local GGUF providers, real local
GGUF discovery with safety, Task / ModelSelection / CognitiveResult, explicit
CognitiveDepthScore (D0–D6) with FAST_FIELD / DEEP_FIELD, offline-first modes,
failover within retry/budget policy, provider health, historical performance
(cold-start honest, persistence, weight learning), verification integration
(MODEL_OUTPUT → OBSERVED_RESULT → VERIFIED_RESULT), secret redaction, the
required E2E scenarios 1–5 and the local-model discovery test.
**Date:** 2026-08-12
**Status:** Implemented, tested, wired into the real runtime. Slice 7+
intentionally NOT started.

---

## 1. Reused Slice 1–5 components (no duplicates created)

| Component | Source | How Slice 6 uses it |
|---|---|---|
| Event Bus | Slice 1 `AsyncEventBus` (single repo bus) | The router emits its whole lifecycle on it via the runtime bridge: `ROUTING_STARTED`, `MODEL_SELECTED`, `PROVIDER_CALLED`, `PROVIDER_SUCCEEDED`, `PROVIDER_FAILED`, `FAILOVER_STARTED`, `ROUTING_COMPLETED`, `ROUTING_FAILED` (9 new types; no second event system). |
| Provider implementations | Legacy `zerion/model_providers/` (OpenAIProvider, GeminiProvider, LocalGGUFProvider, DeterministicFallbackProvider) | **Reused, not duplicated** — Slice 6 adapters wrap them (`provider_adapters.py`). The legacy providers' correction-phase honesty (labeled FALLBACK, never fabricated tokens/cost) is preserved and their regression tests (`test_correction_phase_regressions.py`) still pass untouched. |
| Verification / evidence | Slice 3 `EvidenceStore` / `EvidenceMode` / `Provenance` | Model output is never auto-truthed: `record_observed_result` stores Slice 3 **OBSERVED** evidence; `confirm_verified` requires OBSERVED evidence ids. MODEL_OUTPUT / OBSERVED_RESULT / VERIFIED_RESULT stay distinct. |
| Experience / failure / capability | Slices 4–5 stores | Router selection consumes the Slice 6 performance ledger (which records real task outcomes in the Slice 1–5 SQLite-WAL + SHA-256 pattern); capability matching uses declared provider capabilities — never model-name guessing. |
| Runtime coordinator | Slice 5 `CognitiveRuntime` | Extended **in place** (additively) with the router, health tracker, ledger and local-model discovery; Slice 1–5 behavior unchanged. |
| Persistence pattern | SQLite-WAL + SHA-256 checksums (Slices 1–5) | `PerformanceLedger` (`performance_ledger.db`) stores real outcomes with per-row checksums and strict-load corruption handling. |

Duplication documented (not silently created): `zerion/model_providers/router.py`
(legacy CognitiveRouter) and the legacy `zerion/model_fabric`/OfflineFallbackManager
stay untouched — Slice 6's router is provider-independent by construction
(imports only its own protocol types), which the legacy router was not
(it hard-codes OpenAI/Gemini/GGUF classes).

## 2. Files created

- `zerion/cognitive_os/router_types.py` — `Task` (task_id, type, difficulty,
  uncertainty, novelty, stakes, goal_relevance, latency/cost budgets,
  required_capabilities, offline_required, verification_required, metadata),
  `RoutingMode` (OFFLINE_ONLY / ONLINE_ALLOWED / ONLINE_PREFERRED / AUTO),
  `ProviderStatus`, `ResultStatus` (13 structured failure statuses),
  `VerificationStatus`, `CognitiveField` (FAST_FIELD / DEEP_FIELD),
  `DepthWeights` + `CognitiveDepthScore` (explicit, deterministic,
  configurable formula, D0–D6), `ModelSelection` (provider, model, structural
  `reason`, estimates — None when unknown, capabilities, confidence,
  fallback_chain, routing_policy_version, depth/field/mode),
  `CognitiveResult` (provider-independent; never fabricates tokens/cost/
  latency/confidence), `redact_secrets` (key-name AND token-value scrubbing).
- `zerion/cognitive_os/provider_interface.py` — `ModelProvider` Protocol
  (generate / stream / health_check / capabilities / model_info / list_models;
  `is_local`; `field_profile`), `ProviderCall`, `RawProviderResponse`,
  `ProviderFailureKind` (11 kinds), `RETRIABLE_FAILURES`, `ModelInfo`.
- `zerion/cognitive_os/provider_health.py` — `ProviderHealthTracker`:
  availability, latency EMA, error/timeout rates, recent failures, consecutive
  failures, last successful request, resource usage. Status is derived from
  real call outcomes — configured-but-unproven is **UNKNOWN**, never READY.
- `zerion/cognitive_os/performance_ledger.py` — `PerformanceLedger` +
  `PerformanceStats`: persistent real outcomes (task type, provider, model,
  difficulty bucket, domain, success, latency, cost, verification); cold start
  = INSUFFICIENT_DATA (never invented); routing weights shift only after
  min-samples (no overfitting from tiny samples).
- `zerion/cognitive_os/gguf_discovery.py` — `LocalModelDiscovery` (recursive
  `.gguf` scan, GGUF-magic integrity probe, duplicate names, size budget,
  path-containment against symlink escape, capabilities only when
  format-guaranteed, context detection from naming conventions) and
  `ModelLoadManager` (resource-aware load/unload with slot + byte budgets —
  never all models in RAM at once).
- `zerion/cognitive_os/provider_adapters.py` — `LegacyOpenAIAdapter`,
  `LegacyGeminiAdapter`, `LegacyGGUFAdapter` wrapping the legacy providers with
  honest statuses (see §4). The only place provider SDKs may appear.
- `zerion/cognitive_os/cognitive_router.py` — `ModelSelector` (pure
  deterministic scoring) + `CognitiveRouter` (register, `route`, `execute`
  with failover/budgets/redaction/event emission).
- `tests/test_routing_foundation.py` — 70 tests.
- `ZERION_SLICE_6_REPORT.md` — this report.

## 3. Files modified

- `zerion/runtime/events.py` — added the 9 Slice 6 routing/provider event types.
- `zerion/cognitive_os/cognitive_runtime.py` — owns `provider_health`,
  `performance_ledger`, `local_models`, `cognitive_router` (adapters registered
  for openai / gemini / local_gguf); new `models_dir` constructor parameter
  (default `data_dir/models`); new methods `route_task` / `execute_task` /
  `record_observed_result` / `confirm_verified` / `record_task_outcome` and the
  `_emit_routing_event` bus bridge.
- `zerion/cognitive_os/__init__.py` — exports for the new types.

## 4. Providers actually implemented (honest statuses, nothing faked)

| Adapter | Status | Evidence |
|---|---|---|
| OpenAI | NOT_CONFIGURED without `OPENAI_API_KEY`; AVAILABLE with one | Real httpx integration exists in the legacy provider; adapter only forwards REAL_MODEL_RESPONSE results and returns a structured failure for the labeled fallback. |
| Gemini | NOT_CONFIGURED without key; UNAVAILABLE with one | The legacy provider explicitly has NO real Gemini API integration (always returns a labeled fallback) — the adapter refuses to fake support and returns a structured failure. |
| Local GGUF | Discovery: AVAILABLE when valid `.gguf` files exist; UNAVAILABLE otherwise. Generation: structured `MODEL_LOAD_FAILURE` (output=None) | Discovery is real (file scan + GGUF magic + safety checks). No inference engine is wired into this runtime (llama-cpp not installed), so generation honestly fails instead of returning canned text. |
| DeterministicFallbackProvider (legacy) | NOT registered by Slice 6 | Its canned SIMULATION text would be fabricated intelligence; the router returns a structured failure instead. Tests use deterministic **stubs**. |

## 5. Local GGUF discovery & safety

- Only `.gguf` files are discovered (recursive scan; `.txt`/`.md` ignored).
- Integrity probe: first 4 bytes must be the GGUF magic header — files without
  it are marked UNAVAILABLE with reason "corrupted or invalid GGUF header",
  never silently accepted.
- Duplicate model names (same stem in different subdirectories): first (sorted)
  wins deterministically, duplicate dropped.
- Oversized models (above the configured byte budget) → UNAVAILABLE.
- Path containment: a symlink resolving outside the models directory is
  rejected before any read.
- `ModelLoadManager`: slot and byte budgets; `load()` refuses when full;
  `unload()` frees; resident bytes tracked. Never loads everything at once.
- Model files are data — never executed as code.

## 6. Routing policy

- **Selection scoring (deterministic, inspectable, configurable):**
  `capability 0.35 · health 0.20 · performance 0.20 · offline 0.10 ·
  field 0.05 · cost 0.05 · latency 0.05`. Candidates are eligible only if they
  cover the required capabilities (no name-based claims — capabilities are
  declared by adapters), are configured/implemented, and (in OFFLINE_ONLY) are
  local. Ties break by (score desc, provider, model) — stable and reproducible.
- `ModelSelection.reason` is a structural explanation: field/depth, provider
  coverage, health (err_rate), performance (or INSUFFICIENT_DATA), offline
  constraint, score, fallback chain.
- **Depth score:** D0 Reflex … D6 Architecture Investigation from uncertainty,
  novelty, stakes, goal relevance, contradiction, historical failure rate,
  expected value with explicit configurable weights and thresholds. FAST_FIELD
  = D0–D2, DEEP_FIELD = D3–D6. "Deep" is a property of the task, never defined
  as calling a model multiple times.
- **Failover:** fallback chain = remaining candidates in score order; retries
  bounded by `max_attempts` (default 2) — never forever. Timeout, quota,
  network, resource, load failures are retriable; malformed/invalid responses
  fail immediately (retry cannot repair them). Provider failure is recorded to
  health + ledger and never equals system failure.
- **Offline modes:** OFFLINE_ONLY never calls cloud providers; with no usable
  local model it returns `ROUTING_FAILED` with `output=None` — a real degraded
  state, never a fabricated answer.

## 7. Provider health & historical performance

- Health is proven by outcomes: fresh configured providers are UNKNOWN;
  success → AVAILABLE; repeated failures → DEGRADED → UNAVAILABLE; timeouts
  tracked separately; latency EMA and last-success timestamps recorded.
- The performance ledger persists real task outcomes. Cold start is
  INSUFFICIENT_DATA; routing weights stay neutral below the min-sample guard
  (5) and shift with bounded steps per outcome — a model that repeatedly fails
  a category becomes less likely for it, one that performs well becomes more
  likely (verified: loser weight < 0.5, winner > 0.5, and routing prefers the
  winner). Nothing invented.

## 8. Verification & security

- High-risk tasks: results start as MODEL_OUTPUT; `record_observed_result`
  promotes to OBSERVED_RESULT by storing Slice 3 OBSERVED evidence with full
  provenance; `confirm_verified` promotes to VERIFIED_RESULT only with real
  OBSERVED evidence ids — fabricated/missing evidence raises. Model output can
  never promote itself.
- Secrets: provider configuration never reaches logs, events, UI state or
  selection explanations. `redact_secrets` scrubs secret-looking keys
  (api_key/token/secret/…) recursively AND token-shaped string values
  (sk-…, Bearer …, ghp_…, xox…, AIza…, PEM keys). Verified on event payloads,
  selection dicts and result dicts.
- No security permissions change because a provider "requests" them — nothing
  in Slice 6 touches permissions.

## 9. Required E2E (verified in tests AND through the real engine)

1. Complex reasoning / high uncertainty / high stakes → **DEEP_FIELD**
   (D4, deep-profile provider selected).
2. Simple routine operation → **FAST_FIELD** (D0, fast-profile provider).
3. OFFLINE_ONLY with cloud configured → **local GGUF selected**; cloud never
   called (calls == 0).
4. Selected provider fails → **compatible fallback selected**; failure
   recorded, retries within budget.
5. No provider available → **structured ROUTING_FAILED, output=None** — no
   fabricated answer.

Local model discovery E2E: `model_a.gguf`, `model_b.gguf`, `not_a_model.txt`
→ only the two `.gguf` files discovered; a corrupted file marked UNAVAILABLE.

Real-engine smoke (`AscendantEngine`): OFFLINE_ONLY with a valid
`qwen-8k.gguf` → selected `local_gguf/qwen-8k` (DEEP_FIELD D4) → honest
`MODEL_LOAD_FAILURE` (no inference engine) with `output=None` → full bus trail
(`ROUTING_STARTED`, `MODEL_SELECTED`, `PROVIDER_CALLED`, `PROVIDER_FAILED`,
`ROUTING_FAILED`) → verification `MODEL_OUTPUT → OBSERVED_RESULT →
VERIFIED_RESULT` with Slice 3 OBSERVED evidence.

## 10. Model independence

The router core imports only its own protocol types. A test scans
`cognitive_router.py`, `router_types.py`, `provider_health.py`,
`performance_ledger.py`, `gguf_discovery.py`, `provider_interface.py` for
import statements and asserts none reference openai / google / llama_cpp.
Provider SDKs live exclusively in `provider_adapters.py`. Future providers are
addable by implementing the protocol + registering — the cognitive core does
not change.

## 11. Exact test results (run just now, not fabricated)

| Command | Result | Time |
|---|---|---|
| `python3 -m unittest tests.test_routing_foundation` | **70 passed** | 0.55s |
| `python3 -m unittest discover -s tests -p "test_*.py"` | **461 tests — OK** (was 391; zero regressions across Slices 1–5) | 15.93s |
| `python3 -m pytest tests/test_cognitive_foundation.py tests/test_question_foundation.py tests/test_experiment_foundation.py tests/test_experience_foundation.py tests/test_capability_foundation.py tests/test_routing_foundation.py -q` | **336 passed** | 9.15s |
| Real `AscendantEngine` E2E smoke | offline selection → honest MODEL_LOAD_FAILURE → full bus trail → verification chain | exit 0 |

## 12. Limitations

- No real GGUF inference engine is wired in (llama-cpp not installed) — the
  adapter honestly reports MODEL_LOAD_FAILURE. When a runtime ships with a
  GGUF engine, only the adapter's `generate` needs to change; the router,
  discovery and safety layers are engine-agnostic.
- Gemini has no real API integration in the legacy provider; the adapter keeps
  that honest rather than pretending.
- `stream` is declared on the protocol but every current adapter raises
  NotImplementedError — the router never calls it; streaming is wired for the
  interface, not for the current providers.
- Health tracking is in-memory (per-session); the performance ledger is
  persistent. Health persistence across restarts was not required by the spec
  and was deliberately left out of scope.
- Adapter field profiles (FAST/DEEP) are not declared for the real adapters
  (they serve text generally), so field matching only affects providers that
  declare a profile; selection still works without one (neutral 0.5).

## 13. Slice 7 prerequisites

- A way for routed results to flow back into Slice 2/3/4: `record_task_outcome`
  already feeds the ledger; Slice 7 can link task outcomes to goals/experiments.
- If Slice 7 adds a SelfModificationGate, it should consume the router's
  provider health + performance ledger as evidence (a provider's repeated
  failure is a real signal, not an opinion).
- Keep the `ModelProvider` protocol stable — adapters for future providers
  (e.g. an offline GGUF engine, a local STT provider for the voice issue)
  implement it without touching the cognitive core.
- The event vocabulary is complete for routing; Slice 7 may add a
  `ROUTING_POLICY_UPDATED` event if weights become configurable at runtime.
