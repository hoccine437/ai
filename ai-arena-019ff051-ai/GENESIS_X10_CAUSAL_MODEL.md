# ZERION-X GENESIS ×10 — Causal World Model 4.0
**Subsystems:** `zerion/world/`, `zerion/counterfactual/`  
**Date:** 2026-08-11  

---

## 1. 8 Epistemic States & Relationship Typology

Every belief node in the World Model is explicitly classified into one of eight states:
1. `OBSERVED`: Qualitative empirical observation directly sampled from environment.
2. `MEASURED`: Quantitative metric measured in hardware or isolated sandbox.
3. `INFERRED`: Derived logically from verified axioms.
4. `PREDICTED`: Expected future state prior to observation.
5. `HYPOTHESIZED`: Proposed causal mechanism undergoing empirical test.
6. `ASSUMED`: Unverified working premise.
7. `UNKNOWN`: Explicitly recognized epistemic void.
8. `CONTRADICTED`: Falsified by counter-evidence or invariant breach.

### Causal Relationship Types:
- `A -> B` (Definite Causal Driver)
- `A correlates with B` (Statistical Correlation without Proven Causal Link)
- `A depends on B` (Prerequisite Dependency)
- `A contradicts B` (Mutually Exclusive Invariant Breach)

---

## 2. Interventions & Counterfactual Simulation

$$\text{Causal Delta} = \Delta \text{Outcome}(\text{do}(X_{\text{treatment}})) - \Delta \text{Outcome}(X_{\text{baseline}})$$

The `CounterfactualEngine` executes sandbox state interventions to distinguish true causal mechanisms from spurious correlations with $92\%$ confidence.
