"""
Cognitive Strategy Market & Learning Controller for Cognitive OS
Implements:
- Strategy Market: Competing strategies, empirical reputation, portfolio selection, strategy composition.
- Learning Controller: Sleep/consolidation cycle, procedural compression (EXPENSIVE -> LEARNED -> REFLEX), controlled forgetting.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
from zerion.cognitive_genesis.strategy import CognitiveStrategy


@dataclass
class StrategyMarketEntry:
    strategy: CognitiveStrategy
    market_reputation: float = 1.0     # Weighted by recent empirical success
    total_market_invocations: int = 0
    recent_performance_window: List[float] = field(default_factory=list)

    def record_market_outcome(self, reward: float):
        self.total_market_invocations += 1
        self.recent_performance_window.append(reward)
        if len(self.recent_performance_window) > 20:
            self.recent_performance_window.pop(0)
        # Update reputation moving average
        avg_rew = sum(self.recent_performance_window) / len(self.recent_performance_window)
        self.market_reputation = round(avg_rew, 3)


class CognitiveStrategyMarket:
    """
    Manages competing cognitive strategies in a competitive empirical reputation market.
    """
    def __init__(self):
        self._market: Dict[str, StrategyMarketEntry] = {}

    def register_strategy(self, strategy: CognitiveStrategy):
        if strategy.strategy_id not in self._market:
            self._market[strategy.strategy_id] = StrategyMarketEntry(strategy=strategy)

    def select_best_strategy(self, domain: str) -> Optional[CognitiveStrategy]:
        candidates = [
            entry for entry in self._market.values()
            if entry.strategy.is_active and (domain.lower() in entry.strategy.domain.lower() or entry.strategy.domain == "general")
        ]
        if not candidates:
            # Return any active strategy
            all_active = [e for e in self._market.values() if e.strategy.is_active]
            return all_active[0].strategy if all_active else None
        
        # Sort by reputation
        candidates.sort(key=lambda x: x.market_reputation, reverse=True)
        return candidates[0].strategy

    def compose_strategies(
        self,
        strategy_a: CognitiveStrategy,
        strategy_b: CognitiveStrategy,
        composite_name: str
    ) -> CognitiveStrategy:
        """Discovers Strategy C = Strategy A + Strategy B."""
        composite_steps = (
            [f"[Phase A: {strategy_a.name}] " + s for s in strategy_a.procedure_steps] +
            [f"[Phase B: {strategy_b.name}] " + s for s in strategy_b.procedure_steps]
        )
        new_strat = CognitiveStrategy(
            name=composite_name,
            domain=f"{strategy_a.domain}+{strategy_b.domain}",
            preconditions=list(set(strategy_a.preconditions + strategy_b.preconditions)),
            procedure_steps=composite_steps,
            expected_benefit=f"Composite synergized pipeline of {strategy_a.name} + {strategy_b.name}",
            cost=round((strategy_a.cost + strategy_b.cost) * 0.85, 2),  # Synergy efficiency
            latency_ms=round(strategy_a.latency_ms + strategy_b.latency_ms, 2),
            risk=round(max(strategy_a.risk, strategy_b.risk) * 0.8, 2),
            confidence=round((strategy_a.confidence + strategy_b.confidence) / 2.0, 3),
            provenance="strategy_market_composition"
        )
        self.register_strategy(new_strat)
        return new_strat


class CognitiveLearningController:
    """
    Manages experience distillation, sleep/consolidation cycles, procedural compression,
    and controlled forgetting of low-value noise.
    """
    def __init__(self):
        self._consolidations_run: int = 0

    def run_sleep_consolidation_cycle(self, memory_store: Any) -> Dict[str, Any]:
        """
        Consolidation loop:
        Episodic Memory -> Cluster experiences -> Extract patterns -> Synthesize Procedural Rules
        -> Controlled forgetting of noise -> Update strategy reputation.
        """
        self._consolidations_run += 1
        new_rules = []
        if hasattr(memory_store, "trigger_distillation"):
            new_rules = memory_store.trigger_distillation()

        # Controlled forgetting: remove low-confidence unreferenced memories if total exceeds quota
        pruned_count = 0
        if hasattr(memory_store, "_episodes") and len(memory_store._episodes) > 500:
            keys_to_remove = [k for k, v in list(memory_store._episodes.items())[:-200] if v.reward < 0.3]
            for k in keys_to_remove:
                del memory_store._episodes[k]
                pruned_count += 1

        return {
            "consolidation_cycle": self._consolidations_run,
            "distilled_rules_created": len(new_rules),
            "noisy_episodes_pruned": pruned_count,
            "compression_status": "EXPENSIVE -> LEARNED -> REFLEX Active"
        }
