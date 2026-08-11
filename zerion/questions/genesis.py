"""
Autonomous Question Genesis Engine
"""

from typing import List, Optional
from zerion.pressure.generator import ProblemCandidate
from zerion.questions.question import Question, QuestionType, QuestionStatus
from zerion.questions.graph import QuestionGraph
from zerion.world.graph import WorldModel
from zerion.self_model.introspector import SelfModel


class QuestionGenesis:
    def __init__(self, question_graph: QuestionGraph):
        self.graph = question_graph

    def generate_from_problem(self, problem: ProblemCandidate) -> List[Question]:
        """
        Decomposes a ProblemCandidate into a structured hierarchy of diagnostic, causal,
        and counterfactual questions.
        """
        root_q = Question(
            text=f"What is the root cause of: '{problem.title}'?",
            question_type=QuestionType.DIAGNOSTIC,
            origin="problem_candidate",
            uncertainty=0.9,
            expected_information_gain=0.85,
            impact=problem.impact,
            goal_relevance=0.9,
            cost=1.0,
            metadata={"problem_id": problem.id}
        )
        self.graph.add_question(root_q)

        # Causal follow-up
        causal_q = Question(
            text=f"What mechanism triggers the anomaly in {problem.source}?",
            question_type=QuestionType.CAUSAL,
            origin="problem_candidate",
            parent_question_id=root_q.id,
            uncertainty=0.8,
            expected_information_gain=0.8,
            impact=problem.impact,
            goal_relevance=0.85,
            cost=1.2,
            dependencies=[root_q.id]
        )
        self.graph.add_question(causal_q)

        # Counterfactual question
        cf_q = Question(
            text=f"What would happen if the state of {problem.source} is restored or patched?",
            question_type=QuestionType.COUNTERFACTUAL,
            origin="problem_candidate",
            parent_question_id=causal_q.id,
            uncertainty=0.7,
            expected_information_gain=0.75,
            impact=problem.impact * 0.9,
            goal_relevance=0.8,
            cost=1.5,
            dependencies=[causal_q.id]
        )
        self.graph.add_question(cf_q)

        # Falsification question
        falsify_q = Question(
            text=f"What observable evidence would disprove our hypothesis about {problem.source}?",
            question_type=QuestionType.FALSIFICATION,
            origin="problem_candidate",
            parent_question_id=causal_q.id,
            uncertainty=0.6,
            expected_information_gain=0.9,
            impact=problem.impact,
            goal_relevance=0.9,
            cost=1.0,
            dependencies=[causal_q.id]
        )
        self.graph.add_question(falsify_q)

        return [root_q, causal_q, cf_q, falsify_q]

    def generate_investigation_frontier(
        self,
        world_model: Optional[WorldModel] = None,
        self_model: Optional[SelfModel] = None
    ) -> Question:
        """
        Answers: «"What should I investigate next?"» autonomously by scanning epistemic voids.
        """
        frontier_q = Question(
            text="What is the most critical unknown or uncertainty currently constraining system performance?",
            question_type=QuestionType.META_COGNITIVE,
            origin="metacognitive_frontier",
            uncertainty=0.95,
            expected_information_gain=0.95,
            impact=0.9,
            goal_relevance=1.0,
            cost=1.0
        )
        self.graph.add_question(frontier_q)
        return frontier_q
