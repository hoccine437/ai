"""
Unit tests for Pressure Field and Question Genesis
"""

import os
import shutil
import tempfile
import unittest
from zerion.pressure.signals import PressureSignal, SignalType
from zerion.pressure.field import PressureField
from zerion.pressure.generator import ProblemCandidateGenerator
from zerion.questions.question import Question, QuestionType
from zerion.questions.scorer import QuestionScorer
from zerion.questions.graph import QuestionGraph
from zerion.questions.genesis import QuestionGenesis


class TestPressureAndQuestions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.q_db = os.path.join(self.temp_dir, "questions.db")
        self.field = PressureField()
        self.prob_gen = ProblemCandidateGenerator(pressure_threshold=0.3)
        self.graph = QuestionGraph(db_path=self.q_db)
        self.genesis = QuestionGenesis(self.graph)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pressure_and_problem_genesis(self):
        sig = PressureSignal(
            signal_type=SignalType.INEFFICIENCY,
            magnitude=0.8,
            source="database_query_cache",
            description="High cache miss rate observed"
        )
        self.field.inject_signal(sig)
        self.assertEqual(self.field.total_pressure, 0.8)

        problems = self.prob_gen.generate_candidates(self.field)
        self.assertEqual(len(problems), 1)
        self.assertIn("Resolve Inefficiency", problems[0].title)

        # Question Genesis from Problem
        questions = self.genesis.generate_from_problem(problems[0])
        self.assertEqual(len(questions), 4)

        root_q = questions[0]
        self.assertEqual(root_q.question_type, QuestionType.DIAGNOSTIC)
        self.assertGreater(root_q.priority, 0.0)

    def test_question_scoring_formula(self):
        scorer = QuestionScorer()
        q = Question(
            text="Test Question",
            question_type=QuestionType.CAUSAL,
            impact=0.8,
            uncertainty=0.9,
            expected_information_gain=0.8,
            goal_relevance=0.9,
            cost=1.0
        )
        score = scorer.score(q)
        # Priority = (0.8 * 0.9 * 0.8 * 0.9 / 1.0) * 10 = 5.184
        self.assertAlmostEqual(score, 5.184, places=2)


if __name__ == "__main__":
    unittest.main()
