"""
Slice 2 — QuestionGenesis.

Deterministically turns internal signals (uncertainty, contradiction, anomaly, goal
gap, missing dependency, prediction failure, repeated failure, capability gap) and
user requests into structured Questions. No LLM, no randomness: identical events
produce identical questions.

Questions are DATA. The text is always treated as a string to investigate — it is
never executed, never interpreted as a command, and never granted permissions.
"""

from typing import Any, Dict, List, Optional

from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.question import (
    Question,
    QuestionSource,
    QuestionStore,
    score_question,
)

# Trigger event type -> genesis source label + template.
_TEMPLATES: Dict[EventType, str] = {
    EventType.UNCERTAINTY_DETECTED: "UNCERTAINTY",
    EventType.CONTRADICTION_FOUND: "CONTRADICTION",
    EventType.ANOMALY_DETECTED: "ANOMALY",
    EventType.GOAL_GAP_DETECTED: "GOAL_GAP",
    EventType.MISSING_DEPENDENCY_DETECTED: "MISSING_DEPENDENCY",
    EventType.PREDICTION_ERROR: "PREDICTION_FAILURE",
    EventType.REPEATED_FAILURE_DETECTED: "REPEATED_FAILURE",
    EventType.CAPABILITY_GAP: "CAPABILITY_GAP",
    EventType.USER_INTERACTION: "USER_REQUEST",
    # Slice 7: a significant bottleneck is an internal uncertainty — questions
    # flow through the SAME genesis -> attention path (no second question engine).
    EventType.BOTTLENECK_DETECTED: "BOTTLENECK",
}

# Deterministic default metrics per genesis source. All overridable via payload
# "question_metrics" (clamped/validated by the Question model).
_DEFAULT_METRICS: Dict[str, Dict[str, float]] = {
    "UNCERTAINTY":        {"urgency": 0.5, "uncertainty": 0.9, "novelty": 0.4, "goal_relevance": 0.7,
                           "expected_information_gain": 0.7, "expected_decision_impact": 0.6,
                           "estimated_cost": 0.2, "risk": 0.1},
    "CONTRADICTION":      {"urgency": 0.8, "uncertainty": 0.9, "novelty": 0.6, "goal_relevance": 0.7,
                           "expected_information_gain": 0.85, "expected_decision_impact": 0.8,
                           "estimated_cost": 0.2, "risk": 0.2},
    "ANOMALY":            {"urgency": 0.7, "uncertainty": 0.8, "novelty": 0.8, "goal_relevance": 0.6,
                           "expected_information_gain": 0.8, "expected_decision_impact": 0.7,
                           "estimated_cost": 0.3, "risk": 0.2},
    "GOAL_GAP":           {"urgency": 0.8, "uncertainty": 0.7, "novelty": 0.5, "goal_relevance": 1.0,
                           "expected_information_gain": 0.8, "expected_decision_impact": 0.9,
                           "estimated_cost": 0.3, "risk": 0.2},
    "MISSING_DEPENDENCY": {"urgency": 0.8, "uncertainty": 0.8, "novelty": 0.5, "goal_relevance": 1.0,
                           "expected_information_gain": 0.8, "expected_decision_impact": 0.8,
                           "estimated_cost": 0.2, "risk": 0.2},
    "PREDICTION_FAILURE": {"urgency": 0.8, "uncertainty": 0.8, "novelty": 0.6, "goal_relevance": 0.7,
                           "expected_information_gain": 0.85, "expected_decision_impact": 0.8,
                           "estimated_cost": 0.3, "risk": 0.2},
    "REPEATED_FAILURE":   {"urgency": 0.8, "uncertainty": 0.6, "novelty": 0.5, "goal_relevance": 0.7,
                           "expected_information_gain": 0.8, "expected_decision_impact": 0.7,
                           "estimated_cost": 0.3, "risk": 0.2},
    "CAPABILITY_GAP":     {"urgency": 0.6, "uncertainty": 0.7, "novelty": 0.6, "goal_relevance": 0.8,
                           "expected_information_gain": 0.8, "expected_decision_impact": 0.7,
                           "estimated_cost": 0.4, "risk": 0.2},
    "USER_REQUEST":       {"urgency": 0.9, "uncertainty": 0.4, "novelty": 0.3, "goal_relevance": 0.8,
                           "expected_information_gain": 0.5, "expected_decision_impact": 0.8,
                           "estimated_cost": 0.1, "risk": 0.1},
    "BOTTLENECK":         {"urgency": 0.85, "uncertainty": 0.8, "novelty": 0.6, "goal_relevance": 0.8,
                           "expected_information_gain": 0.85, "expected_decision_impact": 0.8,
                           "estimated_cost": 0.3, "risk": 0.2},
}


