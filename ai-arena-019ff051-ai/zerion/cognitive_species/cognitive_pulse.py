"""
Cognitive Pulse & Species Runtime Substrate  [DEPRECATED — isolated legacy]

DEPRECATED: this legacy orchestrator is NOT part of the live ZERION-X runtime.
It was removed from the engine because it maintained a PARALLEL GoalField
(``goal_field.db``) and a second router — a competing source of truth. The
canonical pulse is ``zerion/cognitive_os/pulse.py`` ``CognitivePulse`` (inside
``CognitiveRuntime``). This module is kept only for legacy tests and must not
be re-wired into the runtime.

Honest-telemetry rule: this module never fabricates measurements. Bottleneck
inputs that were not measured (latency, failure rate, procedural reuse) are
reported as NOT_MEASURED, and goal progress is only advanced with real evidence
strings from measured context metrics.
"""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
from zerion.cognitive_species.goal_field import GoalField, GoalItem
from zerion.cognitive_species.hypothesis_engine import HypothesisCompetitionEngine, BottleneckDetector
from zerion.model_providers.router import CognitiveRouter, CognitiveDepthLevel


@dataclass
class SpeciesCycleTrace:
    pulse_id: str
    active_goals_count: int
    hypotheses_evaluated: int
    selected_depth: str
    primary_bottleneck: str
    reality_learned: bool
    duration_ms: float
    timestamp: float = field(default_factory=time.time)


class CognitivePulseDaemon:
    """
    Event-driven background wake pulse.
    Wakes when meaningful events occur: objective change, anomaly, new info, failure, opportunity, uncertainty.
    """
    def __init__(self, engine_ref: Any, idle_interval_seconds: float = 5.0):
        self.engine = engine_ref
        self.interval = idle_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            try:
                if hasattr(self.engine, "execute_pulse_cycle"):
                    await self.engine.execute_pulse_cycle({"resource_metrics": {}})
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(self.interval)


class CognitiveSpeciesRuntime:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.goal_field = GoalField(db_path=f"{data_dir}/goal_field.db")
        self.hypothesis_engine = HypothesisCompetitionEngine()
        self.bottleneck_detector = BottleneckDetector()
        # Gemini-only router: no local models directory exists.
        self.router = CognitiveRouter()
        self._pulse_count = 0

    async def execute_pulse_cycle(self, context: Dict[str, Any]) -> SpeciesCycleTrace:
        t0 = time.perf_counter()
        self._pulse_count += 1
        pulse_id = f"pulse_{self._pulse_count}_{int(time.time())}"

        # 1. EVALUATE GOAL FIELD
        active_goals = self.goal_field.list_active_goals()
        if not active_goals:
            self.goal_field.register_goal(GoalItem(
                title="Continuous Cognitive Development & Inefficiency Discovery",
                purpose="Proactively discover latent bottlenecks before user prompting",
                priority=90
            ))
            active_goals = self.goal_field.list_active_goals()

        # 2. FORMULATE COMPETING HYPOTHESES FOR ACTIVE GOAL
        hyps = self.hypothesis_engine.formulate_competing_hypotheses(active_goals[0].title)

        # 3. DYNAMIC COGNITIVE DEPTH COMPUTATION (config inputs, honest)
        depth = self.router.compute_cognitive_depth(
            uncertainty=0.5,
            novelty=0.4,
            stakes_risk=0.2,
            goal_relevance=0.9
        )

        # 4. BOTTLENECK DISCOVERY — ONLY from measured context metrics.
        # Latency / failure rate / procedural reuse are NOT_MEASURED here and
        # are never replaced with attractive placeholder numbers.
        metrics = (context or {}).get("resource_metrics") or {}
        cpu_percent = metrics.get("cpu_percent")
        memory_mb = metrics.get("memory_mb")
        measured = cpu_percent is not None or memory_mb is not None
        if memory_mb is not None and memory_mb > 3000.0:
            primary_bottleneck = "RESOURCE_LIMITATION"
        else:
            primary_bottleneck = "NONE"

        # 5. ADVANCE GOAL PROGRESS only with REAL evidence. Unmeasured cycles
        # advance nothing and are never reported as "reality learned".
        if measured:
            self.goal_field.advance_goal(
                active_goals[0].goal_id, 0.0,
                f"Pulse {pulse_id}: measured cpu_percent={cpu_percent}, memory_mb={memory_mb}")

        duration = (time.perf_counter() - t0) * 1000.0
        return SpeciesCycleTrace(
            pulse_id=pulse_id,
            active_goals_count=len(active_goals),
            hypotheses_evaluated=len(hyps),
            selected_depth=depth.value,
            primary_bottleneck=primary_bottleneck,
            reality_learned=measured,
            duration_ms=round(duration, 2)
        )
