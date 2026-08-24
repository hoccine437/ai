# ZERION-X — GENESIS Cognitive Genome Specification
**Subsystem:** `zerion/cognitive_genome/`  
**Date:** 2026-08-11  

---

## 1. Genome Dimensions & Safe Boundaries

The `CognitiveGenome` represents internal behavioral topologies without model weights:

- `reasoning_depth` $[1, 10]$
- `exploration_ratio` $[0.0, 1.0]$
- `verification_ratio` $[0.0, 1.0]$
- `question_generation_rate` $[0.0, 1.0]$
- `experiment_rate` $[0.0, 1.0]$
- `memory_retrieval_strategy` (e.g. `"hybrid_semantic_procedural"`)
- `model_selection_strategy` (e.g. `"evidence_weighted_cost_optimal"`)
- `tool_selection_strategy` (e.g. `"least_privilege_deterministic_first"`)
- `parallel_reasoning_width` $[1, 8]$
- `abstraction_level` $[0.0, 1.0]$
- `counterfactual_rate` $[0.0, 1.0]$
- `adversarial_check_rate` $[0.0, 1.0]$
- `evidence_threshold` $[0.1, 1.0]$
- `uncertainty_threshold` $[0.1, 1.0]$
- `risk_tolerance` $[0.0, 1.0]$
- `compute_budget_cents` $[0.1, 1000.0]$
- `latency_budget_ms` $[10.0, 60000.0]$
- `cost_budget_cents` $[0.01, 1000.0]$
- `network_budget_kb` $[0.0, 1048576.0]$
- `learning_rate` $[0.01, 1.0]$
- `strategy_reuse_bias` $[0.0, 1.0]$
- `novelty_bias` $[0.0, 1.0]$

---

## 2. Dynamic Phenotype Specialization

`PhenotypeFactory.derive_phenotype()` synthesizes specialized operational profiles:
- **`CodingPhenotype`:** High verification (98%), mandatory sandbox testing, low risk tolerance (0.20).
- **`ResearchPhenotype`:** High exploration (65%), parallel search width 4, epistemic graph exploration.
- **`SecurityPhenotype`:** Zero-trust (risk tolerance 0.01), 100% verification, immutable invariant checks.
- **`MathematicalPhenotype`:** Formal deduction, zero speculation, depth 5.
- **`DiagnosticPhenotype`:** Causal counterfactual probing, prediction error tracing.
