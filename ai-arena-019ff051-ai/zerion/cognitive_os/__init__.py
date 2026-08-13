"""
Cognitive OS subsystem exports for ZERION-X GENESIS X10
"""

from zerion.cognitive_os.perception import PerceptionProcessor, PerceptionFrame
from zerion.cognitive_os.attention import AttentionEconomy, AttentionItem, IntentionTarget
from zerion.cognitive_os.intention import IntentionManager
from zerion.cognitive_os.opportunity_detector import OpportunityDetector, OpportunityCandidate
from zerion.cognitive_os.problem_discovery import AutonomousProblemDiscovery, DiscoveredProblem
from zerion.cognitive_os.question_engine import CognitiveQuestionEngine, CognitiveHypothesisEngine
from zerion.cognitive_os.experiment_controller import ExperimentController, ActionController, ConsequenceAnalyzer
from zerion.cognitive_os.strategy_controller import CognitiveStrategyMarket
from zerion.cognitive_os.learning_controller import LearningController
from zerion.cognitive_os.capability_controller import CapabilityGenesisController
from zerion.cognitive_os.architecture_controller import ArchitectureEvolutionController
from zerion.cognitive_os.reflection import AutopoieticReflectionEngine
from zerion.cognitive_os.objective_manager import (
    ObjectiveContinuityManager,
    ContinuousObjective,
    ObjectiveLifecycle,
    GoalTransitionError,
    GoalDependencyError,
    ObjectiveStoreIntegrityError,
)
from zerion.cognitive_os.attention import (
    AttentionEconomy,
    AttentionItem,
    CognitivePriority,
    ResourceBudgetState,
    AttentionDecision,
)
from zerion.cognitive_os.state import (
    CognitiveState,
    RuntimeStatus,
    StateStore,
    StateIntegrityError,
    StateVersionError,
    PerceptionSnapshot,
    ResourceBudgetView,
    AttentionStateView,
    GoalStateView,
)
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.cognitive_os.organism import CognitiveOrganism, OrganismCycleResult
from zerion.cognitive_os.question import (
    Question,
    QuestionLifecycle,
    QuestionSource,
    QuestionStore,
    QuestionValidationError,
    QuestionStoreIntegrityError,
    score_question,
)
from zerion.cognitive_os.hypothesis import (
    Hypothesis,
    HypothesisLifecycle,
    HypothesisStore,
    HypothesisValidationError,
    HypothesisStoreIntegrityError,
)
from zerion.cognitive_os.question_genesis import QuestionGenesis
from zerion.cognitive_os.hypothesis_engine import HypothesisEngine
from zerion.cognitive_os.evidence import (
    Evidence,
    EvidenceMode,
    EvidenceStore,
    EvidenceValidationError,
    EvidenceStoreIntegrityError,
    EvidenceVerdict,
    Provenance,
    MODE_WEIGHT,
)
from zerion.cognitive_os.experiment import (
    Experiment,
    ExperimentLifecycle,
    ExperimentStore,
    ExperimentTransitionError,
    ExperimentType,
    ExperimentValidationError,
    ExperimentStoreIntegrityError,
)
from zerion.cognitive_os.belief import (
    Belief,
    BeliefLifecycle,
    BeliefRevision,
    BeliefStore,
    BeliefValidationError,
    BeliefStoreIntegrityError,
)
from zerion.cognitive_os.experiment_engine import (
    ExperimentPermissions,
    RealityExperimentEngine,
    ExperimentExecutionError,
    ResourceUnavailableError,
    ToolExecutionError,
    SafetyViolationError,
)
from zerion.cognitive_os.episode import (
    EpisodeMode,
    EpisodeStatus,
    EpisodeStore,
    EpisodeStoreIntegrityError,
    EpisodeValidationError,
    ExperienceEpisode,
)
from zerion.cognitive_os.distilled import (
    CausalityStatus,
    DistilledExperience,
    DistilledExperienceStore,
    DistilledStoreIntegrityError,
    DistilledType,
    DistilledValidationError,
    ValidationStatus,
)
from zerion.cognitive_os.failure_learning import (
    FailureClassification,
    FailureLearning,
    FailureRecord,
    FailureStatus,
    FailureStore,
    FailureStoreIntegrityError,
    RootCauseHypothesis,
    RootCauseStatus,
)
from zerion.cognitive_os.experience_distillation import ExperienceDistillation
from zerion.cognitive_os.knowledge_retrieval import ExperienceReuse
from zerion.cognitive_os.capability import (
    Capability,
    CapabilityHealth,
    CapabilityRegistry,
    CapabilityStatus,
    CapabilityStoreIntegrityError,
    CapabilityType,
    CapabilityValidationError,
    HIGH_RISK_PERMISSIONS,
    LEAST_PRIVILEGE,
    Permission,
    PermissionPolicy,
)
from zerion.cognitive_os.capability_sandbox import CapabilitySandbox, SecurityViolationError
from zerion.cognitive_os.capability_genesis import CapabilityGenesis
from zerion.cognitive_os.router_types import (
    CognitiveDepthLevel,
    CognitiveDepthScore,
    CognitiveField,
    CognitiveResult,
    ModelSelection,
    ProviderStatus,
    ResultStatus,
    RoutingMode,
    Task,
    TaskType,
    VerificationStatus,
    redact_secrets,
)
from zerion.cognitive_os.provider_interface import (
    ModelInfo,
    ModelProvider,
    ProviderCall,
    ProviderFailureKind,
    RawProviderResponse,
)
from zerion.cognitive_os.provider_health import ProviderHealth, ProviderHealthTracker
from zerion.cognitive_os.performance_ledger import PerformanceLedger, PerformanceStats
from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery, ModelLoadManager
from zerion.cognitive_os.local_model_registry import LocalModelRegistry
from zerion.cognitive_os.cognitive_router import CognitiveRouter, ModelSelector
from zerion.cognitive_os.provider_adapters import (
    LegacyGeminiAdapter,
    LegacyGGUFAdapter,
    LegacyOpenAIAdapter,
)
from zerion.cognitive_os.telemetry import ArchitectureTelemetry, ComponentMetric
from zerion.cognitive_os.bottlenecks import (
    BottleneckDetector,
    BottleneckReport,
    BottleneckStore,
    BottleneckType,
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
    AnalysisResult,
    BenchmarkComparison,
    GatePolicy,
    PromotionResult,
    RollbackResult,
    SelfModificationGate,
    TestOutcome,
)
from zerion.cognitive_os.telemetry_feed import TelemetryFeed
from zerion.cognitive_os.policy_store import (
    PolicyIntegrityError,
    PolicyStore,
    RuntimePolicies,
    RuntimePolicy,
)
from zerion.cognitive_os.monitor import (
    MonitorConfig,
    MonitorCycle,
    MonitorIntegrityError,
    MonitorScheduler,
    MonitorStore,
)

