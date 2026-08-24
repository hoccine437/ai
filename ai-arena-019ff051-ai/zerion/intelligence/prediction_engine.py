"""
PredictionEngine — Generates predictions, detects surprises, tracks calibration.

Core principle: Before acting, predict what should happen. After acting,
compare prediction to reality. Differences = learning opportunities.

This is the foundation of how Zerion learns from reality instead of
merely generating explanations after the fact.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class PredictionType(Enum):
    """Types of predictions Zerion can make."""
    OUTCOME = "outcome"           # What will happen as a result of X
    BEHAVIOR = "behavior"         # How something will behave
    CAUSAL = "causal"             # X will cause Y
    TEMPORAL = "temporal"         # X will happen before Y
    COUNTERFACTUAL = "counterfactual"  # If X were different, Y would change


class SurpriseLevel(Enum):
    """How surprising the outcome was."""
    NONE = "none"           # Expected
    MILD = "mild"           # Slightly off
    MODERATE = "moderate"   # Notably different
    HIGH = "high"           # Significantly wrong
    EXTREME = "extreme"     # Fundamentally unexpected


@dataclass
class Prediction:
    """A prediction about what should happen."""
    id: str = ""
    type: PredictionType = PredictionType.OUTCOME
    statement: str = ""           # What we predict
    condition: str = ""           # Under what conditions
    confidence: float = 0.5       # How confident we are (0-1)
    reasoning: str = ""           # Why we think this
    alternative_predictions: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    # Filled after observation
    observed_outcome: Optional[str] = None
    surprise_level: Optional[SurpriseLevel] = None
    prediction_error: Optional[float] = None
    verified_at: Optional[float] = None

    def verify(self, actual_outcome: str) -> SurpriseLevel:
        """Compare prediction to reality and compute surprise."""
        self.observed_outcome = actual_outcome
        self.verified_at = time.time()

        # Compute prediction error
        pred_words = set(self.statement.lower().split())
        actual_words = set(actual_outcome.lower().split())
        if pred_words and actual_words:
            overlap = len(pred_words & actual_words)
            total = len(pred_words | actual_words)
            similarity = overlap / total if total > 0 else 0.0
            self.prediction_error = 1.0 - similarity
        else:
            self.prediction_error = 0.5

        # Classify surprise
        if self.prediction_error < 0.15:
            self.surprise_level = SurpriseLevel.NONE
        elif self.prediction_error < 0.3:
            self.surprise_level = SurpriseLevel.MILD
        elif self.prediction_error < 0.5:
            self.surprise_level = SurpriseLevel.MODERATE
        elif self.prediction_error < 0.7:
            self.surprise_level = SurpriseLevel.HIGH
        else:
            self.surprise_level = SurpriseLevel.EXTREME

        return self.surprise_level

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "statement": self.statement,
            "confidence": round(self.confidence, 3),
            "observed": self.observed_outcome,
            "surprise": self.surprise_level.value if self.surprise_level else None,
            "error": round(self.prediction_error, 3) if self.prediction_error else None,
        }


@dataclass
class SurpriseEvent:
    """A detected surprise — an unexpected outcome that needs analysis."""
    prediction_id: str = ""
    expected: str = ""
    actual: str = ""
    surprise_level: SurpriseLevel = SurpriseLevel.MODERATE
    failed_assumption: str = ""
    possible_causes: List[str] = field(default_factory=list)
    recommended_action: str = ""
    timestamp: float = field(default_factory=time.time)


class PredictionEngine:
    """Generates predictions, verifies outcomes, and detects surprises.
    
    This engine is the core of Zerion's ability to learn from reality.
    Before important actions, it predicts what should happen. After the
    action, it compares the prediction to reality. Differences become
    learning opportunities.
    """

    def __init__(self):
        self._predictions: Dict[str, Prediction] = {}
        self._surprises: List[SurpriseEvent] = []
        self._prediction_counter: int = 0
        self._total_predictions: int = 0
        self._correct_predictions: int = 0

    def make_prediction(
        self,
        statement: str,
        *,
        prediction_type: PredictionType = PredictionType.OUTCOME,
        condition: str = "",
        confidence: float = 0.5,
        reasoning: str = "",
        alternatives: Optional[List[str]] = None,
    ) -> Prediction:
        """Record a prediction about what should happen."""
        self._prediction_counter += 1
        pred = Prediction(
            id=f"pred_{self._prediction_counter}",
            type=prediction_type,
            statement=statement,
            condition=condition,
            confidence=confidence,
            reasoning=reasoning,
            alternative_predictions=alternatives or [],
        )
        self._predictions[pred.id] = pred
        self._total_predictions += 1
        return pred

    def verify_prediction(
        self,
        prediction_id: str,
        actual_outcome: str,
    ) -> Optional[SurpriseEvent]:
        """Verify a prediction against reality and detect surprises.
        
        Returns a SurpriseEvent if the outcome was unexpected.
        """
        pred = self._predictions.get(prediction_id)
        if not pred:
            return None

        surprise_level = pred.verify(actual_outcome)

        if surprise_level in (SurpriseLevel.MODERATE, SurpriseLevel.HIGH,
                              SurpriseLevel.EXTREME):
            surprise = SurpriseEvent(
                prediction_id=prediction_id,
                expected=pred.statement,
                actual=actual_outcome,
                surprise_level=surprise_level,
                failed_assumption=pred.reasoning,
            )
            self._surprises.append(surprise)
            return surprise

        if surprise_level == SurpriseLevel.NONE:
            self._correct_predictions += 1

        return None

    def generate_predictions_for_task(
        self,
        task_description: str,
        approach: str = "",
    ) -> List[Prediction]:
        """Generate predictions before executing a task.
        
        These predictions serve as hypotheses that will be verified
        after execution, providing learning signals.
        """
        predictions = []

        # 1. Success prediction
        predictions.append(self.make_prediction(
            statement=f"Task '{task_description[:100]}' will succeed with approach: {approach[:100]}",
            prediction_type=PredictionType.OUTCOME,
            confidence=0.6,
            reasoning=f"Based on past experience with similar tasks",
        ))

        # 2. If it's a problem-solving task, predict root cause
        lower = task_description.lower()
        if any(w in lower for w in ["fix", "error", "broken", "problem"]):
            predictions.append(self.make_prediction(
                statement="Root cause will be identified within the first investigation step",
                prediction_type=PredictionType.OUTCOME,
                confidence=0.5,
                reasoning="Most problems have identifiable root causes",
            ))

        # 3. If it involves tool usage, predict tool effectiveness
        if any(w in lower for w in ["scan", "check", "test", "run"]):
            predictions.append(self.make_prediction(
                statement="Tool execution will complete without timeout",
                prediction_type=PredictionType.BEHAVIOR,
                confidence=0.7,
                reasoning="Standard tool execution",
            ))

        return predictions

    def analyze_surprises(self) -> Dict[str, Any]:
        """Analyze accumulated surprises for patterns."""
        if not self._surprises:
            return {
                "total_surprises": 0,
                "pattern": "No surprises detected",
                "recommendation": "Continue current approach",
            }

        # Count by level
        level_counts = {}
        for s in self._surprises:
            level_counts[s.surprise_level.value] = (
                level_counts.get(s.surprise_level.value, 0) + 1
            )

        high_surprises = [s for s in self._surprises
                         if s.surprise_level in (SurpriseLevel.HIGH, SurpriseLevel.EXTREME)]

        # Pattern detection
        if len(high_surprises) >= 3:
            pattern = "Repeated high surprises — underlying model may be wrong"
            recommendation = "Reconsider fundamental assumptions"
        elif len(high_surprises) >= 1:
            pattern = "Some high surprises — specific assumptions may be wrong"
            recommendation = "Investigate failed assumptions"
        elif len(self._surprises) >= 5:
            pattern = "Frequent mild surprises — calibration may need adjustment"
            recommendation = "Reduce prediction confidence slightly"
        else:
            pattern = "Occasional mild surprises — normal learning"
            recommendation = "Continue and monitor"

        return {
            "total_surprises": len(self._surprises),
            "level_distribution": level_counts,
            "high_surprises": len(high_surprises),
            "pattern": pattern,
            "recommendation": recommendation,
        }

    def get_calibration(self) -> Dict[str, Any]:
        """Get prediction calibration metrics."""
        verified = [p for p in self._predictions.values() if p.verified_at]
        if not verified:
            return {"total": 0, "verified": 0, "accuracy": None}

        correct = sum(1 for p in verified
                     if p.surprise_level == SurpriseLevel.NONE)
        return {
            "total": len(self._predictions),
            "verified": len(verified),
            "accuracy": round(correct / len(verified), 3) if verified else None,
            "avg_confidence": round(
                sum(p.confidence for p in verified) / len(verified), 3
            ) if verified else None,
        }

    def to_prompt_context(self) -> str:
        """Format for LLM context."""
        calibration = self.get_calibration()
        surprises = self.analyze_surprises()
        lines = [
            f"PREDICTIONS: {calibration['total']} total, {calibration['verified']} verified",
        ]
        if calibration.get("accuracy") is not None:
            lines.append(f"CALIBRATION: {calibration['accuracy']:.0%} accuracy")
        if surprises["total_surprises"] > 0:
            lines.append(f"SURPRISES: {surprises['total_surprises']} ({surprises['pattern']})")
        return "\n".join(lines)
