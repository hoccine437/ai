# ZERION-X Ω — Cognitive Compiler Specification
**Subsystem:** `zerion/cognition/compiler.py`  
**Date:** 2026-08-11  

---

## 1. Dynamic Cognitive Program Synthesis

The Cognitive Compiler compiles problems into tailored execution DAGs from 20 typed primitive nodes:
`OBSERVE`, `RETRIEVE`, `DECOMPOSE`, `QUESTION`, `HYPOTHESIZE`, `SEARCH`, `REASON`, `SIMULATE`, `EXPERIMENT`, `CALL_MODEL`, `CALL_TOOL`, `COMPARE`, `CRITIQUE`, `FALSIFY`, `VERIFY`, `SYNTHESIZE`, `ACT`, `LEARN`, `STORE`, `STOP`.

- **Trivial Request:** `QUESTION -> FAST_MODEL -> VERIFY` (Latency: 2.5ms).
- **Engineering Task:** `OBSERVE -> DECOMPOSE -> CODE -> TEST -> ADVERSARIAL_ATTACK -> VERIFY` (Latency: 18.0ms).
- **Causal Anomaly:** `OBSERVE -> QUESTION -> HYPOTHESIZE -> EXPERIMENT -> VERIFY -> UPDATE_WORLD` (Latency: 22.0ms).
