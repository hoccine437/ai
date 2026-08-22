"""
Slice 8 — CognitivePulse: persistent, event-driven, resource-aware cognitive
runtime loop.

The Pulse is the COORDINATOR of the cognitive lifecycle, not another agent and
not another reasoning engine. It connects the Slices 1-7 subsystems on the
single Slice 1 event bus:

  WORLD/EVENTS -> PERCEPTION -> ATTENTION -> GOALS -> QUESTIONS -> HYPOTHESES
  -> EXPERIMENTS -> REALITY FEEDBACK -> BELIEF UPDATE -> EXPERIENCE ->
  CAPABILITIES -> BOTTLENECKS -> CONTROLLED IMPROVEMENT -> NEXT CYCLE

Design rules enforced here:

- The Pulse reacts to events (event-driven activation) and runs a configurable
  periodic scheduler (periodic activation) for things that cannot rely on
  events alone. It does NOT blindly run every subsystem every cycle.
- Every expensive action is gated by: deduplication (aggregate equivalent
  events in a window), cooldowns (never repeat an identical investigation),
  resource budgets (DEFER/DEGRADE, never silently exceed), and priority.
- Cognition has exactly ONE provider (Gemini). When it is unavailable the
  Pulse defers provider work and keeps monitoring — it never fabricates results
  and never falls back to another brain.
- When nothing has expected value, the Pulse is IDLE and calls no model.
- Self-improvement only ever runs through the Slice 7 SelfModificationGate
  (proposal -> analysis -> tests -> sandbox -> benchmark -> policy ->
  promotion/rollback). The Pulse schedules BOTTLENECK_ANALYSIS and
  IMPROVEMENT_EVALUATION work; it never mutates source, genomes or
  capabilities directly.
- Voice events (VOICE_*) are external perception sources only — recorded,
  never consumed for cognition. No STT/TTS in this slice.
"""

import asyncio
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from zerion.runtime.events import Event, EventType
from zerion.cognitive_os.attention import AttentionItem
from zerion.cognitive_os.pulse_store import (
    CognitiveWorkItem,
    FailureKind,
    PulseStore,
    WorkStatus,
    WorkType,
)


class PulseLifecycle(str, Enum):
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


# OfflineMode removed: there is no local model, no offline brain, and no
# offline/online routing switch. Gemini is the only provider; when it is
# unavailable, provider-required work is deferred honestly — never fabricated.


# Work types whose execution chain is deterministic and never requires a
# model provider. Anything NOT in this set is treated as provider-required
# and is DEFERRED when no provider is available.
_LOCAL_ONLY_WORK_TYPES = {
    WorkType.GOAL_REVIEW,
    WorkType.ATTENTION_REVIEW,
    WorkType.BOTTLENECK_ANALYSIS,
    WorkType.CAPABILITY_HEALTH,
    WorkType.MEMORY_MAINTENANCE,
    WorkType.EXPERIENCE_DISTILLATION,
    WorkType.FAILURE_ANALYSIS,
    WorkType.BELIEF_UPDATE,
    WorkType.EXPERIMENT,
    WorkType.IMPROVEMENT_EVALUATION,
    WorkType.STALE_TASK_SCAN,
    WorkType.ENVIRONMENT_HEALTH,
    # Deterministic engines (Slice 2 genesis + hypothesis, deep cycle bundles
    # local scans) — no LLM, no network.
    WorkType.QUESTION_GENERATION,
    WorkType.HYPOTHESIS_INVESTIGATION,
    WorkType.DEEP_CYCLE,
}

DEFAULT_PULSE_CONFIG: Dict[str, Any] = {
    "tick_interval_s": 1.0,
    "deep_cycle_interval_s": 300.0,
    "goal_health_interval_s": 30.0,
    "telemetry_scan_interval_s": 30.0,
    # Periodic activation: each area keeps its OWN cadence (rule: configurable
    # intervals, no aggressive polling, no global timer that one activity
    # resets for everyone).
    "memory_maintenance_interval_s": 120.0,
    "capability_health_interval_s": 60.0,
    "stale_task_interval_s": 30.0,
    "stale_task_threshold_s": 300.0,   # queued work older than this is "unfinished"
    "environment_health_interval_s": 60.0,
    "cooldowns": {
        "GOAL_REVIEW": 10.0,
        "ATTENTION_REVIEW": 5.0,
        "QUESTION_GENERATION": 5.0,
        "HYPOTHESIS_INVESTIGATION": 10.0,
        "EXPERIMENT": 10.0,
        "BELIEF_UPDATE": 5.0,
        "EXPERIENCE_DISTILLATION": 15.0,
        "FAILURE_ANALYSIS": 15.0,
        "CAPABILITY_HEALTH": 60.0,
        "BOTTLENECK_ANALYSIS": 30.0,
        "IMPROVEMENT_EVALUATION": 60.0,
        "MEMORY_MAINTENANCE": 120.0,
        "DEEP_CYCLE": 300.0,
        "STALE_TASK_SCAN": 30.0,
        "ENVIRONMENT_HEALTH": 60.0,
    },
    "dedup_window_s": 60.0,
    "repeated_failure_threshold": 3,
    "retry_policy": {
        "TRANSIENT": {"max_attempts": 3, "backoff_s": 2.0},
        "PERMANENT": {"max_attempts": 0, "backoff_s": 0.0},
        "UNKNOWN": {"max_attempts": 2, "backoff_s": 4.0},
    },
    "budgets": {
        "cpu_units_per_hour": 100.0,          # abstract cognitive compute units
        "api_cost_per_day": 100.0,            # abstract API cost units
        "model_inference_ms_per_hour": 60000.0,  # abstract model-inference units
        "network_requests_per_hour": 100,
        "concurrent_tasks": 2,
    },
    "max_queue_size": 500,
}


