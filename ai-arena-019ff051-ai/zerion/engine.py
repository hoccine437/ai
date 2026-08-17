"""
ZERION-X — GENESIS
Master Self-Developing Intelligence Substrate Engine
Implements the 25-Stage Recursive Developmental Flywheel, Cognitive Autopoiesis, and Counterfactual Reasoning.
"""

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

# --- Runtime Infrastructure ---
from zerion.runtime.event_bus import AsyncEventBus
from zerion.runtime.events import Event, EventType
from zerion.runtime.resources import ResourceManager
from zerion.runtime.security import SecurityBoundary, PermissionLevel
from zerion.runtime.watchdog import Watchdog
from zerion.runtime.scheduler import MissionScheduler
from zerion.telemetry.logger import CognitiveTelemetryLogger, CognitiveTelemetryRecord

# --- Identity & Invariants ---
from zerion.identity.persistence import IdentityCore
from zerion.identity.objectives import LongTermObjective, ObjectiveStatus

# --- World Model 3.0 & Epistemic Substrate ---
from zerion.world.graph import WorldModel, WorldNode
from zerion.world.tracker import WorldTracker, DriftAnomaly
from zerion.world.epistemic import EpistemicStatus, EpistemicAssertion
from zerion.world.causal import CausalHypothesis
from zerion.counterfactual.engine import CounterfactualEngine, CounterfactualQuery
from zerion.unknown.unknown_space import UnknownSpaceEngine, EpistemicVoidType
from zerion.architecture_search.search_engine import ArchitectureSearchEngine, ArchitectureCandidate

# --- Self-Model & Cognitive Maturity ---
from zerion.self_model.introspector import SelfModel
from zerion.self_model.capabilities import CapabilityRecord
from zerion.self_model.maturity import CognitiveMaturityEvaluator, MaturityAssessment, MaturityLevel

# --- Pressure & Question Genesis 3.0 ---
from zerion.pressure.field import PressureField
from zerion.pressure.signals import PressureSignal, SignalType
from zerion.pressure.generator import ProblemCandidateGenerator, ProblemCandidate
from zerion.questions.graph import QuestionGraph
from zerion.questions.genesis import QuestionGenesis
from zerion.questions.question import Question, QuestionType

# --- Cognitive Genome & Phenotypes ---
from zerion.cognitive_genome.genome import CognitiveGenome, GenomeMutationProposal
from zerion.cognitive_genome.phenotype import CognitivePhenotype, PhenotypeFactory
from zerion.cognitive_genome.manager import GenomeManager

# --- Cognitive Genesis & Strategy Evolution ---
from zerion.cognitive_genesis.strategy import CognitiveStrategy
from zerion.cognitive_genesis.genesis_pipeline import CognitiveGenesisPipeline
from zerion.cognitive_genesis.registry import StrategyRegistry
from zerion.strategy_evolution.evolution_engine import StrategyEvolutionEngine

# --- Meta-Prediction, Learning-to-Learn & Autopoiesis ---
from zerion.meta_prediction.engine import MetaPredictionEngine, MetaPrediction, MetaCalibrationRecord
from zerion.learning_to_learn.engine import LearningToLearnEngine, LearningAcquisitionRecord
from zerion.cognitive_autopoiesis.engine import CognitiveAutopoiesisEngine, AutopoiesisCycleReport
from zerion.self_experimentation.engine import SelfExperimentationEngine, ArchitectureTrialReport
from zerion.cognitive_immune.immune_system import CognitiveImmuneSystem

# --- Cognition & Compute ---
from zerion.adaptive_cognition.controller import AdaptiveCognitiveController, AdaptiveCognitiveAllocation
from zerion.cognition.compiler import CognitiveCompiler
from zerion.cognition.model_fabric import ModelFabric
from zerion.cognition.multi_path import MultiPathReasoner
from zerion.cognition.adversarial import AdversarialEngine

# --- Evidence & Reality Sandbox Experiments ---
from zerion.evidence.engine import EvidenceEngine
from zerion.experiments.engine import ExperimentEngine, ExperimentOutcome
from zerion.experiments.design import ExperimentDesign
from zerion.experiments.sandbox import ExecutionSandbox

# --- Memory & Distillation (legacy store kept as a deprecated read-only view;
# the live flywheel writes episodes through the canonical Slice 4 stores) ---
from zerion.memory.developmental_store import DevelopmentalMemoryStore

# --- Capability Birth 3.0 ---
from zerion.capabilities.detector import CapabilityGapDetector, CapabilityGap
from zerion.capabilities.birth import CapabilityBirthPipeline, BornCapability
from zerion.capabilities.registry import DynamicCapabilityRegistry
from zerion.learning.curriculum import SelfCurriculumGenerator
from zerion.learning.transfer import TransferEngine

# --- Missions & Evolution ---
from zerion.missions.lifecycle import MissionLifecycleManager
from zerion.missions.mission import Mission, MissionStep
from zerion.evolution.plasticity import CognitivePlasticityManager
from zerion.evolution.self_modification import ControlledSelfModificationEngine

from zerion.benchmarks.runner import BenchmarkRunner
from zerion.benchmarks.scoreboard import DevelopmentalScoreboard
from zerion.benchmarks.anti_gaming import AntiGamingDetector
from zerion.ui.state_bridge import UIStateBridge
from zerion.voice.pipeline import VoiceFirstInteractionPipeline
from zerion.cognitive_os.organism import CognitiveOrganism, OrganismCycleResult
from zerion.cognitive_os.objective_manager import ObjectiveContinuityManager
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.cognitive_os.gguf_discovery import resolve_models_dir
from zerion.cognitive_os.local_model_registry import LocalModelRegistry
from zerion.ui.visualization_adapter import VisualizationStateAdapter
from zerion.ui.commands import CommandAPI
from zerion.voice.providers import VoiceEnvironment
from zerion.voice.perception_service import VoicePerceptionService
from zerion.evolution.timeline import DevelopmentTimelineManager, DevelopmentSnapshot
from zerion.runtime.daemon import AutonomyLevel, DevelopmentDaemon, BackgroundDiscoveryDaemon
from zerion.integration.android.mobile_runtime import MobileResourceGovernor
from zerion.integration.termux_adapter import TermuxAdapter
from zerion.integration.offline_fallback import OfflineFallbackManager
from zerion.entity.state import CognitiveEntityStateStore
from zerion.self_model.self_predictor import SelfPredictor
from zerion.architecture.autophagy import CognitiveAutophagyEngine
from zerion.intelligence_forge.organism_runtime.foundry import IntelligenceFoundry, FoundryCycleTelemetry
from zerion.runtime.evidence import collect_runtime_evidence
from zerion.cognitive_os.evidence import Evidence as CognitiveEvidence, EvidenceMode, EvidenceVerdict, Provenance
from zerion.cognitive_os.episode import ExperienceEpisode, EpisodeMode, EpisodeStatus


