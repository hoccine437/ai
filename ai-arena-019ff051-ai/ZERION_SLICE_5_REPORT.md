# ZERION — Slice 5 Report: Capability Genesis

**Scope:** Capability object, CapabilityGenesis (NEEDED → DESIGN → GENERATE →
SANDBOX → TEST → VALIDATE → REGISTER), CapabilityRegistry (versioning,
monitoring, rollback), the hardened capability sandbox, least-privilege
permissions, validation/monitoring rules, security + adversarial tests, the
required E2E (Slice 4 evidence → registered usable capability that survives
restart), persistence.
**Date:** 2026-08-12
**Status:** Implemented, tested, wired into the real runtime. Slice 6+
intentionally NOT started.

---

## 1. Reused Slice 1–4 components (no duplicates created)

| Component | Source | How Slice 5 uses it |
|---|---|---|
| Event Bus | Slice 1 `AsyncEventBus` (single repo bus) | All capability events flow on it: `CAPABILITY_GAP` (pre-existing trigger, reused), `CAPABILITY_DESIGNED/GENERATED/SANDBOXED/TESTED/REGISTERED/DEGRADED/DEPRECATED/ROLLBACK` (new), `CAPABILITY_VALIDATED` + `CAPABILITY_BORN` (pre-existing, reused). No second event system. |
| Attention Field | Slice 1 `CognitivePriority` | Every detected gap publishes `CAPABILITY_GAP` → Slice 2 genesis → a high-priority question competes through Slice 1 attention (verified: the gap question reaches INVESTIGATING, focus updates). Gaps never auto-generate code. |
| Question Field | Slice 2 `question_genesis.py` | `CAPABILITY_GAP` is an existing genesis trigger; gap questions carry the missing-capability task and are attended normally. |
| Experience/Distillation/Failure | Slice 4 `episode.py` / `distilled.py` / `failure_learning.py` | Gap detection reads Slice 4 stores: validated `FAILURE_PREVENTION_RULE`s (with provenance signals) and repeated failures (`repeat_count ≥ threshold`). Capability designs carry `source_rules` / `source_experiences`. |
| Runtime coordinator | Slice 4 `CognitiveRuntime` | Extended **in place** (additively) with the Slice 5 stores + pipeline methods. Slices 1–4 behavior unchanged. |
| Persistence pattern | SQLite-WAL + SHA-256 checksums (Slices 1–4) | Same pattern for `CapabilityRegistry`. |
| Execution sandbox | Legacy `zerion/experiments/sandbox.py` `ExecutionSandbox` | **Reused** as the outer subprocess + hard-timeout layer of the new capability sandbox (see §4). |

Duplication documented (not silently created): the legacy pipeline has
`zerion/capabilities/` (`birth.py` — 9-stage capability synthesis) and
`zerion/cognitive_os/capability_controller.py` (`CapabilityGenesisController`),
tied to the legacy engine and its `capabilities.db`. They are left untouched;
the Slice 5 registry uses `cognitive_capabilities.db` to avoid the DB-name
collision. The legacy `ExecutionSandbox` runs plain subprocesses with the full
stdlib available (os/socket/secrets reachable) — that is not strong enough for
untrusted generated code, which is the documented justification for the
hardened `CapabilitySandbox` that **reuses** `ExecutionSandbox` underneath.

## 2. Files created

- `zerion/cognitive_os/capability.py` — `Permission` (READ/WRITE/EXECUTE/
  NETWORK/COMMUNICATION/FINANCIAL/SYSTEM_CONTROL/SELF_MODIFICATION),
  `HIGH_RISK_PERMISSIONS` (financial/system-control/self-modification require
  explicit policy approval), `LEAST_PRIVILEGE` (default = READ + EXECUTE),
  `CapabilityType` (8 types incl. PROCEDURE, TOOL_CHAIN, VALIDATOR, HEURISTIC,
  RETRIEVAL_STRATEGY, PLANNING_STRATEGY, DETERMINISTIC_MODULE,
  SPECIALIZED_WORKFLOW), `CapabilityStatus` (NEEDED → DESIGNED → GENERATED →
  SANDBOXED → TESTED → VALIDATED → REGISTERED → MONITORED, plus DEPRECATED /
  REJECTED), `CapabilityHealth` (HEALTHY/DEGRADED/FAILING), `Capability`
  (procedure, validation_evidence, success/failure rates, usage_count,
  last_used, health, risk_level, metadata), `PermissionPolicy`, `CapabilityRegistry`
  (register/lookup/versioning/enable/disable/deprecate/rollback/dependency
  inspection, active-version dedup, corruption-safe SQLite-WAL store).
