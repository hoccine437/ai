"""
Slice 2 — HypothesisEngine.

For one question, generates at least two COMPETING explanations. Each hypothesis is
falsifiable: it carries assumptions, predictions, expected evidence and failure
conditions. Generation is deterministic (no LLM, no randomness).

A generated hypothesis is DATA, not knowledge: nothing is declared true, nothing is
executed, and no permissions are implied. Experiments / evidence testing belong to
Slice 3 (RealityExperimentEngine) and are intentionally NOT performed here.
"""

import time
from typing import Any, Dict, List, Optional

from zerion.cognitive_os.hypothesis import (
    Hypothesis,
    HypothesisLifecycle,
    HypothesisStore,
    HypothesisValidationError,
)
from zerion.cognitive_os.question import Question, QuestionStore


class HypothesisEngine:
    def __init__(self, hypothesis_store: HypothesisStore,
                 question_store: Optional[QuestionStore] = None):
        self.hypotheses = hypothesis_store
        self.question_store = question_store

    def generate_for_question(self, question: Question) -> List[Hypothesis]:
        """Generate competing hypotheses for a stored question. Duplicates are skipped.

        Raises HypothesisValidationError for unknown question references or
        malformed questions — never silently produces empty output.
        """
        if question is None or not str(question.question).strip():
            raise HypothesisValidationError("Cannot generate hypotheses for an empty question")
        if self.question_store is not None and self.question_store.get(question.question_id) is None:
            raise HypothesisValidationError(f"Unknown question reference: {question.question_id}")

        candidates = self._competing_hypotheses(question)
        generated: List[Hypothesis] = []
        for h in candidates:
            if self.hypotheses.get_by_fingerprint(h.question_id, h.statement):
                continue  # duplicate hypothesis for the same question
            self.hypotheses.put(h)
            generated.append(h)
        return generated

    # --- Competing explanations -----------------------------------------------

    def _competing_hypotheses(self, question: Question) -> List[Hypothesis]:
        source = question.source
        if source == "CONTRADICTION":
            return self._contradiction_hypotheses(question)
        if source == "PREDICTION_FAILURE":
            return self._prediction_failure_hypotheses(question)
        if source == "ANOMALY":
            return self._anomaly_hypotheses(question)
        if source in ("GOAL_GAP", "MISSING_DEPENDENCY"):
            return self._goal_gap_hypotheses(question)
        return self._generic_hypotheses(question)

    def _contradiction_hypotheses(self, question: Question) -> List[Hypothesis]:
        ctx = question.metadata or {}
        observed = str(ctx.get("observed") or "the observed outcome")
        expected = str(ctx.get("expected") or "the expected state")

        return [
            self._make(
                question,
                statement=f"An unobserved cause produced {observed}.",
                confidence=0.45,
                assumptions=[
                    f"A hidden variable exists and is not yet observed",
                    f"The rule '{expected} precedes {observed}' is correct",
                ],
                predictions=[
                    f"A candidate hidden cause will be identified that explains {observed}",
                ],
                expected_evidence=[
                    f"Measurement finds a third factor that correlates with {observed}",
                ],
                failure_conditions=[
                    f"All candidate causes are measured and ruled out",
                ],
            ),
            self._make(
                question,
                statement=f"The observation that {expected} did not occur is inaccurate.",
                confidence=0.40,
                assumptions=[
                    "The observation channel can be fallible",
                ],
                predictions=[
                    f"Re-observation will find {expected} present",
                ],
                expected_evidence=[
                    f"An independent re-observation records {expected}",
                ],
                failure_conditions=[
                    f"Independent re-observation confirms {expected} absent",
                ],
            ),
            self._make(
                question,
                statement=f"The rule that {expected} precedes {observed} is incorrect.",
                confidence=0.35,
                assumptions=[
                    "The causal ordering rule itself may be wrong",
                ],
                predictions=[
                    f"Further cases of {observed} without {expected} will recur",
                ],
                expected_evidence=[
                    f"More {observed}-without-{expected} cases are observed over time",
                ],
                failure_conditions=[
                    f"Every observed {observed} case is preceded by {expected}",
                ],
            ),
        ]

    def _prediction_failure_hypotheses(self, question: Question) -> List[Hypothesis]:
        ctx = question.metadata or {}
        subject = str(ctx.get("subject") or "the system")
        expected = str(ctx.get("expected") or "the prediction")
        return [
            self._make(
                question,
                statement=f"The model underlying the prediction for {subject} is incomplete.",
                confidence=0.45,
                assumptions=[f"Reality follows the measured variables for {subject}"],
                predictions=[f"A previously ignored variable will account for the failure"],
                expected_evidence=[f"Adding the missing variable restores prediction accuracy"],
                failure_conditions=[f"All measured variables already explain the deviation"],
            ),
            self._make(
                question,
                statement=f"The prediction for {subject} was based on stale or wrong input.",
                confidence=0.40,
                assumptions=["Input observations are the ground truth for prediction"],
                predictions=[f"Correcting the input restores the expected outcome"],
                expected_evidence=[f"A corrected observation of the input changes the prediction"],
                failure_conditions=[f"Corrected inputs still deviate from '{expected}'"],
            ),
        ]

    def _anomaly_hypotheses(self, question: Question) -> List[Hypothesis]:
        ctx = question.metadata or {}
        subject = str(ctx.get("subject") or "the system")
        return [
            self._make(
                question,
                statement=f"A genuine but unobserved cause produces the anomaly in {subject}.",
                confidence=0.45,
                assumptions=[f"{subject} is functioning as instrumented"],
                predictions=[f"The anomaly will recur and be traceable to a cause"],
                expected_evidence=[f"A root cause correlates with the anomaly across observations"],
                failure_conditions=[f"No reproducible cause is found after repeated observation"],
            ),
            self._make(
                question,
                statement=f"The anomaly in {subject} is an artifact of faulty observation.",
                confidence=0.40,
                assumptions=["The anomaly signal originates from the observation channel"],
                predictions=[f"Re-instrumenting {subject} removes the anomaly"],
                expected_evidence=[f"Independent instrumentation shows no anomaly"],
                failure_conditions=[f"Independent instrumentation reproduces the anomaly"],
            ),
        ]

    def _goal_gap_hypotheses(self, question: Question) -> List[Hypothesis]:
        ctx = question.metadata or {}
        dependency = str(ctx.get("dependency") or ctx.get("gap") or "the missing piece")
        goal_title = str(ctx.get("goal_title") or "the goal")
        return [
            self._make(
                question,
                statement=f"{dependency} is the true blocker for goal '{goal_title}'.",
                confidence=0.45,
                assumptions=[f"Goal '{goal_title}' is correctly specified"],
                predictions=[f"Resolving {dependency} unblocks the goal"],
                expected_evidence=[f"Completing {dependency} advances the goal"],
                failure_conditions=[f"Goal progress is unaffected after {dependency} is resolved"],
            ),
            self._make(
                question,
                statement=f"An unlisted dependency, not {dependency}, blocks goal '{goal_title}'.",
                confidence=0.35,
                assumptions=["The goal's dependency list is incomplete"],
                predictions=[f"A different dependency will surface as the true blocker"],
                expected_evidence=[f"Another missing prerequisite is discovered"],
                failure_conditions=[f"{dependency} resolution alone is sufficient to proceed"],
            ),
        ]

    def _generic_hypotheses(self, question: Question) -> List[Hypothesis]:
        text = question.question
        return [
            self._make(
                question,
                statement=f"The answer to '{text}' is explained by an unobserved factor.",
                confidence=0.40,
                assumptions=["A relevant factor has not been observed yet"],
                predictions=["Observation of the missing factor will resolve the question"],
                expected_evidence=["A new observation consistent with the explanation is found"],
                failure_conditions=["All observed factors contradict this explanation"],
            ),
            self._make(
                question,
                statement=f"The premise behind '{text}' is inaccurate.",
                confidence=0.35,
                assumptions=["The question's premise may be wrong"],
                predictions=["Correcting the premise changes the answer"],
                expected_evidence=["A more accurate formulation of the question exists"],
                failure_conditions=["The premise holds under re-examination"],
            ),
        ]

    # --- Factory ---------------------------------------------------------------

    def _make(self, question: Question, statement: str, confidence: float,
              assumptions: List[str], predictions: List[str],
              expected_evidence: List[str], failure_conditions: List[str]) -> Hypothesis:
        return Hypothesis(
            question_id=question.question_id,
            statement=statement,
            source="hypothesis_engine",
            confidence=confidence,
            assumptions=assumptions,
            predictions=predictions,
            expected_evidence=expected_evidence,
            failure_conditions=failure_conditions,
            status=HypothesisLifecycle.PROPOSED,
            revision_history=[{"event": "created", "at": time.time()}],
        )
