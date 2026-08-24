"""
Opportunity Discovery Subsystem for Cognitive OS
Proactively discovers:
- Unused computational resources
- Latent capabilities that can accelerate active objectives
- Emerging bottlenecks
- Unexploited information and strategy optimization windows
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class OpportunityCandidate:
    opportunity_id: str = field(default_factory=lambda: f"opp_{uuid.uuid4().hex[:8]}")
    title: str = ""
    opportunity_type: str = "RESOURCE_SURPLUS"  # "RESOURCE_SURPLUS", "STRATEGY_SHORTCUT", "LATENT_CAPABILITY", "INFORMATION_GAIN"
    description: str = ""
    expected_gain: float = 0.5  # [0.0, 1.0]
    required_effort: float = 0.2# [0.0, 1.0]
    action_plan: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def value_to_effort_ratio(self) -> float:
        return round(self.expected_gain / max(0.01, self.required_effort), 2)


class OpportunityDetector:
    def __init__(self):
        self._discovered_opportunities: List[OpportunityCandidate] = []

    def scan_for_opportunities(
        self,
        resource_snapshot: Dict[str, Any],
        active_objectives: List[Dict[str, Any]],
        available_capabilities: List[str]
    ) -> List[OpportunityCandidate]:
        opportunities = []

        # Opportunity 1: Low CPU load + unfinished heavy objective -> Trigger Background Consolidation
        cpu = resource_snapshot.get("cpu_percent", 50.0)
        mem = resource_snapshot.get("memory_mb", 512.0)

        if cpu < 25.0 and mem > 1024.0:
            opp = OpportunityCandidate(
                title="Idle Resource Window: Execute Background Memory Consolidation",
                opportunity_type="RESOURCE_SURPLUS",
                description="Low CPU utilization and abundant RAM allow non-intrusive background strategy search and memory compression.",
                expected_gain=0.85,
                required_effort=0.15,
                action_plan="Trigger BackgroundDiscoveryDaemon sleep-consolidation pass."
            )
            opportunities.append(opp)

        # Opportunity 2: Latent capability match
        for obj in active_objectives:
            obj_title = obj.get("title", "").lower()
            if "index" in obj_title and any("bloom_filter" in c or "btree" in c for c in available_capabilities):
                opp = OpportunityCandidate(
                    title=f"Latent Capability Acceleration for '{obj.get('title')}'",
                    opportunity_type="LATENT_CAPABILITY",
                    description="Verified procedural indexing primitives are available to bypass slow linear search.",
                    expected_gain=0.90,
                    required_effort=0.10,
                    action_plan="Bind specialized Bloom filter indexing cell directly to objective DAG."
                )
                opportunities.append(opp)

        self._discovered_opportunities.extend(opportunities)
        return opportunities

    def get_highest_value_opportunity(self) -> Optional[OpportunityCandidate]:
        if not self._discovered_opportunities:
            return None
        return max(self._discovered_opportunities, key=lambda o: o.value_to_effort_ratio)
