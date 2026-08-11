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
from zerion.cognitive_os.objective_manager import ObjectiveContinuityManager, ContinuousObjective
from zerion.cognitive_os.organism import CognitiveOrganism, OrganismCycleResult

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
    "CognitiveOrganism",
    "OrganismCycleResult",
]
