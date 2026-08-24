# ZERION-X GENESIS ×10 — Cognitive OS Specification
**Subsystem:** `zerion/cognitive_os/`  
**Date:** 2026-08-11  

---

## 1. Subsystem Architecture

The Cognitive OS acts as the high-level coordination substrate, separating broad environmental perception from focused, deep cognition:

```
zerion/cognitive_os/
├── perception.py           # Ingests raw hardware and environmental telemetry into PerceptionFrames
├── attention.py            # Implements the Attention Economy and priority scoring formula
├── intention.py            # Translates top attention targets into actionable IntentionTargets
├── objective_manager.py    # SQLite-backed ContinuousObjective state machine
├── opportunity_detector.py # Scans for resource surplus, latent capability acceleration, and information gain
├── problem_discovery.py    # Autonomous problem discovery and expected value ranking
├── question_engine.py      # Formulates diagnostic, causal, counterfactual, and falsification questions
├── hypothesis_engine.py    # Generates testable causal hypotheses with testable predictions
├── experiment_controller.py# Runs isolated Python sandbox experiments
├── action_controller.py    # Executes safe system interventions
├── consequence_analyzer.py # Compares predicted vs observed outcomes and derives reality delta
├── strategy_controller.py  # Strategy Market, empirical reputation, and dynamic composition (A+B->C)
├── learning_controller.py  # Sleep/consolidation cycles, procedural compression (EXPENSIVE -> REFLEX)
├── capability_controller.py# Capability Birth X10 with multi-parameterization & negative testing
├── architecture_controller.py# Cognitive topology evolution (Reflex, Experimental, Adversarial)
├── reflection.py           # Autopoietic reflection on 2nd and 3rd-order developmental bottlenecks
└── organism.py             # CognitiveOrganism master coordinator executing the closed-loop cycle
```
