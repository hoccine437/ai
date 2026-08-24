"""
CognitiveEngine — The master intelligence orchestrator.

Replaces the old keyword-based _cognitive_pre_reason and _cognitive_reflect
with a genuine cognitive pipeline:

INPUT → SituationModel → UncertaintyTracker → StrategySelector → [LLM] → PredictionEngine → SelfModel

The engine:
1. Understands the situation (SituationModel)
2. Assesses uncertainty (UncertaintyTracker)
3. Selects the best cognitive strategy (StrategySelector)
4. Generates predictions before acting (PredictionEngine)
5. Verifies outcomes after acting (PredictionEngine)
6. Updates capability model (SelfModel)
7. Learns from the experience (SmartMemory)
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from zerion.intelligence.situation_model import (
    SituationModel, Situation, IntentType, Complexity, Urgency,
)
from zerion.intelligence.uncertainty_tracker import (
    UncertaintyTracker, UncertaintyAssessment, Belief, BeliefState,
)
from zerion.intelligence.strategy_selector import (
    StrategySelector, CognitiveStrategy,
)
from zerion.intelligence.prediction_engine import (
    PredictionEngine, Prediction, SurpriseEvent, SurpriseLevel,
)
from zerion.intelligence.self_model import SelfModel


class CognitiveEngine:
    """Master intelligence orchestrator for Zerion.
    
    This is the brain that decides HOW to think about a problem,
    not just WHAT to think.
    
    Usage:
        engine = CognitiveEngine()
        
        # Before processing a user message:
        context = await engine.pre_reason(user_input, memory, tools)
        # → inject `context` into the LLM prompt
        
        # After getting a response:
        outcome = await engine.post_act(user_input, response, context)
        # → learns from the outcome, updates strategy performance
    """

    def __init__(self):
        self.situation = SituationModel()
        self.uncertainty = UncertaintyTracker()
        self.strategy = StrategySelector()
        self.predictions = PredictionEngine()
        self.self_model = SelfModel()

        # Session tracking
        self._turn_count = 0
        self._total_surprises = 0
        self._consecutive_failures = 0
        self._last_strategy: Optional[CognitiveStrategy] = None
        self._last_situation: Optional[Situation] = None
        self._pending_predictions: List[Prediction] = []
        self._turn_start: float = 0.0

    async def pre_reason(
        self,
        user_input: str,
        memory_context: str = "",
        available_tools: Optional[List[str]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        past_failures: Optional[List[str]] = None,
    ) -> str:
        """Cognitive pre-reasoning: analyze the situation BEFORE generating a response.
        
        Returns enriched cognitive context to inject into the LLM prompt.
        This replaces the old _cognitive_pre_reason.
        """
        self._turn_start = time.time()
        self._turn_count += 1

        # 1. BUILD SITUATION MODEL
        situation = self.situation.analyze(
            user_input,
            conversation_history=conversation_history,
            memory_context=memory_context,
        )
        self._last_situation = situation

        # 2. ASSESS UNCERTAINTY
        uncertainty_assessment = self.uncertainty.assess_situation_uncertainty(
            user_input,
            intent=situation.intent.value,
            available_info={
                "has_memory": bool(memory_context),
                "has_similar_past": situation.is_followup or situation.references_prior,
            },
            past_failures=past_failures,
        )

        # 3. SELECT COGNITIVE STRATEGY
        problem_type_str = situation.problem_type.value
        if situation.complexity.value >= 4:
            problem_type_str = "complex_task"

        selected_strategy, strategy_confidence = self.strategy.select(
            problem_type=problem_type_str,
            uncertainty=uncertainty_assessment.overall_uncertainty,
            complexity=situation.complexity.value,
            constraints=situation.constraints,
            past_failures=past_failures,
        )
        self._last_strategy = selected_strategy

        # 4. GENERATE PREDICTIONS
        self._pending_predictions = self.predictions.generate_predictions_for_task(
            user_input[:200],
            approach=selected_strategy.value,
        )

        # 5. CHECK FOR REPEATED FAILURES → STRATEGY CHANGE
        strategy_note = ""
        if self._consecutive_failures >= 3:
            strategy_note = (
                "\n[COGNITIVE NOTE: Same approach failed 3+ times. "
                "Try a fundamentally different strategy.]"
            )
            self._consecutive_failures = 0

        # 6. CHECK FOR SURPRISES → ADAPT
        surprise_note = ""
        if self._total_surprises > 0:
            surprise_note = (
                f"\n[COGNITIVE NOTE: {self._total_surprises} surprise(s) detected. "
                f"Review assumptions before proceeding.]"
            )

        # 7. BUILD COGNITIVE CONTEXT
        parts = []

        # Situation understanding
        parts.append(situation.to_prompt_context())

        # Uncertainty assessment
        parts.append(uncertainty_assessment.to_prompt_context())

        # Strategy
        parts.append(f"SELECTED_STRATEGY: {selected_strategy.value} "
                     f"(confidence: {strategy_confidence:.2f})")

        # Strategy stats
        parts.append(self.strategy.to_prompt_context())

        # Self-model
        parts.append(self.self_model.to_prompt_context())

        # Predictions
        parts.append(self.predictions.to_prompt_context())

        # Memory context
        if memory_context:
            parts.append(f"RELEVANT_MEMORY:\n{memory_context}")

        # Cognitive notes
        if strategy_note:
            parts.append(strategy_note.strip())
        if surprise_note:
            parts.append(surprise_note.strip())

        # Follow-up context
        if situation.is_followup:
            parts.append("NOTE: This appears to be a follow-up. "
                        "Use conversation context to understand references.")

        return "\n".join(parts)

    async def post_act(
        self,
        user_input: str,
        response: str,
        pre_reason_context: str = "",
        tool_used: str = "",
        success: bool = True,
        cost: float = 1.0,
        latency_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Post-action reflection: analyze what happened and learn.
        
        Returns a dict with learning signals.
        This replaces the old _cognitive_reflect.
        """
        result: Dict[str, Any] = {
            "learned": False,
            "surprise_detected": False,
            "strategy_updated": False,
            "capability_updated": False,
        }

        # 1. VERIFY PREDICTIONS
        for pred in self._pending_predictions:
            surprise = self.predictions.verify_prediction(pred.id, response[:200])
            if surprise:
                result["surprise_detected"] = True
                self._total_surprises += 1
                result["surprise_details"] = {
                    "expected": surprise.expected[:100],
                    "actual": surprise.actual[:100],
                    "level": surprise.surprise_level.value,
                }

        # 2. UPDATE STRATEGY OUTCOME
        if self._last_strategy:
            quality = 0.8 if success else 0.2
            # Adjust quality based on response quality
            if response and len(response) > 10:
                quality = min(1.0, quality + 0.1)
            if not response or len(response) < 5:
                quality = max(0.0, quality - 0.3)

            self.strategy.record_outcome(
                self._last_strategy,
                success=success,
                cost=cost,
                quality=quality,
                problem_type=self._last_situation.problem_type.value
                    if self._last_situation else "",
            )
            result["strategy_updated"] = True

        # 3. UPDATE SELF-MODEL
        if tool_used:
            self.self_model.record_use(
                tool_used,
                success=success,
                cost=cost,
                latency_ms=latency_ms,
                failure_reason="" if success else "tool execution failed",
            )
            result["capability_updated"] = True

        # 4. TRACK FAILURES
        if success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

        # 5. UPDATE BELIEFS
        # If the response was successful, reinforce relevant beliefs
        if success and self._last_situation:
            # Register this as a successful experience
            self.uncertainty.register_belief(
                f"Successfully handled {self._last_situation.intent.value} "
                f"with {self._last_situation.problem_type.value} approach",
                state=BeliefState.SUPPORTED,
                confidence=0.7,
                source="experience",
            )
            result["learned"] = True

        # 6. SURPRISE → LEARNING
        if result["surprise_detected"]:
            # Register that something unexpected happened
            self.uncertainty.register_belief(
                f"Unexpected outcome for: {user_input[:100]}",
                state=BeliefState.UNCERTAIN,
                confidence=0.4,
                source="surprise_detection",
            )
            result["learned"] = True

        # 7. CLEAR PENDING
        self._pending_predictions = []

        return result

    def get_session_summary(self) -> Dict[str, Any]:
        """Get a summary of the current session's cognitive activity."""
        return {
            "turns": self._turn_count,
            "total_surprises": self._total_surprises,
            "consecutive_failures": self._consecutive_failures,
            "strategy_stats": self.strategy.get_strategy_stats(),
            "self_model": self.self_model.get_capability_report(),
            "prediction_calibration": self.predictions.get_calibration(),
            "surprise_analysis": self.predictions.analyze_surprises(),
            "beliefs_by_state": self.uncertainty.count_by_state(),
        }

    def to_prompt_context(self) -> str:
        """Get a compact summary for the LLM."""
        summary = self.get_session_summary()
        lines = [
            f"[ZERION INTELLIGENCE] Turn {summary['turns']}",
            f"Surprises: {summary['total_surprises']}",
            f"Failures: {summary['consecutive_failures']}",
        ]
        if summary["prediction_calibration"].get("accuracy") is not None:
            lines.append(
                f"Prediction accuracy: {summary['prediction_calibration']['accuracy']:.0%}"
            )
        return "\n".join(lines)
