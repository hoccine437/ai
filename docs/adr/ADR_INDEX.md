# Architecture Decision Records (ADRs)

## ADR-001: Explicit Epistemic Status in World & Evidence Models
- **Status:** Accepted
- **Context:** Standard agentic architectures flatten all representations into text or raw embeddings, failing to distinguish between ground-truth observations, probabilistic inferences, future predictions, working assumptions, and acknowledged unknowns.
- **Decision:** All facts, assertions, and state nodes in ASCENDANT must carry an explicit `EpistemicStatus`: `OBSERVED`, `INFERRED`, `PREDICTED`, `ASSUMED`, or `UNKNOWN`, coupled with confidence levels and source provenance.
- **Consequences:** The system can accurately express "I do not know" and resist adversarial hallucination.

## ADR-002: Dynamic Cognitive Compilation over Fixed Prompt Chains
- **Status:** Accepted
- **Context:** Fixed prompt pipelines (e.g. standard ReAct loops) fail when task topology varies (e.g. empirical debugging vs formal verification vs deductive search).
- **Decision:** The `CognitiveCompiler` transforms incoming goals, constraints, and unknowns into a typed DAG of `CognitiveCell` primitives (Observe, Retrieve, Hypothesize, Simulate, Code, Execute, Benchmark, Attack, Verify, Synthesize).
- **Consequences:** Different problems generate structurally distinct cognitive programs with typed data contracts between stages.

## ADR-003: Controlled Ascension with Automatic Rollback
- **Status:** Accepted
- **Context:** Uncontrolled self-modifying code leads to catastrophic forgetting, infinite loops, and safety boundary violations.
- **Decision:** Self-modification is restricted to cognitive strategies, routing tables, and procedural skills through a strict 8-stage pipeline (Hypothesis -> Static Analysis -> Unit Test -> Integration Test -> Benchmark -> Canary -> Promotion -> Rollback on regression). Core safety invariants and identity commitments are strictly immutable.
- **Consequences:** Guarantees that self-improvement is scientifically measured and safe.

## ADR-004: Multi-Store Developmental Memory Architecture
- **Status:** Accepted
- **Context:** Dumping all past events into a single vector database causes retrieval confusion and lacks procedural abstraction.
- **Decision:** ASCENDANT implements 7 specialized memory domains:
  1. Episodic (event logs with temporal ordering)
  2. Semantic (entity-relation concept graph)
  3. Procedural (tested condition-action primitives)
  4. Causal (cause-effect relationships and intervention records)
  5. Failure (classified failure modes with root-cause analysis)
  6. Capability (verified tools, cells, and skills index)
  7. Metacognitive (strategy effectiveness and compute allocation records)
- **Consequences:** Clear semantic separation, efficient indexing, and automatic distillation of repeated episodic successes into procedural skills.

## ADR-005: Pressure Field and Autonomous Question Genesis
- **Status:** Accepted
- **Context:** Conventional assistants are purely passive, responding only when prompted by a human user.
- **Decision:** The `PressureField` continuously samples the World Model and Self Model for anomalies, prediction errors, unfinished goals, and capability gaps, generating unprompted `Question` objects prioritized by Expected Information Gain over Cost.
- **Consequences:** ASCENDANT can discover problems, investigate inefficiencies, and formulate hypotheses autonomously.
