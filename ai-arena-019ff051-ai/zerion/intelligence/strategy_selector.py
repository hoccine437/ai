"""
StrategySelector — Selects the best cognitive strategy for each situation.

Zerion does NOT always reason the same way. It selects the strategy based on:
- Problem type
- Available information
- Uncertainty level
- Past experience with similar problems
- Resource constraints

Strategies are learned over time through outcome tracking.
"""

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple


class CognitiveStrategy(Enum):
    """Available cognitive strategies."""
    DIRECT_ANSWER = "direct_answer"
    DECOMPOSITION = "decomposition"
    ANALOGY = "analogy"
    RETRIEVAL = "retrieval"
    CAUSAL_ANALYSIS = "causal_analysis"
    HYPOTHESIS_TESTING = "hypothesis_testing"
    SIMULATION = "simulation"
    COUNTERFACTUAL = "counterfactual_reasoning"
    CONSTRAINT_SOLVING = "constraint_solving"
    PLANNING = "planning"
    EXPERIMENTATION = "experimentation"
    TOOL_INVESTIGATION = "tool_investigation"
    MODEL_COMPARISON = "model_comparison"
    FAILURE_ANALYSIS = "failure_analysis"
    EXPLORATION = "exploration"
    GRADUAL_APPROACH = "gradual_approach"
    COLLABORATIVE = "collaborative"


