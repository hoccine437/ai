"""
CognitiveRuntime — Slice 1 coordinator.

Owns the authoritative CognitiveState and wires it to the real event bus, the Goal
Field (ObjectiveContinuityManager) and the Attention Economy (AttentionEconomy):

    runtime -> CognitiveState -> EventBus -> GoalField -> AttentionField

Architecture rules honored here:
- Events are consumed by runtime components (the attention field subscribes to
  perception / goal / task events and turns them into candidates).
- The UI observes Slice 1 through ``runtime.snapshot()`` / ``runtime.state``; Slice 1
  never depends on the UI.
- No model imports: this module (and everything it imports) is pure Python stdlib.
  The foundation runs with no LLM at all.

The runtime reuses the existing authoritative implementations:
- the single repo-wide ``AsyncEventBus`` (persisted, deterministic via
  ``dispatch_immediately`` / ``drain_now``)
- the persistent ``ObjectiveContinuityManager`` goal store (SQLite WAL)
- the ``AttentionEconomy`` with ``CognitivePriority`` scoring
"""

import asyncio
from datetime import datetime, timezone
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from zerion.runtime.event_bus import AsyncEventBus
from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.attention import (
    AttentionEconomy,
    AttentionItem,
    ResourceBudgetState,
)
from zerion.cognitive_os.objective_manager import (
    ContinuousObjective,
    ObjectiveContinuityManager,
    ObjectiveLifecycle,
)
from zerion.cognitive_os.question import (
    Question,
    QuestionLifecycle,
    QuestionStore,
)
from zerion.cognitive_os.question_genesis import QuestionGenesis
from zerion.cognitive_os.hypothesis import HypothesisLifecycle, HypothesisStore
from zerion.cognitive_os.hypothesis_engine import HypothesisEngine
from zerion.cognitive_os.belief import (
    Belief,
    BeliefLifecycle,
    BeliefStore,
)
from zerion.cognitive_os.evidence import (
    Evidence,
    EvidenceMode,
    EvidenceStore,
    EvidenceVerdict,
    Provenance,
)
from zerion.cognitive_os.experiment import Experiment, ExperimentLifecycle, ExperimentStore
from zerion.cognitive_os.experiment_engine import (
    ExperimentPermissions,
    RealityExperimentEngine,
)
from zerion.cognitive_os.episode import EpisodeMode, EpisodeStatus, EpisodeStore, ExperienceEpisode
from zerion.cognitive_os.distilled import DistilledExperience, DistilledExperienceStore, DistilledType
from zerion.cognitive_os.failure_learning import (
    FailureClassification,
    FailureLearning,
    FailureRecord,
    FailureStore,
)
from zerion.cognitive_os.experience_distillation import ExperienceDistillation
from zerion.cognitive_os.knowledge_retrieval import ExperienceReuse
from zerion.cognitive_os.capability import (
    Capability,
    CapabilityHealth,
    CapabilityRegistry,
    CapabilityStatus,
    PermissionPolicy,
)
from zerion.cognitive_os.capability_sandbox import CapabilitySandbox
from zerion.cognitive_os.capability_genesis import CapabilityGenesis
from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
from zerion.cognitive_os.performance_ledger import PerformanceLedger
from zerion.cognitive_os.provider_adapters import (
    LegacyGeminiAdapter,
    LegacyGGUFAdapter,
    LegacyOpenAIAdapter,
)
from zerion.cognitive_os.provider_health import ProviderHealthTracker
from zerion.cognitive_os.cognitive_router import CognitiveRouter
from zerion.cognitive_os.router_types import (
    CognitiveResult,
    ModelSelection,
    ResultStatus,
    RoutingMode,
    Task,
    VerificationStatus,
)
from zerion.cognitive_os.telemetry import ArchitectureTelemetry
from zerion.cognitive_os.bottlenecks import (
    BottleneckDetector,
    BottleneckReport,
    BottleneckStore,
)
from zerion.cognitive_os.improvement import (
    ImprovementProposal,
    ModificationType,
    ProposalStatus,
    ProposalStore,
    RiskLevel,
)
from zerion.cognitive_os.genome import (
    CognitiveGenome,
    GenomeManager,
    GenomeStatus,
    GenomeStore,
)
from zerion.cognitive_os.snapshots import RuntimeSnapshot, SnapshotStore
from zerion.cognitive_os.self_modification_gate import (
    GatePolicy,
    PromotionResult,
    RollbackResult,
    SelfModificationGate,
)
from zerion.cognitive_os.state import (
    AttentionStateView,
    CognitiveState,
    GoalStateView,
    LastEventView,
    PerceptionSnapshot,
    ResourceBudgetView,
    RuntimeStatus,
    StateIntegrityError,
    StateStore,
    StateVersionError,
)
from zerion.cognitive_os.telemetry_feed import TelemetryFeed
from zerion.cognitive_os.policy_store import PolicyStore, RuntimePolicies
from zerion.cognitive_os.monitor import (
    MonitorConfig,
    MonitorCycle,
    MonitorScheduler,
    MonitorStore,
)
from zerion.cognitive_os.pulse_store import PulseStore
from zerion.cognitive_os.pulse import CognitivePulse, PulseLifecycle

# The Slice 1 cognitive event vocabulary. The runtime only tracks/consumes these;
# legacy engine events (queued on the same bus) are ignored by the foundation.
_COGNITIVE_EVENT_TYPES = {
    EventType.RUNTIME_STARTED,
    EventType.RUNTIME_STOPPED,
    EventType.STATE_RECOVERED,
    EventType.PERCEPTION_RECEIVED,
    EventType.GOAL_CREATED,
    EventType.GOAL_UPDATED,
    EventType.GOAL_BLOCKED,
    EventType.GOAL_COMPLETED,
    EventType.GOAL_ABANDONED,
    EventType.ATTENTION_CANDIDATE_CREATED,
    EventType.ATTENTION_SELECTED,
    EventType.ATTENTION_DEFERRED,
    EventType.ATTENTION_DISCARDED,
    EventType.RESOURCE_WARNING,
    EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED,
    EventType.TASK_STARTED,
    EventType.TASK_COMPLETED,
    EventType.TASK_FAILED,
    # Slice 2: self-questioning vocabulary
    EventType.UNCERTAINTY_DETECTED,
    EventType.CONTRADICTION_FOUND,
    EventType.ANOMALY_DETECTED,
    EventType.GOAL_GAP_DETECTED,
    EventType.MISSING_DEPENDENCY_DETECTED,
    EventType.PREDICTION_ERROR,
    EventType.REPEATED_FAILURE_DETECTED,
    EventType.CAPABILITY_GAP,
    EventType.USER_INTERACTION,
    EventType.QUESTION_GENERATED,
    EventType.QUESTION_SELECTED,
    EventType.HYPOTHESES_GENERATED,
    # Slice 3: reality feedback vocabulary
    EventType.EXPERIMENT_PROPOSED,
    EventType.EXPERIMENT_APPROVED,
    EventType.EXPERIMENT_STARTED,
    EventType.EXPERIMENT_BLOCKED,
    EventType.EXPERIMENT_CANCELLED,
    EventType.EXPERIMENT_COMPLETED,
    EventType.EXPERIMENT_FAILED,
    EventType.OBSERVATION_RECORDED,
    EventType.EVIDENCE_ADDED,
    EventType.EVIDENCE_REJECTED,
    EventType.BELIEF_UPDATED,
    EventType.HYPOTHESIS_SUPPORTED,
    EventType.HYPOTHESIS_WEAKENED,
    EventType.HYPOTHESIS_CONTRADICTED,
    # Slice 4: experience -> distillation -> validation -> reuse vocabulary
    EventType.EPISODE_STARTED,
    EventType.EPISODE_COMPLETED,
    EventType.EXPERIENCE_DISTILLATION_STARTED,
    EventType.EXPERIENCE_DISTILLED,
    EventType.FAILURE_RECORDED,
    EventType.FAILURE_REPEATED,
    EventType.ROOT_CAUSE_PROPOSED,
    EventType.LESSON_VALIDATED,
    EventType.LESSON_WEAKENED,
    EventType.PREVENTION_RULE_CREATED,
    # Slice 5: capability genesis vocabulary
    EventType.CAPABILITY_GAP,
    EventType.CAPABILITY_DESIGNED,
    EventType.CAPABILITY_GENERATED,
    EventType.CAPABILITY_SANDBOXED,
    EventType.CAPABILITY_TESTED,
    EventType.CAPABILITY_VALIDATED,
    EventType.CAPABILITY_REGISTERED,
    EventType.CAPABILITY_DEGRADED,
    EventType.CAPABILITY_DEPRECATED,
    EventType.CAPABILITY_ROLLBACK,
    # Slice 6: routing vocabulary
    EventType.ROUTING_STARTED,
    EventType.MODEL_SELECTED,
    EventType.PROVIDER_CALLED,
    EventType.PROVIDER_SUCCEEDED,
    EventType.PROVIDER_FAILED,
    EventType.FAILOVER_STARTED,
    EventType.ROUTING_COMPLETED,
    EventType.ROUTING_FAILED,
    # Slice 7: self-improvement gate vocabulary
    EventType.BOTTLENECK_DETECTED,
    EventType.IMPROVEMENT_PROPOSED,
    EventType.MODIFICATION_ANALYSIS_STARTED,
    EventType.MODIFICATION_REJECTED,
    EventType.MODIFICATION_SANDBOXED,
    EventType.MODIFICATION_TESTED,
    EventType.MODIFICATION_BENCHMARKED,
    EventType.MODIFICATION_APPROVED,
    EventType.MODIFICATION_PROMOTED,
    EventType.MODIFICATION_ROLLED_BACK,
    EventType.GENOME_CREATED,
    EventType.GENOME_EVALUATED,
    EventType.GENOME_PROMOTED,
    EventType.GENOME_REJECTED,
}

# Event types that generate attention candidates.
_CANDIDATE_TRIGGER_TYPES = {
    EventType.PERCEPTION_RECEIVED,
    EventType.RESOURCE_WARNING,
    EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED,
    EventType.GOAL_CREATED,
    EventType.GOAL_UPDATED,
    EventType.GOAL_BLOCKED,
    EventType.GOAL_COMPLETED,
    EventType.GOAL_ABANDONED,
    EventType.TASK_STARTED,
    EventType.TASK_COMPLETED,
    EventType.TASK_FAILED,
    EventType.QUESTION_GENERATED,
}

# Goal lifecycle events. CREATE -> UPDATE -> BLOCK all target the SAME goal:
# each must not re-spend the attention budget on a duplicate candidate while
# one for that goal is already in flight (otherwise repeated lifecycle events
# starve genuinely new candidates — e.g. a generated question — of compute).
_GOAL_EVENT_TYPES = {
    EventType.GOAL_CREATED,
    EventType.GOAL_UPDATED,
    EventType.GOAL_BLOCKED,
    EventType.GOAL_COMPLETED,
    EventType.GOAL_ABANDONED,
}

# Slice 2: internal triggers consumed by QuestionGenesis. Each generates structured
# questions which are then published as QUESTION_GENERATED events and compete for
# attention like any other candidate. Voice events are deliberately NOT here.
_QUESTION_TRIGGER_TYPES = {
    EventType.UNCERTAINTY_DETECTED,
    EventType.CONTRADICTION_FOUND,
    EventType.ANOMALY_DETECTED,
    EventType.GOAL_GAP_DETECTED,
    EventType.MISSING_DEPENDENCY_DETECTED,
    EventType.PREDICTION_ERROR,
    EventType.REPEATED_FAILURE_DETECTED,
    EventType.CAPABILITY_GAP,
    EventType.USER_INTERACTION,
    # Slice 7: a significant bottleneck is an internal uncertainty.
    EventType.BOTTLENECK_DETECTED,
}


