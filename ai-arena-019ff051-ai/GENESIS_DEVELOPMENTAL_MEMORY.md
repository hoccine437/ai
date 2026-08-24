# ZERION-X — GENESIS Developmental Memory Architecture
**Subsystem:** `zerion/memory/`  
**Date:** 2026-08-11  

---

## 1. The 7 Semantic Memory Domains

1. **Episodic Memory (`mem_episodes`):** Chronological log of goals, action sequences, rewards, and duration.
2. **Semantic Memory (`mem_semantic`):** Entity-relation concept ontology with property confidence.
3. **Procedural Memory (`mem_procedural`):** Distilled, reusable action rules (`ProceduralRule`) with empirical reliability scores.
4. **Causal Memory (`mem_causal`):** Causal intervention records and conditional probabilities $P(\text{Effect} \mid \text{Cause})$.
5. **Failure Memory (`mem_failures`):** 12-class failure records with root-cause analysis and preventive rules.
6. **Capability Memory (`mem_capabilities`):** Registry of verified execution cells and tools.
7. **Metacognitive Memory (`mem_metacognitive`):** Strategy performance records and compute allocation history.

---

## 2. Automated Experience Distillation

`ExperienceDistiller` groups repeated successful episodes ($\ge 2$ instances, reward $\ge 0.70$), extracts the common action signature, synthesizes an abstract trigger pattern, and registers a permanent `ProceduralRule`.
