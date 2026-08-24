# ZERION-X — GENESIS Benchmark Integrity & Anti-Gaming Substrate
**Subsystem:** `zerion/benchmarks/anti_gaming.py`  
**Date:** 2026-08-11  

---

## 1. Zero-Gaming Standards & Detection Rules

The `AntiGamingDetector` scans all synthesized code and evaluation outputs for:
- Static score patterns (e.g. hardcoded returns of `0.95`).
- Evaluator answer key leakage.
- Trivial constant function returns without computation.
- Overfitting to evaluation seeds.

If any violation is detected, the trial is flagged as **`BENCHMARK INVALID`**.

---

## 2. Hidden Evaluation Separation

The developmental loop operates strictly within the training sandbox environment. A separate, inaccessible `HiddenEvaluationRunner` administers held-out blind evaluation suites ($N=50$) after the runtime state is frozen.