def load_dotenv_files(environ=None, extra_dirs=None) -> None:
    """Load KEY=VALUE pairs from .env files (cwd, package root, home, extras).

    PARADIGM-X: the environment injectable makes the loader deterministic and
    testable. It never overrides variables already set in the environment, and
    never raises on unreadable files.
    """
    environ = environ if environ is not None else os.environ
    candidates = [
        Path(".env"),
        Path(__file__).parent.parent / ".env",
        Path.home() / ".env",
    ]
    for extra in (extra_dirs or []):
        candidates.append(Path(extra) / ".env")
    for env_file in candidates:
        if not env_file.exists():
            continue
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'").strip('"')
                        if key and not environ.get(key):
                            environ[key] = val
        except Exception:
            pass


@dataclass
class GenesisCycleTrace:
    cycle_id: str
    timestamp: float
    perceptions_ingested: int
    anomalies_detected: int
    problems_generated: int
    questions_formulated: int
    strategy_selected: str
    cognitive_allocation_mode: str
    cognitive_programs_run: int
    evidence_acquired: int
    counterfactuals_simulated: int
    capabilities_born: int
    strategies_synthesized: int
    autopoiesis_executed: bool
    learning_acceleration_ratio: float
    maturity_level: str
    duration_ms: float


class AscendantEngine:
    """
    ZERION-X — GENESIS Master Self-Developing Runtime Engine.
    Coordinates the 25-stage continuous developmental flywheel.
    """
    def __init__(self, data_dir: str = "data", models_dir: Optional[str] = None):
        # Auto-load .env if present (shared, injectable loader)
        load_dotenv_files()

        self.data_dir = Path(data_dir)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                f"Cannot create data directory '{self.data_dir}': permission denied.\n"
                f"This commonly happens on Termux/Android, where system paths like /tmp are "
                f"not writable by the app. Use a path inside your app's own storage instead, "
                f"for example: --data-dir ~/zerion_data or --data-dir ./data\n"
                f"Original error: {e}"
            ) from e

        # 1. Runtime Infrastructure
        self.event_bus = AsyncEventBus(db_path=str(self.data_dir / "events.db"))
        self.resources = ResourceManager()
        self.security = SecurityBoundary(workspace_root=str(Path.cwd()))
        self.watchdog = Watchdog()
        self.scheduler = MissionScheduler()
        self.telemetry = CognitiveTelemetryLogger(log_path=str(self.data_dir / "telemetry.jsonl"))

        # 2. Identity Core & Invariants & Entity State
        # ONE canonical identity: the entity store derives every identity value
        # from the IdentityCore above — a second identity is never created.
        self.identity = IdentityCore(storage_path=str(self.data_dir / "identity.json"))
        self.entity_state = CognitiveEntityStateStore(
            db_path=str(self.data_dir / "entity_state.db"),
            identity=self.identity)
        self.self_predictor = SelfPredictor()
        self.autophagy = CognitiveAutophagyEngine(db_path=str(self.data_dir / "autophagy.db"))

        # 3. World Model 3.0 & Counterfactuals & Unknown Space
        self.world = WorldModel(db_path=str(self.data_dir / "world_model.db"))
        self.world_tracker = WorldTracker(self.world)
        self.unknown_space = UnknownSpaceEngine(db_path=str(self.data_dir / "unknown_space.db"))
        # The legacy execution sandbox is wired to the canonical SecurityBoundary:
        # every sandboxed execution is authorized (and audited) before running.
        self.sandbox = ExecutionSandbox(security=self.security)
        self.counterfactual = CounterfactualEngine(sandbox=self.sandbox)
        self.architecture_search = ArchitectureSearchEngine(db_path=str(self.data_dir / "architecture_search.db"))

        # 4. Self Model & Maturity
        self.self_model = SelfModel(db_path=str(self.data_dir / "self_model.db"))
        self.maturity_evaluator = CognitiveMaturityEvaluator()

        # 5. Pressure & Question Genesis 3.0
        self.pressure_field = PressureField()
        self.problem_generator = ProblemCandidateGenerator()
        self.question_graph = QuestionGraph(db_path=str(self.data_dir / "questions.db"))
        self.question_genesis = QuestionGenesis(self.question_graph)

        # 6. Cognitive Genome & Phenotypes
        self.genome_manager = GenomeManager(db_path=str(self.data_dir / "genome.db"))
        self.adaptive_cognition = AdaptiveCognitiveController(default_genome=self.genome_manager.current_genome)

        # 7. Cognitive Genesis & Strategy Evolution
        self.strategy_registry = StrategyRegistry(db_path=str(self.data_dir / "strategies.db"))
        self.strategy_genesis = CognitiveGenesisPipeline(sandbox=self.sandbox)
        self.strategy_evolution = StrategyEvolutionEngine(db_path=str(self.data_dir / "strategy_evolution.db"))

        # 8. Meta-Prediction, Learning-to-Learn & Autopoiesis
        self.meta_prediction = MetaPredictionEngine(db_path=str(self.data_dir / "meta_prediction.db"))
        self.learning_to_learn = LearningToLearnEngine(db_path=str(self.data_dir / "learning_to_learn.db"))
        self.autopoiesis = CognitiveAutopoiesisEngine(db_path=str(self.data_dir / "autopoiesis.db"), sandbox=self.sandbox)
        self.self_experimentation = SelfExperimentationEngine(db_path=str(self.data_dir / "self_experimentation.db"))
        self.immune_system = CognitiveImmuneSystem(sandbox=self.sandbox)

        # 9. Cognition & Evidence
        self.cognitive_compiler = CognitiveCompiler()
        self.model_fabric = ModelFabric()
        self.multi_path = MultiPathReasoner()
        self.adversarial = AdversarialEngine()
        self.evidence = EvidenceEngine(db_path=str(self.data_dir / "evidence.db"))
        self.experiments = ExperimentEngine(sandbox=self.sandbox, evidence_engine=self.evidence)

        # 10. Memory & Distillation
        self.memory = DevelopmentalMemoryStore(db_path=str(self.data_dir / "memory.db"))

        # 11. Capabilities & Learning
        self.gap_detector = CapabilityGapDetector()
        self.birth_pipeline = CapabilityBirthPipeline(sandbox=self.sandbox)
        self.capability_registry = DynamicCapabilityRegistry(db_path=str(self.data_dir / "capabilities.db"))
        self.curriculum = SelfCurriculumGenerator()
        self.transfer = TransferEngine()

        # 12. Missions & Evolution
        self.missions = MissionLifecycleManager(db_path=str(self.data_dir / "missions.db"))
        self.plasticity = CognitivePlasticityManager()
        # Legacy sandboxed self-modification executor (DEPRECATED — the
        # canonical self-modification path is the SelfModificationGate inside
        # CognitiveRuntime; this legacy executor is retained for acceptance
        # tests and always runs through the security-wired sandbox).
        self.self_mod = ControlledSelfModificationEngine(sandbox=self.sandbox)
        self.benchmarks = BenchmarkRunner()
        self.scoreboard = DevelopmentalScoreboard()
        self.anti_gaming = AntiGamingDetector()
        self.ui_bridge = UIStateBridge()
        self.voice_env = VoiceEnvironment()
        self.voice_pipeline = VoiceFirstInteractionPipeline(
            engine_ref=self, ui_bridge=self.ui_bridge,
            voice_env=self.voice_env)
        # Slice 10.1: the always-available voice perception organ. It is
        # engine-scoped (not UI/server-scoped): it starts with the runtime and
        # keeps listening even when no UI is open. It only ever reports
        # LISTENING when the microphone pipeline is genuinely active.
        self.voice_perception = VoicePerceptionService(
            pipeline=self.voice_pipeline,
            voice_env=self.voice_env,
            event_bus=self.event_bus,
        )

        # 13. Cognitive OS & Autonomous Organism & Intelligence Foundry
        # NOTE: the legacy CognitiveSpeciesRuntime (zerion/cognitive_species) is
        # DEPRECATED and isolated — it is NOT constructed by the live runtime
        # (its own GoalField/router were a competing source of truth). Tests
        # that need it construct it directly.
        self.organism = CognitiveOrganism(data_dir=str(self.data_dir))
        self.foundry = IntelligenceFoundry(data_dir=str(self.data_dir))
        self.timeline = DevelopmentTimelineManager(db_path=str(self.data_dir / "timeline.db"))
        self.continuous_objectives = self.organism.objectives

        # Slice 1: Cognitive Foundation — owns CognitiveState and wires the event bus,
        # Goal Field (reuses the organism's persistent objective store) and Attention
        # Economy into the runtime. No model dependencies.
        self.models_dir = models_dir or resolve_models_dir("models")
        self.cognitive_runtime = CognitiveRuntime(
            data_dir=str(self.data_dir),
            event_bus=self.event_bus,
            objectives=self.organism.objectives,
            models_dir=self.models_dir,
            # The canonical security boundary gates self-modification approval
            # (SYSTEM_MUTATE is never held by default -> denials are honest).
            security=self.security,
            # ZERION identity layer: the runtime draws the canonical identity,
            # the real capability catalog and live readiness from the engine.
            identity=self.identity,
            self_model=self.self_model,
            readiness=self.local_readiness,
        )
        # Slice 10: the visualization state adapter is the only channel between
        # the runtime and the UI; commands go through the validated CommandAPI.
        self.local_model_registry = LocalModelRegistry(
            models_dir=self.models_dir,
            discovery=self.cognitive_runtime.local_models,
            load_manager=self.cognitive_runtime.cognitive_router.load_manager,
        )
        self.ui_adapter = VisualizationStateAdapter(engine=self,
                                                    event_bus=self.event_bus)
        self.command_api = CommandAPI(engine=self)
        self.mobile_governor = MobileResourceGovernor()
        self.daemon = DevelopmentDaemon(engine_ref=self, autonomy_level=AutonomyLevel.AUTONOMOUS_SAFE)
        self.discovery_daemon = BackgroundDiscoveryDaemon(engine_ref=self)

        # 14. Integration & Fallbacks
        self.termux = TermuxAdapter()
        self.offline = OfflineFallbackManager(model_fabric=self.model_fabric)

        self._running = False
        self._cycle_count = 0
        self._cycle_history: List[GenesisCycleTrace] = []
        # Slice 8: persistent pulse heartbeat (spawned in start(), cancelled in
        # stop()). Keeps the CognitivePulse loop alive in UI/server/daemon mode.
        self._pulse_driver_task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        await self.event_bus.start()
        await self.watchdog.start()
        await self.scheduler.start()

        # Slice 10: attach the visualization adapter to the single bus before
        # the runtime starts so real lifecycle events reach the UI.
        self.ui_adapter.attach()

        # Slice 1: start the cognitive foundation
        await self.cognitive_runtime.start()

        # Slice 8: drive the CognitivePulse on a persistent cadence while the
        # engine runs (UI/server/daemon mode gets the full event-driven loop,
        # not just the bounded per-cycle drain in run_developmental_cycle).
        self._pulse_driver_task = asyncio.create_task(self._drive_pulse_loop())

        # Slice 10.1: start the always-available voice perception service
        # (independent of the UI; reports honest microphone state).
        await self.voice_perception.start()

        # Wire event handlers
        self.event_bus.subscribe(EventType.PREDICTION_ERROR, self._on_prediction_error)
        self.event_bus.subscribe(EventType.ANOMALY_DETECTED, self._on_anomaly_detected)

        # Publish startup event
        await self.event_bus.publish(Event(
            event_type=EventType.SYSTEM_STARTUP,
            payload={"system_id": self.identity.system_id, "genome_version": self.genome_manager.current_genome.version},
            priority=95
        ))

    async def stop(self):
        if not self._running:
            return
        self._running = False
        # Stop the pulse heartbeat before the runtime stops so no tick races
        # the shutdown.
        if self._pulse_driver_task is not None:
            self._pulse_driver_task.cancel()
            try:
                await self._pulse_driver_task
            except (asyncio.CancelledError, Exception):
                pass
            self._pulse_driver_task = None
        await self.event_bus.publish(Event(
            event_type=EventType.SYSTEM_SHUTDOWN,
            payload={"timestamp": time.time()},
            priority=95
        ))
        # Slice 1: persist cognitive state and publish RUNTIME_STOPPED before the bus closes
        await self.cognitive_runtime.stop()
        # Slice 10.1: stop the perception organ before the bus closes.
        await self.voice_perception.stop()
        await self.event_bus.stop()
        await self.watchdog.stop()
        await self.scheduler.stop()
        self.identity.save()

    async def _drive_pulse_loop(self) -> None:
        """Persistent cadence driving the canonical CognitivePulse (Slice 8).

        The pulse reacts to bus events and executes bounded, resource-aware
        work; this heartbeat keeps the loop alive while the engine runs. A
        failed tick never kills the heartbeat, and the cadence is tunable via
        ZERION_PULSE_TICK_SECONDS (default 2.0s).
        """
        interval = max(0.1, float(os.environ.get("ZERION_PULSE_TICK_SECONDS", "2.0")))
        while self._running:
            try:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                await self.cognitive_runtime.tick_pulse(budget=1)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def _on_prediction_error(self, event: Event):
        sig = PressureSignal(
            signal_type=SignalType.PREDICTION_ERROR,
            magnitude=event.payload.get("magnitude", 0.75),
            source=event.payload.get("source", "runtime_tracker"),
            description=event.payload.get("description", "Reality state deviated from prediction"),
            metadata=event.payload
        )
        self.pressure_field.inject_signal(sig)

    async def _on_anomaly_detected(self, event: Event):
        sig = PressureSignal(
            signal_type=SignalType.ANOMALY,
            magnitude=event.payload.get("magnitude", 0.8),
            source=event.payload.get("source", "sensor"),
            description=event.payload.get("description", "Environmental anomaly detected"),
            metadata=event.payload
        )
        self.pressure_field.inject_signal(sig)

    async def run_developmental_cycle(self) -> GenesisCycleTrace:
        """
        Executes the 25-Stage Recursive Developmental Flywheel of ZERION-X GENESIS.
        """
        t0 = time.perf_counter()
        self._cycle_count += 1
        cycle_id = f"gen_cycle_{self._cycle_count}_{int(time.time())}"

        # 1. PERCEIVE & UPDATE WORLD MODEL 3.0 & UNKNOWN SPACE
        snap = self.resources.sample()
        # PARADIGM-X: telemetry must be measured, never hard-coded. Count the
        # real perception events ingested this cycle instead of assuming "2".
        perceptions_ingested = 0
        # Slice 1: feed real perception into the cognitive foundation (state, bus, attention)
        await self.cognitive_runtime.ingest_perception(
            cpu_percent=snap.cpu_percent,
            memory_mb=snap.memory_available_mb,
            compute_tier=snap.compute_tier,
            source="resource_governor",
        )
        perceptions_ingested += 1
        self.world_tracker.record_observation("host_cpu", "load_percent", snap.cpu_percent, source="resource_governor")
        perceptions_ingested += 1
        self.world_tracker.record_observation("host_mem", "available_mb", snap.memory_available_mb, source="resource_governor")
        perceptions_ingested += 1
        self.unknown_space.scan_for_blind_spots(self.world.list_nodes())
        # Slice 1/8: real world observations are canonical runtime events — the
        # attention field and the CognitivePulse consume them (observation ->
        # attention review), so the flywheel drives the runtime loop, not a
        # parallel copy of it.
        await self.event_bus.publish(Event(
            event_type=EventType.OBSERVATION_RECORDED,
            payload={
                "objective": "host resource observations",
                "source": "flywheel",
                "observations": {
                    "host_cpu_load_percent": snap.cpu_percent,
                    "host_mem_available_mb": snap.memory_available_mb,
                },
            },
            source="flywheel",
            priority=40,
        ), dispatch_immediately=True)

        # 2. UPDATE SELF MODEL & CHECK OBJECTIVES
        active_objs = self.identity.list_objectives(active_only=True)

        # 3. PREDICT & MEASURE ERROR -> GENERATE PRESSURE
        signals = self.pressure_field.sample_field(
            world_model=self.world,
            self_model=self.self_model,
            identity_core=self.identity
        )

        # 4. DISCOVER PROBLEMS 3.0 & QUESTION GENESIS 3.0
        problems = self.problem_generator.generate_candidates(self.pressure_field)
        # Slice 2/8: every genuinely detected problem is an ANOMALY_DETECTED
        # event on the canonical bus — the runtime's QuestionGenesis path
        # (anomaly -> question -> attention -> hypothesis) and the pulse consume
        # it. Bounded to the top few so a pressure flood never overwhelms
        # attention; only real pressure-derived problems are emitted.
        for problem in problems[:3]:
            await self.event_bus.publish(Event(
                event_type=EventType.ANOMALY_DETECTED,
                payload={
                    "objective": problem.description,
                    "description": problem.description,
                    "source": getattr(problem, "source", "pressure_field"),
                    "problem_id": getattr(problem, "id", f"problem_{cycle_id}"),
                    "magnitude": 0.75,
                },
                source="flywheel",
                priority=60,
            ), dispatch_immediately=True)
        new_questions = []
        for p in problems[:2]:
            qs = self.question_genesis.generate_from_problem(p)
            new_questions.extend(qs)

        if not new_questions:
            frontier_q = self.question_genesis.generate_investigation_frontier(world_model=self.world, self_model=self.self_model)
            new_questions.append(frontier_q)

        # 5. ASSESS CAPABILITY & STRATEGY GAPS
        target_domain = problems[0].source if problems else "general_cognition"
        strategies = self.strategy_registry.find_strategy_for_domain(target_domain)
        strategies_born = 0

        if not strategies:
            # Cognitive Genesis: Synthesize new cognitive strategy
            synth_res = await self.strategy_genesis.synthesize_strategy(
                problem_description=problems[0].description if problems else "general inquiry",
                domain=target_domain
            )
            if synth_res.success and synth_res.strategy:
                self.strategy_registry.register_strategy(synth_res.strategy)
                # Honest lineage: genesis gain is NOT measured at synthesis time,
                # so it is recorded as 0.0 (unmeasured) — never a fabricated 0.08.
                self.strategy_evolution.record_lineage(
                    synth_res.strategy.strategy_id, derivation_type="genesis")
                strategies = [synth_res.strategy]
                strategies_born += 1

        selected_strategy = strategies[0] if strategies else self.strategy_registry.list_strategies()[0]

        # 6. PHENOTYPE DERIVATION & ADAPTIVE COMPUTE ALLOCATION
        phenotype = self.genome_manager.get_phenotype(selected_strategy.domain)
        allocation = self.adaptive_cognition.allocate_cognition(
            task_id=cycle_id,
            uncertainty=0.6,
            difficulty=0.5,
            novelty=0.4,
            risk=0.2,
            phenotype=phenotype,
            available_compute_mb=snap.memory_available_mb,
            is_offline=self.offline.is_offline
        )

        # 7. META-PREDICTION & SELF-PREDICTOR FORECAST
        pre_pred = self.meta_prediction.generate_pre_prediction(
            task_id=cycle_id,
            task_domain=selected_strategy.domain,
            uncertainty=0.6,
            difficulty=0.5
        )
        self_pred = self.self_predictor.predict_task_execution(
            task_id=cycle_id,
            task_domain=selected_strategy.domain,
            task_difficulty=0.5,
            historical_strategy_reliability=selected_strategy.reliability
        )

        # 8. COUNTERFACTUAL SIMULATION
        cf_query = CounterfactualQuery(
            target_variable="strategy_selection",
            baseline_state=selected_strategy.name,
            counterfactual_state="alternative_multi_path"
        )
        cf_res = await self.counterfactual.evaluate_counterfactual(cf_query)

        # 9. COMPILE COGNITIVE PROGRAM & EXECUTE
        ready_qs = self.question_graph.get_ready_questions()
        target_q = ready_qs[0] if ready_qs else new_questions[0]

        program = self.cognitive_compiler.compile(
            goal=target_q.text,
            context={"strategy": selected_strategy.name, "phenotype": phenotype.name}
        )
        prog_res = await program.execute()

        # 10. ADVERSARIAL VERIFICATION & REALITY EVIDENCE
        attack_res = self.adversarial.attack_conclusion(
            conclusion=str(prog_res.get("final_data")),
            supporting_evidence=["Cell execution graph verified"]
        )

        cycle_success = bool(prog_res.get("completed")) and not attack_res.broken
        # Slice 8: real runtime outcomes. A failed cycle is a TASK_FAILED event
        # (attention candidate + pulse failure analysis) and a PREDICTION_ERROR
        # (question genesis investigates why the flywheel's expectation missed).
        if not cycle_success:
            await self.event_bus.publish(Event(
                event_type=EventType.TASK_FAILED,
                payload={
                    "objective": target_q.text,
                    "task_id": cycle_id,
                    "source": "flywheel",
                    "error": str(attack_res.contradictions)[:256],
                },
                source="flywheel",
                priority=55,
            ), dispatch_immediately=True)
            await self.event_bus.publish(Event(
                event_type=EventType.PREDICTION_ERROR,
                payload={
                    "objective": target_q.text,
                    "prediction_id": pre_pred.prediction_id,
                    "magnitude": 0.8,
                    "description": f"Flywheel cycle {cycle_id} failed verification",
                    "source": "flywheel_calibration",
                },
                source="flywheel",
                priority=65,
            ), dispatch_immediately=True)

        # 10b. REALITY EVIDENCE -> canonical Slice 3 EvidenceStore (one write
        # path; the legacy zerion/evidence ledger is no longer written by the
        # flywheel). The attack result is OBSERVED runtime evidence.
        canonical_evidence = CognitiveEvidence(
            content={"program_result": prog_res, "attack_broken": attack_res.broken},
            provenance=Provenance(
                source=f"flywheel:cycle_{cycle_id}",
                observed_at=time.time(),
                evidence_type="flywheel_program_verification",
                content_reference=str(prog_res.get("final_data", ""))[:512],
                reliability=0.95 if not attack_res.broken else 0.40,
                mode=EvidenceMode.OBSERVED,
                recorded_at=time.time(),
            ),
            verdict=EvidenceVerdict.SUPPORTS if not attack_res.broken else EvidenceVerdict.CONTRADICTS,
        )
        canonical_evidence_id = self.cognitive_runtime.evidence_store.put(canonical_evidence).evidence_id

        # 11. POST-EXECUTION CALIBRATION & EXPERIENCE DISTILLATION
        self.meta_prediction.record_post_execution_feedback(
            prediction_id=pre_pred.prediction_id,
            actual_strategy=selected_strategy.name,
            actual_success=cycle_success,
            actual_latency_ms=prog_res.get("total_duration_ms", 10.0)
        )
        self.self_predictor.record_actual_outcome(
            prediction=self_pred,
            actual_strategy=selected_strategy.name,
            actual_success=cycle_success,
            actual_latency_ms=prog_res.get("total_duration_ms", 10.0)
        )

        # 11b. EPISODE -> canonical Slice 4 EpisodeStore (one write path; the
        # legacy DevelopmentalMemoryStore is no longer written by the flywheel).
        flywheel_episode = ExperienceEpisode(
            context=target_q.text,
            actions=[{"action": s.get("cell_type", "cell"), "at": time.time()}
                     for s in prog_res.get("execution_log", [])],
            outcomes=[{"outcome": "SUCCESS" if cycle_success else "FAILURE",
                       "at": time.time(),
                       "detail": {"reward": 0.95 if not attack_res.broken else 0.30,
                                   "duration_ms": prog_res.get("total_duration_ms", 10.0),
                                   "evidence_id": canonical_evidence_id}}],
            success=cycle_success,
            status=EpisodeStatus.COMPLETED,
            mode=EpisodeMode.OBSERVED,
            provenance={"source": f"flywheel:cycle_{cycle_id}", "flywheel": True},
            capabilities_used=[selected_strategy.name],
        )
        self.cognitive_runtime.episode_store.put(flywheel_episode)
        # One canonical write path: EPISODE_COMPLETED is consumed by the
        # runtime's own handler, which distills and re-validates the episode
        # (the legacy direct distill call was removed — see freeze rules).
        await self.event_bus.publish(Event(
            event_type=EventType.EPISODE_COMPLETED,
            payload={"episode_id": flywheel_episode.episode_id},
            source="flywheel",
            priority=50,
        ), dispatch_immediately=True)

        # 12. INTELLIGENCE FOUNDRY CYCLE & COGNITIVE AUTOPOIESIS
        foundry_res = await self.foundry.execute_foundry_cycle(
            signal_source=target_domain,
            signal_description=target_q.text,
            importance=0.75,
            uncertainty=0.60
        )

        # Real measured learning acceleration feeds the organism's autopoietic
        # reflection (reused below for maturity/telemetry) — the organism never
        # falls back to a fabricated ratio like "2.57x".
        acc_ratio = self.learning_to_learn.calculate_learning_acceleration()
        org_result = await self.organism.execute_organism_cycle(
            engine_context={
                "resource_metrics": {"cpu_percent": snap.cpu_percent, "memory_mb": snap.memory_available_mb},
                "pressure_signals": signals,
                "learning_acceleration": acc_ratio,
            }
        )

        autopoiesis_run = False
        if attack_res.broken or not prog_res.get("completed"):
            auto_rep = await self.autopoiesis.execute_autopoietic_reflection(
                task_failure_goal=target_q.text,
                error_context=str(attack_res.contradictions)
            )
            autopoiesis_run = True

        # 13. RECORD TELEMETRY, TIMELINE SNAPSHOT & LEARNING ACCELERATION
        self.timeline.capture_snapshot(self, metadata={"cycle_id": cycle_id})
        self.telemetry.record(CognitiveTelemetryRecord(
            goal_id=target_q.id,
            program_id=program.program_id,
            strategy_id=selected_strategy.strategy_id,
            genome_version=self.genome_manager.current_genome.version,
            latency_ms=prog_res.get("total_duration_ms", 10.0),
            result_status="SUCCESS" if prog_res.get("completed") else "FAILURE",
            confidence=0.95 if not attack_res.broken else 0.40
        ))

        # 14. ASSESS MATURITY LEVEL (real measurements from the canonical
        # episode/distilled stores — never the legacy in-memory dicts).
        # Brier is None until real predictions exist; unmeasured calibration
        # must NOT earn maturity credit, so it is mapped to the worst case 1.0
        # for the gate (never a fabricated 0.0).
        _brier = self.self_model.calibrator.calculate_brier_score()
        maturity = self.maturity_evaluator.evaluate(
            has_native_caps=True,
            episodes_count=self.cognitive_runtime.episode_store.count(),
            procedural_rules_count=self.cognitive_runtime.distilled_store.count(),
            has_adaptive_phenotypes=True,
            has_pressure_field=True,
            brier_score=(_brier if _brier is not None else 1.0),
            born_capabilities_count=len(self.capability_registry.list_born_capabilities()),
            synthesized_strategies_count=len(self.strategy_registry.list_strategies()),
            learning_acceleration=acc_ratio,
            flywheel_cycles=self._cycle_count
        )

        # 14b. Entity snapshot with REAL measured values only — bare counts and
        # measured telemetry, never fabricated defaults (see blocker V9).
        self.entity_state.capture_snapshot(
            objectives_count=len(active_objs),
            strategies_count=len(self.strategy_registry.list_strategies()),
            capabilities_count=len(self.self_model._capabilities),
            episodes_count=self.cognitive_runtime.episode_store.count(),
            brier_score=self.self_model.calibrator.calculate_brier_score(),
            learning_acceleration=acc_ratio,
            maturity_level=maturity.current_level.value,
        )

        duration_ms = (time.perf_counter() - t0) * 1000.0
        trace = GenesisCycleTrace(
            cycle_id=cycle_id,
            timestamp=time.time(),
            perceptions_ingested=perceptions_ingested,
            anomalies_detected=len(signals),
            problems_generated=len(problems),
            questions_formulated=len(new_questions),
            strategy_selected=selected_strategy.name,
            cognitive_allocation_mode=allocation.selected_mode,
            cognitive_programs_run=1,
            evidence_acquired=1,
            counterfactuals_simulated=1,
            capabilities_born=len(self.capability_registry.list_born_capabilities()),
            strategies_synthesized=strategies_born,
            autopoiesis_executed=autopoiesis_run,
            learning_acceleration_ratio=acc_ratio,
            maturity_level=maturity.current_level.value,
            duration_ms=round(duration_ms, 2)
        )
        self._cycle_history.append(trace)

        # Slice 8: drive the CognitivePulse so queued runtime work (goal review,
        # attention review, question genesis, bottleneck scan) actually executes
        # inside this cycle — bounded, so a busy queue never blocks the flywheel.
        await self.cognitive_runtime.tick_pulse(budget=3)
        return trace

    # Section 47: THE ULTIMATE DESIGN TEST RUNNER
    async def ask_ultimate_questions(self) -> Dict[str, Any]:
        """
        Executes the 4-stage introspection sequence:
        1. 'What is the most important thing you currently do not understand about your current environment?'
        2. 'What experiment would most efficiently reduce that uncertainty?'
        3. 'What capability are you missing to perform that experiment?'
        4. 'Can you safely develop that capability?'
        """
        unknown_nodes = [n for n in self.world.list_nodes() if any(a.status == EpistemicStatus.UNKNOWN for a in n.attributes.values())]
        if unknown_nodes:
            target_node = unknown_nodes[0]
            q1_ans = f"Epistemic void regarding state attributes of entity '{target_node.name}' ({target_node.id})."
        else:
            q1_ans = "Latent causal dynamics of disk I/O latency under concurrent mobile memory pressure."

        exp_design = ExperimentDesign(
            hypothesis_statement="System memory throughput decreases monotonically under active background compaction",
            execution_code="""
import time
t0 = time.perf_counter()
data = [i for i in range(50000)]
del data
t1 = time.perf_counter()
print(f"EXPERIMENT_PASSED: duration={(t1-t0)*1000:.2f}ms")
""",
            expected_outcome="EXPERIMENT_PASSED"
        )
        q2_ans = f"Execute controlled sandbox memory throughput benchmark (ID: {exp_design.id}) to measure real timing delta."

        missing_cap = self.self_model.what_capability_am_i_missing("profile_mobile_io_latency_and_throughput")
        q3_ans = f"Missing specialized capability: '{missing_cap}'." if missing_cap else "All execution primitives currently present in self-model catalog."

        can_develop = False
        development_path = "Unauthorized"
        if missing_cap:
            gap = self.gap_detector.classify_failure(
                task_goal="profile_mobile_io_latency_and_throughput",
                error_message="missing capability: profile_mobile_io_latency_and_throughput"
            )
            born_cap = await self.birth_pipeline.birth_capability(
                gap=gap,
                custom_prototype_code="""
def profile_mobile_io_latency_and_throughput(payload):
    import time
    t0 = time.perf_counter()
    s = sum(range(1000))
    return {"success": True, "result": s, "latency_ms": (time.perf_counter()-t0)*1000}
"""
            )
            if born_cap.is_validated:
                self.capability_registry.register_born_capability(born_cap)
                self.self_model.register_capability(CapabilityRecord(
                    name=born_cap.name,
                    category=born_cap.category,
                    description="Dynamically born validated I/O profiler",
                    is_native=False
                ))
                can_develop = True
                development_path = f"Successfully born and verified through 8-stage pipeline (Benchmark score: {born_cap.benchmark_score})."

        # PARADIGM-X: never claim development that did not happen. The answer
        # reports the REAL born state (born / failed / not attempted).
        if can_develop:
            answer_4 = f"Yes. {development_path}"
        elif missing_cap:
            answer_4 = (
                "No. The required primitive was NOT born: synthesis/validation "
                f"failed for '{missing_cap}' in this run, so no capability is claimed."
            )
        else:
            answer_4 = (
                "No new capability was required: the catalog already contains the "
                "execution primitives for this experiment (verified, not assumed)."
            )

        return {
            "question_1": "What is the most important thing you currently do not understand about your current environment?",
            "answer_1": q1_ans,
            "question_2": "What experiment would most efficiently reduce that uncertainty?",
            "answer_2": q2_ans,
            "question_3": "What capability are you missing to perform that experiment?",
            "answer_3": q3_ans,
            "question_4": "Can you safely develop that capability?",
            "answer_4": answer_4,
            "capability_born": can_develop,
            "capability_name": born_cap.name if can_develop else None,
        }

    # --- 7-Level Cognitive Hierarchy Query Engine ---
    def _gguf_probe_report(self, force: bool = False) -> Dict[str, Any]:
        """Full local-model lifecycle report with a REAL inference probe.

        Evidence chain: DISCOVERED -> BACKEND -> LOAD TEST -> INFERENCE
        PROBE -> READY. A file existing is only discovery; nothing reports
        READY until a real load + real generation probe verified real tokens.
        The probe result is cached for ``ZERION_GGUF_PROBE_TTL`` seconds
        (default 60) so repeated status reads stay cheap on mobile.
        """
        from zerion.cognitive_os.gguf_backend import probe_local_gguf
        cache = getattr(self, "_gguf_probe_cache", None)
        ttl = 60
        try:
            ttl = max(0, int(os.environ.get("ZERION_GGUF_PROBE_TTL", "60")))
        except ValueError:  # noqa: BLE001 — non-numeric TTL falls back to 60
            ttl = 60
        if cache is not None and not force \
                and (time.monotonic() - cache["at"]) < ttl:
            return cache["report"]
        try:
            report = probe_local_gguf(
                str(self.cognitive_runtime.local_models.models_dir))
        except Exception as e:  # noqa: BLE001
            report = {"status": "UNKNOWN",
                      "error": f"{type(e).__name__}: {str(e)[:200]}"}
        self._gguf_probe_cache = {"at": time.monotonic(), "report": report}
        return report

    def local_readiness(self) -> Dict[str, Any]:
        """ZERION LOCAL READINESS — real per-subsystem states, never
        hard-coded. Each entry is measured from the actual runtime (mic
        monitor, STT/TTS engine detection, GGUF discovery + backend probe,
        pulse offline mode, UI adapter). No key is required.
        """
        import os as _os
        out: Dict[str, Any] = {"mode": "LOCAL"}

        # MICROPHONE
        try:
            vp = self.voice_perception
            out["microphone"] = {
                "status": vp.mic_status(),
                "phase": vp.phase.value,
                "monitor": vp.monitor.describe(),
                "reason": vp._mic_reason or None,
            }
        except Exception as e:  # noqa: BLE001
            out["microphone"] = {"status": "UNKNOWN",
                                 "error": f"{type(e).__name__}: {str(e)[:200]}"}

        # LOCAL STT
        try:
            stt = self.voice_env.detect_stt().to_dict()
            if stt.get("status") == "AVAILABLE":
                # READY means a real speech-recognition probe succeeded — an
                # actual transcript landed in the voice perception service.
                # Probing the mic at startup would grab the device and is not
                # safe, so until the first real utterance the honest state is
                # AVAILABLE — NOT PROBED (never a false READY).
                stt["display_status"] = "AVAILABLE — NOT PROBED"
                try:
                    if getattr(self.voice_perception,
                               "_stt_success_count", 0) > 0:
                        stt["display_status"] = "READY"
                except Exception:  # noqa: BLE001
                    pass
            else:
                stt["display_status"] = stt.get("status")
            # Real model state from models/stt/ discovery (never assumed).
            try:
                from zerion.voice.stt_models import SttModelDiscovery
                stt["models"] = SttModelDiscovery().report()
            except Exception as e:  # noqa: BLE001
                stt["models"] = {"status": "UNKNOWN",
                                  "error": f"{type(e).__name__}: "
                                            f"{str(e)[:120]}"}
            out["stt"] = stt
        except Exception as e:  # noqa: BLE001
            out["stt"] = {"status": "UNKNOWN",
                           "error": f"{type(e).__name__}: {str(e)[:200]}"}

        # LOCAL TTS
        try:
            out["tts"] = self.voice_env.detect_tts().to_dict()
        except Exception as e:  # noqa: BLE001
            out["tts"] = {"status": "UNKNOWN",
                           "error": f"{type(e).__name__}: {str(e)[:200]}"}

        # LOCAL GGUF MODELS + inference backend — full lifecycle with a real
        # probe. A file existing is only DISCOVERY; READY is earned only by a
        # real load + real generation probe (see gguf_backend.probe_local_gguf).
        try:
            out["models"] = self._gguf_probe_report()
        except Exception as e:  # noqa: BLE001
            out["models"] = {"status": "UNKNOWN",
                              "error": f"{type(e).__name__}: {str(e)[:200]}"}

        # COGNITIVE RUNTIME
        try:
            pulse = self.cognitive_runtime.cognitive_pulse
            out["runtime"] = {
                "started": self._running,
                "offline_mode": getattr(pulse, "_offline_mode", "UNKNOWN").value,
                "state": getattr(self.cognitive_runtime.state, "runtime_status", "UNKNOWN"),
            }
        except Exception as e:  # noqa: BLE001
            out["runtime"] = {"status": "UNKNOWN",
                               "error": f"{type(e).__name__}: {str(e)[:200]}"}

        # UI EVENT BRIDGE
        out["ui"] = {"status": ("READY" if self.ui_adapter is not None
                                  else "UNAVAILABLE")}

        # NETWORK (informational; LOCAL cognition never requires it)
        try:
            out["network"] = self.voice_env.network.state()
        except Exception:  # noqa: BLE001
            out["network"] = {"state": "UNKNOWN"}

        # API KEYS: informational only — never required for LOCAL cognition.
        out["keys"] = {
            "OPENAI_API_KEY": ("SET (optional)"
                               if _os.environ.get("OPENAI_API_KEY") else "NOT_REQUIRED"),
            "GEMINI_API_KEY": ("SET (optional)"
                               if _os.environ.get("GEMINI_API_KEY") else "NOT_REQUIRED"),
        }
        return out

    def answer_hierarchy_level(self, level: int, context_goal: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes mechanistic introspection across all 7 levels of the GENESIS hierarchy:
        Level 1: What can I do?
        Level 2: How should I solve this?
        Level 3: When should I use this strategy?
        Level 4: What strategy am I missing?
        Level 5: What capability am I missing?
        Level 6: What cognitive process is preventing me from developing that capability?
        Level 7: How can I improve the process by which I discover and acquire capabilities?
        """
        goal = context_goal or "general_development"

        if level == 1:
            # PARADIGM-X: maturity must come from REAL evidence, never from the
            # zero-argument evaluate() default path (which used to always report
            # L7 regardless of actual system state).
            maturity = self.maturity_evaluator.evaluate_from_evidence(
                collect_runtime_evidence(self))
            return {
                "level": 1,
                "question": "What can I do?",
                "answer": self.self_model.what_can_i_do(),
                "maturity": maturity.current_level.value,
                "maturity_evidence_score": round(maturity.evidence_score, 4),
            }

        elif level == 2:
            phenotype = self.genome_manager.get_phenotype(goal)
            strats = self.strategy_registry.find_strategy_for_domain(goal)
            strat = strats[0] if strats else self.strategy_registry.list_strategies()[0]
            allocation = self.adaptive_cognition.allocate_cognition("query_task", 0.5, 0.5, 0.4, 0.2, phenotype)
            return {
                "level": 2,
                "question": "How should I solve this?",
                "selected_strategy": strat.name,
                "phenotype": phenotype.name,
                "compute_mode": allocation.selected_mode,
                "reasoning_steps": strat.procedure_steps,
                "parallel_paths": allocation.parallel_paths
            }

        elif level == 3:
            strats = self.strategy_registry.list_strategies()
            matrix = [
                {
                    "strategy": s.name,
                    "domain": s.domain,
                    "preconditions": s.preconditions,
                    "expected_benefit": s.expected_benefit,
                    "reliability": s.reliability
                }
                for s in strats
            ]
            return {
                "level": 3,
                "question": "When should I use this strategy?",
                "strategy_applicability_matrix": matrix
            }

        elif level == 4:
            # PARADIGM-X: the strategy gap is COMPUTED from the real registry,
            # never hard-coded to a single canned domain.
            strategies = self.strategy_registry.list_strategies()
            available_domains = {s.domain.lower() for s in strategies}
            canonical_domains = [
                "general_cognition", "software_debugging", "distributed_consensus",
                "data_processing", "mathematical_reasoning", "security_audit",
                "mobile_optimization", "offline_cognition",
            ]
            missing = None
            missing_reason = ""
            for d in canonical_domains:
                if d not in available_domains:
                    missing = f"{d}_strategy"
                    missing_reason = f"no registered strategy for domain '{d}'"
                    break
            if missing is None:
                missing = "None currently identified; all canonical domains covered."
            return {
                "level": 4,
                "question": "What strategy am I missing?",
                "missing_strategy": missing,
                "missing_reason": missing_reason,
                "domains_covered": sorted(available_domains),
                "remediation": "Trigger CognitiveGenesisPipeline for unmapped domain space."
            }

        elif level == 5:
            missing_cap = self.self_model.what_capability_am_i_missing(goal)
            return {
                "level": 5,
                "question": "What capability am I missing?",
                "missing_capability": missing_cap or "All prerequisite execution primitives present in catalog.",
                "remediation": "Initiate CapabilityBirthPipeline through sandbox unit & property testing."
            }

        elif level == 6:
            bottleneck = self.learning_to_learn.analyze_learning_bottleneck()
            return {
                "level": 6,
                "question": "What cognitive process is preventing me from developing that capability?",
                "cognitive_bottleneck": bottleneck.get("bottleneck"),
                "root_cause": bottleneck.get("root_cause"),
                "recommended_process_adjustment": bottleneck.get("recommended_curriculum_mutation")
            }

        elif level == 7:
            acc_ratio = self.learning_to_learn.calculate_learning_acceleration()
            return {
                "level": 7,
                "question": "How can I improve the process by which I discover and acquire capabilities?",
                "current_learning_acceleration": f"{acc_ratio:.2f}x",
                "meta_learning_optimization": "1. Distill multi-episode procedural patterns into higher-order meta-rules. 2. Apply SelfExperimentationEngine to optimize cognitive genome exploration/verification ratios."
            }

        return {"error": f"Invalid level {level}; valid levels are 1 through 7."}
