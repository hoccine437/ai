# ZERION-X — GENESIS Strategy Evolution Specification
**Subsystem:** `zerion/strategy_evolution/`  
**Date:** 2026-08-11  

---

## 1. Strategy Lineage & Higher-Order Composition

Strategies evolve through four distinct derivation pathways:
1. **Genesis:** Created de novo to fill an unmapped strategy gap.
2. **Composition:** Combining two complementary strategies (`StratA + StratB`) with shared preconditions and reduced synergistic risk.
3. **Specialization:** Tuning a general strategy for a high-risk domain (e.g. general search $\to$ zero-trust security audit).
4. **Generalization:** Abstracting domain-specific constants into parameterized interval operators.

---

## 2. Non-Destructive Retirement & Rollback

Obsolete strategies are archived in `retired_strategies` with full provenance, timestamps, and supersession links. If a downstream benchmark regression occurs, `StrategyEvolutionEngine` immediately restores the retired predecessor strategy.