- `zerion/cognitive_os/capability_sandbox.py` — `CapabilitySandbox`:
  static AST gate (blocks `import`/`from`, `os`, `sys`, `subprocess`, `socket`,
  `open`/file access, `eval`/`exec`/`compile`, `__import__`, dunder
  introspection, dangerous callables, destructive command strings) **plus** a
  restricted-exec harness (whitelisted builtins, no IO/network/secrets) running
  inside the reused `ExecutionSandbox` outer subprocess with hard timeouts and
  resource limits. `SecurityViolationError` for violations.
- `zerion/cognitive_os/capability_genesis.py` — `CapabilityGenesis`:
  `detect_gaps()` (from validated prevention rules + repeated failures;
  detection only, never auto-generation), `design()` (fills the design
  contract: purpose, inputs, outputs, dependencies, procedure, permissions,
  success/failure criteria, test strategy, rollback strategy, resources),
  `generate()` (marks the artifact **untrusted**), `sandbox()`, `test()`
  (runs the artifact through the sandbox against test cases), `validate()`
  (evidence-only), `register()` (registry + active-version dedup), `execute()`
  (controlled, still sandboxed), `record_usage()` (monitoring → DEGRADED →
  DEPRECATED), `promote()`/`rollback()` (versioned comparison + rollback).
- `tests/test_capability_foundation.py` — 48 tests.
- `ZERION_SLICE_5_REPORT.md` — this report.

## 3. Files modified

- `zerion/runtime/events.py` — added `CAPABILITY_DESIGNED`, `CAPABILITY_GENERATED`,
  `CAPABILITY_SANDBOXED`, `CAPABILITY_TESTED`, `CAPABILITY_REGISTERED`,
  `CAPABILITY_DEGRADED`, `CAPABILITY_DEPRECATED`, `CAPABILITY_ROLLBACK`
  (reused pre-existing `CAPABILITY_GAP`, `CAPABILITY_VALIDATED`,
  `CAPABILITY_BORN`).
- `zerion/cognitive_os/cognitive_runtime.py` — owns `capability_registry`,
  `capability_genesis`, `capability_sandbox`; `CAPABILITY_GAP` events already
  route to Slice 2 genesis (existing path); new methods `detect_capability_gaps`
  / `design_capability` / `generate_capability` / `sandbox_capability` /
  `test_capability` / `validate_capability` / `register_capability` /
  `execute_capability` / `record_capability_usage` / `promote_capability` /
  `rollback_capability` / `get_capability` / `list_capabilities`.
- `zerion/cognitive_os/__init__.py` — exports for the new types.

## 4. Capability model, genesis, registry

