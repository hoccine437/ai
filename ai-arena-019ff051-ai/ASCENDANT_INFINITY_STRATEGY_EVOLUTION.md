# ASCENDANT ∞ — Strategy Evolution & Lineage Substrate
**Subsystem:** `zerion/strategy_evolution/`  
**Date:** 2026-08-11  

---

## 1. Strategy Lifecycle & Transitions

```
[Problem Space]
       │
       ▼
  [DISCOVER] ──► [EVALUATE] ──► [COMPARE] ──► [COMPOSE]
                                                  │
                                                  ▼
[RETIRE WITH PROVENANCE] ◄── [REPLACE] ◄── [SPECIALIZE / GENERALIZE]
```

---

## 2. Lineage Tracking & Composition

Every strategy maintains an immutable lineage graph in SQLite (`strategy_lineage` table):
- `strategy_id`: Unique identifier.
- `parent_strategy_id`: Ancestor strategy ID.
- `derivation_type`: `"genesis"`, `"composition"`, `"specialization"`, or `"generalization"`.
- `lineage_depth`: Generation depth in the evolutionary tree.
- `benchmark_gain`: Empirical delta achieved over parent strategy.

### Strategy Composition Mechanism:
`StrategyEvolutionEngine.compose_strategies(strat_a, strat_b, name)` combines two complementary strategies (e.g. `IntervalBisection` + `CausalCounterfactualProbe`) into a synergized pipeline with reduced composite risk ($0.9 \times \max(R_A, R_B)$).

---

## 3. Non-Destructive Retirement & Rollback

No strategy is ever blindly deleted.
When a strategy is superseded:
1. `is_active` is toggled to `False`.
2. A formal retirement record is written to `retired_strategies` with the reason, timestamp, and `superseded_by` pointer.
3. If the replacement strategy causes a downstream benchmark regression, the retired strategy can be instantly reactivated.
