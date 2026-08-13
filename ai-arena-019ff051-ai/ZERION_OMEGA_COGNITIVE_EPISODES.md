# ZERION-X Ω — Cognitive Episode Substrate
**Subsystem:** `zerion/intelligence_forge/cognitive_episode/`  
**Date:** 2026-08-11  

---

## 1. The Fundamental Unit of Cognition

A `CognitiveEpisode` is a temporary, task-specific cognitive system compiled for one objective:

```
[CREATED] ──► [SCOPING] ──► [COMPILING] ──► [EXECUTING] ──► [VERIFYING]
                                                                  │
                                                                  ▼
[COMPLETED] ◄── [CONSOLIDATING] ◄── [CREDIT ASSIGNMENT] ◄── [LEARNING]
```

### Key Schema Elements:
- `episode_id`: Unique persistent identifier.
- `objective` / `problem_statement`: Scoped target.
- `budget`: Allocated time (ms), tokens, model calls, tool calls, risk, and cost cents.
- `selected_models`: Bound models from `ModelEconomy`.
- `cognitive_credit_assignment`: Empirical percentage breakdown of contributing cognitive organs.
- SQLite WAL persistence guarantees that active episodes survive process crashes.