class CognitiveRuntime:
    """Owns CognitiveState and drives the event bus, goal field and attention field."""

    def __init__(self,
                 data_dir: str = "data",
                 event_bus: Optional[AsyncEventBus] = None,
                 objectives: Optional[ObjectiveContinuityManager] = None,
                 attention: Optional[AttentionEconomy] = None,
                 cpu_warning_threshold: float = 85.0,
                 cpu_degraded_threshold: float = 60.0,
                 stale_event_window_s: float = 60.0,
                 experiment_permissions: Optional[ExperimentPermissions] = None,
                 models_dir: Optional[str] = None,
                 security: Optional[Any] = None,
                 identity: Optional[Any] = None,
                 self_model: Optional[Any] = None,
                 readiness: Optional[Callable[[], Dict[str, Any]]] = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Engine-owned sources the runtime may draw on for the ZERION
        # identity layer (canonical IdentityCore, self-model capability
        # catalog, live readiness probe). Optional: the runtime stays
        # functional standalone with its own registries.
        self._identity = identity
        self._self_model = self_model
        self._readiness = readiness

        self.event_bus = event_bus or AsyncEventBus(db_path=str(self.data_dir / "cognitive_events.db"))
        self.objectives = objectives or ObjectiveContinuityManager(
            db_path=str(self.data_dir / "continuous_objectives.db"), strict_load=True)
        self.attention = attention or AttentionEconomy(capacity_slots=3)
        # Runtime repair: observable inference records, decision policy
        # (principle 9) and user learning (principle 8). All three are real
        # runtime state — never fabricated metrics.
        from zerion.cognitive_os.decision_policy import DecisionPolicy
        from zerion.cognitive_os.inference_ledger import InferenceLedger
        from zerion.cognitive_os.user_learning import UserLearningStore
        self.inference_ledger = InferenceLedger()
        self.decision_policy = DecisionPolicy()
        self.user_learning = UserLearningStore(data_dir=str(self.data_dir))
        # Goal ids whose attention candidate was already submitted this session
        # (dedupes CREATE -> UPDATE -> BLOCK re-events so repeated lifecycle
        # events cannot starve genuinely new candidates of compute budget).
        self._goal_candidates_seen = set()
        self.cpu_warning_threshold = cpu_warning_threshold
        self.cpu_degraded_threshold = cpu_degraded_threshold
        self.stale_event_window_s = stale_event_window_s

        # Slice 2: self-questioning layer — Question Field + Hypothesis Engine,
        # wired through the same bus / attention / goal field.
        self.question_store = QuestionStore(db_path=str(self.data_dir / "question_field.db"),
                                            strict_load=True)
        self.hypothesis_store = HypothesisStore(db_path=str(self.data_dir / "hypotheses.db"),
                                                strict_load=True)
        self.question_genesis = QuestionGenesis(question_store=self.question_store,
                                                objectives=self.objectives)
        self.hypothesis_engine = HypothesisEngine(hypothesis_store=self.hypothesis_store,
                                                  question_store=self.question_store)

        # Slice 3: reality feedback — Experiment / Evidence / Belief field,
        # wired through the same bus. Safety gates default to fully locked down.
        self.experiment_store = ExperimentStore(db_path=str(self.data_dir / "experiments.db"),
                                                strict_load=True)
        self.evidence_store = EvidenceStore(db_path=str(self.data_dir / "cognitive_evidence.db"),
                                            strict_load=True)
        self.belief_store = BeliefStore(db_path=str(self.data_dir / "beliefs.db"),
                                        strict_load=True)
        self.reality_experiments = RealityExperimentEngine(
            experiment_store=self.experiment_store,
            evidence_store=self.evidence_store,
            belief_store=self.belief_store,
            hypothesis_store=self.hypothesis_store,
            question_store=self.question_store,
            permissions=experiment_permissions or ExperimentPermissions(),
        )

        # Slice 4: experience -> distill -> validate -> reuse. Episodic experience,
        # procedural knowledge, failure knowledge and validated rules live in
        # separate stores (never one generic memory dump), all corruption-safe.
        self.episode_store = EpisodeStore(db_path=str(self.data_dir / "experience_episodes.db"),
                                          strict_load=True)
        self.distilled_store = DistilledExperienceStore(
            db_path=str(self.data_dir / "distilled_experiences.db"), strict_load=True)
        self.failure_store = FailureStore(db_path=str(self.data_dir / "failures.db"),
                                          strict_load=True)
        self.failure_learning = FailureLearning(failure_store=self.failure_store)
        self.experience_distillation = ExperienceDistillation(
            episode_store=self.episode_store,
            distilled_store=self.distilled_store,
            failure_store=self.failure_store,
            evidence_store=self.evidence_store,
        )
        self.experience_reuse = ExperienceReuse(distilled_store=self.distilled_store)

        # Slice 5: capability genesis. Generated artifacts are untrusted until
        # sandbox + tests + policy + registry prove them; the sandbox reuses the
        # legacy ExecutionSandbox subprocess layer with added isolation.
        self.capability_registry = CapabilityRegistry(
            db_path=str(self.data_dir / "cognitive_capabilities.db"), strict_load=True)
        self.capability_sandbox = CapabilitySandbox()
        self.capability_genesis = CapabilityGenesis(
            registry=self.capability_registry,
            sandbox=self.capability_sandbox,
            distilled_store=self.distilled_store,
            failure_store=self.failure_store,
            permission_policy=PermissionPolicy(),
        )

        # Slice 6: cognitive routing. The runtime does not care which provider
        # supplies its cognitive substrate. Provider health is proven by real
        # call outcomes, historical performance comes from the persistent
        # outcome ledger (cold start = INSUFFICIENT_DATA, never invented), and
        # local GGUF discovery is real file scanning with safety checks. The
        # router emits its lifecycle on the same single bus.
        self.provider_health = ProviderHealthTracker()
        self.performance_ledger = PerformanceLedger(
            db_path=str(self.data_dir / "performance_ledger.db"), strict_load=True)
        self.local_models = LocalModelDiscovery(
            models_dir=models_dir or str(self.data_dir / "models"))
        self.cognitive_router = CognitiveRouter(
            health=self.provider_health,
            ledger=self.performance_ledger,
            local_models=self.local_models,
            emit=self._emit_routing_event,
        )
        # OpenAI: REMOVED — Gemini is the sole authoritative provider.
        # GGUF: REMOVED — local model is not used.
        self.cognitive_router.register_provider(
            LegacyGeminiAdapter(),
            configured=bool(os.environ.get("GEMINI_API_KEY", "")),
            integration_implemented=True)  # real Gemini API integration
        # LegacyGGUFAdapter intentionally NOT registered — local model removed.

        # ZERION runtime identity & tool layer. The local model is only the
        # reasoning engine; these own the identity/context, the executable
        # tool registry and the bounded self-critic for the live loop.
        from zerion.cognitive_os.zerion_context import ZerionRuntimeContext
        from zerion.cognitive_os.tool_router import ZerionToolRouter
        from zerion.cognitive_os.self_critic import ZerionSelfCritic
        self.zerion_context = ZerionRuntimeContext(
            self, identity=self._identity, self_model=self._self_model,
            readiness=self._readiness)
        self.tool_router = ZerionToolRouter(
            self, identity=self._identity, self_model=self._self_model,
            readiness=self._readiness)
        self.self_critic = ZerionSelfCritic(self)

        # Master intelligence: 21 specialized agents + 100 real tools.
        # Zerion selects the best agent(s) for each task.
        try:
            from zerion.agents.registry import AgentRegistry
            from zerion.tools.registry import ToolRegistry
            self.agent_registry = AgentRegistry()
            self.master_tools = ToolRegistry()
        except Exception:
            self.agent_registry = None
            self.master_tools = None

        # Intelligence pipeline: SituationModel → Uncertainty → Strategy →
        # Prediction → SelfModel. This replaces keyword-based _cognitive_pre_reason.
        try:
            from zerion.intelligence import CognitiveEngine
            self.cognitive_engine = CognitiveEngine()
        except Exception:
            self.cognitive_engine = None

        # Slice 7: self-improvement gate. Real telemetry -> evidence-required
        # bottleneck detection -> improvement proposals -> static analysis /
        # risk policy / tests / baseline-vs-candidate benchmark -> promotion or
        # rejection, with atomic snapshots, versioned genomes and rollback.
        # No unrestricted autonomous source modification. Provider-independent.
        self.architecture_telemetry = ArchitectureTelemetry(
            db_path=str(self.data_dir / "architecture_telemetry.db"),
            strict_load=True)
        self.bottleneck_store = BottleneckStore(
            db_path=str(self.data_dir / "bottlenecks.db"), strict_load=True)
        self.bottleneck_detector = BottleneckDetector(
            telemetry=self.architecture_telemetry, store=self.bottleneck_store)
        self.proposal_store = ProposalStore(
            db_path=str(self.data_dir / "proposals.db"), strict_load=True)
        self.genome_store = GenomeStore(
            db_path=str(self.data_dir / "genomes.db"), strict_load=True)
        self.genome_manager = GenomeManager(store=self.genome_store)
        self.snapshot_store = SnapshotStore(
            db_path=str(self.data_dir / "snapshots.db"), strict_load=True)
        # The canonical SecurityBoundary (when provided) is wired into the
        # self-modification gate: self-modification can never bypass it.
        self.self_modification_gate = SelfModificationGate(
            sandbox=self.capability_sandbox,
            policy=GatePolicy(allow_low_auto=True, allow_medium_auto=False),
            security=security)

        # Slice 8: CognitivePulse — the persistent, event-driven coordinator.
        # It owns no engines: it reacts to bus events, schedules work through
        # the priority queue, enforces budgets/cooldowns/dedup/offline modes,
        # and routes every subsystem call through the existing Slices 1-7
        # components on the single bus.
        self.pulse_store = PulseStore(
            db_path=str(self.data_dir / "pulse_store.db"), strict_load=True)
        self.policy_store = PolicyStore(
            db_path=str(self.data_dir / "runtime_policies.db"), strict_load=True)
        self.runtime_policies = RuntimePolicies(self.policy_store)
        self.telemetry_feed = TelemetryFeed(self.architecture_telemetry)
        self.cognitive_pulse = CognitivePulse(
            runtime=self, store=self.pulse_store)

        # Slice 8: background monitor loop. Cadence-driven OBSERVE -> DETECT ->
        # PERSISTENT -> PROPOSE (opt-in) -> REGRESSION -> AUTO-ROLLBACK over the
        # SAME Slice 7 machinery — no duplicate detector/gate. run_once() can be
        # invoked explicitly (tests, demos); start() runs the background cadence.
        self.monitor = MonitorScheduler(
            runtime=self,
            config=MonitorConfig(interval_s=30.0, persistent_cycles=3,
                                 auto_rollback=True, auto_propose=False),
            store=MonitorStore(db_path=str(self.data_dir / "monitor.db"),
                               strict_load=True))

        self.state_store = StateStore(db_path=str(self.data_dir / "cognitive_state.db"))
        self.state = self._load_or_init_state()
        self._running = False

        # The runtime consumes real events from the bus.
        self.event_bus.subscribe_all(self._on_event)

    # --- State lifecycle --------------------------------------------------------

    def _load_or_init_state(self) -> CognitiveState:
        if self.objectives.load_errors:
            state = CognitiveState()
            state.runtime_status = RuntimeStatus.RECOVERING
            state.recovery_error = "Goal store load error: " + self.objectives.load_errors[0]
            return state
        try:
            if self.state_store.exists():
                loaded = self.state_store.load()
                loaded.runtime_status = RuntimeStatus.INITIALIZING
                return loaded
            return CognitiveState()
        except (StateIntegrityError, StateVersionError) as e:
            state = CognitiveState()
            state.runtime_status = RuntimeStatus.RECOVERING
            state.recovery_error = f"{type(e).__name__}: {e}"
            return state

    async def tick_pulse(self, budget: int = 1) -> int:
        """Drive the CognitivePulse scheduler for up to ``budget`` tick passes.

        The pulse executes at most one work item per tick and returns cheaply
        when idle; a bounded budget lets callers (flywheel cycles, the engine's
        heartbeat cadence, UI server loops) drain queued runtime work without
        unbounded loops. Returns the number of tick passes actually executed.
        """
        executed = 0
        for _ in range(max(0, budget)):
            if not self._running:
                break
            if self.cognitive_pulse.state not in (
                    PulseLifecycle.RUNNING, PulseLifecycle.DEGRADED):
                break
            await self.cognitive_pulse.tick()
            executed += 1
        return executed

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self.state.runtime_status in (RuntimeStatus.RECOVERING, RuntimeStatus.ERROR):
            await self.event_bus.publish(Event(
                event_type=EventType.STATE_RECOVERED,
                payload={"state_id": self.state.state_id, "recovery_error": self.state.recovery_error},
                source="cognitive_runtime",
                priority=90,
            ), dispatch_immediately=True)
        self.state.runtime_status = RuntimeStatus.RUNNING
        self.state.recovery_error = None
        await self.event_bus.publish(Event(
            event_type=EventType.RUNTIME_STARTED,
            payload={"state_id": self.state.state_id},
            source="cognitive_runtime",
            priority=95,
        ), dispatch_immediately=True)
        # Slice 8: the CognitivePulse joins the runtime lifecycle.
        await self.cognitive_pulse.start()
        self._sync_state()
        self.persist_state()

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.state.runtime_status = RuntimeStatus.STOPPED
        await self.event_bus.publish(Event(
            event_type=EventType.RUNTIME_STOPPED,
            payload={"state_id": self.state.state_id},
            source="cognitive_runtime",
            priority=95,
        ), dispatch_immediately=True)
        # Slice 8: the CognitivePulse shuts down with the runtime.
        await self.cognitive_pulse.shutdown()
        self._sync_state()
        self.persist_state()

    def persist_state(self) -> None:
        self.state_store.put(self.state)

    def snapshot(self) -> Dict[str, Any]:
        """UI observation point: a plain dict of the authoritative state."""
        return self.state.to_dict()

    # --- Perception & resources -------------------------------------------------

    def _apply_resource_budget(self, cpu_percent: float) -> None:
        if cpu_percent >= self.cpu_warning_threshold:
            compute_units = 0.6
        elif cpu_percent >= self.cpu_degraded_threshold:
            compute_units = 0.8
        else:
            compute_units = 1.0
        self.attention.set_budget(
            compute_units=compute_units,
            concurrent_workload=0,
        )

    async def ingest_perception(self, cpu_percent: float, memory_mb: float,
                                compute_tier: str = "UNKNOWN",
                                source: str = "runtime") -> None:
        self.state.perception = PerceptionSnapshot(
            cpu_percent=float(cpu_percent),
            memory_mb=float(memory_mb),
            compute_tier=compute_tier,
            source=source,
            observed_at=time.time(),
        )
        self._apply_resource_budget(float(cpu_percent))

        metrics = {
            "urgency": max(0.05, min(1.0, float(cpu_percent) / 100.0)),
            "importance": 0.7,
            "uncertainty": 0.5,
            "novelty": 0.4,
            "goal_relevance": 0.6,
            "expected_information_gain": 0.5,
            "expected_utility": 0.5,
            "risk": 0.2,
            "resource_cost": 0.2,
            "api_cost": 0.0,
            "estimated_latency_ms": 10.0,
        }
        await self.event_bus.publish(Event(
            event_type=EventType.PERCEPTION_RECEIVED,
            payload={
                "cpu_percent": float(cpu_percent),
                "memory_mb": float(memory_mb),
                "compute_tier": compute_tier,
                "source": source,
                "attention_metrics": metrics,
            },
            source=source,
            priority=60,
        ), dispatch_immediately=True)

        if float(cpu_percent) >= self.cpu_warning_threshold:
            warning_metrics = dict(metrics)
            warning_metrics.update({
                "urgency": 0.9,
                "importance": 0.9,
                "goal_relevance": 0.8,
                "risk": 0.4,
                "resource_cost": 0.4,
            })
            await self.event_bus.publish(Event(
                event_type=EventType.RESOURCE_WARNING,
                payload={
                    "warning": f"System resource degradation detected: cpu={cpu_percent:.1f}%",
                    "cpu_percent": float(cpu_percent),
                    "attention_metrics": warning_metrics,
                },
                source="resource_governor",
                priority=90,
            ), dispatch_immediately=True)

        self._sync_state()
        self.persist_state()

    # --- Goals ------------------------------------------------------------------

    async def create_goal(self, objective: str, purpose: str = "",
                          priority: int = 80,
                          dependencies: Optional[List[str]] = None,
                          success_criteria: Optional[List[str]] = None,
                          abandonment_criteria: Optional[List[str]] = None,
                          next_action: str = "",
                          goal_id: Optional[str] = None) -> ContinuousObjective:
        goal = self.objectives.create_goal(
            objective=objective,
            purpose=purpose,
            priority=priority,
            dependencies=dependencies,
            success_criteria=success_criteria,
            abandonment_criteria=abandonment_criteria,
            next_action=next_action,
            goal_id=goal_id,
        )
        await self._publish_goal_event(EventType.GOAL_CREATED, goal)
        return goal

    async def activate_goal(self, goal_id: str) -> ContinuousObjective:
        goal = self.objectives.activate(goal_id)
        await self._publish_goal_event(EventType.GOAL_UPDATED, goal, note="activated")
        return goal

    async def set_goal_progress(self, goal_id: str, progress: float,
                                note: str = "", evidence: Optional[str] = None) -> ContinuousObjective:
        goal = self.objectives.set_progress(goal_id, progress, note=note, evidence=evidence)
        event_type = EventType.GOAL_COMPLETED if goal.status == ObjectiveLifecycle.COMPLETED else EventType.GOAL_UPDATED
        await self._publish_goal_event(event_type, goal, note=note)
        return goal

    async def block_goal(self, goal_id: str, reason: str) -> ContinuousObjective:
        goal = self.objectives.block(goal_id, reason)
        await self._publish_goal_event(EventType.GOAL_BLOCKED, goal, note=reason)
        return goal

    async def unblock_goal(self, goal_id: str) -> ContinuousObjective:
        goal = self.objectives.unblock(goal_id)
        await self._publish_goal_event(EventType.GOAL_UPDATED, goal, note="unblocked")
        return goal

    async def pause_goal(self, goal_id: str) -> ContinuousObjective:
        goal = self.objectives.pause(goal_id)
        await self._publish_goal_event(EventType.GOAL_UPDATED, goal, note="paused")
        return goal

    async def resume_goal(self, goal_id: str) -> ContinuousObjective:
        goal = self.objectives.resume(goal_id)
        await self._publish_goal_event(EventType.GOAL_UPDATED, goal, note="resumed")
        return goal

    async def complete_goal(self, goal_id: str, note: str = "") -> ContinuousObjective:
        goal = self.objectives.complete(goal_id, note)
        await self._publish_goal_event(EventType.GOAL_COMPLETED, goal, note=note)
        return goal

    async def abandon_goal(self, goal_id: str, reason: str = "") -> ContinuousObjective:
        goal = self.objectives.abandon(goal_id, reason)
        await self._publish_goal_event(EventType.GOAL_ABANDONED, goal, note=reason)
        return goal

    async def set_goal_next_action(self, goal_id: str, next_action: str) -> ContinuousObjective:
        goal = self.objectives.set_next_action(goal_id, next_action)
        await self._publish_goal_event(EventType.GOAL_UPDATED, goal, note="next_action")
        return goal

    async def _publish_goal_event(self, event_type: EventType, goal: ContinuousObjective,
                                  note: str = "") -> None:
        await self.event_bus.publish(Event(
            event_type=event_type,
            payload={
                "goal_id": goal.objective_id,
                "objective": goal.title,
                "status": goal.status.value,
                "progress": round(goal.progress, 4),
                "note": note,
                "attention_metrics": {
                    "urgency": 0.6,
                    "importance": 0.8,
                    "uncertainty": 0.4,
                    "novelty": 0.4,
                    "goal_relevance": 1.0,
                    "expected_information_gain": 0.6,
                    "expected_utility": 0.7,
                    "risk": 0.15,
                    "resource_cost": 0.3,
                    "api_cost": 0.0,
                    "estimated_latency_ms": 20.0,
                },
            },
            source="goal_field",
            priority=70,
        ), dispatch_immediately=True)
        self._sync_state()
        self.persist_state()

    # --- Event consumption ------------------------------------------------------

    async def _on_event(self, event: Event) -> None:
        """Runtime component consuming real bus events."""
        if event.event_type not in _COGNITIVE_EVENT_TYPES:
            return
        self.state.last_event = LastEventView(
            event_id=event.event_id,
            event_type=event.event_type.value,
            sequence=event.sequence,
            timestamp=event.timestamp,
            source=event.source,
        )

        # Slice 2: internal triggers -> QuestionGenesis -> QUESTION_GENERATED.
        if event.event_type in _QUESTION_TRIGGER_TYPES:
            await self._handle_question_trigger(event)
            return

        if event.event_type in _CANDIDATE_TRIGGER_TYPES:
            if self._is_stale(event):
                self.state.stale_events_discarded += 1
                self.state.touch()
                return
            item = self._candidate_from_event(event)
            if (event.event_type in _GOAL_EVENT_TYPES
                    and item.goal_id
                    and item.goal_id in self._goal_candidates_seen):
                # Same-goal re-event (CREATE -> UPDATE -> BLOCK): this goal's
                # attention candidate was already submitted once this session;
                # do not spend budget on a duplicate (the pulse's GOAL_REVIEW
                # surfaces urgency changes like blocked goals separately).
                return
            if event.event_type in _GOAL_EVENT_TYPES and item.goal_id:
                self._goal_candidates_seen.add(item.goal_id)
            self.attention.submit(item)
            # Slice 2: the attention field is the authoritative question priority.
            if event.event_type == EventType.QUESTION_GENERATED and event.payload.get("question_id"):
                self._sync_question_priority(event.payload["question_id"], item.priority)
            await self.event_bus.publish(Event(
                event_type=EventType.ATTENTION_CANDIDATE_CREATED,
                payload={"item_id": item.item_id, "topic": item.topic,
                         "priority": item.priority, "source": event.event_type.value},
                source="attention_field",
                priority=50,
            ), dispatch_immediately=True)
            await self._process_attention()
        elif event.event_type == EventType.ATTENTION_SELECTED:
            payload = event.payload
            self.state.current_focus = payload.get("topic", "")
            self.state.attention.current_focus_id = payload.get("item_id")
            self.state.touch()
            # Slice 2: a selected question flows into hypothesis generation.
            qid = payload.get("question_id")
            if qid:
                await self._mark_question_selected(qid)
            # The selection's focus processing is complete: release its
            # concurrency slot so the attention field never deadlocks once
            # max_concurrent selections have been made.
            self.attention.release_slot()
        elif event.event_type == EventType.QUESTION_SELECTED:
            qid = event.payload.get("question_id")
            q = self.question_store.get(qid) if qid else None
            if q is not None and q.status == QuestionLifecycle.SELECTED:
                await self._generate_hypotheses(q)
        elif event.event_type == EventType.HYPOTHESES_GENERATED:
            # Slice 3: competing hypotheses immediately get controlled experiments
            # planned (PROPOSED only — approval and execution are explicit gates).
            qid = event.payload.get("question_id")
            if qid:
                await self._plan_experiments(qid)
        elif event.event_type == EventType.EPISODE_COMPLETED:
            # Slice 4: a completed episode is distilled and revalidated by a real
            # runtime component (never by the UI).
            eid = event.payload.get("episode_id")
            if eid:
                await self._after_episode_completed(eid)
        elif event.event_type in (EventType.ATTENTION_DEFERRED, EventType.ATTENTION_DISCARDED):
            self.state.touch()

    def _candidate_from_event(self, event: Event) -> AttentionItem:
        payload = event.payload
        topic = payload.get("objective", payload.get("warning",
                        payload.get("topic", event.event_type.value)))
        defaults: Dict[str, Any] = {
            "topic": topic,
            "source": event.event_type.value,
            "urgency": 0.5,
            "importance": 0.6,
            "uncertainty": 0.5,
            "novelty": 0.4,
            "goal_relevance": 0.5,
            "expected_information_gain": 0.5,
            "expected_utility": 0.5,
            "risk": 0.2,
            "resource_cost": 0.2,
            "api_cost": 0.0,
            "estimated_latency_ms": 20.0,
        }
        if event.event_type == EventType.PERCEPTION_RECEIVED:
            cpu = float(payload.get("cpu_percent", 0.0))
            defaults.update({
                "topic": f"perception:{payload.get('source', 'runtime')}",
                "urgency": max(0.05, min(1.0, cpu / 100.0)),
                "importance": 0.7,
                "goal_relevance": 0.8 if self._has_active_goals() else 0.5,
            })
        elif event.event_type in (EventType.RESOURCE_WARNING,
                                  EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED):
            defaults.update({"urgency": 0.9, "importance": 0.9, "goal_relevance": 0.8, "risk": 0.4})
        elif event.event_type in (EventType.GOAL_CREATED, EventType.GOAL_UPDATED,
                                  EventType.GOAL_BLOCKED, EventType.GOAL_COMPLETED,
                                  EventType.GOAL_ABANDONED):
            defaults.update({"goal_relevance": 1.0, "importance": 0.8})
        elif event.event_type == EventType.TASK_FAILED:
            defaults.update({"urgency": 0.8, "importance": 0.7, "risk": 0.3})

        overrides = payload.get("attention_metrics")
        if isinstance(overrides, dict):
            defaults.update({k: v for k, v in overrides.items() if k in (
                "urgency", "importance", "uncertainty", "novelty", "goal_relevance",
                "expected_information_gain", "expected_utility", "risk",
                "resource_cost", "api_cost", "estimated_latency_ms")})

        return AttentionItem(
            topic=defaults["topic"],
            source=defaults["source"],
            urgency=defaults["urgency"],
            importance=defaults["importance"],
            uncertainty=defaults["uncertainty"],
            novelty=defaults["novelty"],
            objective_relevance=defaults["goal_relevance"],
            expected_information_gain=defaults["expected_information_gain"],
            expected_utility=defaults["expected_utility"],
            risk=defaults["risk"],
            resource_cost=defaults["resource_cost"],
            api_cost=defaults["api_cost"],
            estimated_latency_ms=defaults["estimated_latency_ms"],
            goal_id=payload.get("goal_id"),
            payload=self._candidate_payload(event),
        )

    def _candidate_payload(self, event: Event) -> Dict[str, Any]:
        """Origin metadata for attention candidates; question links pass through so
        selected questions can flow into hypothesis generation."""
        payload: Dict[str, Any] = {
            "origin_event_id": event.event_id,
            "origin_event_type": event.event_type.value,
        }
        qid = event.payload.get("question_id")
        if qid:
            payload["question_id"] = qid
        return payload

    def _is_stale(self, event: Event) -> bool:
        """True if the event is older than the staleness window (discarded, not processed)."""
        try:
            ts = datetime.fromisoformat(event.timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_seconds = time.time() - ts.timestamp()
            return age_seconds > self.stale_event_window_s
        except Exception:
            # Unparseable timestamps are not silently treated as stale.
            return False

    def _has_active_goals(self) -> bool:
        return any(g.is_active for g in self.objectives.list_active_objectives())

    async def _process_attention(self) -> None:
        decision = self.attention.evaluate()
        for item in decision.selected:
            await self.event_bus.publish(Event(
                event_type=EventType.ATTENTION_SELECTED,
                payload={"item_id": item.item_id, "topic": item.topic,
                         "priority": item.priority, "goal_id": item.goal_id,
                         "source": item.source,
                         "question_id": (item.payload or {}).get("question_id")},
                source="attention_field",
                priority=50,
            ), dispatch_immediately=True)
        for item in decision.deferred:
            await self.event_bus.publish(Event(
                event_type=EventType.ATTENTION_DEFERRED,
                payload={"item_id": item.item_id, "topic": item.topic,
                         "priority": item.priority,
                         "reason": decision.reasons.get(item.item_id, "deferred"),
                         "goal_id": item.goal_id, "source": item.source},
                source="attention_field",
                priority=40,
            ), dispatch_immediately=True)
        for item in decision.discarded:
            await self.event_bus.publish(Event(
                event_type=EventType.ATTENTION_DISCARDED,
                payload={"item_id": item.item_id, "topic": item.topic,
                         "priority": item.priority,
                         "reason": decision.reasons.get(item.item_id, "discarded"),
                         "goal_id": item.goal_id, "source": item.source},
                source="attention_field",
                priority=40,
            ), dispatch_immediately=True)
        self._sync_state()
        self.persist_state()

    # --- Slice 2: question flow -------------------------------------------------

    async def _handle_question_trigger(self, event: Event) -> None:
        """QuestionGenesis consumes the trigger and publishes QUESTION_GENERATED per
        new question; each then competes for attention through the normal path.

        Slice 3: a contradiction that names an existing belief (payload['beliefs'])
        materializes that belief in the Belief Field so evidence can later revise it.
        """
        linked_beliefs: List[str] = []
        if event.event_type == EventType.CONTRADICTION_FOUND:
            named = event.payload.get("beliefs")
            if isinstance(named, list):
                for statement in named:
                    belief = self._ensure_rule_belief(statement, event)
                    if belief is not None and belief.belief_id not in linked_beliefs:
                        linked_beliefs.append(belief.belief_id)
        questions = self.question_genesis.generate(event)
        for q in questions:
            # Link beliefs named by the trigger to the question so evidence later
            # recorded against them revises them (Slice 3 belief field).
            for bid in linked_beliefs:
                if bid not in q.related_beliefs:
                    q.related_beliefs.append(bid)
            self.question_store.put(q)
            await self.event_bus.publish(Event(
                event_type=EventType.QUESTION_GENERATED,
                payload={
                    "question_id": q.question_id,
                    "topic": q.question,
                    "goal_id": q.related_goal,
                    "source_kind": q.source_kind.value,
                    "source": q.source,
                    "attention_metrics": {
                        "urgency": q.urgency,
                        "importance": 0.5,
                        "uncertainty": q.uncertainty,
                        "novelty": q.novelty,
                        "goal_relevance": q.goal_relevance,
                        "expected_information_gain": q.expected_information_gain,
                        "expected_utility": q.expected_decision_impact,
                        "risk": q.risk,
                        "resource_cost": q.estimated_cost,
                        "api_cost": 0.0,
                        "estimated_latency_ms": 0.0,
                    },
                },
                source="question_genesis",
                priority=60,
            ), dispatch_immediately=True)
            self._sync_state()
            self.persist_state()

    def _sync_question_priority(self, question_id: str, score: float) -> None:
        """The attention field is the single authoritative question priority."""
        q = self.question_store.get(question_id)
        if q is not None:
            q.priority = round(float(score), 6)
            q.updated_at = time.time()
            self.question_store.put(q)

    async def _mark_question_selected(self, question_id: str) -> None:
        """A question won attention: QUEUED -> SELECTED, publish QUESTION_SELECTED."""
        q = self.question_store.get(question_id)
        if q is None or q.status != QuestionLifecycle.QUEUED:
            return
        q.status = QuestionLifecycle.SELECTED
        q.updated_at = time.time()
        self.question_store.put(q)
        await self.event_bus.publish(Event(
            event_type=EventType.QUESTION_SELECTED,
            payload={"question_id": q.question_id, "question": q.question,
                     "source_kind": q.source_kind.value},
            source="question_field",
            priority=60,
        ), dispatch_immediately=True)
        # The QUESTION_SELECTED handler above generates hypotheses synchronously.

    def _ensure_rule_belief(self, statement: str, event: Event) -> Optional[Belief]:
        """Materialize a belief named by an event (e.g. 'A normally precedes B')
        so evidence can revise it. Deduplicated by statement+source."""
        existing = self.belief_store.get_by_fingerprint(statement, "contradiction_detector")
        if existing is not None:
            return existing
        belief = Belief(
            statement=statement,
            source="contradiction_detector",
            confidence=0.7,
            status=BeliefLifecycle.PREDICTED,
            predictions=[
                f"'{statement}' should hold in the observed record"],
            provenance={
                "source": "contradiction_detector",
                "trigger_event": event.event_type.value,
                "trigger_payload": dict(event.payload),
            },
        )
        self.belief_store.put(belief)
        return belief

    async def _generate_hypotheses(self, q: Question) -> None:
        """Selected question -> competing hypotheses -> HYPOTHESES_GENERATED.
        Slice 3: each hypothesis materializes a Belief (status HYPOTHESIS) whose
        confidence tracks the hypothesis through evidence; experiments are planned
        but never executed here."""
        hyps = self.hypothesis_engine.generate_for_question(q)
        for h in hyps:
            belief = Belief(
                statement=h.statement,
                source="hypothesis_engine",
                confidence=h.confidence,
                status=BeliefLifecycle.HYPOTHESIS,
                predictions=list(h.predictions),
                related_hypotheses=[h.hypothesis_id],
                provenance={"source": "hypothesis_engine",
                            "question_id": q.question_id},
            )
            self.belief_store.put(belief)
            if belief.belief_id not in q.related_beliefs:
                q.related_beliefs.append(belief.belief_id)
        q.related_hypotheses = [h.hypothesis_id for h in hyps]
        q.status = QuestionLifecycle.INVESTIGATING
        q.updated_at = time.time()
        self.question_store.put(q)
        await self.event_bus.publish(Event(
            event_type=EventType.HYPOTHESES_GENERATED,
            payload={"question_id": q.question_id,
                     "hypothesis_ids": [h.hypothesis_id for h in hyps],
                     "count": len(hyps)},
            source="hypothesis_engine",
            priority=50,
        ), dispatch_immediately=True)
        self._sync_state()
        self.persist_state()

    # --- Slice 3: reality feedback pipeline -------------------------------------

    async def _plan_experiments(self, question_id: str) -> None:
        """Plan one controlled experiment per competing hypothesis (PROPOSED).
        Planning is data-only; approval/execution require explicit gates."""
        experiments = self.reality_experiments.plan_for_question(question_id)
        for exp in experiments:
            await self.event_bus.publish(Event(
                event_type=EventType.EXPERIMENT_PROPOSED,
                payload={"experiment_id": exp.experiment_id,
                         "question_id": exp.question_id,
                         "hypothesis_ids": exp.hypothesis_ids,
                         "type": exp.type.value,
                         "predictions": exp.predictions},
                source="reality_experiment_engine",
                priority=60,
            ), dispatch_immediately=True)

    async def approve_experiment(self, experiment_id: str,
                                 inputs: Optional[Dict[str, Any]] = None) -> Experiment:
        """Approve a planned experiment. Unsafe types (missing permissions) become
        BLOCKED and are never executed."""
        exp = self.experiment_store.get(experiment_id)
        if exp is None:
            raise KeyError(f"Unknown experiment {experiment_id}")
        exp = self.reality_experiments.approve(exp, inputs=inputs)
        event_type = (EventType.EXPERIMENT_APPROVED if exp.status == ExperimentLifecycle.APPROVED
                      else EventType.EXPERIMENT_BLOCKED)
        await self.event_bus.publish(Event(
            event_type=event_type,
            payload={"experiment_id": exp.experiment_id,
                     "question_id": exp.question_id,
                     "status": exp.status.value,
                     "reason": exp.rollback_info},
            source="reality_experiment_engine",
            priority=60,
        ), dispatch_immediately=True)
        return exp

    async def run_experiment(self, experiment_id: str) -> Experiment:
        """Execute an approved experiment: RUNNING -> OBSERVATION -> COMPARISON ->
        (COMPLETED with Evidence | FAILED with recorded errors)."""
        exp = self.experiment_store.get(experiment_id)
        if exp is None:
            raise KeyError(f"Unknown experiment {experiment_id}")
        await self.event_bus.publish(Event(
            event_type=EventType.EXPERIMENT_STARTED,
            payload={"experiment_id": exp.experiment_id,
                     "question_id": exp.question_id,
                     "type": exp.type.value},
            source="reality_experiment_engine",
            priority=70,
        ), dispatch_immediately=True)

        exp, evidence = self.reality_experiments.run(exp)

        if evidence is not None:
            await self.event_bus.publish(Event(
                event_type=EventType.OBSERVATION_RECORDED,
                payload={"experiment_id": exp.experiment_id,
                         "question_id": exp.question_id,
                         "observation": evidence.content,
                         "mode": evidence.provenance.mode.value},
                source=evidence.provenance.source,
                priority=50,
            ), dispatch_immediately=True)
            await self.event_bus.publish(Event(
                event_type=EventType.EVIDENCE_ADDED,
                payload={"evidence_id": evidence.evidence_id,
                         "experiment_id": exp.experiment_id,
                         "verdict": evidence.verdict.value,
                         "mode": evidence.provenance.mode.value,
                         "reliability": evidence.provenance.reliability},
                source="reality_experiment_engine",
                priority=50,
            ), dispatch_immediately=True)

        event_type = (EventType.EXPERIMENT_COMPLETED if exp.status == ExperimentLifecycle.COMPLETED
                      else EventType.EXPERIMENT_FAILED)
        await self.event_bus.publish(Event(
            event_type=event_type,
            payload={"experiment_id": exp.experiment_id,
                     "question_id": exp.question_id,
                     "status": exp.status.value,
                     "result": exp.result,
                     "errors": exp.errors,
                     "attempts": exp.attempts},
            source="reality_experiment_engine",
            priority=60,
        ), dispatch_immediately=True)
        return exp

    async def record_observation(self, *, content: Dict[str, Any], source: str,
                                 reliability: float = 0.9,
                                 mode: EvidenceMode = EvidenceMode.OBSERVED,
                                 verdict: EvidenceVerdict = EvidenceVerdict.NEUTRAL,
                                 experiment_id: Optional[str] = None,
                                 hypothesis_ids: Optional[List[str]] = None,
                                 belief_ids: Optional[List[str]] = None) -> Evidence:
        """Record an external observation (e.g. from perception) as Evidence with
        provenance. Fabricated/duplicate/mode-lying evidence raises instead of
        being recorded."""
        try:
            evidence = self.reality_experiments.record_external_observation(
                content=content, source=source, reliability=reliability, mode=mode,
                verdict=verdict, experiment_id=experiment_id,
                hypothesis_ids=hypothesis_ids, belief_ids=belief_ids)
        except Exception:
            # Rejected evidence is observable, never silently dropped.
            await self.event_bus.publish(Event(
                event_type=EventType.EVIDENCE_REJECTED,
                payload={"source": source, "content": content},
                source="reality_experiment_engine",
                priority=40,
            ), dispatch_immediately=True)
            raise
        await self.event_bus.publish(Event(
            event_type=EventType.OBSERVATION_RECORDED,
            payload={"observation": evidence.content,
                     "mode": evidence.provenance.mode.value,
                     "evidence_id": evidence.evidence_id},
            source=source,
            priority=50,
        ), dispatch_immediately=True)
        await self.event_bus.publish(Event(
            event_type=EventType.EVIDENCE_ADDED,
            payload={"evidence_id": evidence.evidence_id,
                     "verdict": evidence.verdict.value,
                     "mode": evidence.provenance.mode.value,
                     "reliability": evidence.provenance.reliability},
            source="reality_experiment_engine",
            priority=50,
        ), dispatch_immediately=True)
        return evidence

    async def evaluate_question(self, question_id: str) -> Dict[str, Any]:
        """Compare evidence, score competing hypotheses (evidence-determined, no
        model opinion) and revise related beliefs. Emits the full feedback trail:
        HYPOTHESIS_* and BELIEF_UPDATED events."""
        result = self.reality_experiments.evaluate_question(question_id)
        for item in result.get("hypotheses", []):
            hyp = self.hypothesis_store.get(item["hypothesis_id"])
            if hyp is None:
                continue
            status = hyp.status
            if status == HypothesisLifecycle.SUPPORTED:
                event_type = EventType.HYPOTHESIS_SUPPORTED
            elif status == HypothesisLifecycle.WEAKENED:
                event_type = EventType.HYPOTHESIS_WEAKENED
            elif status == HypothesisLifecycle.CONTRADICTED:
                event_type = EventType.HYPOTHESIS_CONTRADICTED
            else:
                event_type = None
            if event_type is not None:
                await self.event_bus.publish(Event(
                    event_type=event_type,
                    payload={"hypothesis_id": hyp.hypothesis_id,
                             "question_id": question_id,
                             "status": status.value,
                             "score": hyp.score},
                    source="reality_experiment_engine",
                    priority=60,
                ), dispatch_immediately=True)
        for record in result.get("revisions", []):
            if record.get("applied"):
                await self.event_bus.publish(Event(
                    event_type=EventType.BELIEF_UPDATED,
                    payload={"evidence_id": record["evidence_id"],
                             "previous_confidence": record["previous_confidence"],
                             "new_confidence": record["new_confidence"],
                             "previous_status": record["previous_status"],
                             "new_status": record["new_status"],
                             "reason": record["reason"]},
                    source=record["source"],
                    priority=50,
                ), dispatch_immediately=True)
        self._sync_state()
        self.persist_state()
        return result

    # --- Slice 4: experience -> distillation -> validation -> reuse --------------

    async def start_episode(self, context: str, goal_ids: Optional[List[str]] = None,
                            capabilities_used: Optional[List[str]] = None,
                            resources: Optional[Dict[str, Any]] = None,
                            mode: EpisodeMode = EpisodeMode.OBSERVED) -> ExperienceEpisode:
        """Begin a structured experience episode (never a plain transcript)."""
        episode = ExperienceEpisode(
            context=context,
            goal_ids=goal_ids or [],
            capabilities_used=capabilities_used or [],
            resources=resources or {},
            status=EpisodeStatus.IN_PROGRESS,
            mode=mode,
            provenance={"source": "cognitive_runtime", "created_by": "runtime"},
        )
        self.episode_store.put(episode)
        await self.event_bus.publish(Event(
            event_type=EventType.EPISODE_STARTED,
            payload={"episode_id": episode.episode_id, "context": episode.context,
                     "mode": episode.mode.value},
            source="cognitive_runtime",
            priority=50,
        ), dispatch_immediately=True)
        return episode

    async def complete_episode(self, episode_id: str, *, outcomes: Optional[List[Dict[str, Any]]] = None,
                               success: bool = False,
                               failures: Optional[List[Dict[str, Any]]] = None,
                               actions: Optional[List[Dict[str, Any]]] = None,
                               lessons: Optional[List[str]] = None) -> ExperienceEpisode:
        """Finish an episode: attach outcomes/actions, record every failure via
        FailureLearning (recurrence + escalation), then publish EPISODE_COMPLETED
        which triggers distillation + validation of lessons."""
        episode = self.episode_store.get(episode_id)
        if episode is None:
            raise KeyError(f"Unknown episode {episode_id}")
        if actions:
            episode.actions.extend(actions)
        if outcomes:
            episode.outcomes.extend(outcomes)
        if lessons:
            episode.lessons.extend(lessons)
        episode.success = bool(success)
        episode.completed_at = time.time()
        episode.status = EpisodeStatus.COMPLETED
        episode.updated_at = time.time()
        self.episode_store.put(episode)

        for failure in failures or []:
            rec = await self.record_failure(
                episode_id=episode_id,
                action=str(failure.get("action", "")),
                error=str(failure.get("error", "")),
                context=str(failure.get("context", "") or episode.context),
                classification=failure.get("classification", FailureClassification.UNKNOWN_FAILURE),
                signals=failure.get("signals"),
                recovery_attempt=str(failure.get("recovery_attempt", "")),
                recovery_result=str(failure.get("recovery_result", "")),
            )
            if rec.failure_id not in episode.failures:
                episode.failures.append(rec.failure_id)
                episode.updated_at = time.time()
                self.episode_store.put(episode)

        await self.event_bus.publish(Event(
            event_type=EventType.EPISODE_COMPLETED,
            payload={"episode_id": episode.episode_id, "success": episode.success,
                     "failure_count": len(episode.failures)},
            source="cognitive_runtime",
            priority=55,
        ), dispatch_immediately=True)
        return episode

    async def record_failure(self, *, episode_id: str, action: str, error: str,
                             context: str = "",
                             classification: FailureClassification = FailureClassification.UNKNOWN_FAILURE,
                             signals: Optional[List[str]] = None,
                             recovery_attempt: str = "",
                             recovery_result: str = "") -> FailureRecord:
        """Record one failure occurrence. Recurrences are detected by
        fingerprint; repeated failure escalates into a REPEATED_FAILURE_DETECTED
        event -> Slice 2 question -> Slice 1 attention (investigation priority
        rises — no endless repetition of the same strategy)."""
        if self.episode_store.get(episode_id) is None:
            raise KeyError(f"Unknown episode {episode_id}")
        result = self.failure_learning.record_failure(
            episode_id=episode_id, action=action, error=error, context=context,
            classification=classification, signals=signals,
            recovery_attempt=recovery_attempt, recovery_result=recovery_result)
        failure = result["failure"]
        if result["created"]:
            await self.event_bus.publish(Event(
                event_type=EventType.FAILURE_RECORDED,
                payload={"failure_id": failure.failure_id,
                         "episode_id": episode_id,
                         "classification": failure.classification.value,
                         "action": failure.action,
                         "error": failure.error,
                         "signals": failure.signals},
                source="failure_learning",
                priority=75,
            ), dispatch_immediately=True)
            await self.event_bus.publish(Event(
                event_type=EventType.ROOT_CAUSE_PROPOSED,
                payload={"hypothesis_id": result["root_cause"].hypothesis_id,
                         "failure_id": failure.failure_id,
                         "statement": result["root_cause"].statement,
                         "signals": failure.signals,
                         "status": result["root_cause"].status.value},
                source="failure_learning",
                priority=70,
            ), dispatch_immediately=True)
        else:
            await self.event_bus.publish(Event(
                event_type=EventType.FAILURE_REPEATED,
                payload={"failure_id": failure.failure_id,
                         "episode_id": episode_id,
                         "repeat_count": result["repeat_count"],
                         "action": failure.action,
                         "error": failure.error},
                source="failure_learning",
                priority=80,
            ), dispatch_immediately=True)
        if result["escalated"]:
            # Slice 2 + Slice 1: repeated failure becomes a high-priority internal
            # question that competes for attention through the normal path.
            await self.event_bus.publish(Event(
                event_type=EventType.REPEATED_FAILURE_DETECTED,
                payload={"task": failure.action,
                         "last_error": failure.error,
                         "attempts": result["repeat_count"],
                         "failure_id": failure.failure_id},
                source="failure_learning",
                priority=90,
            ), dispatch_immediately=True)
        return failure

    async def _after_episode_completed(self, episode_id: str) -> None:
        """Distill the completed episode and re-validate all pending lessons.
        Real runtime consumption — this is how experience becomes knowledge."""
        episode = self.episode_store.get(episode_id)
        if episode is None:
            return
        await self.event_bus.publish(Event(
            event_type=EventType.EXPERIENCE_DISTILLATION_STARTED,
            payload={"episode_id": episode_id},
            source="experience_distillation",
            priority=50,
        ), dispatch_immediately=True)
        produced = self.experience_distillation.distill_episode(episode)
        for item in produced:
            await self.event_bus.publish(Event(
                event_type=EventType.EXPERIENCE_DISTILLED,
                payload={"item_id": item.id, "type": item.type.value,
                         "statement": item.statement,
                         "episode_id": episode_id,
                         "validation_status": item.validation_status.value},
                source="experience_distillation",
                priority=50,
            ), dispatch_immediately=True)
            if item.type == DistilledType.FAILURE_PREVENTION_RULE:
                await self.event_bus.publish(Event(
                    event_type=EventType.PREVENTION_RULE_CREATED,
                    payload={"item_id": item.id,
                             "action": item.action,
                             "statement": item.statement,
                             "failure_id": item.provenance.get("failure_id")},
                    source="experience_distillation",
                    priority=55,
                ), dispatch_immediately=True)
        changes = self.experience_distillation.validate_lessons()
        for change in changes:
            status = change["validation_status"]
            if status == "VALIDATED":
                event_type = EventType.LESSON_VALIDATED
            elif status in ("WEAKENED", "REJECTED"):
                event_type = EventType.LESSON_WEAKENED
            else:
                continue
            await self.event_bus.publish(Event(
                event_type=event_type,
                payload={"item_id": change["id"], "type": change["type"],
                         "validation_status": status,
                         "confidence": change["confidence"],
                         "source_episodes": change["source_episodes"],
                         "counterexamples": change["counterexamples"]},
                source="experience_distillation",
                priority=60,
            ), dispatch_immediately=True)

    def retrieve_experiences(self, *, goal: str = "", problem: str = "",
                             context: str = "", failure_pattern: str = "",
                             top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve relevant distilled experiences for a future decision — the
        reuse side of the loop (deterministic, top-K, never everything)."""
        return self.experience_reuse.retrieve(
            goal=goal, problem=problem, context=context,
            failure_pattern=failure_pattern, top_k=top_k)

    # --- Slice 5: capability genesis pipeline -----------------------------------

    async def detect_capability_gaps(self) -> List[Capability]:
        """Propose NEEDED capabilities from Slice 4 evidence. Every gap becomes a
        CAPABILITY_GAP event -> Slice 2 question -> Slice 1 attention candidate:
        gaps compete for cognitive resources like everything else."""
        gaps = self.capability_genesis.detect_gaps()
        for cap in gaps:
            gap = cap.metadata.get("gap", {})
            await self.event_bus.publish(Event(
                event_type=EventType.CAPABILITY_GAP,
                payload={
                    "subject": gap.get("problem", cap.name),
                    "task": gap.get("problem", cap.name),
                    "missing_capability": cap.name,
                    "capability_id": cap.capability_id,
                    "frequency": gap.get("frequency", 0),
                    "evidence": gap.get("evidence", ""),
                    "goal_id": (gap.get("affected_goals") or [None])[0],
                },
                source="capability_genesis",
                priority=80,
            ), dispatch_immediately=True)
        return gaps

    async def design_capability(self, capability_id: str) -> Capability:
        cap = self._require_capability(capability_id)
        cap = self.capability_genesis.design(cap)
        await self.event_bus.publish(Event(
            event_type=EventType.CAPABILITY_DESIGNED,
            payload={"capability_id": cap.capability_id, "name": cap.name,
                     "version": cap.version, "type": cap.type.value},
            source="capability_genesis", priority=60),
            dispatch_immediately=True)
        return cap

    async def generate_capability(self, capability_id: str,
                                  implementation: Optional[str] = None) -> Capability:
        cap = self._require_capability(capability_id)
        cap = self.capability_genesis.generate(cap, implementation=implementation)
        await self.event_bus.publish(Event(
            event_type=EventType.CAPABILITY_GENERATED,
            payload={"capability_id": cap.capability_id, "name": cap.name,
                     "version": cap.version,
                     "untrusted": True},
            source="capability_genesis", priority=60),
            dispatch_immediately=True)
        return cap

    async def sandbox_capability(self, capability_id: str) -> Capability:
        cap = self._require_capability(capability_id)
        cap = self.capability_genesis.sandbox(cap)
        if cap.status == CapabilityStatus.SANDBOXED:
            await self.event_bus.publish(Event(
                event_type=EventType.CAPABILITY_SANDBOXED,
                payload={"capability_id": cap.capability_id, "name": cap.name,
                         "status": cap.status.value},
                source="capability_genesis", priority=60),
                dispatch_immediately=True)
        return cap

    async def test_capability(self, capability_id: str,
                              test_cases: Optional[List[Dict[str, Any]]] = None) -> Capability:
        cap = self._require_capability(capability_id)
        cap = self.capability_genesis.test(cap, test_cases=test_cases)
        passed = sum(1 for r in cap.test_results if r["passed"])
        await self.event_bus.publish(Event(
            event_type=EventType.CAPABILITY_TESTED,
            payload={"capability_id": cap.capability_id, "name": cap.name,
                     "tests": len(cap.test_results), "passed": passed,
                     "success_rate": cap.success_rate},
            source="capability_genesis", priority=60),
            dispatch_immediately=True)
        return cap

    async def validate_capability(self, capability_id: str) -> Capability:
        cap = self._require_capability(capability_id)
        cap = self.capability_genesis.validate(cap)
        if cap.status == CapabilityStatus.VALIDATED:
            await self.event_bus.publish(Event(
                event_type=EventType.CAPABILITY_VALIDATED,
                payload={"capability_id": cap.capability_id, "name": cap.name,
                         "success_rate": cap.success_rate,
                         "evidence": cap.validation_evidence},
                source="capability_genesis", priority=65),
                dispatch_immediately=True)
        return cap

    async def register_capability(self, capability_id: str) -> Capability:
        cap = self._require_capability(capability_id)
        cap = self.capability_genesis.register(cap)
        if cap.status in (CapabilityStatus.REGISTERED, CapabilityStatus.VALIDATED):
            await self.event_bus.publish(Event(
                event_type=EventType.CAPABILITY_REGISTERED,
                payload={"capability_id": cap.capability_id, "name": cap.name,
                         "version": cap.version,
                         "status": cap.status.value,
                         "pending_promotion": cap.status == CapabilityStatus.VALIDATED},
                source="capability_registry", priority=70),
                dispatch_immediately=True)
        return cap

    def execute_capability(self, capability_id: str, payload: Any) -> Dict[str, Any]:
        """Execute a registered capability on a controlled case (still sandboxed),
        record the usage outcome, and return the measured result."""
        cap = self._require_capability(capability_id)
        outcome = self.capability_genesis.execute(cap, payload)
        ok = bool(outcome.get("success") and not outcome.get("blocked"))
        cap = self.capability_genesis.record_usage(
            cap, success=ok, latency_ms=outcome.get("latency_ms", 0.0))
        return {"outcome": outcome, "capability": cap,
                "result": outcome.get("result"),
                "latency_ms": outcome.get("latency_ms", 0.0),
                "success": ok}

    async def record_capability_usage(self, capability_id: str, success: bool,
                                      latency_ms: float = 0.0,
                                      resource_cost: float = 0.0,
                                      permission_violation: bool = False) -> Capability:
        cap = self._require_capability(capability_id)
        before_status = cap.status
        before_health = cap.health
        cap = self.capability_genesis.record_usage(
            cap, success=success, latency_ms=latency_ms,
            resource_cost=resource_cost,
            permission_violation=permission_violation)
        if before_health != cap.health and cap.health == CapabilityHealth.DEGRADED:
            await self.event_bus.publish(Event(
                event_type=EventType.CAPABILITY_DEGRADED,
                payload={"capability_id": cap.capability_id, "name": cap.name,
                         "consecutive_failures": cap.consecutive_failures},
                source="capability_monitor", priority=60),
                dispatch_immediately=True)
        if before_status != cap.status and cap.status == CapabilityStatus.DEPRECATED:
            await self.event_bus.publish(Event(
                event_type=EventType.CAPABILITY_DEPRECATED,
                payload={"capability_id": cap.capability_id, "name": cap.name,
                         "consecutive_failures": cap.consecutive_failures,
                         "failure_rate": cap.failure_rate},
                source="capability_monitor", priority=60),
                dispatch_immediately=True)
        return cap

    async def promote_capability(self, name: str, version: int) -> Dict[str, Any]:
        return self.capability_genesis.promote(name, version)

    async def rollback_capability(self, name: str, reason: str) -> Dict[str, Any]:
        result = self.capability_genesis.rollback(name, reason)
        await self.event_bus.publish(Event(
            event_type=EventType.CAPABILITY_ROLLBACK,
            payload={"name": name, "ok": result["ok"],
                     "reason": result.get("reason"),
                     "restored_version": result.get("restored_version"),
                     "deactivated_version": result.get("deactivated_version")},
            source="capability_registry", priority=70),
            dispatch_immediately=True)
        return result

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        return self.capability_registry.get(capability_id)

    def list_capabilities(self, status: Optional[CapabilityStatus] = None) -> List[Capability]:
        return self.capability_registry.list(status=status)

    def _require_capability(self, capability_id: str) -> Capability:
        cap = self.capability_registry.get(capability_id)
        if cap is None:
            raise KeyError(f"Unknown capability {capability_id}")
        return cap

    # -- cognitive pre-reasoning -------------------------------------------

    async def _cognitive_pre_reason(self, task, prompt, goal_id=None):
        """Cognitive pre-reasoning: Zerion analyzes the task BEFORE
        generating a response. Returns enriched cognitive context.

        Uses the Intelligence Pipeline when available, with keyword fallback."""
        # --- NEW: Intelligence Pipeline ---
        if self.cognitive_engine is not None:
            try:
                memory_hints = []
                try:
                    for ep in self.episode_store.list()[-20:]:
                        ctx = str(getattr(ep, 'context', '') or '')
                        if any(w in ctx.lower() for w in prompt.lower().split() if len(w) > 3):
                            memory_hints.append(ctx[:100])
                except Exception:
                    pass
                past_failures = []
                try:
                    for f in self.failure_store.list_failures()[-10:]:
                        action = str(getattr(f, 'action', '') or '')
                        error = str(getattr(f, 'error', '') or '')
                        if action or error:
                            past_failures.append(f'{action}: {error}')
                except Exception:
                    pass
                tool_names = []
                try:
                    tool_names = [n for n, _ in self.tool_router.describe_pairs()]
                except Exception:
                    pass
                ctx = await self.cognitive_engine.pre_reason(
                    user_input=prompt,
                    memory_context='; '.join(memory_hints[:5]) if memory_hints else '',
                    available_tools=tool_names,
                    past_failures=past_failures,
                )
                if goal_id:
                    ctx = f'ACTIVE GOAL: {goal_id}\n{ctx}'
                return ctx
            except Exception:
                pass
        # --- LEGACY FALLBACK ---
        parts = []
        prompt_lower = prompt.lower().strip()

        # 1) UNDERSTANDING
        intent = self._classify_intent(prompt_lower)
        parts.append("INTENT: " + intent)

        # 2) GOAL ALIGNMENT
        if goal_id:
            parts.append("ACTIVE GOAL: " + str(goal_id))

        # 3) MEMORY RETRIEVAL
        memory_hints = []
        try:
            episodes = self.episode_store.list()[-20:]
            for ep in episodes:
                ctx = str(getattr(ep, "context", "") or "")
                if any(w in ctx.lower() for w in prompt_lower.split() if len(w) > 3):
                    memory_hints.append(ctx[:100])
        except Exception:
            pass
        if memory_hints:
            parts.append("RELEVANT MEMORY: " + "; ".join(memory_hints[:3]))

        # 4) STRATEGY
        strategy = self._select_strategy(prompt_lower, intent)
        parts.append("STRATEGY: " + strategy)

        # 5) UNCERTAINTY
        uncertainty = []
        if "?" in prompt:
            uncertainty.append("User expects an answer")
        if any(w in prompt_lower for w in ["how", "why", "explain"]):
            uncertainty.append("Depth of explanation needed")
        if any(w in prompt_lower for w in ["fix", "solve", "debug"]):
            uncertainty.append("Problem diagnosis required")
        if uncertainty:
            parts.append("CONSIDERATIONS: " + "; ".join(uncertainty))

        # 6) FAILURE AWARENESS
        try:
            failures = self.failure_store.list_failures()[-10:]
            for f in failures:
                action = str(getattr(f, "action", "") or "")
                error = str(getattr(f, "error", "") or "")
                if any(w in (action + error).lower()
                       for w in prompt_lower.split() if len(w) > 3):
                    parts.append("PAST FAILURE: " + action + " failed: " + error[:80])
                    break
        except Exception:
            pass

        return "\n".join(parts)

    def _classify_intent(self, prompt_lower):
        """Classify user intent from their message."""
        if any(w in prompt_lower for w in ["hello", "hi ", "hey", "greetings"]):
            return "greeting"
        if any(w in prompt_lower for w in ["remember", "learn this", "save"]):
            return "knowledge_storage"
        if any(w in prompt_lower for w in ["what did you learn", "what do you know",
                                            "recall", "what is my"]):
            return "knowledge_retrieval"
        if any(w in prompt_lower for w in ["forget", "remove", "delete"]):
            return "knowledge_forget"
        if any(w in prompt_lower for w in ["actually", "no,", "wrong", "correct"]):
            return "knowledge_correction"
        if any(w in prompt_lower for w in ["who are you", "what are you"]):
            return "identity"
        if any(w in prompt_lower for w in ["what can you do", "capabilities"]):
            return "capabilities"
        if any(w in prompt_lower for w in ["status", "are you ready"]):
            return "status"
        if any(w in prompt_lower for w in ["fix", "solve", "debug", "error",
                                            "broken", "problem"]):
            return "problem_solving"
        if any(w in prompt_lower for w in ["how", "why", "explain", "what is"]):
            return "question"
        if any(w in prompt_lower for w in ["create", "build", "write", "make"]):
            return "creation"
        if "?" in prompt_lower:
            return "question"
        return "conversation"

    def _select_strategy(self, prompt_lower, intent):
        """Select strategy based on intent."""
        if "greeting" in intent:
            return "friendly acknowledgment"
        if "storage" in intent or "retrieval" in intent or "forget" in intent:
            return "use memory tools directly"
        if "problem_solving" in intent:
            return "diagnose, identify root cause, propose fix, verify"
        if "question" in intent:
            return "draw from knowledge, provide clear answer"
        if "creation" in intent:
            return "understand requirements, plan, implement, test"
        return "understand intent, gather context, reason, respond"

    # -- cognitive reflection -----------------------------------------------

    async def _cognitive_reflect(self, task, prompt, result, goal_id=None):
        """Post-action reflection: Zerion reflects on what happened.
        Uses the Intelligence Pipeline when available."""
        # --- NEW: Intelligence Pipeline post_act ---
        if self.cognitive_engine is not None:
            try:
                output = getattr(result, "output", None) or ""
                success = bool(output) and getattr(result, "status", None) == ResultStatus.SUCCESS
                tool_used = str(result.metadata.get("tool", "")
                               or result.metadata.get("tool_used", ""))
                latency = getattr(result, "latency_ms", 0) or 0
                await self.cognitive_engine.post_act(
                    user_input=prompt,
                    response=output[:500],
                    tool_used=tool_used,
                    success=success,
                    latency_ms=latency,
                )
            except Exception:
                pass
        # --- Legacy reflection ---
        try:
            output = getattr(result, "output", None) or ""
            success = bool(output) and getattr(result, "status", None) == ResultStatus.SUCCESS
            tool_used = str(result.metadata.get("tool", "")
                           or result.metadata.get("tool_used", ""))

            reflection = {
                "user_intent": self._classify_intent(prompt.lower()),
                "strategy_used": tool_used if tool_used else "model_reasoning",
                "success": success,
                "output_length": len(output),
            }

            if success and len(output.strip()) < 10:
                reflection["quality_signal"] = "suspiciously_short"
            elif success and len(output.strip()) > 500:
                reflection["quality_signal"] = "comprehensive"
            else:
                reflection["quality_signal"] = "normal"

            if tool_used:
                reflection["tool_reliability"] = "used_successfully" if success else "tool_failed"

            result.metadata["cognitive_reflection"] = reflection

        except Exception:
            pass

    # --- Slice 6: cognitive routing --------------------------------------------

    async def _emit_routing_event(self, event_type: str,
                                  payload: Dict[str, Any]) -> None:
        """Bridge the router's lifecycle onto the single repo event bus."""
        try:
            et = EventType(event_type)
        except ValueError:
            return
        await self.event_bus.publish(Event(
            event_type=et, payload=payload, source="cognitive_router",
            priority=60), dispatch_immediately=True)

    def route_task(self, task: Task, mode: RoutingMode = RoutingMode.AUTO,
                   historical_failure_rate: float = 0.0) -> ModelSelection:
        """Pure, deterministic model selection for a task (no execution)."""
        return self.cognitive_router.route(
            task, mode=mode, historical_failure_rate=historical_failure_rate)

    async def execute_task(self, task: Task, prompt: str,
                           mode: RoutingMode = RoutingMode.AUTO,
                           selection: Optional[ModelSelection] = None) -> CognitiveResult:
        """THE canonical live conversation path (CLI / UI / voice all route
        here). ZERION owns the loop; the local model (Qwen GGUF) is only the
        reasoning engine underneath:

            USER INPUT -> ZERION CONTEXT (identity/constitution/cognition/
            memory/capabilities/tools) -> intent + goal analysis ->
            [tool fast path] OR model -> [model tool call -> execute] ->
            self-critic (accept / revise / retry / escalate) -> memory
            update -> ZERION RESPONSE

        - The bounded identity context is injected before EVERY model call.
        - The tool router never advertises a tool that is not executable.
        - Self-critique is bounded (1 revision max) — unlimited inference
          time per call, no runaway loops.
        - Every turn updates episodic memory; model output is never verified
          truth (verification_status = MODEL_OUTPUT until observed)."""
        from zerion.cognitive_os.inference_ledger import (
            InferenceRequest,
            InferenceResult,
        )
        from zerion.cognitive_os.self_critic import SelfCriticDecision
        t0 = time.perf_counter()
        goal_id = None
        try:
            active = self.objectives.list_active_objectives()
            if active:
                goal_id = active[0].objective_id
        except Exception:  # noqa: BLE001 - goal lookup must never break inference
            goal_id = None
        context_sources = ["user_input", "identity", "constitution", "memory"]
        if goal_id is not None:
            context_sources.append("goal")
        req = InferenceRequest(
            request_id=task.task_id,
            user_input=prompt,
            selected_model=None,
            selected_provider=None,
            context_sources=context_sources,
            goal_id=goal_id,
            cognitive_depth=getattr(getattr(task, "type", None), "value", None),
        )
        self.inference_ledger.record_request(req)

        # 1) ZERION identity / system context (size-bounded, dynamic
        #    retrieval: memory and capabilities are pulled from real stores).
        field = None
        try:
            field = self.cognitive_router.selector.depth.field(task)
        except Exception:  # noqa: BLE001 — depth must never break a turn
            field = None
        try:
            tool_meta = [{"name": n, "description": d}
                         for n, d in self.tool_router.describe_pairs()]
        except Exception:  # noqa: BLE001
            tool_meta = []
        system_context = self.zerion_context.build_system_prompt(
            prompt, task=task,
            field=getattr(field, "value", None) if field else None,
            tools=tool_meta)
        full_prompt = "<im_start>system\n" + system_context + "\n<im_end>\n<im_start>user\n" + prompt + "\n<im_end>\n<im_start>assistant\n"

        # 2) FAST FIELD: deterministic local tool routing (no model tokens).
        tool_name = None
        try:
            tool_name = self.tool_router.detect(prompt)
        except Exception:  # noqa: BLE001 — detection never breaks a turn
            tool_name = None
        if tool_name is not None:
            tool_result = await self.tool_router.execute(tool_name, prompt)
            result = self._tool_result_to_cognitive(task, tool_result, mode,
                                                    t0)
            self._record_conversation_episode(task, prompt, result)
            self._finish_execute_task(task, prompt, result, goal_id,
                                      decision="local_tool")
            return result

        # 3) COGNITIVE PRE-REASONING: Zerion thinks BEFORE responding.
        #    This is NOT just passing input to the LLM — Zerion analyzes
        #    the task, identifies what it understands vs. what it needs
        #    to figure out, considers strategies, and prepares the model
        #    call with enriched cognitive context.
        cognitive_context = await self._cognitive_pre_reason(
            task, prompt, goal_id)
        if cognitive_context:
            # Insert cognitive context into the user section, BEFORE the
            # assistant marker, so the model sees it as part of the input.
            full_prompt = full_prompt.replace(
                "\n<im_end>\n<im_start>assistant\n",
                "\n\n[ZERION COGNITIVE CONTEXT]\n"
                + cognitive_context
                + "\n[/ZERION COGNITIVE CONTEXT]\n"
                + "<im_end>\n<im_start>assistant\n")

        # 3b) MODEL call with enriched ZERION context.
        result = await self.cognitive_router.execute(
            task, full_prompt, mode=mode, selection=selection)

        # 4) DEEP FIELD: a model-requested tool call or agent call is executed
        #    against the real registry, then the model produces the final
        #    response with the result. Bounded to ONE call per turn.
        if result.status == ResultStatus.SUCCESS and result.output:
            # Check for agent call first: [[AGENT:agent_id|task]]
            agent_parsed = None
            agent_match = re.search(
                r'\[\[\s*AGENT\s*:\s*([A-Za-z0-9_]+)\s*\|\s*(.*?)\s*\]\]',
                result.output, re.IGNORECASE | re.DOTALL)
            if agent_match:
                agent_id = agent_match.group(1).strip()
                agent_task = agent_match.group(2).strip()
                registry = getattr(self, 'agent_registry', None)
                if registry is not None:
                    agent = registry.get(agent_id)
                    if agent is not None:
                        agent_parsed = (agent, agent_task)

            if agent_parsed is not None:
                agent, agent_task = agent_parsed
                # Execute through the specialized agent
                async def _tool_exec(name, arg):
                    return await self.tool_router.execute(name, arg)
                agent_result = await agent.execute(
                    agent_task or prompt, {}, _tool_exec)
                result.metadata["agent_used"] = agent.name
                result.metadata["agent_result"] = agent_result.output[:500]
                # Now ask the model to synthesize the agent's output
                second = await self.cognitive_router.execute(
                    task,
                    full_prompt
                    + "\n\nAgent " + agent.name + " result:\n"
                    + agent_result.output[:1000]
                    + "\n\nSynthesize this into a concise answer for the user.",
                    mode=mode)
                if getattr(second, "output", None):
                    result = second
                    result.metadata["agent_used"] = agent.name
                    result.metadata["agent_success"] = True
                else:
                    result.output = agent_result.output
                    result.metadata["agent_success"] = True

            elif not agent_parsed:
                parsed = self.tool_router.parse_model_tool_call(result.output)
            if parsed is not None and not agent_parsed:
                name, arg = parsed
                tool_result = await self.tool_router.execute(name, arg or prompt)
                result.metadata["tool_used"] = name
                if not tool_result.ok:
                    # Never fabricate execution: keep the honest failure in
                    # the result metadata and let the final response report it.
                    result.metadata["tool_error"] = tool_result.error
                else:
                    second = await self.cognitive_router.execute(
                        task,
                        full_prompt
                        + "\n\nTool result:\n" + tool_result.output
                        + "\n\nRespond to the user as ZERION with the final "
                          "answer based on that tool result.",
                        mode=mode)
                    if getattr(second, "output", None):
                        result = second
                        result.metadata["tool_used"] = name
                        result.metadata["tool_success"] = True
                    else:
                        # The tool ran; the final phrasing call failed.
                        # Report the tool result honestly instead of silence.
                        result.metadata["tool_success"] = True
                        result.metadata["tool_result"] = tool_result.output[:500]

        # 5) Self-critic: bounded ACCEPT / REVISE / RETRY / ESCALATE.
        revisions = 0
        while revisions <= self.self_critic.max_revisions:
            decision, note, _revised = await self.self_critic.review(
                task, result, user_text=prompt, revisions_used=revisions)
            result.metadata.setdefault("self_critic", []).append(
                {"decision": decision, "note": note})
            if decision in (SelfCriticDecision.ACCEPT,
                            SelfCriticDecision.ESCALATE):
                break
            if decision == SelfCriticDecision.RETRY:
                result = await self.cognitive_router.execute(
                    task, full_prompt, mode=mode, selection=selection)
                revisions += 1
                continue
            if decision == SelfCriticDecision.REVISE:
                revised = await self.self_critic.critique(
                    task, result, full_prompt=full_prompt)
                if revised:
                    result.output = revised
                    result.metadata["self_critic_revised"] = True
                revisions += 1
                continue

        # 6) COGNITIVE REFLECTION: Zerion reflects on what happened,
        #    what it learned, and updates its understanding.
        await self._cognitive_reflect(task, prompt, result, goal_id)

        # 6b) Memory update: this turn becomes a real episodic record.
        self._record_conversation_episode(task, prompt, result)

        # 7) Ledger + decision policy over REAL evidence.
        self._finish_execute_task(task, prompt, result, goal_id,
                                  decision="decision_policy")
        return result

    # -- execute_task helpers -------------------------------------------------

    def _tool_result_to_cognitive(self, task: Task, tool_result: Any,
                                  mode: RoutingMode, t0: float) -> CognitiveResult:
        """Wrap a real tool execution in a CognitiveResult (provider is the
        local tool registry, never a faked model)."""
        usage = {"provider": "local_tool", "tool": tool_result.tool,
                 "timestamp": time.time()}
        if tool_result.ok:
            return CognitiveResult(
                task_id=task.task_id, provider="local_tool",
                model=f"tool:{tool_result.tool}",
                output=tool_result.output,
                latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                usage=usage, status=ResultStatus.SUCCESS,
                verification_required=task.verification_required,
                verification_status=VerificationStatus.MODEL_OUTPUT,
                confidence=1.0, mode=mode,
                metadata={"tool": tool_result.tool,
                          "routing_policy_version": 0})
        return CognitiveResult(
            task_id=task.task_id, provider="local_tool",
            model=f"tool:{tool_result.tool}",
            output=None, latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            usage=usage, status=ResultStatus.PROVIDER_UNAVAILABLE,
            errors=[tool_result.error or "tool execution failed"],
            verification_required=task.verification_required,
            verification_status=VerificationStatus.MODEL_OUTPUT,
            confidence=0.0, mode=mode,
            metadata={"tool": tool_result.tool})

    def _record_conversation_episode(self, task: Task, prompt: str,
                                     result: CognitiveResult) -> None:
        """Persist the turn as a real episodic memory record (bounded size,
        best-effort — a memory write must never break a turn)."""
        try:
            from zerion.cognitive_os.episode import (
                EpisodeMode,
                EpisodeStatus,
                ExperienceEpisode,
            )
            output = getattr(result, "output", None) or ""
            tools_used = (str(result.metadata.get("tool", ""))
                          or str(result.metadata.get("tool_used", ""))
                          or str(getattr(result, "model", "") or ""))
            episode = ExperienceEpisode(
                context=f"user message: {prompt[:300]}",
                mode=EpisodeMode.OBSERVED,
                status=EpisodeStatus.COMPLETED,
                success=bool(output),
                actions=[{"action": "conversation_turn",
                          "detail": prompt[:200]}],
                outcomes=[{"outcome": ("model_response" if output
                                       else "no_response"),
                           "detail": str(output)[:200]}],
                capabilities_used=[tools_used] if tools_used
                else ["conversation"],
            )
            self.episode_store.put(episode)
        except Exception:  # noqa: BLE001 — memory update never breaks a turn
            pass

    def _finish_execute_task(self, task: Task, prompt: str,
                             result: CognitiveResult, goal_id: Optional[str],
                             decision: str) -> None:
        """Shared ledger tail: complete the request record and write the
        observable InferenceResult over REAL evidence."""
        from zerion.cognitive_os.inference_ledger import InferenceResult
        self.inference_ledger.complete_request(
            task.task_id,
            model=getattr(result, "model", None) or None,
            provider=getattr(result, "provider", None) or None)
        produced = getattr(result, "output", None) is not None
        verdict = self.decision_policy.decide(
            uncertainty=float(getattr(task, "uncertainty", 0.0) or 0.0),
            stakes=float(getattr(task, "stakes", 0.0) or 0.0),
            confidence=1.0 if produced else 0.0,
            missing_information=False,
            permissions_allowed=True,
            provider_available=bool(getattr(result, "provider", "")) or produced,
        )
        usage = getattr(result, "usage", None) or {}
        inf_result = InferenceResult(
            request_id=task.task_id,
            model=getattr(result, "model", None) or None,
            provider=getattr(result, "provider", None) or None,
            generated_text=produced and getattr(result, "output", None) or None,
            latency_ms=getattr(result, "latency_ms", None),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            termination_reason=getattr(
                getattr(result, "status", None), "value", None),
            success=produced,
            error="; ".join(getattr(result, "errors", None) or []) or None,
            decision=verdict.decision.value,
            decision_reason=verdict.reason,
        )
        self.inference_ledger.record_result(inf_result)
    # --- Slice 7: self-improvement gate -----------------------------------------

    def record_telemetry(self, component: str, metric: str, *,
                         success: Optional[bool] = None,
                         latency_ms: Optional[float] = None,
                         value: Optional[float] = None) -> None:
        """Record a REAL measurement. No fabricated metrics: components with
        insufficient samples report UNKNOWN/INSUFFICIENT_DATA to consumers."""
        self.architecture_telemetry.record(
            component, metric, success=success,
            latency_ms=latency_ms, value=value)

    async def detect_bottlenecks(self) -> List[BottleneckReport]:
        """Run evidence-required bottleneck detection over real telemetry.
        Newly detected reports are persisted and published as
        BOTTLENECK_DETECTED (which routes into Slice 2 question genesis)."""
        reports = self.bottleneck_detector.detect()
        new_reports = []
        for report in reports:
            # The detector already persists + dedupes; publish only genuinely
            # new reports (store lookup confirms, idempotent re-put is safe).
            if self.bottleneck_store.get(report.id) is not None:
                new_reports.append(report)
                await self.event_bus.publish(Event(
                    event_type=EventType.BOTTLENECK_DETECTED,
                    payload={"report_id": report.id,
                             "bottleneck_type": report.type,
                             "component": report.affected_component,
                             "confidence": report.confidence,
                             "evidence": report.evidence},
                    source="bottleneck_detector",
                    priority=70,
                ), dispatch_immediately=True)
        self._sync_state()
        self.persist_state()
        return new_reports

    def propose_improvement(self, *, target_component: str, problem: str,
                            hypothesis: str, proposed_change: Any,
                            evidence: Optional[List[Dict[str, Any]]] = None,
                            expected_benefit: str = "", expected_cost: str = "",
                            dependencies: Optional[List[str]] = None,
                            affected_capabilities: Optional[List[str]] = None,
                            test_plan: Optional[List[Dict[str, Any]]] = None,
                            rollback_plan: str = "restore previous snapshot",
                            modification_type: ModificationType = ModificationType.CONFIGURATION_CHANGE,
                            risk: RiskLevel = RiskLevel.MEDIUM,
                            scope: Optional[List[str]] = None) -> ImprovementProposal:
        """Create a proposal. A proposal is never an improvement by itself — it
        must survive analysis, tests, benchmark, policy and rollback."""
        proposal = ImprovementProposal(
            target_component=target_component,
            problem=problem,
            hypothesis=hypothesis,
            proposed_change=proposed_change,
            evidence=list(evidence or []),
            expected_benefit=expected_benefit,
            expected_cost=expected_cost,
            dependencies=list(dependencies or []),
            affected_capabilities=list(affected_capabilities or []),
            test_plan=list(test_plan or []),
            rollback_plan=rollback_plan,
            modification_type=modification_type,
            risk=risk,
            scope=list(scope or []),
        )
        self.proposal_store.put(proposal)
        return proposal

    async def analyze_modification(self, proposal: ImprovementProposal,
                                   baseline_config: Dict[str, Any],
                                   candidate_config: Dict[str, Any]) -> ImprovementProposal:
        """Static analysis + risk assessment. Unsafe changes are rejected here
        (outside scope, forbidden patterns, code failing the AST gate)."""
        await self.event_bus.publish(Event(
            event_type=EventType.MODIFICATION_ANALYSIS_STARTED,
            payload={"proposal_id": proposal.proposal_id,
                     "target_component": proposal.target_component},
            source="self_modification_gate",
            priority=60,
        ), dispatch_immediately=True)
        proposal.transition(ProposalStatus.ANALYZING)
        result = self.self_modification_gate.static_analysis(proposal)
        proposal.analysis = {
            "passed": result.passed,
            "violations": result.violations,
            "risk": result.risk.value,
            "baseline_config": baseline_config,
            "candidate_config": candidate_config,
        }
        if not result.passed:
            proposal.status = ProposalStatus.REJECTED
            proposal.rejection_reason = "; ".join(result.violations)
            proposal.rejection_history.append({
                "stage": "static_analysis",
                "reason": proposal.rejection_reason,
                "at": time.time(),
            })
            await self.event_bus.publish(Event(
                event_type=EventType.MODIFICATION_REJECTED,
                payload={"proposal_id": proposal.proposal_id,
                         "stage": "static_analysis",
                         "reason": proposal.rejection_reason},
                source="self_modification_gate",
                priority=60,
            ), dispatch_immediately=True)
        self.proposal_store.put(proposal)
        return proposal

    async def sandbox_modification(self, proposal: ImprovementProposal) -> ImprovementProposal:
        """Sandbox stage: untrusted modification code is compiled and gated
        (Slice 5 sandbox reuse); never executed in the production runtime."""
        proposal.transition(ProposalStatus.SANDBOXED)
        if proposal.modification_type in (ModificationType.CODE_CHANGE,
                                          ModificationType.CAPABILITY_CHANGE):
            code = proposal.proposed_change
            violation = self.capability_sandbox.inspect(code) if isinstance(code, str) else None
            if violation is not None:
                proposal.status = ProposalStatus.REJECTED
                proposal.rejection_reason = f"sandbox: {violation}"
                proposal.rejection_history.append({
                    "stage": "sandbox", "reason": proposal.rejection_reason,
                    "at": time.time(),
                })
        await self.event_bus.publish(Event(
            event_type=(EventType.MODIFICATION_SANDBOXED if proposal.status == ProposalStatus.SANDBOXED
                        else EventType.MODIFICATION_REJECTED),
            payload={"proposal_id": proposal.proposal_id,
                     "status": proposal.status.value,
                     "reason": proposal.rejection_reason},
            source="self_modification_gate",
            priority=60,
        ), dispatch_immediately=True)
        self.proposal_store.put(proposal)
        return proposal

    async def test_modification(self, proposal: ImprovementProposal,
                                tests: Optional[List[Dict[str, Any]]] = None) -> ImprovementProposal:
        """Run the proposal's test plan. A failing test means rejection —
        generated code that fails tests never proceeds to benchmark."""
        proposal.transition(ProposalStatus.TESTING)
        outcome = self.self_modification_gate.run_tests(proposal, tests=tests)
        proposal.test_results = list(outcome.results)
        proposal.analysis["tests_passed"] = outcome.passed
        if not outcome.passed:
            proposal.status = ProposalStatus.REJECTED
            failed = [r for r in outcome.results if not r.get("passed")]
            proposal.rejection_reason = (
                "tests failed: " + ", ".join(
                    f"{r.get('name')}: {r.get('violation', 'wrong result')}" for r in failed))
            proposal.rejection_history.append({
                "stage": "tests", "reason": proposal.rejection_reason,
                "at": time.time(),
            })
        await self.event_bus.publish(Event(
            event_type=(EventType.MODIFICATION_TESTED if proposal.status == ProposalStatus.TESTING
                        else EventType.MODIFICATION_REJECTED),
            payload={"proposal_id": proposal.proposal_id,
                     "status": proposal.status.value,
                     "passed": outcome.passed,
                     "results": outcome.results,
                     "reason": proposal.rejection_reason},
            source="self_modification_gate",
            priority=60,
        ), dispatch_immediately=True)
        self.proposal_store.put(proposal)
        return proposal

    async def benchmark_modification(self, proposal: ImprovementProposal,
                                     baseline_runner: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
                                     candidate_runner: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
                                     trials: int = 10,
                                     min_trials: int = 5) -> ImprovementProposal:
        """BASELINE vs CANDIDATE on identical deterministic benchmark tasks.
        Insufficient evidence or a supported-but-weak result is INCONCLUSIVE,
        never a promotion."""
        proposal.transition(ProposalStatus.BENCHMARKING)
        comparison = self.self_modification_gate.benchmark(
            proposal, baseline_runner, candidate_runner,
            trials=trials, min_trials=min_trials)
        proposal.benchmark = comparison.to_dict()
        self.proposal_store.put(proposal)
        await self.event_bus.publish(Event(
            event_type=EventType.MODIFICATION_BENCHMARKED,
            payload={"proposal_id": proposal.proposal_id,
                     "verdict": comparison.verdict,
                     "improvement": comparison.deltas.get("success"),
                     "improvement_observed": comparison.verdict == "SUPPORTED",
                     "baseline": comparison.baseline,
                     "candidate": comparison.candidate},
            source="self_modification_gate",
            priority=60,
        ), dispatch_immediately=True)
        return proposal

    async def approve_modification(self, proposal: ImprovementProposal,
                                   approval: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """Policy check: LOW may auto-promote only when policy permits;
        MEDIUM/HIGH/CRITICAL require explicit approval. No silent bypass."""
        ok, reason = self.self_modification_gate.approve(proposal, approval=approval)
        if ok:
            proposal.status = ProposalStatus.APPROVED
            proposal.approval = dict(approval or {})
            await self.event_bus.publish(Event(
                event_type=EventType.MODIFICATION_APPROVED,
                payload={"proposal_id": proposal.proposal_id,
                         "risk": proposal.risk.value,
                         "modification_type": proposal.modification_type.value},
                source="self_modification_gate",
                priority=70,
            ), dispatch_immediately=True)
        else:
            proposal.status = ProposalStatus.REJECTED
            proposal.rejection_reason = reason
            proposal.rejection_history.append({
                "stage": "policy", "reason": reason, "at": time.time(),
            })
            await self.event_bus.publish(Event(
                event_type=EventType.MODIFICATION_REJECTED,
                payload={"proposal_id": proposal.proposal_id,
                         "stage": "policy", "reason": reason},
                source="self_modification_gate",
                priority=60,
            ), dispatch_immediately=True)
        self.proposal_store.put(proposal)
        self._sync_state()
        self.persist_state()
        return ok, reason

    async def promote_modification(self, proposal: ImprovementProposal,
                                   approval: Optional[Dict[str, Any]] = None) -> PromotionResult:
        """Atomic promotion: snapshot persisted BEFORE any mutation; promotion
        only for CONFIGURATION_CHANGE (applied to the genome). Other types are
        approved with evidence + snapshot but never auto-applied to production."""
        result = self.self_modification_gate.promote(
            proposal, self.genome_manager, self.snapshot_store,
            approval=approval, policy_store=self.policy_store)
        if result.ok:
            await self.event_bus.publish(Event(
                event_type=EventType.MODIFICATION_PROMOTED,
                payload={"proposal_id": proposal.proposal_id,
                         "snapshot_version": result.snapshot_version,
                         "applied": result.applied,
                         "message": result.message},
                source="self_modification_gate",
                priority=70,
            ), dispatch_immediately=True)
        else:
            proposal.status = ProposalStatus.REJECTED
            proposal.rejection_reason = result.message
            proposal.rejection_history.append({
                "stage": "promotion", "reason": result.message, "at": time.time(),
            })
            await self.event_bus.publish(Event(
                event_type=EventType.MODIFICATION_REJECTED,
                payload={"proposal_id": proposal.proposal_id,
                         "stage": "promotion", "reason": result.message},
                source="self_modification_gate",
                priority=60,
            ), dispatch_immediately=True)
        self.proposal_store.put(proposal)
        self._sync_state()
        self.persist_state()
        return result

    async def rollback_modification(self, proposal: ImprovementProposal,
                                    reason: str = "") -> RollbackResult:
        """Post-promotion regression -> restore the pre-change snapshot genome,
        record the rollback, and emit the event trail. The previous known-good
        state is never destroyed."""
        result = self.self_modification_gate.rollback(
            proposal, self.genome_manager, self.snapshot_store,
            reason=reason, policy_store=self.policy_store)
        if result.ok:
            await self.event_bus.publish(Event(
                event_type=EventType.MODIFICATION_ROLLED_BACK,
                payload={"proposal_id": proposal.proposal_id,
                         "restored_version": result.restored_version,
                         "reason": reason or "post-promotion regression"},
                source="self_modification_gate",
                priority=80,
            ), dispatch_immediately=True)
        self.proposal_store.put(proposal)
        self._sync_state()
        self.persist_state()
        return result

    # --- Genome: controlled candidate evaluation -------------------------------

    def current_genome(self) -> CognitiveGenome:
        """The promoted production genome (runtime configuration, not weights)."""
        return self.genome_manager.current()

    async def propose_genome_variation(self, changes: Dict[str, Any],
                                       allow_new_keys: bool = False) -> CognitiveGenome:
        """PROPOSE_VARIATION: clones the current genome; the production genome
        is never mutated during experimentation."""
        candidate = self.genome_manager.propose_variation(
            changes, allow_new_keys=allow_new_keys)
        await self.event_bus.publish(Event(
            event_type=EventType.GENOME_CREATED,
            payload={"genome_id": candidate.genome_id,
                     "parent_id": candidate.parent_id,
                     "version": candidate.version},
            source="genome_manager",
            priority=50,
        ), dispatch_immediately=True)
        return candidate

    async def evaluate_genome(self, genome_id: str,
                              evaluation: Dict[str, Any]) -> CognitiveGenome:
        """Record identical deterministic benchmark results for a candidate."""
        genome = self.genome_manager.record_evaluation(genome_id, evaluation)
        await self.event_bus.publish(Event(
            event_type=EventType.GENOME_EVALUATED,
            payload={"genome_id": genome.genome_id,
                     "evaluation": genome.evaluation_results},
            source="genome_manager",
            priority=50,
        ), dispatch_immediately=True)
        return genome

    async def promote_genome(self, genome_id: str) -> CognitiveGenome:
        """PROMOTE only after evaluation evidence exists."""
        genome = self.genome_manager.promote(genome_id)
        await self.event_bus.publish(Event(
            event_type=EventType.GENOME_PROMOTED,
            payload={"genome_id": genome.genome_id, "version": genome.version},
            source="genome_manager",
            priority=70,
        ), dispatch_immediately=True)
        return genome

    async def reject_genome(self, genome_id: str, reason: str = "") -> CognitiveGenome:
        """REJECT a candidate with a recorded reason."""
        genome = self.genome_manager.reject(genome_id, reason=reason)
        await self.event_bus.publish(Event(
            event_type=EventType.GENOME_REJECTED,
            payload={"genome_id": genome.genome_id, "reason": reason},
            source="genome_manager",
            priority=50,
        ), dispatch_immediately=True)
        return genome

    def create_snapshot(self, *, label: str,
                        configuration: Optional[Dict[str, Any]] = None,
                        changed_components: Optional[List[str]] = None,
                        tests: Optional[List[Dict[str, Any]]] = None,
                        benchmark_results: Optional[Dict[str, Any]] = None,
                        approval_state: Optional[Dict[str, Any]] = None,
                        rollback_reference: Optional[str] = None) -> RuntimeSnapshot:
        """Versioned, checksummed snapshot of runtime configuration state."""
        current = self.genome_manager.current()
        snapshot = RuntimeSnapshot(
            version=self.snapshot_store.next_version(),
            timestamp=time.time(),
            changed_components=list(changed_components or []),
            configuration=dict(configuration or current.configuration),
            tests=list(tests or []),
            benchmark_results=dict(benchmark_results or {}),
            approval_state=dict(approval_state or {}),
            rollback_reference=rollback_reference or current.genome_id,
            label=label,
        )
        self.snapshot_store.put(snapshot)
        return snapshot

    def monitor_proposal_regression(self, proposal: ImprovementProposal,
                                    thresholds: Optional[Dict[str, float]] = None) -> bool:
        """Post-promotion monitoring via REAL telemetry; degraded health triggers
        rollback through the gate. Broken changes are never kept active silently."""
        return self.self_modification_gate.monitor_regression(
            proposal, self.architecture_telemetry, thresholds=thresholds)

    def record_observed_result(self, result: CognitiveResult, *,
                               observation: Dict[str, Any],
                               source: str) -> CognitiveResult:
        """Verification step 1: MODEL_OUTPUT -> OBSERVED_RESULT. Corroboration
        is recorded as Slice 3 OBSERVED evidence (full provenance); model
        output alone can never promote itself."""
        if result.verification_status != VerificationStatus.MODEL_OUTPUT:
            raise ValueError(
                f"Cannot observe a result already in {result.verification_status.value}")
        evidence = Evidence(
            content={"task_id": result.task_id, "observation": observation,
                     "model_output": result.output},
            provenance=Provenance(
                source=source,
                observed_at=time.time(),
                evidence_type="task_observation",
                content_reference=f"task:{result.task_id}",
                reliability=1.0,
                mode=EvidenceMode.OBSERVED,
                recorded_at=time.time(),
            ),
            verdict=EvidenceVerdict.NEUTRAL,
        )
        self.evidence_store.put(evidence)
        ids = list(result.metadata.get("evidence_ids", []))
        ids.append(evidence.evidence_id)
        result.metadata["evidence_ids"] = ids
        result.verification_status = VerificationStatus.OBSERVED_RESULT
        return result

    def confirm_verified(self, result: CognitiveResult, *,
                         evidence_ids: List[str]) -> CognitiveResult:
        """Verification step 2: OBSERVED_RESULT -> VERIFIED_RESULT. Requires
        real OBSERVED evidence from the Slice 3 store — fabricated or
        MODEL_GENERATED evidence can never confirm a result."""
        if result.verification_status not in (VerificationStatus.MODEL_OUTPUT,
                                              VerificationStatus.OBSERVED_RESULT):
            raise ValueError(
                f"Cannot verify a result already in {result.verification_status.value}")
        if not evidence_ids:
            raise ValueError("verification requires at least one evidence id")
        for eid in evidence_ids:
            ev = self.evidence_store.get(eid)
            if ev is None:
                raise ValueError(f"evidence {eid} does not exist")
            if ev.provenance.mode != EvidenceMode.OBSERVED:
                raise ValueError(
                    f"evidence {eid} is {ev.provenance.mode.value}, not OBSERVED — "
                    "cannot verify a model result")
        result.metadata["verified_by"] = list(evidence_ids)
        result.verification_status = VerificationStatus.VERIFIED_RESULT
        return result

    def record_task_outcome(self, task: Task, result: CognitiveResult, *,
                            verified: Optional[bool] = None) -> None:
        """Feed a REAL outcome into the performance ledger (used by routing
        weights). Success = the provider returned a usable result."""
        self.performance_ledger.record_outcome(
            task=task, provider=result.provider, model=result.model,
            success=(result.status == ResultStatus.SUCCESS),
            latency_ms=result.latency_ms, cost_cents=None, verified=verified)
        # Slice 8: live outcomes also feed architecture telemetry so Slice 7
        # bottleneck detection runs on REAL task data, never invented metrics.
        self.telemetry_feed.feed_outcome(
            provider=result.provider, model=result.model,
            latency_ms=result.latency_ms,
            success=(result.status == ResultStatus.SUCCESS),
            verified=verified)

    # --- State mirroring --------------------------------------------------------

    def _sync_state(self) -> None:
        stats = self.attention.stats()
        self.state.pending_events = self.event_bus.pending_count
        self.state.attention = AttentionStateView(
            current_focus_id=self.state.attention.current_focus_id,
            current_focus=self.state.current_focus,
            selected_count=stats["selected_count"],
            deferred_count=stats["deferred_count"],
            discarded_count=stats["discarded_count"],
            pending_candidates=stats["pending_candidates"],
            deferred_candidates=stats["deferred_candidates"],
        )
        counts = self.objectives.count_goals()
        self.state.goals = GoalStateView(
            total=counts["total"],
            proposed=counts["PROPOSED"],
            active=counts["ACTIVE"],
            blocked=counts["BLOCKED"],
            paused=counts["PAUSED"],
            completed=counts["COMPLETED"],
            abandoned=counts["ABANDONED"],
        )
        budget = stats["budget"]
        self.state.resources = ResourceBudgetView(
            compute_units=budget["compute_units"],
            api_calls=budget["api_calls"],
            latency_ms=budget["latency_ms"],
            concurrent_workload=budget["concurrent_workload"],
            max_concurrent=budget["max_concurrent"],
        )
        self.state.touch()
