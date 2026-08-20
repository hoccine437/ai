"""
Slice 4 — ExperienceReuse.

Retrieves relevant distilled experiences for future runtime decisions based on
the current goal, problem, context, failure pattern, causal relevance, historical
usefulness and confidence. Retrieval is deterministic, score-based and bounded
(top-K + minimum score) — it never returns everything.

    score = 0.5 * relevance + 0.3 * confidence + 0.2 * usefulness

Retrieving an item counts as a use (historical usefulness is tracked so the
system can learn which rules actually get used).
"""

import re
from typing import Any, Dict, List, Optional

from zerion.cognitive_os.distilled import (
    DistilledExperience,
    DistilledExperienceStore,
    ValidationStatus,
)


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9_]+", str(text).lower()))


def _overlap(a: str, b: str) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class ExperienceReuse:
    def __init__(self, distilled_store: DistilledExperienceStore,
                 relevance_weight: float = 0.5,
                 confidence_weight: float = 0.3,
                 usefulness_weight: float = 0.2,
                 min_score: float = 0.15,
                 default_top_k: int = 5):
        self.distilled = distilled_store
        self.relevance_weight = relevance_weight
        self.confidence_weight = confidence_weight
        self.usefulness_weight = usefulness_weight
        self.min_score = min_score
        self.default_top_k = default_top_k

    def retrieve(self, *, goal: str = "", problem: str = "",
                 context: str = "", failure_pattern: str = "",
                 top_k: Optional[int] = None,
                 min_score: Optional[float] = None,
                 include_statuses: Optional[List[ValidationStatus]] = None) -> List[Dict[str, Any]]:
        """Score every stored lesson against the query and return the best
        matches above the score floor. Deterministic for identical inputs."""
        query = f"{goal} {problem} {context} {failure_pattern}"
        top_k = top_k or self.default_top_k
        floor = self.min_score if min_score is None else min_score
        allowed = include_statuses or [
            ValidationStatus.CANDIDATE, ValidationStatus.VALIDATING,
            ValidationStatus.VALIDATED, ValidationStatus.WEAKENED,
        ]
        scored: List[Dict[str, Any]] = []
        for item in self.distilled.list():
            if item.validation_status not in allowed:
                continue
            relevance = _overlap(query, f"{item.conditions} {item.statement} "
                                         f"{item.action}")
            usefulness = 0.0
            if item.times_used > 0:
                usefulness = item.times_successful / item.times_used
            score = (self.relevance_weight * relevance
                     + self.confidence_weight * item.confidence
                     + self.usefulness_weight * usefulness)
            if score < floor:
                continue
            scored.append({
                "id": item.id,
                "type": item.type.value,
                "statement": item.statement,
                "action": item.action,
                "conditions": item.conditions,
                "confidence": round(item.confidence, 6),
                "validation_status": item.validation_status.value,
                "score": round(score, 6),
                "source_episodes": item.source_episodes,
            })
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:top_k]

    def record_use(self, item_id: str, success: bool) -> DistilledExperience:
        """Track historical usefulness: how often a lesson was retrieved and
        whether using it helped."""
        item = self.distilled.get(item_id)
        if item is None:
            raise KeyError(f"Unknown distilled item {item_id}")
        item.times_used += 1
        if success:
            item.times_successful += 1
        self.distilled.put(item)
        return item
