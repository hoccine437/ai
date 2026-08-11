# ZERION-X — ASCENDANT
**Developmental Cognitive Architecture & Runtime**

> *«intelligence is not a fixed model capability, but a continuously developing computational process.»*

---

## 1. Architectural Philosophy & Thesis

ASCENDANT is not a chatbot, wrapper, prompt chain, or multi-agent orchestrator. It is a **Developmental Cognitive Runtime** designed to achieve autonomous problem discovery, empirical reality learning, durable long-horizon competence, and scientifically measured self-improvement.

### The Developmental Cognitive Loop
```
                         REALITY
                            │
                            ▼
                      PERCEPTION
                            │
                            ▼
                       WORLD MODEL
                            │
                            ▼
                        SELF MODEL
                            │
                            ▼
                     PREDICTION ENGINE
                            │
                            ▼
                       REALITY DELTA
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          PROBLEM          GAP        OPPORTUNITY
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                     QUESTION GENESIS
                            │
                            ▼
                    COGNITIVE COMPILER
                            │
                            ▼
                   COGNITIVE PROGRAM
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
         REASONING      EXPERIMENT       SEARCH
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    EVIDENCE ENGINE
                            │
                            ▼
                  ADVERSARIAL VERIFICATION
                            │
                            ▼
                       DECISION
                            │
                            ▼
                         ACTION
                            │
                            ▼
                         REALITY
                            │
                            ▼
                       EXPERIENCE
                            │
                            ▼
                     DEVELOPMENT
                            │
                            ▼
                     CAPABILITY GROWTH
                            │
                            ▼
                     COGNITIVE GROWTH
```

---

## 2. Core Subsystems

| Module | Location | Purpose & Mechanisms |
| :--- | :--- | :--- |
| **Runtime & Event Bus** | `zerion/runtime/` | Async priority event bus, bounded backpressure queue, dead letter queue (DLQ), security boundary, watchdog monitor, task scheduler, resource governor. |
| **Identity Core** | `zerion/identity/` | Invariant safety constraints (INV-001 through INV-005), user contract commitments, long-term durable objectives surviving process restart and failure. |
| **World Model** | `zerion/world/` | Entity-relation-state graph with strict epistemic status tagging (`OBSERVED`, `INFERRED`, `PREDICTED`, `ASSUMED`, `UNKNOWN`), causal hypotheses, and drift anomaly detection. |
| **Self Model** | `zerion/self_model/` | Introspective capability catalog, known failure modes, confidence calibration (Brier score), and capability gap identification. |
| **Pressure Field** | `zerion/pressure/` | Continuous aggregation of prediction errors, anomalies, stalled goals, and inefficiencies into unprompted problem candidates. |
| **Question Genesis & Graph** | `zerion/questions/` | First-class question DAG scored by $\text{Priority} = \frac{\text{Impact} \times \text{Uncertainty} \times \text{Gain} \times \text{Relevance}}{\text{Cost}}$. |
| **Cognitive Compiler & Cells** | `zerion/cognition/` | Dynamically compiles problem topologies into typed cognitive programs (`OBSERVE`, `DECOMPOSE`, `HYPOTHESIZE`, `CODE`, `TEST`, `ATTACK`, `VERIFY`, `SYNTHESIZE`). Multi-path reasoning and adversarial critique. |
| **Evidence Engine** | `zerion/evidence/` | Claim-evidence ledger with epistemic uncertainty levels (`KNOWN`, `SUPPORTED`, `PROBABLE`, `UNCERTAIN`, `UNKNOWN`) and formal "I don't know" assertion. |
| **Reality Experiment Engine** | `zerion/experiments/` | Empirical hypothesis testing loop in an isolated sub-process sandbox. |
| **Developmental Memory** | `zerion/memory/` | 7 distinct semantic memory stores (Episodic, Semantic, Procedural, Causal, Failure, Capability, Metacognitive) with automated experience distillation. |
| **Capability Engine** | `zerion/capabilities/` | 10-class failure taxonomy gap detector and 9-stage capability birth pipeline. |
| **Self-Curriculum & Transfer** | `zerion/learning/` | Autonomous mastery pathways and cross-domain strategy transfer testing. |
| **Long-Horizon Missions** | `zerion/missions/` | Checkpoint-backed durable mission DAGs that survive crashes and interruptions. |
| **Ascension Engine** | `zerion/evolution/` | 8-stage canary-verified self-modification and cognitive plasticity engine with automatic rollback on regression. |
| **Benchmark & Scoreboard** | `zerion/benchmarks/` | 14-category empirical benchmark suite, 5× improvement tracking, learning velocity, and developmental scoreboard. |
| **Mobile & Offline** | `zerion/integration/` | Termux/Android hardware awareness, battery throttle, and pure offline local fallback. |

---

## 3. Quickstart & CLI Usage

### Run Autonomous Developmental Cycles
```bash
# Execute 1 autonomous cycle
python3 main.py --cycle

# Execute N autonomous cycles
python3 main.py --cycles 5
```

### Run the 14-Category Scientific Benchmark Suite
```bash
python3 main.py --benchmark
```

### Run Section 47 Ultimate Design Test Loop
```bash
python3 main.py --ultimate
```

### Inspect Introspection & Developmental Scoreboard
```bash
python3 main.py --introspect
python3 main.py --scoreboard
```

---

## 4. Verification & Acceptance Testing

The entire system is covered by an automated test suite containing 44 unit and acceptance tests:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

### 10 Core Acceptance Tests Verified
1. **TEST 1 — Problem Discovery:** Autonomous detection of latent system inefficiencies without user prompting.
2. **TEST 2 — Reality Learning:** Empirical improvement measured before and after sandbox reality experiments.
3. **TEST 3 — Long-Term Memory:** Mission persistence and state recovery across hard process restarts.
4. **TEST 4 — Question Generation:** Automatic genesis of diagnostic, causal, counterfactual, and falsification questions.
5. **TEST 5 — Self-Correction:** Detection of contradictory evidence and automated belief updates.
6. **TEST 6 — Capability Gap & Birth:** Failure classification and dynamic capability genesis through sandbox validation.
7. **TEST 7 — Strategy Transfer:** Generalization of learned strategies across differing domains.
8. **TEST 8 — Controlled Self-Improvement:** Benchmark-backed self-modification with automatic rollback on regression.
9. **TEST 9 — Offline Degradation:** Seamless local heuristic fallback when cloud access is severed.
10. **TEST 10 — Long-Horizon Execution:** Multi-stage mission execution with incremental checkpointing.
11. **Ultimate Design Test:** 4-stage introspection sequence executed as a live runtime loop.