__all__ = [
    "PerceptionProcessor",
    "PerceptionFrame",
    "AttentionEconomy",
    "AttentionItem",
    "IntentionTarget",
    "IntentionManager",
    "OpportunityDetector",
    "OpportunityCandidate",
    "AutonomousProblemDiscovery",
    "DiscoveredProblem",
    "CognitiveQuestionEngine",
    "CognitiveHypothesisEngine",
    "ExperimentController",
    "ActionController",
    "ConsequenceAnalyzer",
    "CognitiveStrategyMarket",
    "LearningController",
    "CapabilityGenesisController",
    "ArchitectureEvolutionController",
    "AutopoieticReflectionEngine",
    "ObjectiveContinuityManager",
    "ContinuousObjective",
    "ObjectiveLifecycle",
    "GoalTransitionError",
    "GoalDependencyError",
    "ObjectiveStoreIntegrityError",
    "CognitivePriority",
    "ResourceBudgetState",
    "AttentionDecision",
    "CognitiveState",
    "RuntimeStatus",
    "StateStore",
    "StateIntegrityError",
    "StateVersionError",
    "PerceptionSnapshot",
    "ResourceBudgetView",
    "AttentionStateView",
    "GoalStateView",
    "CognitiveRuntime",
    "CognitiveOrganism",
    "OrganismCycleResult",
    "Question",
    "QuestionLifecycle",
    "QuestionSource",
    "QuestionStore",
    "QuestionValidationError",
    "QuestionStoreIntegrityError",
    "score_question",
    "Hypothesis",
    "HypothesisLifecycle",
    "HypothesisStore",
    "HypothesisValidationError",
    "HypothesisStoreIntegrityError",
    "QuestionGenesis",
    "HypothesisEngine",
    "Evidence",
    "EvidenceMode",
    "EvidenceStore",
    "EvidenceValidationError",
    "EvidenceStoreIntegrityError",
    "EvidenceVerdict",
    "Provenance",
    "MODE_WEIGHT",
    "Experiment",
    "ExperimentLifecycle",
    "ExperimentStore",
    "ExperimentTransitionError",
    "ExperimentType",
    "ExperimentValidationError",
    "ExperimentStoreIntegrityError",
    "Belief",
    "BeliefLifecycle",
    "BeliefRevision",
    "BeliefStore",
    "BeliefValidationError",
    "BeliefStoreIntegrityError",
    "ExperimentPermissions",
    "RealityExperimentEngine",
    "ExperimentExecutionError",
    "ResourceUnavailableError",
    "ToolExecutionError",
    "SafetyViolationError",
    "EpisodeMode",
    "EpisodeStatus",
    "EpisodeStore",
    "EpisodeStoreIntegrityError",
    "EpisodeValidationError",
    "ExperienceEpisode",
    "CausalityStatus",
    "DistilledExperience",
    "DistilledExperienceStore",
    "DistilledStoreIntegrityError",
    "DistilledType",
    "DistilledValidationError",
    "ValidationStatus",
    "FailureClassification",
    "FailureLearning",
    "FailureRecord",
    "FailureStatus",
    "FailureStore",
    "FailureStoreIntegrityError",
    "RootCauseHypothesis",
    "RootCauseStatus",
    "ExperienceDistillation",
    "ExperienceReuse",
    "Capability",
    "CapabilityHealth",
    "CapabilityRegistry",
    "CapabilityStatus",
    "CapabilityStoreIntegrityError",
    "CapabilityType",
    "CapabilityValidationError",
    "HIGH_RISK_PERMISSIONS",
    "LEAST_PRIVILEGE",
    "Permission",
    "PermissionPolicy",
    "CapabilitySandbox",
    "SecurityViolationError",
    "CapabilityGenesis",
    "ArchitectureTelemetry",
    "ComponentMetric",
    "BottleneckDetector",
    "BottleneckReport",
    "BottleneckStore",
    "BottleneckType",
    "ImprovementProposal",
    "ModificationType",
    "ProposalStatus",
    "ProposalStore",
    "RiskLevel",
    "CognitiveGenome",
    "GenomeManager",
    "GenomeStatus",
    "GenomeStore",
    "RuntimeSnapshot",
    "SnapshotStore",
    "AnalysisResult",
    "BenchmarkComparison",
    "GatePolicy",
    "PromotionResult",
    "RollbackResult",
    "SelfModificationGate",
    "TestOutcome",
    "TelemetryFeed",
    "PolicyIntegrityError",
    "PolicyStore",
    "RuntimePolicies",
    "RuntimePolicy",
    "MonitorConfig",
    "MonitorCycle",
    "MonitorIntegrityError",
    "MonitorScheduler",
    "MonitorStore",
]