class QuestionGenesis:
    """Turns trigger events into structured, deduplicated Questions."""

    def __init__(self, question_store: QuestionStore,
                 objectives: Optional[Any] = None):
        """
        objectives: the Slice 1 Goal Field (ObjectiveContinuityManager) used to
        boost goal relevance for goal-related triggers. Optional.
        """
        self.store = question_store
        self.objectives = objectives

    # --- Event handling --------------------------------------------------------

    def generate(self, event: Event) -> List[Question]:
        """Generate zero or more Questions for a trigger event.

        Returns [] for unrecognized events, empty user requests, or when an
        unresolved duplicate already exists.
        """
        source = _TEMPLATES.get(event.event_type)
        if source is None:
            return []

        payload = event.payload if isinstance(event.payload, dict) else {}
        if source == "USER_REQUEST":
            return self._generate_user_request(payload, event)

        text, context = self._build_text(source, payload)
        if not text:
            return []

        metrics = self._metrics(source, payload)
        goal_id = payload.get("goal_id") or payload.get("objective_id")
        # Goal-related uncertainty increases question relevance against the Goal Field.
        goal_relevance = self._goal_relevance(goal_id, metrics["goal_relevance"])

        q = Question(
            question=text,
            source=source,
            source_kind=QuestionSource.ZERION_GENERATED,
            urgency=metrics["urgency"],
            uncertainty=metrics["uncertainty"],
            novelty=metrics["novelty"],
            goal_relevance=goal_relevance,
            expected_information_gain=metrics["expected_information_gain"],
            expected_decision_impact=metrics["expected_decision_impact"],
            estimated_cost=metrics["estimated_cost"],
            risk=metrics["risk"],
            related_goal=goal_id,
            related_event=event.event_id or event.event_type.value,
            related_beliefs=[str(b) for b in payload.get("beliefs", [])],
            parent_question=payload.get("parent_question"),
            metadata=context,
        )
        # Deduplicate: an unresolved question with the same fingerprint wins.
        if self.store.get_by_fingerprint(q.fingerprint, unresolved_only=True):
            return []
        q.priority = score_question(q)
        self.store.put(q)
        return [q]

    # --- Per-source text -------------------------------------------------------

    def _build_text(self, source: str, payload: Dict[str, Any]) -> (str, Dict[str, Any]):
        subject = (payload.get("subject") or payload.get("entity")
                   or payload.get("source") or "the system")
        observed = payload.get("observed") or payload.get("actual") or payload.get("value")
        expected = payload.get("expected") or payload.get("predicted")
        goal_title = payload.get("objective") or ""
        gap = payload.get("gap") or payload.get("description") or ""
        dependency = payload.get("dependency") or "the missing dependency"
        task = payload.get("task") or subject
        capability = payload.get("missing_capability") or "the missing capability"

        if source == "UNCERTAINTY":
            return f"What is the current state of {subject}?", {"subject": subject}
        if source == "CONTRADICTION":
            observed_txt = observed or "the observed outcome"
            expected_txt = expected or "the expected state"
            return (f"What alternative variable could explain {observed_txt}?",
                    {"subject": subject, "observed": observed_txt, "expected": expected_txt,
                     "description": payload.get("description", "")})
        if source == "ANOMALY":
            return f"What mechanism could produce the anomaly in {subject}?", {"subject": subject}
        if source == "GOAL_GAP":
            if goal_title:
                return (f"What is needed to close the gap on goal '{goal_title}': {gap or 'unknown gap'}?",
                        {"goal_title": goal_title, "gap": gap, "goal_id": payload.get("goal_id")})
            return f"What is needed to close the gap: {gap or 'unknown gap'}?", {"gap": gap}
        if source == "MISSING_DEPENDENCY":
            context = {"dependency": dependency, "goal_title": goal_title,
                       "goal_id": payload.get("goal_id")}
            if goal_title:
                return f"What is the current state of {dependency} for goal '{goal_title}'?", context
            return f"What is the current state of {dependency}?", context
        if source == "PREDICTION_FAILURE":
            return (f"Why did the prediction '{expected or 'the prediction'}' fail to hold for {subject}?",
                    {"subject": subject, "expected": expected, "observed": observed})
        if source == "REPEATED_FAILURE":
            return (f"What differs across the repeated failures of {task}?",
                    {"task": task, "attempts": payload.get("attempts"),
                     "last_error": payload.get("last_error", "")})
        if source == "CAPABILITY_GAP":
            return (f"What capability does {subject} require that is currently missing?",
                    {"subject": subject, "missing_capability": capability})
        if source == "BOTTLENECK":
            component = payload.get("component") or subject
            bottleneck = payload.get("bottleneck") or "the limiting component"
            return (f"What component is currently limiting system performance, "
                    f"and what evidence supports this ({bottleneck} in {component})?",
                    {"component": component, "bottleneck": bottleneck,
                     "evidence": payload.get("evidence", "")})
        return "", {}

    def _generate_user_request(self, payload: Dict[str, Any],
                               event: Event) -> List[Question]:
        transcript = (payload.get("transcript") or payload.get("text")
                      or payload.get("message") or "").strip()
        if not transcript:
            return []  # empty user requests are ignored, never stored
        metrics = self._metrics("USER_REQUEST", payload)
        q = Question(
            question=transcript,
            source="USER_REQUEST",
            source_kind=QuestionSource.USER_REQUESTED,
            urgency=metrics["urgency"],
            uncertainty=metrics["uncertainty"],
            novelty=metrics["novelty"],
            goal_relevance=metrics["goal_relevance"],
            expected_information_gain=metrics["expected_information_gain"],
            expected_decision_impact=metrics["expected_decision_impact"],
            estimated_cost=metrics["estimated_cost"],
            risk=metrics["risk"],
            related_goal=payload.get("goal_id") or payload.get("objective_id"),
            related_event=event.event_id or event.event_type.value,
            related_beliefs=[],
            metadata={"transcript": transcript},
        )
        if self.store.get_by_fingerprint(q.fingerprint, unresolved_only=True):
            return []
        q.priority = score_question(q)
        self.store.put(q)
        return [q]

    # --- Metrics ---------------------------------------------------------------

    def _metrics(self, source: str, payload: Dict[str, Any]) -> Dict[str, float]:
        base = dict(_DEFAULT_METRICS.get(source, _DEFAULT_METRICS["UNCERTAINTY"]))
        overrides = payload.get("question_metrics")
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                if k not in base:
                    continue
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                # Sanitize contradictory metadata: clamp, never raise, never store junk.
                if k == "estimated_cost":
                    base[k] = max(0.0, f)
                else:
                    base[k] = max(0.0, min(1.0, f))
        return base

    def _goal_relevance(self, goal_id: Optional[str], base: float) -> float:
        if not goal_id or self.objectives is None:
            return base
        goal = self.objectives.get_goal(goal_id)
        if goal is None:
            return base
        # An active goal directly targeted by the question is maximally relevant.
        if getattr(goal, "is_active", True) and goal.status.value not in ("COMPLETED", "ABANDONED"):
            return max(base, 1.0)
        return max(base, 0.8)
