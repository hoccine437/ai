"""
Autopoietic Reflection Engine for Cognitive OS
Diagnoses second- and third-order developmental learning bottlenecks.
"""

from typing import Any, Dict, List, Optional


class AutopoieticReflectionEngine:
    def __init__(self):
        self._reflection_history: List[Dict[str, Any]] = []

    def perform_reflection(
        self,
        recent_learning_acceleration: Optional[float],
        strategy_market_reputations: Optional[Dict[str, float]],
        failed_tasks_count: int
    ) -> Dict[str, Any]:
        # Honest reflection: a fabricated acceleration ratio (e.g. a hard-coded
        # 2.57) must never be presented as a measured one. None means "not
        # measured" and produces an UNMEASURED record — it does not trigger a
        # plateau/failure diagnosis from invented evidence.
        if recent_learning_acceleration is None:
            reflection_record = {
                "bottleneck_identified": "Unknown (learning acceleration not measured)",
                "recommended_prescription": "Collect a measured learning acceleration before prescribing reflection changes.",
                "acceleration_ratio": None,
                "status": "UNMEASURED"
            }
            self._reflection_history.append(reflection_record)
            return reflection_record

        bottleneck = "None"
        prescription = "Maintain current developmental loop trajectory."

        if recent_learning_acceleration < 1.1:
            bottleneck = "Learning process plateau"
            prescription = "Trigger curriculum parameter mutation and increase sandbox practice variation."
        elif failed_tasks_count > 3:
            bottleneck = "Elevated strategy failure rate"
            prescription = "Retire degraded strategies and trigger Cognitive Genesis for unmapped domains."

        reflection_record = {
            "bottleneck_identified": bottleneck,
            "recommended_prescription": prescription,
            "acceleration_ratio": recent_learning_acceleration,
            "status": "OPTIMIZED"
        }
        self._reflection_history.append(reflection_record)
        return reflection_record