@dataclass
class StrategyRecord:
    """Record of a strategy's performance."""
    strategy: CognitiveStrategy = CognitiveStrategy.DIRECT_ANSWER
    attempts: int = 0
    successes: int = 0
    total_cost: float = 0.0
    avg_quality: float = 0.5
    last_used: float = 0.0
    problem_types_used: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.5
        return self.successes / self.attempts

    @property
    def avg_cost(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.total_cost / self.attempts

    def record_use(self, success: bool, cost: float = 1.0, quality: float = 0.5):
        self.attempts += 1
        if success:
            self.successes += 1
        self.total_cost += cost
        # Running average quality
        self.avg_quality = ((self.avg_quality * (self.attempts - 1)) + quality) / self.attempts
        self.last_used = time.time()


# ── Strategy → Problem type mappings ──────────────────────────────────────────

_STRATEGY_SUITABILITY: Dict[CognitiveStrategy, Dict[str, float]] = {
    CognitiveStrategy.DIRECT_ANSWER: {
        "factual": 0.9, "conversation": 0.8, "greeting": 0.95,
        "knowledge_retrieval": 0.85, "status_check": 0.9,
    },
    CognitiveStrategy.DECOMPOSITION: {
        "diagnostic": 0.8, "analytical": 0.7, "complex_task": 0.85,
        "procedural": 0.6,
    },
    CognitiveStrategy.ANALOGY: {
        "factual": 0.5, "procedural": 0.6, "creative": 0.7,
    },
    CognitiveStrategy.RETRIEVAL: {
        "factual": 0.85, "knowledge_retrieval": 0.9,
        "knowledge_storage": 0.8, "question": 0.7,
    },
    CognitiveStrategy.CAUSAL_ANALYSIS: {
        "diagnostic": 0.9, "analytical": 0.7, "problem_solving": 0.8,
    },
    CognitiveStrategy.HYPOTHESIS_TESTING: {
        "diagnostic": 0.85, "exploratory": 0.8, "analytical": 0.7,
    },
    CognitiveStrategy.PLANNING: {
        "strategic": 0.9, "creation": 0.7, "procedural": 0.7,
        "complex_task": 0.8,
    },
    CognitiveStrategy.TOOL_INVESTIGATION: {
        "diagnostic": 0.8, "problem_solving": 0.85, "status_check": 0.7,
    },
    CognitiveStrategy.FAILURE_ANALYSIS: {
        "diagnostic": 0.9, "problem_solving": 0.75,
    },
    CognitiveStrategy.EXPLORATION: {
        "exploratory": 0.9, "creative": 0.6,
    },
    CognitiveStrategy.GRADUAL_APPROACH: {
        "complex_task": 0.7, "hard": 0.8,
    },
    CognitiveStrategy.EXPERIMENTATION: {
        "diagnostic": 0.7, "exploratory": 0.8,
    },
    CognitiveStrategy.MODEL_COMPARISON: {
        "analytical": 0.7, "diagnostic": 0.6,
    },
}


class StrategySelector:
    """Selects the best cognitive strategy for the current situation.
    
    Uses:
    - Problem type → strategy suitability mapping
    - Past performance data (which strategies work for which problems)
    - Uncertainty level (more uncertainty → more exploration)
    - Cost constraints (cheap strategies preferred when possible)
    
    Learns over time by tracking which strategies succeed for which problems.
    """

    def __init__(self):
        self._records: Dict[CognitiveStrategy, StrategyRecord] = {}
        for strategy in CognitiveStrategy:
            self._records[strategy] = StrategyRecord(strategy=strategy)

    def select(
        self,
        problem_type: str,
        uncertainty: float = 0.5,
        complexity: int = 2,
        constraints: Optional[List[str]] = None,
        past_failures: Optional[List[str]] = None,
    ) -> Tuple[CognitiveStrategy, float]:
        """Select the best strategy for the current situation.
        
        Returns (strategy, confidence_in_selection).
        """
        candidates: List[Tuple[CognitiveStrategy, float]] = []

        for strategy in CognitiveStrategy:
            # 1. Base suitability from problem type mapping
            suitability_map = _STRATEGY_SUITABILITY.get(strategy, {})
            base_score = suitability_map.get(problem_type, 0.1)

            # 2. Historical performance adjustment
            record = self._records[strategy]
            if record.attempts > 0:
                # Blend base suitability with historical success
                historical = record.success_rate * 0.4
                base_score = base_score * 0.6 + historical

            # 3. Uncertainty adjustment
            # High uncertainty → favor exploration strategies
            if uncertainty > 0.6:
                if strategy in (CognitiveStrategy.EXPLORATION,
                                CognitiveStrategy.HYPOTHESIS_TESTING,
                                CognitiveStrategy.EXPERIMENTATION):
                    base_score *= 1.3
                elif strategy == CognitiveStrategy.DIRECT_ANSWER:
                    base_score *= 0.7

            # 4. Complexity adjustment
            if complexity >= 4:
                if strategy in (CognitiveStrategy.DECOMPOSITION,
                                CognitiveStrategy.PLANNING,
                                CognitiveStrategy.GRADUAL_APPROACH):
                    base_score *= 1.2
                elif strategy == CognitiveStrategy.DIRECT_ANSWER:
                    base_score *= 0.6

            # 5. Cost preference (favor cheap strategies when possible)
            if record.attempts > 0 and record.avg_cost > 2.0:
                base_score *= 0.8

            # 6. Failure-based adjustment
            if past_failures:
                # If direct approach failed, favor alternative strategies
                if strategy == CognitiveStrategy.DIRECT_ANSWER and past_failures:
                    base_score *= 0.5
                if strategy == CognitiveStrategy.FAILURE_ANALYSIS:
                    base_score *= 1.2

            candidates.append((strategy, base_score))

        # Sort by score
        candidates.sort(key=lambda x: x[1], reverse=True)

        if not candidates:
            return CognitiveStrategy.DIRECT_ANSWER, 0.3

        best_strategy, best_score = candidates[0]
        second_score = candidates[1][1] if len(candidates) > 1 else 0

        # Confidence in selection = how much better the best is vs second
        if best_score + second_score > 0:
            selection_confidence = best_score / (best_score + second_score)
        else:
            selection_confidence = 0.5

        return best_strategy, round(selection_confidence, 3)

    def record_outcome(
        self,
        strategy: CognitiveStrategy,
        success: bool,
        cost: float = 1.0,
        quality: float = 0.5,
        problem_type: str = "",
    ):
        """Record the outcome of using a strategy."""
        record = self._records[strategy]
        record.record_use(success, cost, quality)
        if problem_type and problem_type not in record.problem_types_used:
            record.problem_types_used.append(problem_type)
            if len(record.problem_types_used) > 20:
                record.problem_types_used = record.problem_types_used[-20:]

    def get_strategy_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get performance stats for all strategies."""
        stats = {}
        for strategy, record in self._records.items():
            if record.attempts > 0:
                stats[strategy.value] = {
                    "attempts": record.attempts,
                    "success_rate": round(record.success_rate, 3),
                    "avg_quality": round(record.avg_quality, 3),
                    "avg_cost": round(record.avg_cost, 2),
                    "problem_types": record.problem_types_used,
                }
        return stats

    def to_prompt_context(self) -> str:
        """Format strategy stats for LLM context."""
        stats = self.get_strategy_stats()
        if not stats:
            return "STRATEGY_STATS: No historical data yet"
        lines = ["STRATEGY_STATS:"]
        for name, data in sorted(stats.items(),
                                   key=lambda x: x[1]["success_rate"],
                                   reverse=True)[:5]:
            lines.append(
                f"  {name}: success={data['success_rate']:.0%} "
                f"quality={data['avg_quality']:.2f} "
                f"used={data['attempts']}x"
            )
        return "\n".join(lines)