class CognitivePulse:
    """Coordinates the cognitive lifecycle on the single event bus."""

    def __init__(self, runtime, store: Optional[PulseStore] = None,
                 config: Optional[Dict[str, Any]] = None,
                 event_bus=None, now_fn=None):
        self.runtime = runtime
        self.event_bus = event_bus or runtime.event_bus
        self.now = now_fn or time.time
        self.store = store or PulseStore()
        self.config = dict(DEFAULT_PULSE_CONFIG)
        if config:
            self.config.update(config)
        self._cooldowns = dict(self.config.get("cooldowns", {}))
        self._budgets = dict(self.config.get("budgets", {}))
        self._dedup_window_s = float(self.config.get("dedup_window_s", 60.0))
        self._retry_policy = self.config.get("retry_policy", {})
        self._repeated_failure_threshold = int(
            self.config.get("repeated_failure_threshold", 3))

        self.state = PulseLifecycle.INITIALIZING
        self.degraded_reason: str = ""
        self._lock = asyncio.Lock()
        self._active_work: Dict[str, str] = {}   # work_id -> work_type
        self._last_success: Optional[float] = None
        self._last_cycle: Optional[Dict[str, Any]] = None
        self._next_scheduled_cycle: Optional[float] = None
        self._idle_since: Optional[float] = None
        self._idle = False
        self._running_loop = False
        self._voice_events_seen = 0
        self._initialized = False
        self._start_time: Optional[float] = None  # periodic baseline
        # Cached resource sample for the RAM floor budget (rule 6): sampled at
        # most every 5s so the budget check never becomes a hot sampler itself.
        self._ram_sample: Optional[Any] = None
        self._ram_sample_at: float = 0.0

        self.event_bus.subscribe_all(self._on_event)

    # --- lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Explicit INITIALIZE step (START -> INITIALIZE -> RUN). Idempotent:
        recovers pending work, restores the persisted lifecycle state,
        establishes the periodic baseline and records what was recovered —
        completed work is never re-created and an explicitly paused/degraded
        pulse is never silently resumed or declared healthy."""
        if self._initialized:
            return
        self._initialized = True
        self._start_time = self.now()
        self._recover_from_restart()
        self._restore_state()
        self.store.record_cycle("INITIALIZED", "pulse initialized")
        self._save_state()

    async def start(self) -> None:
        if self.state in (PulseLifecycle.RUNNING, PulseLifecycle.DEGRADED):
            return
        async with self._lock:
            await self.initialize()
            if self.state not in (PulseLifecycle.PAUSED, PulseLifecycle.DEGRADED):
                # A pulse restored from a persisted PAUSED state stays paused
                # until an explicit resume(); a pulse restored from DEGRADED
                # stays DEGRADED (degraded mode is never silently resumed or
                # declared healthy — it requires explicit recovery).
                self.state = PulseLifecycle.RUNNING
                self.degraded_reason = ""
        if self.state == PulseLifecycle.RUNNING:
            await self.event_bus.publish(Event(
                event_type=EventType.PULSE_STARTED,
                payload={"state": self.state.value},
                source="cognitive_pulse",
                priority=95,
            ), dispatch_immediately=True)
            self.store.record_cycle("STARTED", "pulse started")
        self._save_state()

    def _restore_state(self) -> None:
        """Recover the persisted lifecycle state after a restart."""
        lifecycle, reason = self.store.load_pulse_state()
        if lifecycle == PulseLifecycle.PAUSED.value:
            self.state = PulseLifecycle.PAUSED
            self.store.record_cycle("RESTORED", "pulse restored as PAUSED")
        elif lifecycle == PulseLifecycle.DEGRADED.value:
            self.state = PulseLifecycle.DEGRADED
            self.degraded_reason = reason or ""
            self.store.record_cycle("RESTORED", "pulse restored as DEGRADED")

    def _save_state(self) -> None:
        self.store.save_pulse_state(self.state.value, self.degraded_reason)

    def _recover_from_restart(self) -> None:
        """Recover pending work after a restart. The store already requeued any
        RUNNING item at load time; here we surface what was recovered."""
        pending = [w for w in self.store.list_work(WorkStatus.QUEUED)]
        if pending:
            self.store.record_cycle(
                "RECOVERED", f"recovered {len(pending)} pending work items")

    async def pause(self) -> None:
        if self.state != PulseLifecycle.RUNNING:
            return
        self.state = PulseLifecycle.PAUSED
        await self.event_bus.publish(Event(
            event_type=EventType.PULSE_PAUSED,
            payload={"state": self.state.value},
            source="cognitive_pulse", priority=90,
        ), dispatch_immediately=True)
        self.store.record_cycle("PAUSED", "pulse paused")
        self._save_state()

    async def resume(self) -> None:
        if self.state != PulseLifecycle.PAUSED:
            return
        self.state = PulseLifecycle.RUNNING
        await self.event_bus.publish(Event(
            event_type=EventType.PULSE_RESUMED,
            payload={"state": self.state.value},
            source="cognitive_pulse", priority=90,
        ), dispatch_immediately=True)
        self.store.record_cycle("RESUMED", "pulse resumed")
        self._save_state()

    async def shutdown(self) -> None:
        if self.state == PulseLifecycle.STOPPED:
            return
        was_paused = self.state == PulseLifecycle.PAUSED
        self.state = PulseLifecycle.STOPPED
        await self.event_bus.publish(Event(
            event_type=EventType.PULSE_STOPPED,
            payload={"state": self.state.value},
            source="cognitive_pulse", priority=95,
        ), dispatch_immediately=True)
        self.store.record_cycle("STOPPED", "pulse shutdown")
        if not was_paused:
            # Keep the persisted PAUSED state across a restart: a pulse the
            # operator explicitly paused must not silently resume on boot.
            self._save_state()

    # --- event-driven activation -------------------------------------------

    # Maps bus events to cognitive work. The Pulse reacts; the engines execute.
    _EVENT_ACTION_MAP: Dict[EventType, WorkType] = {
        EventType.GOAL_BLOCKED: WorkType.GOAL_REVIEW,
        EventType.GOAL_CREATED: WorkType.GOAL_REVIEW,
        EventType.GOAL_UPDATED: WorkType.GOAL_REVIEW,
        EventType.TASK_FAILED: WorkType.FAILURE_ANALYSIS,
        EventType.REPEATED_FAILURE_DETECTED: WorkType.FAILURE_ANALYSIS,
        EventType.PROVIDER_FAILED: WorkType.BOTTLENECK_ANALYSIS,
        EventType.BOTTLENECK_DETECTED: WorkType.IMPROVEMENT_EVALUATION,
        EventType.CAPABILITY_DEGRADED: WorkType.CAPABILITY_HEALTH,
        EventType.CAPABILITY_DEPRECATED: WorkType.CAPABILITY_HEALTH,
        EventType.EXPERIMENT_COMPLETED: WorkType.BELIEF_UPDATE,
        EventType.EXPERIMENT_FAILED: WorkType.FAILURE_ANALYSIS,
        EventType.ANOMALY_DETECTED: WorkType.QUESTION_GENERATION,
        EventType.CONTRADICTION_FOUND: WorkType.QUESTION_GENERATION,
        EventType.PREDICTION_ERROR: WorkType.QUESTION_GENERATION,
        EventType.UNCERTAINTY_DETECTED: WorkType.QUESTION_GENERATION,
        EventType.GOAL_GAP_DETECTED: WorkType.QUESTION_GENERATION,
        EventType.CAPABILITY_GAP: WorkType.QUESTION_GENERATION,
        EventType.USER_INTERACTION: WorkType.ATTENTION_REVIEW,
        EventType.ATTENTION_DEFERRED: WorkType.ATTENTION_REVIEW,
        EventType.OBSERVATION_RECORDED: WorkType.ATTENTION_REVIEW,
        EventType.EPISODE_COMPLETED: WorkType.EXPERIENCE_DISTILLATION,
        # Resource degradation is a real event -> resample the environment and
        # feed the resource governor (never invented CPU/RAM numbers).
        EventType.RESOURCE_WARNING: WorkType.ENVIRONMENT_HEALTH,
        EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED: WorkType.ENVIRONMENT_HEALTH,
    }

    # Event types that always arrive from the world/perception and never from
    # the Pulse itself (guard against self-trigger loops).
    _WORLD_EVENT_TYPES = {
        EventType.USER_INTERACTION,
        EventType.OBSERVATION_RECORDED,
        EventType.PERCEPTION_RECEIVED,
        EventType.ANOMALY_DETECTED,
        EventType.CONTRADICTION_FOUND,
        EventType.PREDICTION_ERROR,
        EventType.GOAL_BLOCKED,
        EventType.GOAL_CREATED,
        EventType.GOAL_UPDATED,
        EventType.TASK_FAILED,
        EventType.PROVIDER_FAILED,
        EventType.CAPABILITY_DEGRADED,
        EventType.CAPABILITY_DEPRECATED,
        EventType.EXPERIMENT_FAILED,
        EventType.EXPERIMENT_COMPLETED,
        EventType.EPISODE_COMPLETED,
        EventType.BOTTLENECK_DETECTED,
        EventType.REPEATED_FAILURE_DETECTED,
        EventType.VOICE_STARTED,
        EventType.VOICE_TRANSCRIPT_PARTIAL,
        EventType.VOICE_TRANSCRIPT_FINAL,
        EventType.VOICE_INTERRUPTED,
        EventType.VOICE_ENDED,
        EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED,
        EventType.RESOURCE_WARNING,
        EventType.SYSTEM_STARTUP,
        EventType.SYSTEM_SHUTDOWN,
    }

    async def _on_event(self, event: Event) -> None:
        """The Pulse's event-driven activation. Reacts to real bus events by
        computing priority, deduplicating, cooldown-gating and enqueueing work.
        No expensive reasoning happens inline."""
        if self.state not in (PulseLifecycle.RUNNING, PulseLifecycle.DEGRADED):
            return
        if event.source == "cognitive_pulse":
            return  # never react to our own published work events

        if event.event_type in (EventType.VOICE_STARTED,
                                EventType.VOICE_TRANSCRIPT_PARTIAL,
                                EventType.VOICE_TRANSCRIPT_FINAL,
                                EventType.VOICE_INTERRUPTED,
                                EventType.VOICE_ENDED):
            # Voice is an external perception source only (Slice 8 rule 34).
            self._voice_events_seen += 1
            self.store.record_cycle("VOICE_EVENT",
                                    event.event_type.value)
            return

        work_type = self._EVENT_ACTION_MAP.get(event.event_type)
        if work_type is None:
            return

        # Event deduplication: equivalent events within the window aggregate.
        fingerprint = self._fingerprint(event)
        occurrences = self.store.dedup_register(
            fingerprint, event.event_type.value, self._dedup_window_s,
            related_event=event.event_id)
        if occurrences > 1 and not self._is_escalation(work_type, occurrences):
            # Already handled in this window; aggregate count retained as
            # evidence (never lost), but do not spawn duplicate investigations.
            return

        priority, metrics = self._priority_for(event)
        item = CognitiveWorkItem(
            work_type=work_type,
            priority=priority,
            source_event=event.event_type.value,
            goal_ids=self._goal_ids_from_event(event),
            cost_estimate=self._cost_for(work_type),
            risk=metrics.get("risk", 0.2),
            depth_required=self._depth_for(work_type),
            payload={"source_event_id": event.event_id,
                     "payload": dict(event.payload),
                     "occurrences": occurrences},
        )
        # Repeated-failure escalation is a NEW deeper investigation: it may
        # proceed even while the routine FAILURE_ANALYSIS cooldown is active.
        await self._enqueue_work(
            item, reason=event.event_type.value,
            force=self._is_escalation(work_type, occurrences))

    def _fingerprint(self, event: Event) -> str:
        key = event.event_type.value
        payload = event.payload
        for field in ("task", "action", "error", "topic", "question_id",
                      "experiment_id", "episode_id", "goal_id",
                      "objective_id", "failure_id", "provider", "bottleneck_type"):
            if field in payload:
                key += ":" + str(payload[field])[:120]
        return key

    def _is_escalation(self, work_type: WorkType, occurrences: int) -> bool:
        """Repeated failures escalate: after the threshold, aggregate into ONE
        deeper investigation (rule: do not launch 10 identical investigations)."""
        if work_type != WorkType.FAILURE_ANALYSIS:
            return False
        return occurrences == self._repeated_failure_threshold

    def _goal_ids_from_event(self, event: Event) -> List[str]:
        for field in ("goal_id", "objective_id"):
            val = event.payload.get(field)
            if isinstance(val, str) and val:
                return [val]
        return []

    def _priority_for(self, event: Event) -> (float, Dict[str, float]):
        """Reuse the Slice 1 CognitivePriority through the AttentionEconomy."""
        urgency = float(event.payload.get("urgency", 0.5))
        importance = float(event.payload.get("importance", 0.5))
        uncertainty = float(event.payload.get("uncertainty", 0.5))
        novelty = float(event.payload.get("novelty", 0.3))
        goal_relevance = float(event.payload.get("goal_relevance", 0.5))
        risk = float(event.payload.get("risk", 0.2))
        cost = float(event.payload.get("resource_cost", 0.3))
        gain = float(event.payload.get("expected_information_gain", 0.4))
        utility = float(event.payload.get("expected_utility", 0.4))

        # Event-type-specific shaping (mild; the field's own weights dominate).
        if event.event_type == EventType.REPEATED_FAILURE_DETECTED:
            urgency, importance, goal_relevance = 0.95, 0.9, 0.85
        elif event.event_type == EventType.PROVIDER_FAILED:
            urgency, importance = 0.9, 0.9
        elif event.event_type == EventType.GOAL_BLOCKED:
            urgency, importance, goal_relevance = 0.9, 0.9, 1.0
        elif event.event_type == EventType.CONTRADICTION_FOUND:
            uncertainty, novelty = 0.95, 0.9
        elif event.event_type == EventType.BOTTLENECK_DETECTED:
            importance, goal_relevance = 0.95, 0.9
        elif event.event_type == EventType.CAPABILITY_DEGRADED:
            importance, goal_relevance = 0.8, 0.8
        elif event.event_type == EventType.OBSERVATION_RECORDED:
            priority_override = self._low_priority_for_observation(event)
            if priority_override is not None:
                return priority_override
        elif event.event_type in (EventType.RESOURCE_WARNING,
                                  EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED):
            urgency, importance = 0.9, 0.9

        metrics = {
            "urgency": max(0.0, min(1.0, urgency)),
            "importance": max(0.0, min(1.0, importance)),
            "uncertainty": max(0.0, min(1.0, uncertainty)),
            "novelty": max(0.0, min(1.0, novelty)),
            "goal_relevance": max(0.0, min(1.0, goal_relevance)),
            "expected_information_gain": max(0.0, min(1.0, gain)),
            "expected_utility": max(0.0, min(1.0, utility)),
            "risk": max(0.0, min(1.0, risk)),
            "resource_cost": max(0.0, min(1.0, cost)),
            "api_cost": float(event.payload.get("api_cost", 0.0)),
            "estimated_latency_ms": float(event.payload.get("estimated_latency_ms", 0.0)),
        }
        item = AttentionItem(
            topic=f"pulse:{event.event_type.value}",
            source=event.event_type.value,
            urgency=metrics["urgency"],
            importance=metrics["importance"],
            uncertainty=metrics["uncertainty"],
            novelty=metrics["novelty"],
            objective_relevance=metrics["goal_relevance"],
            expected_information_gain=metrics["expected_information_gain"],
            expected_utility=metrics["expected_utility"],
            risk=metrics["risk"],
            resource_cost=metrics["resource_cost"],
            api_cost=metrics["api_cost"],
            estimated_latency_ms=metrics["estimated_latency_ms"],
        )
        priority = self.runtime.attention.scorer.score(item)
        return priority, metrics

    def _low_priority_for_observation(self, event: Event) -> Optional[tuple]:
        """Routine observations are cheap bookkeeping, not expensive cognition."""
        if event.event_type == EventType.OBSERVATION_RECORDED:
            return (0.1, {"urgency": 0.1, "importance": 0.1, "uncertainty": 0.1,
                          "novelty": 0.1, "goal_relevance": 0.1,
                          "expected_information_gain": 0.1,
                          "expected_utility": 0.1, "risk": 0.0,
                          "resource_cost": 0.05, "api_cost": 0.0,
                          "estimated_latency_ms": 0.0})
        return None

    def _cost_for(self, work_type: WorkType) -> float:
        costs = {
            WorkType.DEEP_CYCLE: 5.0,
            WorkType.IMPROVEMENT_EVALUATION: 4.0,
            WorkType.BOTTLENECK_ANALYSIS: 2.0,
            WorkType.QUESTION_GENERATION: 1.0,
            WorkType.HYPOTHESIS_INVESTIGATION: 1.0,
            WorkType.EXPERIMENT: 2.0,
            WorkType.BELIEF_UPDATE: 1.0,
            WorkType.EXPERIENCE_DISTILLATION: 1.5,
            WorkType.FAILURE_ANALYSIS: 1.0,
            WorkType.GOAL_REVIEW: 0.5,
            WorkType.ATTENTION_REVIEW: 0.5,
            WorkType.CAPABILITY_HEALTH: 0.5,
            WorkType.MEMORY_MAINTENANCE: 0.2,
            WorkType.ATTENTION_REVIEW: 0.2,
            WorkType.STALE_TASK_SCAN: 0.1,
            WorkType.ENVIRONMENT_HEALTH: 0.2,
        }
        return costs.get(work_type, 1.0)

    def _depth_for(self, work_type: WorkType) -> str:
        """Slice 6 depth selection: DEEP_FIELD only where the work justifies it."""
        if work_type in (WorkType.IMPROVEMENT_EVALUATION, WorkType.DEEP_CYCLE):
            return "D3"
        if work_type == WorkType.BOTTLENECK_ANALYSIS:
            return "D2"
        if work_type == WorkType.QUESTION_GENERATION:
            return "D2"
        return "D1"  # FAST_FIELD for everything routine

    # --- priority queue ----------------------------------------------------

    async def _enqueue_work(self, item: CognitiveWorkItem, *, reason: str = "",
                            force: bool = False,
                            provider_required: bool = False) -> None:
        # Safe-by-default classification: work is provider-required unless it
        # is in the proven-local whitelist (or explicitly marked otherwise).
        item.provider_required = (bool(provider_required)
                                  or item.provider_required
                                  or item.work_type not in _LOCAL_ONLY_WORK_TYPES)
        async with self._lock:
            key = item.work_type.value
            if not force and self.store.in_cooldown(f"work:{key}"):
                return  # cooldown gates repeated expensive processing
            if len(self.store.list_work(WorkStatus.QUEUED)) >= int(
                    self.config.get("max_queue_size", 500)):
                return  # bounded queue
            # Deduplicate queued work of the same type targeting the same object.
            # A MORE URGENT signal for the same target upgrades the queued item
            # instead of being silently dropped (e.g. a blocked goal outranks
            # the routine review created when that goal was first created).
            for existing in self.store.list_work(WorkStatus.QUEUED):
                if (existing.work_type == item.work_type and
                        self._same_target(existing, item)):
                    if item.priority > existing.priority:
                        existing.priority = item.priority
                        existing.source_event = item.source_event
                        existing.payload = item.payload
                        existing.provider_required = item.provider_required
                        self.store.enqueue(existing)
                    return
            self.store.enqueue(item)
        await self.event_bus.publish(Event(
            event_type=EventType.WORK_QUEUED,
            payload={"work_id": item.work_id,
                     "work_type": item.work_type.value,
                     "priority": item.priority,
                     "reason": reason},
            source="cognitive_pulse", priority=40,
        ), dispatch_immediately=True)

    @staticmethod
    def _same_target(a: CognitiveWorkItem, b: CognitiveWorkItem) -> bool:
        pa, pb = a.payload.get("payload", {}), b.payload.get("payload", {})
        for field in ("question_id", "experiment_id", "episode_id",
                      "goal_id", "objective_id", "failure_id"):
            if pa.get(field) is not None or pb.get(field) is not None:
                if pa.get(field) == pb.get(field):
                    return True
        return False

    async def _dequeue_next(self) -> Optional[CognitiveWorkItem]:
        async with self._lock:
            candidates = [w for w in self.store.list_work(WorkStatus.QUEUED)
                          if w.scheduled_at <= self.now()]
            if not candidates:
                return None
            # Highest priority first; ties broken by earliest creation.
            candidates.sort(key=lambda w: (-w.priority, w.created_at))
            for item in candidates:
                key = f"work:{item.work_type.value}"
                # Escalated repeated-failure analysis is a NEW deeper
                # investigation: it is not blocked by the routine cooldown.
                escalated = self._is_escalation(
                    item.work_type, int(item.payload.get("occurrences", 1)))
                if not escalated and self.store.in_cooldown(key):
                    continue
                block_reason = self._provider_block_reason(item)
                if block_reason is not None:
                    # Offline / no provider: DEFER with the reason persisted —
                    # never execute, never fabricate. A later pass requeues it
                    # once the mode/provider situation allows.
                    await self._defer(item, reason=block_reason)
                    continue
                if not self._budget_allows(item):
                    await self._defer(item, reason="budget exhausted")
                    continue
                if self.store.transition(item.work_id, WorkStatus.QUEUED,
                                         WorkStatus.RUNNING):
                    self._active_work[item.work_id] = item.work_type.value
                    return self.store.get_work(item.work_id)
            return None

    async def _defer(self, item: CognitiveWorkItem, *, reason: str) -> None:
        """DEFER a candidate instead of executing it. The reason is persisted
        in the item payload so recovery knows what to requeue later."""
        item.status = WorkStatus.DEFERRED
        item.payload["defer_reason"] = reason
        self.store.enqueue(item)
        self.store.record_cycle("DEFERRED", f"{item.work_type.value}: {reason}")
        await self.event_bus.publish(Event(
            event_type=EventType.WORK_DEFERRED,
            payload={"work_id": item.work_id,
                     "work_type": item.work_type.value,
                     "reason": reason},
            source="cognitive_pulse", priority=40,
        ), dispatch_immediately=True)

    def _budget_allows(self, item: CognitiveWorkItem) -> bool:
        """Check budgets BEFORE expensive work. Exhausted budgets DEFER.
        Reads the live config (single source of truth) so budgets can be
        tightened at runtime. Model-inference budget applies to
        provider-required work only — local deterministic work cannot spend
        what it never consumes."""
        budgets = self.config.get("budgets", {})
        hour = time.strftime("%Y%m%d%H")
        day = time.strftime("%Y%m%d")
        cpu_hour = float(budgets.get("cpu_units_per_hour", 100.0))
        api_day = float(budgets.get("api_cost_per_day", 100.0))
        net_hour = float(budgets.get("network_requests_per_hour", 100))
        if self.store.budget_usage("cpu_units", hour) + item.cost_estimate > cpu_hour:
            return False
        if self.store.budget_usage("api_cost", day) + item.cost_estimate > api_day:
            return False
        if self.store.budget_usage("network_requests", hour) + 1 > net_hour:
            return False
        # RAM floor: with a real resource sampler, expensive work is DEFERRED
        # when available memory is below the configured floor. Without a
        # sampler (or on a failed sample) the check is skipped — the pulse
        # never fabricates memory numbers.
        if not self._ram_allows():
            return False
        if item.provider_required:
            ms_hour = float(budgets.get("model_inference_ms_per_hour", 60000.0))
            if self.store.budget_usage("model_inference_ms", hour) + \
                    item.cost_estimate > ms_hour:
                return False
        if len(self._active_work) >= int(budgets.get("concurrent_tasks", 2)):
            return False
        return True

    def _record_budget_spend(self, item: CognitiveWorkItem) -> None:
        hour = time.strftime("%Y%m%d%H")
        day = time.strftime("%Y%m%d")
        self.store.spend_budget("cpu_units", item.cost_estimate, hour)
        self.store.spend_budget("api_cost", item.cost_estimate, day)
        self.store.spend_budget("network_requests", 1.0, hour)
        if item.provider_required:
            self.store.spend_budget("model_inference_ms",
                                    item.cost_estimate, hour)

    def _ram_allows(self) -> bool:
        """RAM floor budget (rule 6). The sampler is read at most once per 5s
        (cached), so the budget check never becomes a hot sampler itself.
        Returns True when: the RAM budget is disabled (floor <= 0), no real
        sampler exists (INSUFFICIENT_DATA — cannot enforce what we cannot
        measure), the sample is unavailable, or available memory is at/above
        the floor."""
        budgets = self.config.get("budgets", {})
        floor = float(budgets.get("ram_available_mb", 0.0))
        if floor <= 0.0:
            return True
        sampler = getattr(self.runtime, "resources", None)
        if sampler is None or not hasattr(sampler, "sample"):
            return True
        now = self.now()
        if self._ram_sample is None or (now - self._ram_sample_at) > 5.0:
            try:
                self._ram_sample = sampler.sample()
                self._ram_sample_at = now
            except Exception:  # noqa: BLE001 — a failed sample must not crash
                return True
        snap = self._ram_sample
        if snap is None:
            return True
        available = float(getattr(snap, "memory_available_mb", 0.0))
        return available >= floor

    # --- provider availability ----------------------------------------------

    def _provider_available(self) -> bool:
        """Honest provider availability: at least one registered provider is
        configured, implemented and not proven unavailable. UNKNOWN (configured
        but unproven) counts as routable — health is only ever proven by real
        call outcomes."""
        tracker = getattr(self.runtime, "provider_health", None)
        if tracker is None:
            return False  # no substrate -> cognition unavailable
        try:
            snapshot = tracker.snapshot()
        except Exception:  # noqa: BLE001 — health must never crash the pulse
            return False
        if not snapshot:
            return False
        return any(tracker.eligible(name) for name in snapshot)

    def _provider_block_reason(self, item: CognitiveWorkItem) -> Optional[str]:
        """Why a provider-required item cannot run right now, or None.
        Local deterministic work is never blocked; provider-required work is
        deferred only when no provider is genuinely available — never faked."""
        if not item.provider_required:
            return None
        if not self._provider_available():
            return "no provider available"
        return None

    def _recover_deferred(self) -> None:
        """Requeue DEFERRED items whose blocking reason no longer applies
        (offline mode relaxed, provider back). The bounded, safe unblock."""
        for w in self.store.list_work(WorkStatus.DEFERRED):
            reason = (w.payload or {}).get("defer_reason", "")
            if not reason:
                continue
            if reason == "no provider available":
                if self._provider_block_reason(w) is None:
                    w.status = WorkStatus.QUEUED
                    w.payload.pop("defer_reason", None)
                    self.store.enqueue(w)

    # --- periodic scheduler -------------------------------------------------

    async def tick(self) -> None:
        """One scheduler pass. Called on a cadence; cheap when idle."""
        if self.state not in (PulseLifecycle.RUNNING, PulseLifecycle.DEGRADED):
            return
        now = self.now()

        # A mode/provider change unblocks previously deferred provider-required
        # work; the next pass picks it up (nothing is ever lost).
        self._recover_deferred()

        # Periodic activation: things that cannot rely on events alone. Each
        # area runs on its OWN configurable interval (recovered across
        # restarts), never a global timer and never aggressive polling.
        if self._period_due("goal_health", now,
                            float(self.config.get("goal_health_interval_s", 30.0))):
            await self._schedule(WorkType.GOAL_REVIEW, priority=0.5,
                                 reason="periodic goal health")
            self.store.mark_periodic_run("goal_health")
        if self._period_due("telemetry_scan", now,
                            float(self.config.get("telemetry_scan_interval_s", 30.0))):
            await self._schedule(WorkType.BOTTLENECK_ANALYSIS, priority=0.4,
                                 reason="periodic telemetry scan")
            self.store.mark_periodic_run("telemetry_scan")
        if self._period_due("deep_cycle", now,
                            float(self.config.get("deep_cycle_interval_s", 300.0))):
            await self._schedule(WorkType.DEEP_CYCLE, priority=0.3,
                                 reason="scheduled deep cycle")
            self.store.mark_periodic_run("deep_cycle")
        if self._period_due("memory_maintenance", now,
                            float(self.config.get("memory_maintenance_interval_s", 120.0))):
            await self._schedule(WorkType.MEMORY_MAINTENANCE, priority=0.2,
                                 reason="periodic memory maintenance")
            self.store.mark_periodic_run("memory_maintenance")
        if self._period_due("capability_health", now,
                            float(self.config.get("capability_health_interval_s", 60.0))):
            await self._schedule(WorkType.CAPABILITY_HEALTH, priority=0.3,
                                 reason="periodic capability health")
            self.store.mark_periodic_run("capability_health")
        if self._period_due("stale_task_scan", now,
                            float(self.config.get("stale_task_interval_s", 30.0))):
            await self._schedule(WorkType.STALE_TASK_SCAN, priority=0.3,
                                 reason="periodic stale-task scan")
            self.store.mark_periodic_run("stale_task_scan")
        if self._period_due("environment_health", now,
                            float(self.config.get("environment_health_interval_s", 60.0))):
            await self._schedule(WorkType.ENVIRONMENT_HEALTH, priority=0.25,
                                 reason="periodic environment health")
            self.store.mark_periodic_run("environment_health")

        # Execute at most one work item per tick (bounded, resource-aware).
        item = await self._dequeue_next()
        if item is None:
            await self._maybe_enter_idle(now)
            return
        self._idle = False
        self._idle_since = None
        self._last_cycle = {"state": item.work_type.value,
                            "timestamp": now, "work_id": item.work_id}
        self._next_scheduled_cycle = None
        await self.event_bus.publish(Event(
            event_type=EventType.PULSE_CYCLE_STARTED,
            payload={"work_id": item.work_id,
                     "work_type": item.work_type.value},
            source="cognitive_pulse", priority=30,
        ), dispatch_immediately=True)
        self.store.record_cycle("WORK_STARTED",
                                f"{item.work_type.value}:{item.work_id}")
        await self.event_bus.publish(Event(
            event_type=EventType.WORK_STARTED,
            payload={"work_id": item.work_id,
                     "work_type": item.work_type.value,
                     "priority": item.priority},
            source="cognitive_pulse", priority=40,
        ), dispatch_immediately=True)

        self._record_budget_spend(item)
        ok = await self._execute_work(item)
        self._active_work.pop(item.work_id, None)

        if ok:
            self.store.transition(item.work_id, WorkStatus.RUNNING,
                                  WorkStatus.COMPLETED)
            self._last_success = self.now()
            self._last_cycle["outcome"] = "COMPLETED"
            cooldown = self._cooldowns.get(item.work_type.value, 0.0)
            if cooldown:
                self.store.set_cooldown(f"work:{item.work_type.value}",
                                        cooldown,
                                        trigger_reason=item.work_type.value)
            await self.event_bus.publish(Event(
                event_type=EventType.WORK_COMPLETED,
                payload={"work_id": item.work_id,
                         "work_type": item.work_type.value},
                source="cognitive_pulse", priority=40,
            ), dispatch_immediately=True)
        else:
            self.store.transition(item.work_id, WorkStatus.RUNNING,
                                  WorkStatus.FAILED)
            await self.event_bus.publish(Event(
                event_type=EventType.WORK_FAILED,
                payload={"work_id": item.work_id,
                         "work_type": item.work_type.value,
                         "attempts": item.attempts + 1},
                source="cognitive_pulse", priority=50,
            ), dispatch_immediately=True)
        self.store.record_cycle("WORK_" + ("COMPLETED" if ok else "FAILED"),
                                item.work_id)
        await self.event_bus.publish(Event(
            event_type=EventType.PULSE_CYCLE_COMPLETED,
            payload={"work_id": item.work_id,
                     "work_type": item.work_type.value,
                     "outcome": "COMPLETED" if ok else "FAILED"},
            source="cognitive_pulse", priority=30,
        ), dispatch_immediately=True)

    def _period_due(self, key: str, now: float, interval: float) -> bool:
        """Each periodic evaluation has its OWN last-run timestamp (persisted,
        so cadences survive restarts). The baseline is the pulse's start time:
        nothing fires before its interval has elapsed — no aggressive polling."""
        baseline = self._start_time if self._start_time is not None else now
        last = self.store.last_periodic_run(key, default=baseline)
        return (now - float(last)) >= interval

    async def _maybe_enter_idle(self, now: float) -> None:
        """Idle is intentional: when nothing has expected value the Pulse does
        nothing and calls no model."""
        if not self._idle:
            self._idle = True
            self._idle_since = now
            self._last_cycle = {"state": "IDLE", "timestamp": now}
            self.store.record_cycle("IDLE", "no high-value work")
            await self.event_bus.publish(Event(
                event_type=EventType.PULSE_IDLE,
                payload={"idle_since": now},
                source="cognitive_pulse", priority=20,
            ), dispatch_immediately=True)

    async def run_forever(self) -> None:
        """The persistent loop. Only enters when started; sleeps between ticks."""
        self._running_loop = True
        while self._running_loop and self.state in (
                PulseLifecycle.RUNNING, PulseLifecycle.DEGRADED):
            await self.tick()
            await asyncio.sleep(float(self.config.get("tick_interval_s", 1.0)))
        self._running_loop = False

    def stop_loop(self) -> None:
        self._running_loop = False

    # --- scheduling helpers -------------------------------------------------

    async def _schedule(self, work_type: WorkType, *, priority: float,
                        reason: str, payload: Optional[Dict[str, Any]] = None,
                        goal_ids: Optional[List[str]] = None,
                        provider_required: bool = False) -> None:
        if self.store.in_cooldown(f"work:{work_type.value}"):
            return
        item = CognitiveWorkItem(
            work_type=work_type, priority=priority, source_event="scheduler",
            goal_ids=goal_ids or [],
            cost_estimate=self._cost_for(work_type),
            risk=0.2, depth_required=self._depth_for(work_type),
            provider_required=provider_required,
            payload={"payload": payload or {}},
        )
        await self._enqueue_work(item, reason=reason,
                                 provider_required=provider_required)

    # --- work execution (handlers reuse the engines, never duplicate them) ---

    async def _execute_work(self, item: CognitiveWorkItem) -> bool:
        try:
            handler = {
                WorkType.GOAL_REVIEW: self._exec_goal_review,
                WorkType.ATTENTION_REVIEW: self._exec_attention_review,
                WorkType.QUESTION_GENERATION: self._exec_question_generation,
                WorkType.HYPOTHESIS_INVESTIGATION: self._exec_hypothesis_investigation,
                WorkType.EXPERIMENT: self._exec_experiment,
                WorkType.BELIEF_UPDATE: self._exec_belief_update,
                WorkType.EXPERIENCE_DISTILLATION: self._exec_experience_distillation,
                WorkType.FAILURE_ANALYSIS: self._exec_failure_analysis,
                WorkType.CAPABILITY_HEALTH: self._exec_capability_health,
                WorkType.BOTTLENECK_ANALYSIS: self._exec_bottleneck_analysis,
                WorkType.IMPROVEMENT_EVALUATION: self._exec_improvement_evaluation,
                WorkType.MEMORY_MAINTENANCE: self._exec_memory_maintenance,
                WorkType.DEEP_CYCLE: self._exec_deep_cycle,
                WorkType.STALE_TASK_SCAN: self._exec_stale_task_scan,
                WorkType.ENVIRONMENT_HEALTH: self._exec_environment_health,
            }[item.work_type]
            await handler(item)
            return True
        except Exception as exc:  # noqa: BLE001 — crash recovery isolates work
            self._handle_work_crash(item, exc)
            return False

    def _handle_work_crash(self, item: CognitiveWorkItem, exc: Exception) -> None:
        """Crash recovery: isolate the failure, record it, apply the bounded
        retry policy, and continue other safe work. Attempts are incremented
        BEFORE the retry decision so the bound actually terminates."""
        error = f"{type(exc).__name__}: {exc}"
        kind = self._classify_failure(item, exc)
        policy = self._retry_policy.get(kind.value, {"max_attempts": 2, "backoff_s": 2.0})
        self.store.bump_attempt(item.work_id)
        item.attempts += 1
        attempt = item.attempts
        self.store.record_failure(item.work_id, attempt, kind.value, error)
        item.last_error = error
        if attempt < int(policy.get("max_attempts", 0)):
            backoff = float(policy.get("backoff_s", 2.0)) * (2 ** (attempt - 1))
            self.store.requeue(item.work_id, backoff_s=backoff, error=error)
        else:
            self.store.record_cycle(
                "FAILED",
                f"{item.work_type.value}:{error[:200]} "
                f"(kind={kind.value}, attempts={attempt})")
            self._escalate_failure(item)

    def _classify_failure(self, item: CognitiveWorkItem, exc: Exception) -> FailureKind:
        name = type(exc).__name__
        if any(token in name.lower() for token in ("timeout", "connection",
                                                   "network", "temporarily",
                                                   "unavailable", "ratelimit")):
            return FailureKind.TRANSIENT
        if any(token in name.lower() for token in ("permission", "denied",
                                                   "unauthorized", "invalid",
                                                   "syntax", "keyerror",
                                                   "notfound", "integrity")):
            return FailureKind.PERMANENT
        return FailureKind.UNKNOWN

    def _escalate_failure(self, item: CognitiveWorkItem) -> None:
        """Persistent failure -> deeper investigation (never endless retries)."""
        asyncio.ensure_future(self.event_bus.publish(Event(
            event_type=EventType.REPEATED_FAILURE_DETECTED,
            payload={"task": item.work_type.value,
                     "last_error": item.last_error,
                     "attempts": item.attempts,
                     "source_work": item.work_id},
            source="cognitive_pulse", priority=90,
        ), dispatch_immediately=True))

    # -- handlers -----------------------------------------------------------

    async def _exec_goal_review(self, item: CognitiveWorkItem) -> None:
        """Goal field review: what currently matters most? Evidence-only;
        blocked/stale goals raise attention candidates (never auto-deleted)."""
        goals = self.runtime.objectives.list_active_objectives()
        if not goals:
            return
        blocked = [g for g in goals if getattr(g, "status", None) is not None
                   and g.status.value == "BLOCKED"]
        for goal in blocked:
            await self.event_bus.publish(Event(
                event_type=EventType.ATTENTION_CANDIDATE_CREATED,
                payload={"item_id": f"goal_review:{goal.objective_id}",
                         "topic": f"goal blocked: {goal.title}",
                         "priority": 0.9,
                         "goal_id": goal.objective_id,
                         "source": "cognitive_pulse"},
                source="cognitive_pulse", priority=50,
            ), dispatch_immediately=True)
        # Staleness: a long-unupdated active goal gets a low-priority review
        # candidate, not a fabricated problem.
        now = self.now()
        for goal in goals:
            updated = getattr(goal, "updated_at", None) or getattr(goal, "created_at", now)
            if now - float(updated) > 3600:
                self.store.record_cycle("GOAL_STALE",
                                        f"{goal.objective_id} not updated")

    async def _exec_attention_review(self, item: CognitiveWorkItem) -> None:
        """Reconsider deferred attention candidates. Re-selected items are
        published as ATTENTION_SELECTED so the runtime's existing Slice 2/3
        chain (question -> hypotheses -> planned experiments) continues on the
        single bus — the Pulse schedules, the engines execute."""
        decision = self.runtime.attention.reconsider_deferred()
        for selected in getattr(decision, "selected", []) or []:
            await self.event_bus.publish(Event(
                event_type=EventType.ATTENTION_SELECTED,
                payload={"item_id": selected.item_id,
                         "topic": selected.topic,
                         "priority": selected.priority,
                         "goal_id": getattr(selected, "goal_id", None),
                         "source": getattr(selected, "source", ""),
                         "question_id": (selected.payload or {}).get("question_id")},
                source="cognitive_pulse", priority=50,
            ), dispatch_immediately=True)
        for deferred in getattr(decision, "deferred", []) or []:
            # Still deferred: evidence retained, never lost.
            self.store.record_cycle("ATTENTION_DEFERRED", deferred.item_id)

    async def _exec_question_generation(self, item: CognitiveWorkItem) -> None:
        """Uncertainty/contradiction crossed thresholds -> QuestionGenesis via
        the existing bus path. The Pulse re-publishes the ORIGINAL trigger so
        the Slice 2 engine (not the Pulse) generates questions."""
        trigger = item.payload.get("payload", {})
        event_type_str = trigger.pop("_event_type", None)
        if event_type_str is None:
            return
        try:
            etype = EventType(event_type_str)
        except ValueError:
            return
        if etype not in (EventType.UNCERTAINTY_DETECTED,
                         EventType.CONTRADICTION_FOUND,
                         EventType.ANOMALY_DETECTED,
                         EventType.PREDICTION_ERROR,
                         EventType.GOAL_GAP_DETECTED,
                         EventType.CAPABILITY_GAP,
                         EventType.REPEATED_FAILURE_DETECTED):
            return
        await self.event_bus.publish(Event(
            event_type=etype,
            payload=dict(trigger),
            source="cognitive_pulse:question_gate",
            priority=60,
        ), dispatch_immediately=True)

    async def _exec_hypothesis_investigation(self, item: CognitiveWorkItem) -> None:
        """High-value question -> competing hypotheses (Slice 2 engine)."""
        qid = item.payload.get("payload", {}).get("question_id")
        if not qid:
            return
        q = self.runtime.question_store.get(qid)
        if q is None:
            return
        # Only investigate questions that won attention (Slice 1 gate).
        if getattr(q, "status", None) is not None and \
                getattr(q.status, "value", str(q.status)) not in (
                    "SELECTED", "INVESTIGATING"):
            return
        await self.event_bus.publish(Event(
            event_type=EventType.QUESTION_SELECTED,
            payload={"question_id": qid, "question": q.question},
            source="cognitive_pulse", priority=60,
        ), dispatch_immediately=True)

    async def _exec_experiment(self, item: CognitiveWorkItem) -> None:
        """Execute only APPROVED experiments (approval is the explicit gate;
        the Pulse never bypasses it)."""
        exp_id = item.payload.get("payload", {}).get("experiment_id")
        if not exp_id:
            return
        exp = self.runtime.experiment_store.get(exp_id)
        if exp is None:
            return
        if getattr(exp, "status", None) is not None and \
                getattr(exp.status, "value", str(exp.status)) != "APPROVED":
            # Not approved: defer, do not run.
            self.store.requeue(item.work_id, cooldown_s=30.0,
                               error="experiment not approved")
            return
        await self.runtime.run_experiment(exp_id)

    async def _exec_belief_update(self, item: CognitiveWorkItem) -> None:
        """Reality feedback: a completed experiment updates hypotheses/beliefs
        through the real engine. Simulated results never become reality."""
        qid = item.payload.get("payload", {}).get("question_id")
        if not qid:
            return
        self.runtime.reality_experiments.evaluate_question(qid)
        # Meaningful outcomes (hypothesis supported/contradicted) schedule
        # experience distillation.
        for hyp in self.runtime.hypothesis_store.list():
            if hyp.question_id != qid:
                continue
            if getattr(hyp.status, "value", str(hyp.status)) in (
                    "SUPPORTED", "CONTRADICTED"):
                await self._schedule(WorkType.EXPERIENCE_DISTILLATION,
                                     priority=0.6,
                                     reason="belief updated by evidence",
                                     payload={"question_id": qid})
                break

    async def _exec_experience_distillation(self, item: CognitiveWorkItem) -> None:
        """Distill meaningful episodes (importance/failure/novelty gates)."""
        eid = item.payload.get("payload", {}).get("episode_id")
        if not eid:
            return
        episode = self.runtime.episode_store.get(eid)
        if episode is None:
            return
        if getattr(episode, "status", None) is not None and \
                getattr(episode.status, "value", str(episode.status)) != "COMPLETED":
            return
        # Gate: only distill meaningful episodes, not trivial ones.
        importance = float(getattr(episode, "importance", 0.0) or 0.0)
        has_failures = bool(getattr(episode, "failures", None))
        if importance < 0.4 and not has_failures:
            return  # trivial episode: no distillation
        produced = self.runtime.experience_distillation.distill_episode(episode)
        for item_out in produced:
            await self.event_bus.publish(Event(
                event_type=EventType.EXPERIENCE_DISTILLED,
                payload={"item_id": item_out.id,
                         "type": item_out.type.value,
                         "episode_id": eid},
                source="cognitive_pulse", priority=40,
            ), dispatch_immediately=True)

    async def _exec_failure_analysis(self, item: CognitiveWorkItem) -> None:
        """Repeated failures -> deeper investigation instead of repeating the
        same strategy. Escalation happens via REPEATED_FAILURE_DETECTED
        (already on the bus) -> attention -> question path."""
        payload = item.payload.get("payload", {})
        occurrences = int(item.payload.get("occurrences", 1))
        if occurrences >= self._repeated_failure_threshold:
            await self.event_bus.publish(Event(
                event_type=EventType.ATTENTION_CANDIDATE_CREATED,
                payload={"item_id": f"failure_analysis:{item.work_id}",
                         "topic": f"persistent failure: {payload.get('task', '')}",
                         "priority": 0.85,
                         "source": "cognitive_pulse"},
                source="cognitive_pulse", priority=50,
            ), dispatch_immediately=True)

    async def _exec_capability_health(self, item: CognitiveWorkItem) -> None:
        """Capability health scan (Slice 5 registry) — monitoring only. The
        Pulse never generates or modifies capabilities outside Slice 5 gates."""
        registry = self.runtime.capability_registry
        if hasattr(registry, "list"):
            for cap in registry.list():
                health = getattr(cap, "health", None)
                if health is not None and \
                        getattr(health, "value", str(health)) == "DEGRADED":
                    await self.event_bus.publish(Event(
                        event_type=EventType.CAPABILITY_DEGRADED,
                        payload={"capability_id": getattr(cap, "capability_id", ""),
                                 "health": str(health)},
                        source="cognitive_pulse", priority=40,
                    ), dispatch_immediately=True)

    async def _exec_bottleneck_analysis(self, item: CognitiveWorkItem) -> None:
        """Evidence-backed bottleneck scan (Slice 7 detector). detect() only
        returns NEW evidence-backed reports and persists them itself; the Pulse
        surfaces each on the bus so the Slice 7 improvement path can pick it up."""
        reports = self.runtime.bottleneck_detector.detect()
        for report in reports:
            await self.event_bus.publish(Event(
                event_type=EventType.BOTTLENECK_DETECTED,
                payload={"report_id": report.id,
                         "bottleneck_type": report.type,
                         "component": report.affected_component,
                         "confidence": report.confidence,
                         "evidence": report.evidence},
                source="cognitive_pulse", priority=70,
            ), dispatch_immediately=True)

    async def _exec_improvement_evaluation(self, item: CognitiveWorkItem) -> None:
        """Self-improvement is ONLY scheduled here; the Slice 7 gate decides.
        The Pulse never approves, promotes or mutates anything."""
        gate = self.runtime.self_modification_gate
        proposals = self.runtime.proposal_store.list()
        for proposal in proposals:
            if getattr(proposal, "status", None) is not None and \
                    getattr(proposal.status, "value", str(proposal.status)) == "PROPOSED":
                await self.event_bus.publish(Event(
                    event_type=EventType.IMPROVEMENT_PROPOSED,
                    payload={"proposal_id": proposal.proposal_id,
                             "target_component": proposal.target_component,
                             "risk": getattr(proposal.risk, "value",
                                             str(proposal.risk))},
                    source="cognitive_pulse", priority=60,
                ), dispatch_immediately=True)
        # Genome health is monitored read-only; the Pulse never mutates it.
        current = self.runtime.genome_manager.current()
        self.store.record_cycle("GENOME_HEALTH",
                                f"v{current.version} {current.status.value}")

    async def _exec_memory_maintenance(self, item: CognitiveWorkItem) -> None:
        """Lightweight store hygiene — no destructive cleanup without policy."""
        self.store.record_cycle("MEMORY_MAINTENANCE", "periodic hygiene")

    async def _exec_stale_task_scan(self, item: CognitiveWorkItem) -> None:
        """Unfinished-work detection (rule: detect unfinished work). Evidence
        only: queued work past the configurable staleness threshold is surfaced
        as UNFINISHED_TASK_DETECTED with its real age/attempts; nothing is
        silently dropped or completed."""
        now = self.now()
        threshold = float(self.config.get("stale_task_threshold_s", 300.0))
        found = 0
        for w in self.store.list_work(WorkStatus.QUEUED):
            age = now - float(w.scheduled_at or w.created_at)
            if age < threshold:
                continue
            found += 1
            await self.event_bus.publish(Event(
                event_type=EventType.UNFINISHED_TASK_DETECTED,
                payload={"work_id": w.work_id,
                         "work_type": w.work_type.value,
                         "age_s": round(age, 1),
                         "attempts": w.attempts,
                         "scheduled_at": w.scheduled_at},
                source="cognitive_pulse", priority=50,
            ), dispatch_immediately=True)
        self.store.record_cycle("STALE_SCAN",
                                f"{found} unfinished task(s)")

    async def _exec_environment_health(self, item: CognitiveWorkItem) -> None:
        """Environment health from REAL samples. Feeds the existing resource
        governor (perception -> budgets -> RESOURCE_WARNING) — the Pulse never
        invents CPU/RAM numbers. With no sampler available it records
        INSUFFICIENT_DATA instead of fabricating a healthy report."""
        sampler = getattr(self.runtime, "resources", None)
        if sampler is None or not hasattr(sampler, "sample"):
            self.store.record_cycle(
                "ENV_HEALTH", "no resource sampler (INSUFFICIENT_DATA)")
            return
        try:
            snap = sampler.sample()
        except Exception as exc:  # noqa: BLE001 — health must never crash
            self.store.record_cycle(
                "ENV_HEALTH", f"sampler failed ({type(exc).__name__}): "
                              f"INSUFFICIENT_DATA")
            return
        if snap is None:
            self.store.record_cycle(
                "ENV_HEALTH", "sampler returned no data (INSUFFICIENT_DATA)")
            return
        ingest = getattr(self.runtime, "ingest_perception", None)
        if callable(ingest):
            await ingest(cpu_percent=float(snap.cpu_percent),
                         memory_mb=float(snap.memory_total_mb),
                         compute_tier=str(getattr(snap, "compute_tier", "UNKNOWN")),
                         source="cognitive_pulse:env_health")
        self.store.record_cycle(
            "ENV_HEALTH",
            f"cpu={snap.cpu_percent:.1f}% mem_avail="
            f"{getattr(snap, 'memory_available_mb', 0.0):.0f}MB "
            f"tier={getattr(snap, 'compute_tier', 'UNKNOWN')}")

    async def _exec_deep_cycle(self, item: CognitiveWorkItem) -> None:
        """Budgeted deep review: goals, unresolved questions, repeated failures,
        capability health, bottlenecks, telemetry, long-term priorities.
        Everything here is evidence-only — the engines decide; the Pulse only
        records what it actually finds (never fabricated)."""
        await self._exec_goal_review(item)
        await self._exec_attention_review(item)
        await self._exec_capability_health(item)
        await self._exec_bottleneck_analysis(item)
        # Unresolved questions: surface the count; attention review above
        # already reconsiders deferred candidates through the Slice 1 field.
        qs = self.runtime.question_store.list_unresolved()
        if qs:
            self.store.record_cycle("DEEP_QUESTIONS",
                                    f"{len(qs)} unresolved")
        # Repeated failures from the pulse's own failure ledger (bounded view).
        for w in self.store.list_work(WorkStatus.FAILED)[:5]:
            self.store.record_cycle(
                "DEEP_FAILURES",
                f"{w.work_type.value} attempts={w.attempts}")
        # Architectural telemetry summary — INSUFFICIENT_DATA is reported as
        # such by telemetry itself; never invented.
        try:
            snap = self.runtime.architecture_telemetry.snapshot()
            self.store.record_cycle("DEEP_TELEMETRY",
                                    f"{len(snap)} component(s) measured")
        except Exception as exc:  # noqa: BLE001 — deep cycle must never crash
            self.store.record_cycle("DEEP_TELEMETRY",
                                    f"unavailable ({type(exc).__name__})")
        self.store.record_cycle("DEEP_CYCLE", "scheduled deep review")

    # --- health & status ----------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Honest health snapshot: never reports READY without evidence."""
        queued = len(self.store.list_work(WorkStatus.QUEUED))
        running = len(self._active_work)
        failed = len(self.store.list_work(WorkStatus.FAILED))
        deferred = len(self.store.list_work(WorkStatus.DEFERRED))
        hour = time.strftime("%Y%m%d%H")
        day = time.strftime("%Y%m%d")
        return {
            "running": self.state in (PulseLifecycle.RUNNING,
                                      PulseLifecycle.DEGRADED),
            "paused": self.state == PulseLifecycle.PAUSED,
            "degraded": self.state == PulseLifecycle.DEGRADED,
            "stopped": self.state == PulseLifecycle.STOPPED,
            "state": self.state.value,
            "degraded_reason": self.degraded_reason,
            "last_cycle": self._last_cycle,
            "last_success": self._last_success,
            "queue_size": queued,
            "active_work": running,
            "failed_work": failed,
            "deferred_work": deferred,
            "idle": self._idle,
            "idle_since": self._idle_since,
            "budget_usage": {
                "cpu_units": self.store.budget_usage("cpu_units", hour),
                "api_cost": self.store.budget_usage("api_cost", day),
                "network_requests": self.store.budget_usage("network_requests", hour),
                "model_inference_ms": self.store.budget_usage(
                    "model_inference_ms", hour),
            },
            "next_scheduled_cycle": self._next_scheduled_cycle,
            "provider_available": self._provider_available(),
            "provider_required_deferred": sum(
                1 for w in self.store.list_work(WorkStatus.DEFERRED)
                if (w.payload or {}).get("defer_reason") in (
                    "no provider available",)),
            "voice_events_seen": self._voice_events_seen,
        }

    def set_degraded(self, reason: str = "") -> None:
        self.state = PulseLifecycle.DEGRADED
        self.degraded_reason = reason
        self.store.record_cycle("DEGRADED", reason)
        asyncio.ensure_future(self.event_bus.publish(Event(
            event_type=EventType.PULSE_DEGRADED,
            payload={"reason": reason, "state": self.state.value},
            source="cognitive_pulse", priority=90,
        ), dispatch_immediately=True))
        self._save_state()

    def set_online(self) -> None:
        if self.state == PulseLifecycle.DEGRADED:
            self.state = PulseLifecycle.RUNNING
            self.degraded_reason = ""
            self.store.record_cycle("RECOVERED", "pulse healthy again")
            self._save_state()
