# ASCENDANT ∞ — Cognitive Genome & Phenotype Specification
**Subsystem:** `zerion/cognitive_genome/`  
**Date:** 2026-08-11  

---

## 1. The 22 Cognitive Dimensions

The `CognitiveGenome` defines the operational envelope of ASCENDANT ∞ without neural weights:

| Dimension | Type | Valid Range | Default | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `reasoning_depth` | int | $[1, 10]$ | 3 | Maximum causal inference hop depth |
| `exploration_ratio` | float | $[0.0, 1.0]$ | 0.25 | Proportion of compute allocated to speculative exploration |
| `verification_ratio` | float | $[0.0, 1.0]$ | 0.85 | Strictness of adversarial verification passes |
| `question_generation_rate` | float | $[0.0, 1.0]$ | 0.70 | Unprompted question genesis sensitivity |
| `experiment_rate` | float | $[0.0, 1.0]$ | 0.60 | Tendency to validate hypotheses in reality sandbox |
| `memory_retrieval_strategy` | str | enum | `"hybrid_semantic_procedural"` | Retrieval arbitration policy across memory domains |
| `model_selection_strategy` | str | enum | `"evidence_weighted_cost_optimal"` | Model router cost/latency optimization |
| `tool_selection_strategy` | str | enum | `"least_privilege_deterministic_first"`| Security tool dispatch policy |
| `parallel_reasoning_width` | int | $[1, 8]$ | 3 | Number of concurrent heterogeneous reasoning paths |
| `abstraction_level` | float | $[0.0, 1.0]$ | 0.75 | Degree of generalization in procedural rule extraction |
| `counterfactual_rate` | float | $[0.0, 1.0]$ | 0.65 | Frequency of counterfactual state simulation |
| `adversarial_check_rate` | float | $[0.0, 1.0]$ | 0.80 | Frequency of "TRY TO BREAK THIS" attacks |
| `evidence_threshold` | float | $[0.1, 1.0]$ | 0.70 | Minimum confidence required to accept a claim |
| `uncertainty_threshold` | float | $[0.1, 1.0]$ | 0.40 | Threshold triggering investigative question genesis |
| `risk_tolerance` | float | $[0.0, 1.0]$ | 0.30 | Maximum permitted probability of irreversible side effects |
| `compute_budget_cents` | float | $[0.1, 1000.0]$ | 50.0 | Soft compute budget cap |
| `latency_budget_ms` | float | $[10.0, 60000.0]$| 2000.0 | Default task latency envelope |
| `cost_budget_cents` | float | $[0.01, 1000.0]$ | 10.0 | Per-mission financial spending ceiling |
| `network_budget_kb` | float | $[0.0, 1048576.0]$| 10240.0 | Bandwidth usage cap |
| `learning_rate` | float | $[0.01, 1.0]$ | 0.20 | Update rate for Brier calibration and strategy weights |
| `strategy_reuse_bias` | float | $[0.0, 1.0]$ | 0.80 | Preference for existing procedural rules over re-synthesis |
| `novelty_bias` | float | $[0.0, 1.0]$ | 0.35 | Preference for novel exploratory paths |

---

## 2. Specialized Cognitive Phenotypes

Phenotypes are derived on demand by `PhenotypeFactory`:

- **`CodingPhenotype`:** Verification=98%, ExperimentRate=85%, Depth=3, RiskTolerance=0.20.
- **`DebuggingPhenotype`:** Verification=95%, AdversarialCheck=95%, Depth=4, ToolPolicy="bisection".
- **`ResearchPhenotype`:** Exploration=65%, ParallelWidth=4, Depth=4, ToolPolicy="epistemic_search".
- **`MathematicalPhenotype`:** Verification=100%, AdversarialCheck=100%, Depth=5, RiskTolerance=0.05.
- **`SecurityPhenotype`:** Verification=100%, AdversarialCheck=100%, RiskTolerance=0.01 (Zero-Trust).
- **`PlanningPhenotype`:** Verification=85%, DAG Acyclicity, Checkpointed Step Execution.
- **`CreativePhenotype`:** Exploration=85%, NoveltyBias=0.85, Speculative Sampling.
- **`DiagnosticPhenotype`:** Causal Counterfactual Probing, Prediction Error Tracing.

---

## 3. Mutation Safeguards

Every proposed genomic mutation passes:
$$\text{Proposal} \to \text{Bounds Verification} \to \text{SHA-256 Digest Validation} \to \text{Canary Benchmark} \to \text{Promotion / Rollback}$$
On regression, `GenomeManager.rollback()` restores the exact previous genome version.
