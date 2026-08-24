"""
Hypothesis Competition & Bottleneck Discovery Substrates for ZERION-X
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class CompetingHypothesis:
    hypothesis_id: str = field(default_factory=lambda: f"hyp_comp_{uuid.uuid4().hex[:8]}")
    title: str = ""
    candidate_explanation: str = ""
    assumptions: List[str] = field(default_factory=list)
    expected_evidence: str = ""
    failure_condition: str = ""
    empirical_support_score: float = 0.5 # [0.0, 1.0]
    is_falsified: bool = False
    created_at: float = field(default_factory=time.time)


class HypothesisCompetitionEngine:
    def __init__(self):
        self._hypotheses: Dict[str, CompetingHypothesis] = {}

    def formulate_competing_hypotheses(self, problem_description: str) -> List[CompetingHypothesis]:
        """Generates competing hypotheses: Ha (Causal), Hb (Alternative/Circumstantial), Hc (Adversarial)."""
        h_a = CompetingHypothesis(
            title=f"Ha (Direct Causal): {problem_description[:30]}",
            candidate_explanation="Underlying state variable exceeds monotonic constraint threshold.",
            assumptions=["System context is stationary", "Variable is directly causal"],
            expected_evidence="Intervention on parameter reduces anomaly delta by >= 50%.",
            failure_condition="Delta remains unchanged under parameter intervention."
        )
        h_b = CompetingHypothesis(
            title=f"Hb (Latent Third Factor): {problem_description[:30]}",
            candidate_explanation="Unobserved background compaction / GC latency produces correlation.",
            assumptions=["Variable is correlated, not directly causal"],
            expected_evidence="Anomaly correlates with memory pressure rather than direct parameter.",
            failure_condition="No correlation with memory pressure."
        )
        h_c = CompetingHypothesis(
            title=f"Hc (Adversarial Null): {problem_description[:30]}",
            candidate_explanation="Transient stochastic sensor noise; no structural fault.",
            assumptions=["Observation is transient"],
            expected_evidence="Subsequent reality samples revert to normal baseline.",
            failure_condition="Anomaly persists across 3 consecutive observation windows."
        )

        for h in [h_a, h_b, h_c]:
            self._hypotheses[h.hypothesis_id] = h
        return [h_a, h_b, h_c]


class BottleneckDetector:
    def __init__(self):
        self._bottleneck_history: List[Dict[str, Any]] = []

    def detect_bottlenecks(
        self,
        avg_latency_ms: float,
        failure_rate: float,
        memory_usage_mb: float,
        procedural_reuse_rate: float
    ) -> Dict[str, Any]:
        bottlenecks = []
        if avg_latency_ms > 500.0:
            bottlenecks.append("MODEL_LATENCY_LIMITATION")
        if failure_rate > 0.15:
            bottlenecks.append("STRATEGY_LIMITATION")
        if procedural_reuse_rate < 0.30:
            bottlenecks.append("PROCEDURAL_COMPRESSION_LIMITATION")
        if memory_usage_mb > 3000.0:
            bottlenecks.append("RESOURCE_LIMITATION")

        primary = bottlenecks[0] if bottlenecks else "NONE"
        record = {
            "primary_bottleneck": primary,
            "detected_bottlenecks": bottlenecks,
            "proposed_intervention": f"Trigger targeted optimization for {primary}" if primary != "NONE" else "Optimal execution",
            "timestamp": time.time()
        }
        self._bottleneck_history.append(record)
        return record
