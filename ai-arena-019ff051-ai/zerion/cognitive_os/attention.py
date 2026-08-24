"""
Cognitive OS: Perception, Attention Economy, and Intention Subsystem
Implements perception framing, mathematical attention prioritization, and goal intention gating.

Slice 1 additions (backward compatible):
- ``AttentionItem`` gains ``expected_utility``, ``risk``, ``api_cost``, ``estimated_latency_ms``
  and ``goal_id`` fields (all defaulted) so the AttentionCandidate role is fully covered.
- ``CognitivePriority``: the authoritative, explicit, configurable and deterministic scoring
  mechanism used by the Cognitive Foundation. Weighted additive score with subtractive
  resource-cost and risk penalties; never ``priority = importance``.
- ``ResourceBudgetState``: computational / API / latency / concurrency budget awareness.
- ``AttentionEconomy.evaluate()``: SELECT / DEFER / DISCARD with configurable thresholds.

The legacy multiplicative ``AttentionItem.compute_priority()`` remains intact for the
legacy organism path; the foundation uses ``CognitivePriority`` via ``evaluate()``.
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
    """
    An attention candidate competing for limited cognitive computation.

    All factor fields are normalized to [0.0, 1.0]. ``resource_cost`` and ``api_cost`` are
    non-negative abstract cost units; ``estimated_latency_ms`` is a non-negative latency
    estimate. ``priority`` is the CognitivePriority score assigned by the economy.
    """
    item_id: str = field(default_factory=lambda: f"att_{uuid.uuid4().hex[:8]}")
    topic: str = ""
    source: str = ""
    urgency: float = 0.5           # [0.0, 1.0]
    importance: float = 0.5        # [0.0, 1.0]
    uncertainty: float = 0.5       # [0.0, 1.0]
    novelty: float = 0.5           # [0.0, 1.0]
    objective_relevance: float = 0.5  # [0.0, 1.0] goal relevance
    expected_information_gain: float = 0.5  # [0.0, 1.0]
    expected_utility: float = 0.5  # [0.0, 1.0]
    risk: float = 0.1              # [0.0, 1.0] higher risk is a penalty
    resource_cost: float = 1.0     # >= 0.0 abstract compute units
    api_cost: float = 0.0          # >= 0.0 abstract API/model budget units
    estimated_latency_ms: float = 0.0  # >= 0.0
    goal_id: Optional[str] = None  # optional link to a specific goal
    priority: float = 0.0          # CognitivePriority score [0.0, 1.0]
    priority_score: float = 0.0    # legacy multiplicative score (0-1000), kept for the legacy organism
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


class AttentionFieldValidationError(ValueError):
    """Raised for invalid candidate fields or resource budgets."""


def _clamp01(value: float, field_name: str) -> float:
    value = float(value)
    if not (0.0 <= value <= 1.0):
        raise AttentionFieldValidationError(f"{field_name} must be in [0.0, 1.0], got {value!r}")
    return value


def _clamp_non_negative(value: float, field_name: str) -> float:
    value = float(value)
    if value < 0.0:
        raise AttentionFieldValidationError(f"{field_name} must be >= 0.0, got {value!r}")
    return value


class CognitivePriority:
    """
    Explicit, inspectable, configurable and deterministic attention scoring.

    score = sum(w * factor for factor in positive factors)
            - sum(p * factor for factor in penalties)

    Positive factors: urgency, importance, uncertainty, novelty, goal relevance,
    expected information gain, expected utility. Penalties: resource cost, risk.
    Positive weights are normalized to sum to 1.0 so the score is in [0.0, 1.0].
    """

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "urgency": 0.20,
        "importance": 0.20,
        "uncertainty": 0.10,
        "novelty": 0.05,
        "goal_relevance": 0.20,
        "expected_information_gain": 0.10,
        "expected_utility": 0.15,
    }
    DEFAULT_PENALTIES: Dict[str, float] = {
        "resource_cost": 0.15,
        "risk": 0.15,
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None,
                 penalties: Optional[Dict[str, float]] = None):
        self.weights: Dict[str, float] = dict(self.DEFAULT_WEIGHTS)
        if weights:
            for k, v in weights.items():
                if k not in self.DEFAULT_WEIGHTS:
                    raise AttentionFieldValidationError(f"Unknown CognitivePriority weight: {k!r}")
                self.weights[k] = float(v)
        self.penalties: Dict[str, float] = dict(self.DEFAULT_PENALTIES)
        if penalties:
            for k, v in penalties.items():
                if k not in self.DEFAULT_PENALTIES:
                    raise AttentionFieldValidationError(f"Unknown CognitivePriority penalty: {k!r}")
                self.penalties[k] = float(v)
        total = sum(self.weights.values())
        if total <= 0.0:
            raise AttentionFieldValidationError("CognitivePriority positive weights must sum to > 0")
        self.weights = {k: v / total for k, v in self.weights.items()}

    def factor_map(self, item: AttentionItem) -> Dict[str, float]:
        """Normalized, validated factor values used by the score (inspectable)."""
        return {
            "urgency": _clamp01(item.urgency, "urgency"),
            "importance": _clamp01(item.importance, "importance"),
            "uncertainty": _clamp01(item.uncertainty, "uncertainty"),
            "novelty": _clamp01(item.novelty, "novelty"),
            "goal_relevance": _clamp01(item.objective_relevance, "objective_relevance"),
            "expected_information_gain": _clamp01(item.expected_information_gain, "expected_information_gain"),
            "expected_utility": _clamp01(item.expected_utility, "expected_utility"),
        }

    def penalty_map(self, item: AttentionItem) -> Dict[str, float]:
        return {
            "resource_cost": _clamp_non_negative(item.resource_cost, "resource_cost"),
            "risk": _clamp01(item.risk, "risk"),
        }

    def score(self, item: AttentionItem) -> float:
        """Deterministic score in [0.0, 1.0]. Identical inputs yield identical scores."""
        positive = sum(w * self.factor_map(item)[k] for k, w in self.weights.items())
        negative = sum(p * self.penalty_map(item)[k] for k, p in self.penalties.items())
        score = positive - negative
        item.priority = round(max(0.0, min(1.0, score)), 6)
        return item.priority

    def explain(self, item: AttentionItem) -> Dict[str, Any]:
        """Inspectable breakdown of the score computation."""
        factors = self.factor_map(item)
        penalties = self.penalty_map(item)
        positive = {k: round(w * factors[k], 6) for k, w in self.weights.items()}
        negative = {k: round(p * penalties[k], 6) for k, p in self.penalties.items()}
        return {
            "score": self.score(item),
            "weights": dict(self.weights),
            "penalties": dict(self.penalties),
            "positive_contributions": positive,
            "negative_contributions": negative,
        }


@dataclass
class ResourceBudgetState:
    """Remaining computational budget that attention must respect."""
    compute_units: float = 1.0        # remaining abstract compute units
    api_calls: float = 10.0           # remaining abstract API/model calls
    latency_ms: float = 1000.0        # latency constraint in ms
    concurrent_workload: int = 0      # currently active concurrent tasks
    max_concurrent: int = 3           # maximum permitted concurrent tasks

    def validate(self):
        if self.compute_units < 0.0:
            raise AttentionFieldValidationError(f"compute_units must be >= 0, got {self.compute_units!r}")
        if self.api_calls < 0.0:
            raise AttentionFieldValidationError(f"api_calls must be >= 0, got {self.api_calls!r}")
        if self.latency_ms < 0.0:
            raise AttentionFieldValidationError(f"latency_ms must be >= 0, got {self.latency_ms!r}")
        if self.concurrent_workload < 0 or self.max_concurrent < 0:
            raise AttentionFieldValidationError("concurrency values must be >= 0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compute_units": self.compute_units,
            "api_calls": self.api_calls,
            "latency_ms": self.latency_ms,
            "concurrent_workload": self.concurrent_workload,
            "max_concurrent": self.max_concurrent,
        }


@dataclass
class AttentionDecision:
    """Result of an attention evaluation pass."""
    selected: List[AttentionItem] = field(default_factory=list)
    deferred: List[AttentionItem] = field(default_factory=list)
    discarded: List[AttentionItem] = field(default_factory=list)
    reasons: Dict[str, str] = field(default_factory=dict)  # item_id -> reason

    @property
    def is_empty(self) -> bool:
        return not (self.selected or self.deferred or self.discarded)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected": [i.item_id for i in self.selected],
            "deferred": [i.item_id for i in self.deferred],
            "discarded": [i.item_id for i in self.discarded],
            "reasons": dict(self.reasons),
        }


class AttentionEconomy:
    """
    Manages attention allocation ensuring broad perception with focused, deep cognitive processing.

    Legacy API preserved: ``submit_candidate`` / ``get_focused_attention`` / ``clear``.
    Slice 1 API: ``submit`` + ``evaluate`` perform deterministic SELECT / DEFER / DISCARD
    using ``CognitivePriority`` and a ``ResourceBudgetState``.
    """
    def __init__(self, capacity_slots: int = 5,
                 scorer: Optional[CognitivePriority] = None,
                 select_threshold: float = 0.55,
                 discard_threshold: float = 0.30,
                 max_deferred: int = 100):
        self.capacity_slots = capacity_slots
        self.scorer = scorer or CognitivePriority()
        self.select_threshold = select_threshold
        self.discard_threshold = discard_threshold
        self.max_deferred = max_deferred
        self._attention_pool: List[AttentionItem] = []
        self._deferred_pool: List[Dict[str, Any]] = []  # {item, deferred_at}
        self.budget: ResourceBudgetState = ResourceBudgetState()
        self.selected_count: int = 0
        self.deferred_count: int = 0
        self.discarded_count: int = 0
        self._last_decision: Optional[AttentionDecision] = None

    def set_budget(self, compute_units: Optional[float] = None,
                   api_calls: Optional[float] = None,
                   latency_ms: Optional[float] = None,
                   concurrent_workload: Optional[int] = None,
                   max_concurrent: Optional[int] = None) -> ResourceBudgetState:
        if compute_units is not None:
            self.budget.compute_units = compute_units
        if api_calls is not None:
            self.budget.api_calls = api_calls
        if latency_ms is not None:
            self.budget.latency_ms = latency_ms
        if concurrent_workload is not None:
            self.budget.concurrent_workload = concurrent_workload
        if max_concurrent is not None:
            self.budget.max_concurrent = max_concurrent
        self.budget.validate()
        return self.budget

    def contains_goal(self, goal_id: str) -> bool:
        """True if a candidate for this goal is already pending or deferred.
        Used by the runtime to avoid re-spending the attention budget on
        duplicate same-goal events (CREATE -> UPDATE -> BLOCK all target the
        same goal) while a candidate is still in flight."""
        for item in self._attention_pool:
            if getattr(item, "goal_id", None) == goal_id:
                return True
        for entry in self._deferred_pool:
            if getattr(entry["item"], "goal_id", None) == goal_id:
                return True
        return False

    def release_slot(self) -> int:
        """Release one concurrency slot after attention-selected work finishes.
        Floors at zero (never negative). Without this, concurrent_workload only
        ever increases and the field silently deadlocks once max_concurrent
        selections have been made — no candidate could ever be selected again."""
        self.budget.validate()
        self.budget.concurrent_workload = max(
            0, self.budget.concurrent_workload - 1)
        return self.budget.concurrent_workload

    def fits_budget(self, item: AttentionItem) -> bool:
        """True if the candidate can run within the current resource budget."""
        self.budget.validate()
        return (
            item.resource_cost <= self.budget.compute_units
            and item.api_cost <= self.budget.api_calls
            and item.estimated_latency_ms <= self.budget.latency_ms
            and self.budget.concurrent_workload < self.budget.max_concurrent
        )

    def submit_candidate(self, item: AttentionItem) -> float:
        """Legacy path: multiplicative priority, append + sort, immediate capacity drain."""
        item.compute_priority()
        self._attention_pool.append(item)
        self._attention_pool.sort(key=lambda x: x.priority_score, reverse=True)
        return item.priority_score

    def submit(self, item: AttentionItem) -> AttentionItem:
        """Slice 1 path: score with CognitivePriority and add to the pool."""
        self.scorer.score(item)
        self._attention_pool.append(item)
        return item

    def submit_candidate_fields(self, topic: str = "", source: str = "",
                                urgency: float = 0.5, importance: float = 0.5,
                                uncertainty: float = 0.5, novelty: float = 0.5,
                                goal_relevance: float = 0.5,
                                expected_information_gain: float = 0.5,
                                expected_utility: float = 0.5, risk: float = 0.1,
                                resource_cost: float = 0.5, api_cost: float = 0.0,
                                estimated_latency_ms: float = 0.0,
                                goal_id: Optional[str] = None,
                                payload: Optional[Dict[str, Any]] = None) -> AttentionItem:
        item = AttentionItem(
            topic=topic,
            source=source,
            urgency=urgency,
            importance=importance,
            uncertainty=uncertainty,
            novelty=novelty,
            objective_relevance=goal_relevance,
            expected_information_gain=expected_information_gain,
            expected_utility=expected_utility,
            risk=risk,
            resource_cost=resource_cost,
            api_cost=api_cost,
            estimated_latency_ms=estimated_latency_ms,
            goal_id=goal_id,
            payload=payload or {}
        )
        return self.submit(item)

    def get_focused_attention(self) -> List[AttentionItem]:
        """Legacy path: returns the top priority items within the cognitive capacity budget."""
        focused = self._attention_pool[:self.capacity_slots]
        # Keep remaining in background buffer
        self._attention_pool = self._attention_pool[self.capacity_slots:]
        return focused

    def evaluate(self, max_selections: Optional[int] = None) -> AttentionDecision:
        """
        Deterministically evaluates every candidate in the pool:

        - scores with ``CognitivePriority``
        - orders by score (desc), then FIFO for ties
        - SELECT while within the resource budget and above ``select_threshold``
        - DEFER candidates above ``discard_threshold`` that cannot be selected now
        - DISCARD candidates at or below ``discard_threshold``
        """
        self.budget.validate()
        pending = list(self._attention_pool)
        self._attention_pool = []
        # Deterministic order: score desc, then creation order (timestamp, item_id)
        pending.sort(key=lambda it: (-it.priority, it.timestamp, it.item_id))

        decision = AttentionDecision()
        selected_so_far = 0
        for idx, item in enumerate(pending):
            if item.priority <= self.discard_threshold:
                decision.discarded.append(item)
                decision.reasons[item.item_id] = "below_discard_threshold"
                self.discarded_count += 1
                continue
            if not self.fits_budget(item):
                if self._defer_item(item):
                    decision.deferred.append(item)
                    decision.reasons[item.item_id] = "insufficient_resource_budget"
                else:
                    decision.discarded.append(item)
                    decision.reasons[item.item_id] = "insufficient_resource_budget_deferred_capacity_full"
                continue
            if item.priority < self.select_threshold:
                if self._defer_item(item):
                    decision.deferred.append(item)
                    decision.reasons[item.item_id] = "below_select_threshold"
                else:
                    decision.discarded.append(item)
                    decision.reasons[item.item_id] = "below_select_threshold_deferred_capacity_full"
                continue
            # SELECT
            self.budget.compute_units = round(self.budget.compute_units - item.resource_cost, 6)
            self.budget.api_calls = round(self.budget.api_calls - item.api_cost, 6)
            self.budget.concurrent_workload += 1
            decision.selected.append(item)
            decision.reasons[item.item_id] = "selected"
            self.selected_count += 1
            selected_so_far += 1
            if max_selections is not None and selected_so_far >= max_selections:
                for leftover in pending[idx + 1:]:
                    self._settle_leftover(leftover, decision, "selection_cap_reached")
                break

        self._last_decision = decision
        return decision

    def _defer_item(self, item: AttentionItem) -> bool:
        """Defer the item if capacity allows. Returns True if deferred, False if discarded."""
        if len(self._deferred_pool) < self.max_deferred:
            self._deferred_pool.append({"item": item, "deferred_at": time.time()})
            self.deferred_count += 1
            return True
        self.discarded_count += 1
        return False

    def _settle_leftover(self, item: AttentionItem, decision: AttentionDecision, reason_prefix: str):
        if item.priority <= self.discard_threshold:
            decision.discarded.append(item)
            decision.reasons[item.item_id] = "below_discard_threshold"
            self.discarded_count += 1
        elif len(self._deferred_pool) < self.max_deferred:
            decision.deferred.append(item)
            decision.reasons[item.item_id] = reason_prefix
            self._deferred_pool.append({"item": item, "deferred_at": time.time()})
            self.deferred_count += 1
        else:
            decision.discarded.append(item)
            decision.reasons[item.item_id] = reason_prefix + "_deferred_capacity_full"
            self.discarded_count += 1

    def reconsider_deferred(self) -> AttentionDecision:
        """Returns deferred candidates to the pool and re-evaluates them."""
        for entry in self._deferred_pool:
            self._attention_pool.append(entry["item"])
        self._deferred_pool = []
        return self.evaluate()

    @property
    def pending_candidates(self) -> int:
        return len(self._attention_pool)

    @property
    def deferred_candidates(self) -> int:
        return len(self._deferred_pool)

    @property
    def last_decision(self) -> Optional[AttentionDecision]:
        return self._last_decision

    def stats(self) -> Dict[str, Any]:
        return {
            "pending_candidates": self.pending_candidates,
            "deferred_candidates": self.deferred_candidates,
            "selected_count": self.selected_count,
            "deferred_count": self.deferred_count,
            "discarded_count": self.discarded_count,
            "budget": self.budget.to_dict(),
            "select_threshold": self.select_threshold,
            "discard_threshold": self.discard_threshold,
        }

    def clear(self):
        self._attention_pool.clear()
        self._deferred_pool = []


@dataclass
class IntentionTarget:
    intention_id: str = field(default_factory=lambda: f"intent_{uuid.uuid4().hex[:8]}")
    goal_statement: str = ""
    target_objective_id: Optional[str] = None
    attention_item: Optional[AttentionItem] = None
    expected_outcome: str = ""
    commitment_level: float = 0.9
    created_at: float = field(default_factory=time.time)
