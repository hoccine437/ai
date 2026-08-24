"""
ZERION-X GENESIS X10 — Cognitive Organism Master Coordinator
Unites all Cognitive OS subsystems into one coherent, autonomous, continuous self-developing entity.
"""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid

from zerion.cognitive_os.perception import PerceptionProcessor
from zerion.cognitive_os.attention import AttentionEconomy, AttentionItem
from zerion.cognitive_os.intention import IntentionManager, IntentionTarget
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


@dataclass
class OrganismCycleResult:
    cycle_id: str
    focused_attention_topics: List[str]
    active_intention: str
    discovered_problems: int
    discovered_opportunities: int
    selected_strategy: str
    selected_architecture: str
    reality_consequence_verified: bool
    # None = not measured. The organism never fabricates an acceleration ratio
    # (a hard-coded "2.57x" was previously reported as if it were a real
    # measurement). The engine passes its real measured value through
    # engine_context["learning_acceleration"] when one exists.
    learning_acceleration: Optional[float]
    duration_ms: float


class CognitiveOrganism:
    """
    The High-Level Autonomous Coordination Layer of GENESIS X10.
    """
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.perception = PerceptionProcessor()
        self.attention = AttentionEconomy(capacity_slots=3)
        self.intention = IntentionManager()
        self.opportunities = OpportunityDetector()
        self.problems = AutonomousProblemDiscovery()
        self.objectives = ObjectiveContinuityManager(db_path=f"{data_dir}/continuous_objectives.db")
        self.question_engine = CognitiveQuestionEngine()
        self.hypothesis_engine = CognitiveHypothesisEngine()
        self.experiments = ExperimentController()
        self.actions = ActionController()
        self.consequences = ConsequenceAnalyzer()
        self.strategy_market = CognitiveStrategyMarket()
        self.learning_controller = LearningController()
        self.capability_genesis = CapabilityGenesisController()
        self.architecture_controller = ArchitectureEvolutionController()
        self.reflection_engine = AutopoieticReflectionEngine()
        self._cycle_count: int = 0

    async def execute_organism_cycle(
        self,
        engine_context: Dict[str, Any]
    ) -> OrganismCycleResult:
        t0 = time.perf_counter()
        self._cycle_count += 1
        cid = f"org_cycle_{self._cycle_count}_{int(time.time())}"

        # 1. PERCEPTION
        metrics = engine_context.get("resource_metrics", {"cpu_percent": 15.0, "memory_mb": 1024.0})
        frame = self.perception.capture_frame(source="host_governor", metrics=metrics)

        # 2. ATTENTION ECONOMY: Filter perception into high-priority attention items
        att_item = AttentionItem(
            topic="Continuous Autonomous Objective Verification",
            source="objective_manager",
            urgency=0.75,
            importance=0.85,
            uncertainty=0.40,
            novelty=0.30,
            objective_relevance=0.95,
            expected_information_gain=0.70,
            resource_cost=0.5
        )
        self.attention.submit_candidate(att_item)
        focused = self.attention.get_focused_attention()

        # 3. INTENTION FORMULATION
        top_att = focused[0] if focused else att_item
        intent = self.intention.formulate_intention(top_att)

        # 4. OPPORTUNITY & PROBLEM DISCOVERY
        active_objs = [o.to_dict() for o in self.objectives.list_active_objectives()]
        opps = self.opportunities.scan_for_opportunities(metrics, active_objs, ["bloom_filter_indexer", "btree_index"])
        probs = self.problems.evaluate_pressure_signals(engine_context.get("pressure_signals", []))

        # 5. STRATEGY MARKET & ARCHITECTURE SELECTION
        strat = self.strategy_market.select_best_strategy(intent.goal_statement)
        strat_name = strat.name if strat else "AdversarialInvariantDefense"
        arch = self.architecture_controller.select_best_topology(task_difficulty=0.5, uncertainty=0.4)

        # 6. ACTION & REALITY CONSEQUENCE ANALYSIS
        action_res = await self.actions.perform_action(
            action_name=f"execute_{strat_name}",
            action_payload={"intention_id": intent.intention_id}
        )
        consequence = self.consequences.analyze_consequence(
            expected_state={"status": "COMPLETED"},
            observed_state=action_res,
            duration_ms=5.0
        )

        # 7. AUTOPOIETIC REFLECTION
        # The engine injects its real measured acceleration ratio via
        # engine_context["learning_acceleration"] (an Optional[float]); without
        # it the reflection is honestly UNMEASURED. No fabricated 2.57, and no
        # invented strategy-market reputations.
        measured_acceleration = engine_context.get("learning_acceleration")
        reflection = self.reflection_engine.perform_reflection(
            recent_learning_acceleration=measured_acceleration,
            strategy_market_reputations={},
            failed_tasks_count=0
        )

        duration = (time.perf_counter() - t0) * 1000.0
        return OrganismCycleResult(
            cycle_id=cid,
            focused_attention_topics=[f.topic for f in focused],
            active_intention=intent.goal_statement,
            discovered_problems=len(probs),
            discovered_opportunities=len(opps),
            selected_strategy=strat_name,
            selected_architecture=arch.name,
            reality_consequence_verified=consequence.reality_verified,
            learning_acceleration=measured_acceleration,
            duration_ms=round(duration, 2)
        )
