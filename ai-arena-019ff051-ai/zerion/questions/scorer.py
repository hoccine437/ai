"""
Question Priority Scoring Engine - Question Genesis 3.0
Computes priority based on the scientific formula:
Priority = (Impact * Uncertainty * ExpectedInformationGain * GoalRelevance) / (max(0.1, Cost) * max(0.1, 1.0 - Risk)) * 10
"""

from zerion.questions.question import Question


class QuestionScorer:
    def __init__(self, cost_floor: float = 0.1, max_priority_cap: float = 100.0):
        self.cost_floor = cost_floor
        self.max_priority_cap = max_priority_cap

    def score(self, question: Question) -> float:
        numerator = (
            question.impact *
            question.uncertainty *
            question.expected_information_gain *
            question.goal_relevance
        )
        cost_term = max(self.cost_floor, question.cost)
        risk_modifier = max(0.1, 1.0 - getattr(question, "risk", 0.0))
        denominator = cost_term * risk_modifier

        raw_score = (numerator / denominator) * 10.0
        final_score = round(min(self.max_priority_cap, max(0.0, raw_score)), 4)
        question.priority = final_score
        return final_score
