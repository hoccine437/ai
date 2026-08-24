"""
SelfModel — Zerion's continuously updated model of its own capabilities.

Tracks:
- What tools/strategies work well
- Success rates and failure patterns
- Known blind spots
- Resource costs
- What the system is good/bad at

This enables better decision-making about HOW to approach problems.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CapabilityRecord:
    """Tracks the performance of a specific capability (tool, strategy, etc.)."""
    name: str = ""
    category: str = ""         # "tool", "strategy", "agent", "inference"
    attempts: int = 0
    successes: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float = 0.0
    last_used: float = 0.0
    failure_patterns: List[str] = field(default_factory=list)
    success_patterns: List[str] = field(default_factory=list)
    known_limitations: List[str] = field(default_factory=list)

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

    @property
    def reliability(self) -> float:
        """Combined reliability score (success rate adjusted for confidence)."""
        if self.attempts < 3:
            return 0.5  # Not enough data
        # Bayesian-ish: shrink toward 0.5 for low sample sizes
        weight = min(1.0, self.attempts / 10)
        return 0.5 * (1 - weight) + self.success_rate * weight

    def record_use(self, success: bool, cost: float = 1.0,
                   latency_ms: float = 0.0, failure_reason: str = ""):
        self.attempts += 1
        if success:
            self.successes += 1
        self.total_cost += cost
        # Running average latency
        if self.attempts == 1:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = (
                (self.avg_latency_ms * (self.attempts - 1) + latency_ms)
                / self.attempts
            )
        self.last_used = time.time()
        if failure_reason and failure_reason not in self.failure_patterns:
            self.failure_patterns.append(failure_reason)
            if len(self.failure_patterns) > 10:
                self.failure_patterns = self.failure_patterns[-10:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "attempts": self.attempts,
            "success_rate": round(self.success_rate, 3),
            "reliability": round(self.reliability, 3),
            "avg_cost": round(self.avg_cost, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "failure_patterns": self.failure_patterns[:5],
        }


class SelfModel:
    """Zerion's continuously updated model of its own capabilities.
    
    This enables the system to:
    - Choose the right tool based on reliability, not just name
    - Avoid tools that have failed recently
    - Adapt strategy based on what works
    - Identify blind spots and areas for improvement
    """

    def __init__(self):
        self._capabilities: Dict[str, CapabilityRecord] = {}
        self._blind_spots: List[str] = []
        self._strengths: List[str] = []
        self._created_at = time.time()

    def register_capability(
        self,
        name: str,
        category: str = "tool",
        known_limitations: Optional[List[str]] = None,
    ) -> CapabilityRecord:
        """Register a capability for tracking."""
        if name not in self._capabilities:
            self._capabilities[name] = CapabilityRecord(
                name=name, category=category,
                known_limitations=known_limitations or [],
            )
        return self._capabilities[name]

    def record_use(
        self,
        name: str,
        success: bool,
        cost: float = 1.0,
        latency_ms: float = 0.0,
        failure_reason: str = "",
    ):
        """Record the use of a capability."""
        if name not in self._capabilities:
            self.register_capability(name)
        self._capabilities[name].record_use(
            success, cost, latency_ms, failure_reason
        )
        # Update strengths and blind spots
        self._update_assessment(name)

    def _update_assessment(self, name: str):
        """Update strengths and blind spots based on new data."""
        cap = self._capabilities[name]
        if cap.attempts >= 3:
            if cap.success_rate >= 0.8 and name not in self._strengths:
                self._strengths.append(name)
                if name in self._blind_spots:
                    self._blind_spots.remove(name)
            elif cap.success_rate < 0.4 and name not in self._blind_spots:
                self._blind_spots.append(name)
                if name in self._strengths:
                    self._strengths.remove(name)

    def get_best_tool(
        self,
        category: str = "",
        candidates: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Get the most reliable tool for a category."""
        options = candidates or list(self._capabilities.keys())
        if category:
            options = [n for n in options
                      if self._capabilities.get(n, CapabilityRecord()).category == category]

        if not options:
            return None

        # Sort by reliability
        options.sort(
            key=lambda n: self._capabilities.get(n, CapabilityRecord()).reliability,
            reverse=True,
        )
        return options[0]

    def get_capability_report(self) -> Dict[str, Any]:
        """Get a report of all tracked capabilities."""
        return {
            "total_capabilities": len(self._capabilities),
            "strengths": self._strengths[:10],
            "blind_spots": self._blind_spots[:10],
            "by_category": self._by_category(),
        }

    def _by_category(self) -> Dict[str, List[Dict[str, Any]]]:
        """Group capabilities by category."""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for cap in self._capabilities.values():
            if cap.attempts > 0:
                cat = cap.category or "unknown"
                if cat not in groups:
                    groups[cat] = []
                groups[cat].append(cap.to_dict())
        return groups

    def to_prompt_context(self) -> str:
        """Format for LLM context."""
        report = self.get_capability_report()
        lines = [f"SELF_MODEL: {report['total_capabilities']} capabilities tracked"]
        if self._strengths:
            lines.append(f"STRENGTHS: {', '.join(self._strengths[:5])}")
        if self._blind_spots:
            lines.append(f"BLIND_SPOTS: {', '.join(self._blind_spots[:3])}")

        # Top tools by reliability
        top = sorted(
            self._capabilities.values(),
            key=lambda c: c.reliability,
            reverse=True,
        )[:5]
        if top:
            lines.append("TOP_TOOLS:")
            for cap in top:
                if cap.attempts > 0:
                    lines.append(
                        f"  {cap.name}: {cap.success_rate:.0%} success, "
                        f"{cap.avg_latency_ms:.0f}ms avg"
                    )
        return "\n".join(lines)
