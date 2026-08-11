"""
Cognitive OS: Perception, Attention Economy, and Intention Subsystem
Implements perception framing, mathematical attention prioritization, and goal intention gating.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class PerceptionFrame:
    frame_id: str = field(default_factory=lambda: f"perc_{uuid.uuid4().hex[:8]}")
    source: str = "environment"
    raw_signals: Dict[str, Any] = field(default_factory=dict)
    observed_metrics: Dict[str, float] = field(default_factory=dict)
    epistemic_tags: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AttentionItem:
    item_id: str = field(default_factory=lambda: f"att_{uuid.uuid4().hex[:8]}")
    topic: str = ""
    source: str = ""
    urgency: float = 0.5           # [0.0, 1.0]
    importance: float = 0.5        # [0.0, 1.0]
    uncertainty: float = 0.5       # [0.0, 1.0]
    novelty: float = 0.5           # [0.0, 1.0]
    objective_relevance: float = 0.5# [0.0, 1.0]
    expected_information_gain: float = 0.5 # [0.0, 1.0]
    resource_cost: float = 1.0     # >= 0.1
    priority_score: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def compute_priority(self) -> float:
        """
        Computes Attention Priority:
        (urgency * importance * uncertainty * novelty * objective_relevance * expected_information_gain) / max(0.1, resource_cost) * 10
        """
        numerator = (
            max(0.01, self.urgency) *
            max(0.01, self.importance) *
            max(0.01, self.uncertainty) *
            max(0.01, self.novelty) *
            max(0.01, self.objective_relevance) *
            max(0.01, self.expected_information_gain)
        )
        denom = max(0.1, self.resource_cost)
        self.priority_score = round((numerator / denom) * 1000.0, 4)
        return self.priority_score


class AttentionEconomy:
    """
    Manages attention allocation ensuring broad perception with focused, deep cognitive processing.
    """
    def __init__(self, capacity_slots: int = 5):
        self.capacity_slots = capacity_slots
        self._attention_pool: List[AttentionItem] = []

    def submit_candidate(self, item: AttentionItem) -> float:
        item.compute_priority()
        self._attention_pool.append(item)
        self._attention_pool.sort(key=lambda x: x.priority_score, reverse=True)
        return item.priority_score

    def get_focused_attention(self) -> List[AttentionItem]:
        """Returns the top priority attention items within the cognitive capacity budget."""
        focused = self._attention_pool[:self.capacity_slots]
        # Keep remaining in background buffer
        self._attention_pool = self._attention_pool[self.capacity_slots:]
        return focused

    def clear(self):
        self._attention_pool.clear()


@dataclass
class IntentionTarget:
    intention_id: str = field(default_factory=lambda: f"intent_{uuid.uuid4().hex[:8]}")
    goal_statement: str = ""
    target_objective_id: Optional[str] = None
    attention_item: Optional[AttentionItem] = None
    expected_outcome: str = ""
    commitment_level: float = 0.9
    created_at: float = field(default_factory=time.time)