- **Capability** is a structured, versioned object (never "generated text
  counts as learned"). Every registered capability has a unique identity +
  version, declared permissions (default least privilege), procedure,
  validation evidence, success/failure rates, usage count, health, risk level,
  supported-task/goal metadata. Registry rejects duplicate **active**
  definitions with conflicting fingerprints; new versions coexist without
  auto-replacing the old one.
- **Genesis flow** (no stages skipped): `detect_gaps()` proposes NEEDED
  capabilities from validated Slice 4 rules and repeated failures — detection
  only, no code generation until an explicit `generate` stage. `design()`
  fills the full design contract; `generate()` marks the artifact
  **untrusted**; `sandbox()` compiles + gates it; `test()` runs real test
  cases (normal, invalid input, edge cases, failure handling, permission
  boundaries, regression, determinism) through the sandbox; `validate()`
  requires actual test results and a passing success rate — "generated
  successfully" is never validation; `register()` only accepts validated
  capabilities and never duplicates an active definition.
- **Sandbox behavior:** static AST gate + restricted builtins + outer
  `ExecutionSandbox` subprocess with hard timeout and resource limits. The
  gate runs **before** any execution; the restricted harness runs **inside**
  the isolated subprocess, so even a gate bypass cannot reach os/socket/
  secrets. Verified blocks (tests): `os.system`, unrestricted `subprocess`,
  filesystem escape (`open`/path tricks), secret access (`environ`, getenv),
  network (`socket`), privilege escalation (`setuid`/`setgid`), destructive
  commands (`rm -rf` / `shutil.rmtree`), introspection escape (`__globals__`/
  `__builtins__` reach-around), infinite loops (outer timeout kills).
- **Permissions:** defaults to READ + EXECUTE. HIGH_RISK_PERMISSIONS
  (FINANCIAL/SYSTEM_CONTROL/SELF_MODIFICATION) require explicit policy
  approval; generated code can never grant permissions to itself. A capability
  requesting excessive permissions is REJECTED at the sandbox stage.
- **Monitoring:** `record_usage` tracks success/failure/latency/resource cost/
  permission violations; repeated failures move health to DEGRADED then
  DEPRECATED (status), with `CAPABILITY_DEGRADED` / `CAPABILITY_DEPRECATED`
  events — a broken capability is never silently left active. A DEGRADED
  capability can recover on a clean run (health back to HEALTHY).
- **Versioning / rollback:** v1 is never replaced automatically. `promote()`
  requires evidence (v2 must beat v1 on the same evidence set); `rollback()`
  deactivates the regressing version, restores the previous validated version,
  and records the rollback reason + evidence. Rollback failure is recorded,
  not silent.

## 5. Required E2E (verified in tests AND through the real engine)

Slice 4 evidence: a validated `FAILURE_PREVENTION_RULE` distilled from 4
repeated auth-expiration failures.

1. `detect_capability_gaps()` → NEEDED `authentication_expired_detector`
   (VALIDATOR) with `source_rules`; no auto-generation (implementation empty).
   Gap → `CAPABILITY_GAP` event → Slice 2 question → Slice 1 attention
   (question reaches INVESTIGATING).
2. DESIGNED (full design contract) → GENERATED (untrusted) → SANDBOXED →
   TESTED (4 real sandboxed test cases, success rate 1.0) → VALIDATED →
   REGISTERED v1.
3. Controlled execution: `"error: authentication expired"` → `detected=True`;
   `"all good"` → `detected=False`; latency + usage measured.
4. Persisted; **restart**; retrieved from the registry — still REGISTERED,
   still executable with the same result (usage_count continues). Nothing
   hard-coded: the artifact under test is the generated implementation, and
   the tests determine success.

## 6. Security + adversarial tests

- Security: `os.system` blocked, unrestricted `subprocess` blocked, filesystem
  escape blocked, secret access blocked, network access blocked, privilege
  escalation blocked, destructive command string blocked, introspection escape
  blocked, infinite loop times out, "looks valid but crashes" fails tests.
- Adversarial: hidden dependency → REJECTED (sandbox), excessive permissions →
  REJECTED, malicious generated implementation never registers, false
  validation evidence rejected (validate requires real test results), missing
  dependency / incompatible version rejected, duplicate active capability
  rejected, rollback failure recorded (not silent), corrupted registry row
  raises `CapabilityStoreIntegrityError` in strict mode, new version does not
  auto-replace the old one, promote without evidence rejected.
- No self-modification: generated capabilities are bounded by permissions +
  sandbox + validation + registry + rollback. `SelfModificationGate` is
  explicitly deferred to Slice 7. No LLM anywhere in the Slice 5 pipeline —
  all fixtures are deterministic.

## 7. Persistence

Capabilities, versions, dependencies, permissions, validation evidence, usage
metrics, health, rollback history and deprecation history persist through the
registry's SQLite-WAL + SHA-256 store (`cognitive_capabilities.db`).
`register → restart → load → verify` is a test; corrupted rows are detected.

## 8. Exact test results (run just now, not fabricated)

| Command | Result | Time |
|---|---|---|
| `python3 -m unittest tests.test_capability_foundation` | **48 passed** | 1.2s |
| `python3 -m unittest discover -s tests -p "test_*.py"` | **391 tests — OK** (was 343; zero regressions across Slices 1–4) | 15.30s |
| `python3 -m pytest tests/test_cognitive_foundation.py tests/test_question_foundation.py tests/test_experiment_foundation.py tests/test_experience_foundation.py tests/test_capability_foundation.py -q` | **266 passed** | 8.46s |
| Real `AscendantEngine` full E2E smoke | gap → full pipeline → REGISTERED v1 → controlled exec → restart → retrieved REGISTERED + usable | exit 0 |

## 9. Limitations

- The capability artifact language is Python; non-code capability types
  (PROCEDURE / HEURISTIC / PLANNING_STRATEGY …) are represented structurally
  and validated through the same lifecycle, but only executable artifacts are
  sandbox-executed today.
- Sandbox isolation is defense-in-depth (static gate + restricted builtins +
  subprocess timeout), not a full OS container; adequate for the declared
  threat model, with the outer subprocess as the hard backstop.
- `execute_capability` runs the artifact sandboxed on every controlled
  execution — production performance tuning is out of scope for this slice.

## 10. Slice 6 prerequisites

- A consumer that selects capabilities for real tasks via the registry
  (lookup by supported task/goal with evidence-gated claims).
- Wiring `CapabilityGenesis` output into the runtime's task loop so gaps are
  proposed from live repeated failures, not only at explicit calls.
- If Slice 6 introduces a CognitiveRouter, it should treat REGISTERED
  capabilities as the candidate set and reuse the registry's metrics
  (success rate, latency, health) — no second registry.
- Keep the event vocabulary stable so Slice 6 can build on the existing
  CAPABILITY_* trail; `CAPABILITY_MONITORED` can be added when monitoring
  events need an explicit lifecycle marker.
