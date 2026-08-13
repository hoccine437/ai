# ASCENDANT ∞ — Security Model & Invariant Guardrails
**Subsystem:** `zerion/runtime/security.py`, `zerion/identity/invariants.py`  
**Date:** 2026-08-11  

---

## 1. Core Invariants (INV-001 through INV-005)

The Core Invariants are strictly immutable and cannot be mutated by genome evolution or self-modification:

- **INV-001 (Epistemic Integrity):** Never present unverified assumptions as observed facts. Explicitly declare unknowns.
- **INV-002 (Safety & Boundary):** Never execute unauthorized filesystem or system calls. Maintain sandbox isolation.
- **INV-003 (Empirical Verification):** Never promote capability or strategy claims without passing sandbox unit and benchmark tests.
- **INV-004 (Durability):** Long-term objectives and verified memory must persist across process deaths and restarts.
- **INV-005 (Resource Sovereignty):** Operate strictly within defined CPU, memory, latency, and cost quotas.

---

## 2. Sandbox Execution & Permission Matrix

All dynamically synthesized capabilities and cognitive strategies run inside `ExecutionSandbox` with:
- Subprocess process-group isolation.
- Hard timeouts (default: 5.0 seconds).
- AST static analysis blocking dangerous imports (`os.system`, `subprocess`, `shutil.rmtree`).
- Automatic secret redaction in telemetry logs.
