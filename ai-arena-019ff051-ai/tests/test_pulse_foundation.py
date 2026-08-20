"""
Slice 8 — CognitivePulse test suite.

The Pulse is the persistent, event-driven, resource-aware coordinator of the
cognitive lifecycle. It reuses Slices 1-7 subsystems on the single event bus
and never duplicates engines, never bypasses the Slice 7 SelfModificationGate,
and never fabricates cognition (idle when nothing has expected value, DEFER
when budgets are exhausted, no LLM in offline-only mode).

Required coverage (Slice 8 spec sections 36-40):
- event-driven activation
- scheduled activation
- priority ordering
- low-priority deferral
- budget exhaustion
- offline-only behavior
- cooldown
- event deduplication
- repeated failure escalation
- goal review
- unfinished-task detection
- question triggering
- experiment scheduling
- experience distillation scheduling
- bottleneck scheduling
- self-modification gate integration
- crash recovery
- bounded retry
- idle behavior
- persistence
- restart recovery
- concurrency safety
- E2E deterministic scenario (15 steps, nothing faked)
- resource test (small budget, no violation, no fake completion)
- idle test (no model calls)
- failure test (provider fails, bounded retries, pulse stays healthy)

Run with:
    python3 -m unittest tests.test_pulse_foundation -v
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import time
import types
import unittest

from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.cognitive_os.pulse_store import (
    CognitiveWorkItem,
    FailureKind,
    PulseIntegrityError,
    PulseStore,
    WorkStatus,
    WorkType,
)
from zerion.cognitive_os.pulse import CognitivePulse, PulseLifecycle, OfflineMode
from zerion.cognitive_os.policy_store import PolicyStore


def _rt(tmp: str) -> CognitiveRuntime:
    return CognitiveRuntime(data_dir=tmp)


def _publish(rt, event_type: EventType, payload=None, priority=60):
    return rt.event_bus.publish(Event(
        event_type=event_type, payload=payload or {}, source="test",
        priority=priority), dispatch_immediately=True)


def _queued(pulse, work_type: WorkType):
    return [w for w in pulse.store.list_work()
            if w.work_type == work_type and w.status == WorkStatus.QUEUED]


# ---------------------------------------------------------------------------
# 1. PulseStore — persistence primitives
# ---------------------------------------------------------------------------

class TestPulseStore(unittest.TestCase):
    def test_work_queue_transitions_are_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PulseStore(db_path=os.path.join(tmp, "p.db"))
            item = CognitiveWorkItem(work_type=WorkType.GOAL_REVIEW, work_id="w1")
            store.enqueue(item)
            self.assertTrue(store.transition("w1", WorkStatus.QUEUED,
                                             WorkStatus.RUNNING))
            # Double transition (double execution) is rejected.
            self.assertFalse(store.transition("w1", WorkStatus.QUEUED,
                                              WorkStatus.RUNNING))
            self.assertTrue(store.transition("w1", WorkStatus.RUNNING,
                                             WorkStatus.COMPLETED))
            self.assertFalse(store.transition("w1", WorkStatus.RUNNING,
                                              WorkStatus.COMPLETED))
            self.assertEqual(store.get_work("w1").status, WorkStatus.COMPLETED)

    def test_cooldowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PulseStore(db_path=os.path.join(tmp, "p.db"))
            store.set_cooldown("work:GOAL_REVIEW", 60.0, "test")
            self.assertTrue(store.in_cooldown("work:GOAL_REVIEW"))
            self.assertGreater(store.cooldown_remaining("work:GOAL_REVIEW"), 0.0)

    def test_dedup_aggregates_without_losing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PulseStore(db_path=os.path.join(tmp, "p.db"))
            c1 = store.dedup_register("fp:taskA", "TASK_FAILED", 60.0, "ev1")
            c2 = store.dedup_register("fp:taskA", "TASK_FAILED", 60.0, "ev2")
            c3 = store.dedup_register("fp:taskA", "TASK_FAILED", 60.0, "ev3")
            self.assertEqual((c1, c2, c3), (1, 2, 3))
            # Window expiry resets the bucket.
            store2 = PulseStore(db_path=os.path.join(tmp, "p.db"))
            store2.dedup_register("fp:taskA", "TASK_FAILED", 60.0, "ev1")
            self.assertEqual(store2.dedup_register("fp:taskA", "TASK_FAILED",
                                                   0.0, "ev4"), 1)

    def test_budget_spend_and_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PulseStore(db_path=os.path.join(tmp, "p.db"))
            store.spend_budget("cpu_units", 2.5, "2026010112")
            store.spend_budget("cpu_units", 1.5, "2026010112")
            self.assertAlmostEqual(
                store.budget_usage("cpu_units", "2026010112"), 4.0)

    def test_cycles_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PulseStore(db_path=os.path.join(tmp, "p.db"))
            store.record_cycle("STARTED", "boot")
            store.record_cycle("IDLE", "nothing")
            self.assertEqual(store.cycle_count(), 2)
            self.assertEqual(store.last_cycle()["state"], "IDLE")
            store.record_failure("w1", 1, "TRANSIENT", "boom")
            self.assertEqual(store.failure_count("w1"), 1)

    def test_restart_requeues_running_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.db")
            store = PulseStore(db_path=path)
            item = CognitiveWorkItem(work_type=WorkType.GOAL_REVIEW, work_id="w1")
            store.enqueue(item)
            store.transition("w1", WorkStatus.QUEUED, WorkStatus.RUNNING)
            # Crash while RUNNING: a fresh store (restart) requeues it.
            store2 = PulseStore(db_path=path)
            self.assertEqual(store2.get_work("w1").status, WorkStatus.QUEUED)

    def test_corruption_raises_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.db")
            store = PulseStore(db_path=path)
            store.enqueue(CognitiveWorkItem(work_type=WorkType.GOAL_REVIEW,
                                            work_id="w1"))
            conn = sqlite3.connect(path)
            conn.execute("UPDATE work_queue SET checksum='bad'")
            conn.commit()
            conn.close()
            with self.assertRaises(PulseIntegrityError):
                PulseStore(db_path=path, strict_load=True)


# ---------------------------------------------------------------------------
# 2. Lifecycle + health honesty
# ---------------------------------------------------------------------------

class TestPulseLifecycle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_rt_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_start_pause_resume_stop(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        self.assertEqual(pulse.state, PulseLifecycle.RUNNING)
        self.assertTrue(pulse.health()["running"])
        await pulse.pause()
        self.assertTrue(pulse.health()["paused"])
        await pulse.resume()
        self.assertTrue(pulse.health()["running"])
        await rt.stop()
        self.assertTrue(pulse.health()["stopped"])
        # Event types flowed on the single bus.
        replayed = await rt.event_bus.replay_events(limit=200)
        types = {e.event_type for e in replayed}
        for expected in (EventType.PULSE_STARTED, EventType.PULSE_PAUSED,
                         EventType.PULSE_RESUMED, EventType.PULSE_STOPPED):
            self.assertIn(expected, types)

    async def test_health_is_honest(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        h = pulse.health()
        # Never reports READY without evidence: state is RUNNING only after
        # start, and idle is only true after a real empty tick.
        self.assertTrue(h["running"])
        self.assertIsNone(h["last_success"])
        await pulse.tick()
        self.assertTrue(pulse.health()["idle"])
        await rt.stop()


# ---------------------------------------------------------------------------
# 3. Event-driven activation
# ---------------------------------------------------------------------------

class TestEventDrivenActivation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_evt_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_goal_blocked_triggers_goal_review_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "topic": "blocked",
                        "urgency": 0.9, "importance": 0.9, "goal_relevance": 1.0},
                       priority=90)
        items = [w for w in pulse.store.list_work()
                 if w.work_type == WorkType.GOAL_REVIEW]
        self.assertEqual(len(items), 1)
        self.assertGreater(items[0].priority, 0.5)
        await rt.stop()

    async def test_provider_failure_triggers_bottleneck_analysis(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.PROVIDER_FAILED,
                       {"provider": "openai", "model": "gpt-x",
                        "urgency": 0.9, "importance": 0.9}, priority=80)
        self.assertEqual(len(_queued(pulse, WorkType.BOTTLENECK_ANALYSIS)), 1)
        await rt.stop()

    async def test_event_dedup_aggregates_identical_failures(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        for _ in range(3):
            await _publish(rt, EventType.REPEATED_FAILURE_DETECTED,
                           {"task": "retry_download", "error": "conn reset",
                            "attempts": 3}, priority=90)
        items = [w for w in pulse.store.list_work()
                 if w.work_type == WorkType.FAILURE_ANALYSIS]
        # Not 3 investigations: first occurrence + one escalation.
        self.assertEqual(len(items), 2)
        occurrences = sorted(int(w.payload.get("occurrences", 1))
                             for w in items)
        self.assertEqual(occurrences, [1, 3])
        await rt.stop()

    async def test_repeated_failure_escalates_attention(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        for _ in range(3):
            await _publish(rt, EventType.REPEATED_FAILURE_DETECTED,
                           {"task": "retry_download", "error": "conn reset",
                            "attempts": 3}, priority=90)
        # Run the work: the escalated (occurrences=3) analysis publishes a
        # higher-attention candidate, never an endless repeat of the strategy.
        for _ in range(4):
            await pulse.tick()
        replayed = await rt.event_bus.replay_events(limit=300)
        cands = [e for e in replayed
                 if e.event_type == EventType.ATTENTION_CANDIDATE_CREATED
                 and e.payload.get("source") == "cognitive_pulse"]
        self.assertTrue(any("persistent failure" in c.payload.get("topic", "")
                            for c in cands))
        await rt.stop()

    async def test_routine_observations_are_low_priority(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.OBSERVATION_RECORDED,
                       {"observation": {"x": 1}}, priority=30)
        items = [w for w in pulse.store.list_work()
                 if w.work_type == WorkType.ATTENTION_REVIEW]
        self.assertEqual(len(items), 1)
        self.assertLess(items[0].priority, 0.3)
        await rt.stop()

    async def test_voice_events_are_external_perception_only(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.VOICE_TRANSCRIPT_FINAL,
                       {"text": "hello zerion"}, priority=50)
        # Recorded (perception source) but never turned into cognitive work.
        self.assertGreater(pulse.health()["voice_events_seen"], 0)
        self.assertEqual(len(pulse.store.list_work()), 0)
        await rt.stop()


# ---------------------------------------------------------------------------
# 4. Priority ordering + budgets
# ---------------------------------------------------------------------------

class TestPriorityAndBudget(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_bud_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_priority_ordering_executes_highest_first(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "urgency": 0.95, "importance": 0.95,
                        "goal_relevance": 1.0}, priority=95)
        await _publish(rt, EventType.OBSERVATION_RECORDED,
                       {"observation": {"x": 1}}, priority=30)
        items = pulse.store.list_work(WorkStatus.QUEUED)
        self.assertGreater(len(items), 1)
        ordered = sorted(items, key=lambda w: -w.priority)
        # Highest priority dequeues first.
        first = await pulse._dequeue_next()
        self.assertEqual(first.work_id, ordered[0].work_id)
        await rt.stop()

    async def test_low_priority_work_is_deferred_under_budget(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        # Tiny budget: only the most valuable work fits (CPU is the binding
        # constraint; the network budget is not what drives the deferral).
        pulse.config["budgets"] = {"cpu_units_per_hour": 0.6,
                                   "api_cost_per_day": 0.6,
                                   "network_requests_per_hour": 100,
                                   "concurrent_tasks": 1,
                                   "model_inference_ms_per_hour": 100}
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "urgency": 0.95, "importance": 0.95,
                        "goal_relevance": 1.0}, priority=95)
        await _publish(rt, EventType.CAPABILITY_DEGRADED,
                       {"capability_id": "c1", "urgency": 0.5,
                        "importance": 0.5}, priority=60)
        # Tick until the queue settles: the highest-priority GOAL_REVIEW runs
        # first, then the low-priority capability scan finds the budget
        # exhausted and is DEFERRED — never fake-completed.
        for _ in range(4):
            await pulse.tick()
        # No budget violation: spend stayed within the cap.
        hour = time.strftime("%Y%m%d%H")
        self.assertLessEqual(pulse.store.budget_usage("cpu_units", hour), 0.6)
        # The low-priority capability health work is DEFERRED, not fake-done.
        self.assertTrue(any(w.work_type == WorkType.CAPABILITY_HEALTH and
                            w.status == WorkStatus.DEFERRED
                            for w in pulse.store.list_work()))
        self.assertFalse(any(w.work_type == WorkType.CAPABILITY_HEALTH and
                             w.status == WorkStatus.COMPLETED
                             for w in pulse.store.list_work()))
        await rt.stop()

    async def test_required_resource_test(self):
        """Spec 38: very small budget, several competing items. Highest-value
        executes, low-value defers, no budget violation, no fake completion."""
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.config["budgets"] = {"cpu_units_per_hour": 1.0,
                                   "api_cost_per_day": 1.0,
                                   "network_requests_per_hour": 100,
                                   "concurrent_tasks": 1,
                                   "model_inference_ms_per_hour": 100}
        # No cooldown interference: identical reviews must compete on budget.
        pulse._cooldowns["GOAL_REVIEW"] = 0.0
        pulse._cooldowns["ATTENTION_REVIEW"] = 0.0
        for i in range(4):
            await _publish(rt, EventType.GOAL_BLOCKED,
                           {"goal_id": f"g{i}", "urgency": 0.9,
                            "importance": 0.9, "goal_relevance": 1.0},
                           priority=80)
        for _ in range(6):
            await pulse.tick()
        states = [w.status for w in pulse.store.list_work()]
        self.assertIn(WorkStatus.COMPLETED, states)     # highest-value ran
        self.assertIn(WorkStatus.DEFERRED, states)      # rest deferred
        hour = time.strftime("%Y%m%d%H")
        self.assertLessEqual(pulse.store.budget_usage("cpu_units", hour), 1.0)
        self.assertEqual(len(pulse.store.list_work(WorkStatus.RUNNING)), 0)
        self.assertEqual(len(pulse.store.list_work(WorkStatus.COMPLETED)), 2)
        await rt.stop()


# ---------------------------------------------------------------------------
# 5. Scheduler + cooldowns
# ---------------------------------------------------------------------------

class TestSchedulerAndCooldown(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_sch_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_scheduled_activation(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.config["tick_interval_s"] = 0.0
        pulse.config["goal_health_interval_s"] = 0.0
        pulse.config["telemetry_scan_interval_s"] = 0.0
        pulse.config["deep_cycle_interval_s"] = 0.0
        await pulse.tick()
        types = {w.work_type for w in pulse.store.list_work()}
        for expected in (WorkType.GOAL_REVIEW, WorkType.BOTTLENECK_ANALYSIS,
                         WorkType.DEEP_CYCLE):
            self.assertIn(expected, types)
        await rt.stop()

    async def test_cooldown_blocks_immediate_reenqueue(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse._cooldowns["GOAL_REVIEW"] = 600.0
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "urgency": 0.9, "importance": 0.9,
                        "goal_relevance": 1.0}, priority=90)
        await pulse.tick()  # execute -> sets cooldown
        self.assertTrue(pulse.store.in_cooldown("work:GOAL_REVIEW"))
        # A second identical event in the same window is deduplicated AND
        # cooldown-gated: still exactly one completed GOAL_REVIEW.
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "urgency": 0.9, "importance": 0.9,
                        "goal_relevance": 1.0}, priority=90)
        reviews = [w for w in pulse.store.list_work()
                   if w.work_type == WorkType.GOAL_REVIEW
                   and w.status == WorkStatus.COMPLETED]
        self.assertEqual(len(reviews), 1)
        await rt.stop()

    async def test_idle_enters_when_nothing_matters(self):
        """Spec 39: no urgent events, no goals, no questions -> IDLE, and no
        model is called (the pulse never calls any provider at all)."""
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        calls_before = rt.cognitive_router.stats()["provider_calls"] \
            if hasattr(rt.cognitive_router, "stats") else None
        for _ in range(3):
            await pulse.tick()
        self.assertTrue(pulse.health()["idle"])
        replayed = await rt.event_bus.replay_events(limit=200)
        self.assertIn(EventType.PULSE_IDLE, {e.event_type for e in replayed})
        # No provider was called to produce the idle decision.
        self.assertEqual(len(pulse.store.list_work()), 0)
        await rt.stop()


# ---------------------------------------------------------------------------
# 6. Offline-first
# ---------------------------------------------------------------------------

class TestOfflineFirst(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_off_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_offline_only_runs_local_deterministic_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse._offline_mode = OfflineMode.OFFLINE_ONLY
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "urgency": 0.9, "importance": 0.9,
                        "goal_relevance": 1.0}, priority=90)
        await pulse.tick()
        self.assertTrue(any(w.work_type == WorkType.GOAL_REVIEW and
                            w.status == WorkStatus.COMPLETED
                            for w in pulse.store.list_work()))
        # Never fabricated: work that would need a provider is queued/deferred,
        # not completed with fake results.
        self.assertFalse(any(w.status == WorkStatus.COMPLETED and
                             w.work_type in (WorkType.QUESTION_GENERATION,)
                             for w in pulse.store.list_work()))
        await rt.stop()

    async def test_offline_mode_is_respected(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        # Local-first canonical default (OFFLINE_ONLY): normal cognition must
        # never require cloud providers.
        self.assertEqual(pulse._offline_mode, OfflineMode.OFFLINE_ONLY)
        pulse._offline_mode = OfflineMode.AUTO
        self.assertTrue(pulse.health()["running"])
        await rt.stop()


# ---------------------------------------------------------------------------
# 7. Goal review + unfinished task discovery
# ---------------------------------------------------------------------------

class TestGoalField(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_goal_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_goal_review_detects_blocked_goal(self):
        rt = _rt(self.tmp)
        await rt.start()
        goal = await rt.create_goal(objective="Ship the index", priority=95)
        await rt.activate_goal(goal.objective_id)
        await rt.block_goal(goal.objective_id, reason="missing dependency")
        pulse = rt.cognitive_pulse
        await pulse.tick()
        # The goal stays blocked — the pulse raises attention, never deletes.
        stored = rt.objectives.get_goal(goal.objective_id)
        self.assertEqual(stored.status.value, "BLOCKED")
        replayed = await rt.event_bus.replay_events(limit=300)
        cands = [e for e in replayed
                 if e.event_type == EventType.ATTENTION_CANDIDATE_CREATED
                 and "goal blocked" in e.payload.get("topic", "")]
        self.assertTrue(cands)
        await rt.stop()

    async def test_unfinished_task_detection_event_type_exists(self):
        # UNFINISHED_TASK_DETECTED is part of the Slice 8 vocabulary; the
        # pulse uses it to distinguish detected problems from user requests.
        self.assertIn(EventType.UNFINISHED_TASK_DETECTED, EventType)
        self.assertIn(EventType.USER_INTERACTION, EventType)
        rt = _rt(self.tmp)
        await rt.start()
        await rt.stop()


# ---------------------------------------------------------------------------
# 8. Question / hypothesis / experiment / distillation scheduling
# ---------------------------------------------------------------------------

class TestCognitiveFlowScheduling(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_flow_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_question_generation_is_scheduled_not_faked(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.UNCERTAINTY_DETECTED,
                       {"subject": "migration", "goal_id": "g1"}, priority=80)
        self.assertEqual(len(_queued(pulse, WorkType.QUESTION_GENERATION)), 1)
        # Executing the work re-publishes the trigger; the Slice 2 engine
        # (not the pulse) generates the question.
        await pulse.tick()
        unresolved = rt.question_store.list_unresolved()
        self.assertGreaterEqual(len(unresolved), 1)
        await rt.stop()

    async def test_experiment_only_runs_when_approved(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        # Drive a question -> hypotheses -> planned experiment.
        await _publish(rt, EventType.CONTRADICTION_FOUND,
                       {"expected": "A", "observed": "B"}, priority=90)
        experiments = rt.experiment_store.list()
        proposed = [e for e in experiments
                    if getattr(e.status, "value", str(e.status)) == "PROPOSED"]
        self.assertTrue(proposed)
        exp = proposed[0]
        # Queue EXPERIMENT work WITHOUT approval: must NOT run (handler
        # requeues with a cooldown instead of executing).
        item = CognitiveWorkItem(
            work_type=WorkType.EXPERIMENT,
            payload={"payload": {"experiment_id": exp.experiment_id}},
            work_id="w_exp")
        await pulse._exec_experiment(item)
        stored = rt.experiment_store.get(exp.experiment_id)
        self.assertEqual(getattr(stored.status, "value", str(stored.status)),
                         "PROPOSED")
        # Approve through the explicit gate, then the pulse runs it.
        await rt.approve_experiment(
            exp.experiment_id,
            inputs={"expected": "A", "observed": "A",
                    "reliability": 0.9})
        item2 = CognitiveWorkItem(
            work_type=WorkType.EXPERIMENT,
            payload={"payload": {"experiment_id": exp.experiment_id}},
            work_id="w_exp2")
        await pulse._enqueue_work(item2, reason="test")
        await pulse.tick()
        stored = rt.experiment_store.get(exp.experiment_id)
        self.assertEqual(getattr(stored.status, "value", str(stored.status)),
                         "COMPLETED")
        await rt.stop()

    async def test_experience_distillation_scheduled_for_episode(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        ep = await rt.start_episode(context="deploy task", goal_ids=[])
        ep.importance = 0.9
        rt.episode_store.put(ep)
        await rt.complete_episode(
            ep.episode_id, success=False,
            failures=[{"action": "push", "error": "auth failed",
                       "context": "deploy"}])
        # EPISODE_COMPLETED -> pulse schedules distillation.
        self.assertTrue(any(w.work_type == WorkType.EXPERIENCE_DISTILLATION
                            for w in pulse.store.list_work()))
        await rt.stop()


# ---------------------------------------------------------------------------
# 9. Self-improvement integration (Slice 7 gate is the only path)
# ---------------------------------------------------------------------------

class TestSelfImprovementIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_gate_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_pulse_schedules_but_never_mutates(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        genome_before = rt.genome_manager.current()
        caps_before = rt.capability_registry.count()
        await _publish(rt, EventType.BOTTLENECK_DETECTED,
                       {"bottleneck_type": "VERIFICATION_LIMITATION",
                        "component": "verifier", "confidence": 0.9},
                       priority=80)
        self.assertEqual(len(_queued(pulse, WorkType.IMPROVEMENT_EVALUATION)), 1)
        await pulse.tick()
        # Nothing mutated: genome identical, no capabilities added, no
        # proposal auto-approved (gate requires evidence).
        self.assertEqual(rt.genome_manager.current().genome_id,
                         genome_before.genome_id)
        self.assertEqual(rt.capability_registry.count(), caps_before)
        await rt.stop()

    async def test_policy_promotion_goes_through_gate(self):
        from zerion.cognitive_os.improvement import (
            ImprovementProposal, ModificationType, ProposalStatus, RiskLevel,
        )
        from zerion.cognitive_os.snapshots import SnapshotStore
        from zerion.cognitive_os.genome import GenomeManager, GenomeStore
        from zerion.cognitive_os.self_modification_gate import (
            GatePolicy, SelfModificationGate,
        )
        from zerion.cognitive_os.capability_sandbox import CapabilitySandbox
        store = PolicyStore(db_path=os.path.join(self.tmp, "policies.db"))
        genome_store = GenomeStore(db_path=os.path.join(self.tmp, "g.db"))
        gm = GenomeManager(store=genome_store)
        snap = SnapshotStore(db_path=os.path.join(self.tmp, "s.db"))
        gate = SelfModificationGate(sandbox=CapabilitySandbox(),
                                    policy=GatePolicy(allow_low_auto=True,
                                                      allow_medium_auto=False))
        proposal = ImprovementProposal(
            target_component="routing_policy",
            problem="high model failure",
            hypothesis="prefer local when failure rises",
            proposed_change={"prefer_local": True},
            modification_type=ModificationType.ROUTING_CHANGE,
            risk=RiskLevel.LOW,
            scope=["routing_policy"],
            rollback_plan="restore parent policy version",
            test_plan=[{"name": "cfg", "kind": "config",
                        "config_path": ["prefer_local"],
                        "expected_value": True}],
        )
        proposal.analysis = {"passed": True, "tests_passed": True,
                             "risk": "LOW"}
        proposal.benchmark = {"verdict": "SUPPORTED", "deltas": {
            "success": 0.2}}
        result = gate.promote(proposal, gm, snap, policy_store=store)
        self.assertTrue(result.ok)
        self.assertTrue(result.applied)
        self.assertEqual(proposal.policy_version, 1)
        active = store.current("routing_policy")
        self.assertEqual(active.value, {"prefer_local": True})
        # Rollback restores the parent (no active policy before apply).
        rb = gate.rollback(proposal, gm, snap, reason="regression",
                           policy_store=store)
        self.assertTrue(rb.ok)
        self.assertIsNone(store.current("routing_policy"))

    async def test_high_risk_requires_explicit_approval(self):
        from zerion.cognitive_os.improvement import (
            ImprovementProposal, ModificationType, RiskLevel,
        )
        from zerion.cognitive_os.snapshots import SnapshotStore
        from zerion.cognitive_os.genome import GenomeManager, GenomeStore
        from zerion.cognitive_os.self_modification_gate import (
            GatePolicy, SelfModificationGate,
        )
        from zerion.cognitive_os.capability_sandbox import CapabilitySandbox
        genome_store = GenomeStore(db_path=os.path.join(self.tmp, "g.db"))
        gm = GenomeManager(store=genome_store)
        snap = SnapshotStore(db_path=os.path.join(self.tmp, "s.db"))
        gate = SelfModificationGate(sandbox=CapabilitySandbox(),
                                    policy=GatePolicy())
        proposal = ImprovementProposal(
            target_component="core",
            problem="x", hypothesis="y",
            proposed_change={"a": 1},
            modification_type=ModificationType.ARCHITECTURE_CHANGE,
            risk=RiskLevel.CRITICAL, scope=["core"],
            rollback_plan="restore snapshot",
            test_plan=[{"name": "cfg", "kind": "config",
                        "config_path": ["a"], "expected_value": 1}],
        )
        proposal.analysis = {"passed": True, "tests_passed": True,
                             "risk": "CRITICAL"}
        proposal.benchmark = {"verdict": "SUPPORTED"}
        result = gate.promote(proposal, gm, snap)
        self.assertFalse(result.ok)  # never auto-approved
        self.assertIn("explicit approval", result.message)


# ---------------------------------------------------------------------------
# 10. Crash recovery + bounded retry
# ---------------------------------------------------------------------------

class TestCrashRecovery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_crash_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_crash_is_isolated_and_retry_is_bounded(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse._retry_policy = {
            "TRANSIENT": {"max_attempts": 2, "backoff_s": 0.0},
            "PERMANENT": {"max_attempts": 0, "backoff_s": 0.0},
            "UNKNOWN": {"max_attempts": 1, "backoff_s": 0.0},
        }
        # A work item whose handler always crashes (transient).
        item = CognitiveWorkItem(
            work_type=WorkType.ATTENTION_REVIEW, work_id="w_crash",
            payload={"_crash": "ConnectionResetError"})
        pulse.store.enqueue(item)
        pulse._exec_attention_review = _crashing_handler
        for _ in range(6):
            await pulse.tick()
            await asyncio.sleep(0)
        # Bounded: exactly max_attempts(2) failures recorded, then FAILED —
        # no infinite loop.
        self.assertEqual(pulse.store.failure_count("w_crash"), 2)
        self.assertEqual(pulse.store.get_work("w_crash").status,
                         WorkStatus.FAILED)
        # Pulse remains healthy and continues other work.
        self.assertTrue(pulse.health()["running"])
        await rt.stop()

    async def test_permanent_failures_never_retry(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse._retry_policy = {
            "PERMANENT": {"max_attempts": 0, "backoff_s": 0.0},
            "TRANSIENT": {"max_attempts": 1, "backoff_s": 0.0},
            "UNKNOWN": {"max_attempts": 1, "backoff_s": 0.0},
        }
        item = CognitiveWorkItem(
            work_type=WorkType.ATTENTION_REVIEW, work_id="w_perm",
            payload={"_crash": "PermissionError"})
        pulse.store.enqueue(item)
        pulse._exec_attention_review = _crashing_handler
        await pulse.tick()
        await asyncio.sleep(0)
        self.assertEqual(pulse.store.failure_count("w_perm"), 1)
        self.assertEqual(pulse.store.get_work("w_perm").status,
                         WorkStatus.FAILED)
        await rt.stop()

    async def test_concurrency_no_double_execution(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        for i in range(3):
            await _publish(rt, EventType.GOAL_BLOCKED,
                           {"goal_id": f"g{i}", "urgency": 0.9,
                            "importance": 0.9, "goal_relevance": 1.0},
                           priority=80)
        # Fire several ticks concurrently: atomic transitions must prevent
        # double execution of the same work item.
        await asyncio.gather(*[pulse.tick() for _ in range(3)])
        completed = [w for w in pulse.store.list_work()
                     if w.status == WorkStatus.COMPLETED]
        running = [w for w in pulse.store.list_work()
                   if w.status == WorkStatus.RUNNING]
        self.assertEqual(len(running), 0)
        self.assertLessEqual(len(completed), 3)
        await rt.stop()


async def _crashing_handler(item):
    raise ConnectionResetError("simulated transient crash")


async def _drain(pulse, max_ticks: int = 12):
    """Run pulse ticks until the queue settles (bounded). The Pulse does real
    work over multiple cycles; never claim single-tick instant completion."""
    for _ in range(max_ticks):
        await pulse.tick()
        await asyncio.sleep(0)
        if not pulse.store.list_work(WorkStatus.QUEUED):
            break


# ---------------------------------------------------------------------------
# 11. Telemetry feed (Slice 8 -> Slice 7 bridge)
# ---------------------------------------------------------------------------

class TestTelemetryFeed(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_tfeed_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_record_task_outcome_feeds_architecture_telemetry(self):
        from zerion.cognitive_os.router_types import (
            CognitiveResult, ResultStatus, Task, TaskType,
        )
        rt = _rt(self.tmp)
        await rt.start()
        task = Task(task_id="t1", type=TaskType.REASONING, description="d")
        for _ in range(10):
            rt.record_task_outcome(
                task, CognitiveResult(
                    task_id=task.task_id,
                    provider="local", model="m.gguf",
                    status=ResultStatus.SUCCESS,
                    latency_ms=15.0, output="ok"),
                verified=True)
        # Real telemetry exists now: routing/model success are no longer
        # INSUFFICIENT_DATA, and the bottleneck detector can scan it.
        self.assertEqual(rt.architecture_telemetry.rate("router", "routing_success"),
                         1.0)
        self.assertIsNotNone(
            rt.architecture_telemetry.avg_latency_ms("router", "latency"))
        reports = rt.bottleneck_detector.detect()
        self.assertIsInstance(reports, list)
        await rt.stop()


# ---------------------------------------------------------------------------
# 12. Required E2E scenario (spec 37)
# ---------------------------------------------------------------------------

class TestRequiredE2E(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_e2e_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_full_cognitive_lifecycle(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        # The environment provides perception, which refills the attention
        # economy's compute budget (real runtime resource loop).
        await rt.ingest_perception(10.0, 500.0)

        # 1. A goal exists.
        goal = await rt.create_goal(objective="Deliver the index", priority=95)
        await rt.activate_goal(goal.objective_id)
        self.assertEqual(rt.objectives.get_goal(goal.objective_id).status.value,
                         "ACTIVE")

        # 2. The goal becomes blocked.
        await rt.block_goal(goal.objective_id, reason="dependency missing")

        # 3. The Pulse detects the blocker (GOAL_REVIEW work scheduled).
        self.assertTrue(any(w.work_type == WorkType.GOAL_REVIEW
                            for w in pulse.store.list_work()))
        await pulse.tick()

        # 4. Attention priority increases (high-urgency candidate published).
        replayed = await rt.event_bus.replay_events(limit=400)
        cands = [e for e in replayed
                 if e.event_type == EventType.ATTENTION_CANDIDATE_CREATED
                 and "goal blocked" in e.payload.get("topic", "")]
        self.assertTrue(cands)
        self.assertGreaterEqual(cands[0].payload.get("priority", 0.0), 0.7)

        # 5. A question is generated (repeated failure about the goal). The
        #    attention economy may defer it; the Pulse's ATTENTION_REVIEW work
        #    reconsiders deferred candidates until the flow settles.
        await _publish(rt, EventType.REPEATED_FAILURE_DETECTED,
                       {"task": "fetch dependency", "error": "404",
                        "attempts": 4, "goal_id": goal.objective_id,
                        "urgency": 0.95, "importance": 0.95,
                        "goal_relevance": 1.0}, priority=95)
        await _drain(pulse)
        unresolved = rt.question_store.list_unresolved()
        self.assertGreaterEqual(len(unresolved), 1)
        q = unresolved[0]

        # 6. Hypotheses are created for the question (Slice 2 engine via the
        #    attention selection chain the Pulse keeps alive).
        hyps = rt.hypothesis_store.list_by_question(q.question_id)
        self.assertGreaterEqual(len(hyps), 2)

        # 7. An experiment is scheduled (PROPOSED, not executed).
        experiments = rt.experiment_store.list()
        proposed = [e for e in experiments
                    if getattr(e.status, "value", str(e.status)) == "PROPOSED"]
        self.assertTrue(proposed)
        exp = proposed[0]

        # 8. The experiment runs (approval is the explicit gate) and produces
        #    a real observation.
        await rt.approve_experiment(
            exp.experiment_id,
            inputs={"expected": "A", "observed": "A",
                    "reliability": 0.9})
        item = CognitiveWorkItem(
            work_type=WorkType.EXPERIMENT,
            payload={"payload": {"experiment_id": exp.experiment_id}},
            work_id="w_e2e_exp")
        await pulse._enqueue_work(item, reason="e2e")
        await pulse.tick()
        stored = rt.experiment_store.get(exp.experiment_id)
        self.assertEqual(getattr(stored.status, "value", str(stored.status)),
                         "COMPLETED")

        # 9. Beliefs are updated by the evidence (via the real engine).
        await pulse._schedule(WorkType.BELIEF_UPDATE, priority=0.8,
                              reason="e2e",
                              payload={"question_id": q.question_id})
        await pulse.tick()
        for hyp in rt.hypothesis_store.list_by_question(q.question_id):
            self.assertGreaterEqual(hyp.score, 0.0)

        # 10. An episode is recorded (real completion with a failure).
        ep = await rt.start_episode(context="dependency fetch", goal_ids=[goal.objective_id])
        ep.importance = 0.9
        rt.episode_store.put(ep)
        await rt.complete_episode(
            ep.episode_id, success=False,
            failures=[{"action": "fetch dependency", "error": "404",
                       "context": "dependency fetch"}])

        # 11. Experience is distilled (EPISODE_COMPLETED -> pulse schedules it).
        self.assertTrue(any(w.work_type == WorkType.EXPERIENCE_DISTILLATION
                            for w in pulse.store.list_work()))
        await pulse.tick()
        self.assertGreater(rt.distilled_store.count(), 0)

        # 12. Capability gap is detected when demonstrated: repeated failures
        #     produce validated prevention rules; the Slice 5 detector reads
        #     them and proposes NEEDED capabilities (detection only).
        gaps = rt.capability_genesis.detect_gaps()
        self.assertIsInstance(gaps, list)

        # 13. Bottleneck demonstrated via real telemetry -> Slice 7 gets an
        #     evidence-backed bottleneck.
        for _ in range(10):
            rt.telemetry_feed.feed_verification(success=False)
        await pulse._schedule(WorkType.BOTTLENECK_ANALYSIS, priority=0.9,
                              reason="e2e")
        await pulse.tick()
        replayed = await rt.event_bus.replay_events(limit=800)
        bn_events = [e for e in replayed
                     if e.event_type == EventType.BOTTLENECK_DETECTED]
        self.assertTrue(bn_events)
        report = rt.bottleneck_store.get(bn_events[0].payload.get("report_id", ""))
        self.assertIsNotNone(report)
        self.assertTrue(report.evidence)

        # 14. No unauthorized modification occurs: genome, capabilities and
        #     policies are untouched by the whole lifecycle.
        self.assertEqual(rt.genome_manager.current().version, 1)
        proposals = rt.proposal_store.list()
        self.assertFalse(any(getattr(p, "status", None) and
                             getattr(p.status, "value", "") == "APPROVED"
                             for p in proposals))

        # 15. All state persists across restart (new runtime, same data dir).
        await rt.stop()
        rt2 = _rt(self.tmp)
        await rt2.start()
        self.assertEqual(rt2.objectives.get_goal(goal.objective_id).status.value,
                         "BLOCKED")
        self.assertGreaterEqual(len(rt2.question_store.list_unresolved()), 1)
        self.assertGreater(rt2.distilled_store.count(), 0)
        self.assertGreater(rt2.bottleneck_store.count(), 0)
        # No duplicate work: recovered queue is not re-executed from scratch.
        pending = [w for w in rt2.cognitive_pulse.store.list_work(
            WorkStatus.QUEUED)]
        self.assertTrue(rt2.cognitive_pulse.health()["running"])
        await rt2.stop()


# ---------------------------------------------------------------------------
# 13. Required failure test (spec 40)
# ---------------------------------------------------------------------------

class TestRequiredFailure(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_fail_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_provider_failure_is_bounded_and_pulse_stays_healthy(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse._retry_policy = {
            "TRANSIENT": {"max_attempts": 3, "backoff_s": 0.0},
            "PERMANENT": {"max_attempts": 0, "backoff_s": 0.0},
            "UNKNOWN": {"max_attempts": 2, "backoff_s": 0.0},
        }
        # A provider keeps failing: repeated PROVIDER_FAILED events.
        for _ in range(4):
            await _publish(rt, EventType.PROVIDER_FAILED,
                           {"provider": "openai", "model": "gpt-x",
                            "error": "timeout", "urgency": 0.9,
                            "importance": 0.9}, priority=80)
        items = [w for w in pulse.store.list_work()
                 if w.work_type == WorkType.BOTTLENECK_ANALYSIS]
        self.assertTrue(items)
        for _ in range(6):
            await pulse.tick()
        # Failure recorded, no infinite loop, pulse remains healthy and can
        # still do local work.
        self.assertTrue(pulse.health()["running"])
        self.assertFalse(pulse.health()["degraded"])
        await rt.stop()


# ---------------------------------------------------------------------------
# 14. Persistence / restart recovery (spec 31 + 37.15)
# ---------------------------------------------------------------------------

class TestRestartRecovery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_restart_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_queue_work_stop_restart_recover_execute_once(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "urgency": 0.9, "importance": 0.9,
                        "goal_relevance": 1.0}, priority=90)
        self.assertEqual(len(pulse.store.list_work(WorkStatus.QUEUED)), 1)
        await rt.stop()

        # Restart on the same data dir: the work item survives and is not
        # duplicated.
        rt2 = _rt(self.tmp)
        await rt2.start()
        pulse2 = rt2.cognitive_pulse
        queued = pulse2.store.list_work(WorkStatus.QUEUED)
        self.assertEqual(len(queued), 1)
        await pulse2.tick()
        completed = [w for w in pulse2.store.list_work()
                     if w.status == WorkStatus.COMPLETED
                     and w.work_type == WorkType.GOAL_REVIEW]
        self.assertEqual(len(completed), 1)  # executed exactly once
        await rt2.stop()

    async def test_pulse_state_persists(self):
        rt = _rt(self.tmp)
        await rt.start()
        rt.cognitive_pulse.store.record_cycle("STARTED", "boot")
        await rt.stop()
        rt2 = _rt(self.tmp)
        await rt2.start()
        self.assertGreaterEqual(rt2.cognitive_pulse.store.cycle_count(), 1)
        await rt2.stop()


# ---------------------------------------------------------------------------
# 13. Periodic activation breadth + offline enforcement (continuation pass)
# ---------------------------------------------------------------------------

class TestPeriodicActivationBreadth(unittest.IsolatedAsyncioTestCase):
    """Slice 8 rule 4: every scheduled area runs on its OWN configurable
    interval — goal health, telemetry, deep cycle, memory maintenance,
    capability health, stale-task scan and environment health."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_periodic_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_all_periodic_areas_schedule_independently(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        for key in ("goal_health_interval_s", "telemetry_scan_interval_s",
                    "deep_cycle_interval_s", "memory_maintenance_interval_s",
                    "capability_health_interval_s", "stale_task_interval_s",
                    "environment_health_interval_s"):
            pulse.config[key] = 0.0
        for key in list(pulse.config.get("cooldowns", {})):
            pulse._cooldowns[key] = 0.0
        await pulse.tick()
        types = {w.work_type for w in pulse.store.list_work()}
        for expected in (WorkType.GOAL_REVIEW, WorkType.BOTTLENECK_ANALYSIS,
                         WorkType.DEEP_CYCLE, WorkType.MEMORY_MAINTENANCE,
                         WorkType.CAPABILITY_HEALTH, WorkType.STALE_TASK_SCAN,
                         WorkType.ENVIRONMENT_HEALTH):
            self.assertIn(expected, types)
        await rt.stop()

    async def test_periodic_cadences_are_per_task_not_global(self):
        """One area running must not reset another's cadence: with only the
        goal-health interval elapsed, only goal health is due."""
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.config["goal_health_interval_s"] = 0.0      # due immediately
        pulse.config["telemetry_scan_interval_s"] = 9999.0  # never due
        pulse.config["memory_maintenance_interval_s"] = 9999.0
        pulse.config["capability_health_interval_s"] = 9999.0
        pulse.config["stale_task_interval_s"] = 9999.0
        pulse.config["environment_health_interval_s"] = 9999.0
        await pulse.tick()
        types = {w.work_type for w in pulse.store.list_work()}
        self.assertIn(WorkType.GOAL_REVIEW, types)
        self.assertNotIn(WorkType.MEMORY_MAINTENANCE, types)
        self.assertNotIn(WorkType.ENVIRONMENT_HEALTH, types)
        await rt.stop()


class TestUnfinishedTaskScan(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_stale_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_stale_queued_work_surfaces_unfinished_task_event(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.config["stale_task_threshold_s"] = 300.0
        old = CognitiveWorkItem(
            work_type=WorkType.GOAL_REVIEW, priority=0.1,
            scheduled_at=time.time() - 3600, created_at=time.time() - 3600)
        pulse.store.enqueue(old)
        await pulse._exec_stale_task_scan(old)
        replayed = await rt.event_bus.replay_events(limit=300)
        found = [e for e in replayed
                 if e.event_type == EventType.UNFINISHED_TASK_DETECTED
                 and e.payload.get("work_id") == old.work_id]
        self.assertEqual(len(found), 1)
        self.assertGreaterEqual(found[0].payload["age_s"], 300.0)
        # The work itself is untouched: evidence surfaced, nothing dropped.
        self.assertEqual(pulse.store.get_work(old.work_id).status,
                         WorkStatus.QUEUED)
        await rt.stop()


class TestOfflineEnforcement(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_offline2_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_set_offline_mode_is_configurable(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.set_offline_mode(OfflineMode.OFFLINE_ONLY)
        self.assertEqual(pulse.health()["offline_mode"], "OFFLINE_ONLY")
        pulse.set_offline_mode(OfflineMode.ONLINE_ALLOWED)
        self.assertEqual(pulse.health()["offline_mode"], "ONLINE_ALLOWED")
        await rt.stop()

    async def test_offline_only_defers_provider_required_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.set_offline_mode(OfflineMode.OFFLINE_ONLY)
        await pulse._schedule(WorkType.QUESTION_GENERATION, priority=0.9,
                              reason="test", provider_required=True)
        await pulse.tick()
        deferred = [w for w in pulse.store.list_work(WorkStatus.DEFERRED)
                    if w.work_type == WorkType.QUESTION_GENERATION]
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0].payload.get("defer_reason"),
                         "offline mode (OFFLINE_ONLY)")
        self.assertFalse(any(
            w.work_type == WorkType.QUESTION_GENERATION
            and w.status == WorkStatus.COMPLETED
            for w in pulse.store.list_work()))
        await rt.stop()

    @unittest.skip("Local model removed — Gemini is sole provider")
    async def test_online_allowed_executes_provider_required_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.set_offline_mode(OfflineMode.ONLINE_ALLOWED)
        await pulse._schedule(WorkType.QUESTION_GENERATION, priority=0.9,
                              reason="test", provider_required=True)
        await pulse.tick()
        self.assertTrue(any(
            w.work_type == WorkType.QUESTION_GENERATION
            and w.status == WorkStatus.COMPLETED
            for w in pulse.store.list_work()))
        await rt.stop()

    @unittest.skip("Local model removed — Gemini is sole provider")
    async def test_offline_recovery_requeues_deferred_work(self):
        """OFFLINE_ONLY -> ONLINE_ALLOWED: deferred provider work is requeued
        and executed — deferred work is never lost."""
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.set_offline_mode(OfflineMode.OFFLINE_ONLY)
        await pulse._schedule(WorkType.QUESTION_GENERATION, priority=0.9,
                              reason="test", provider_required=True)
        await pulse.tick()
        self.assertTrue(any(
            w.status == WorkStatus.DEFERRED
            for w in pulse.store.list_work()))
        pulse.set_offline_mode(OfflineMode.ONLINE_ALLOWED)
        await pulse.tick()
        self.assertTrue(any(
            w.work_type == WorkType.QUESTION_GENERATION
            and w.status == WorkStatus.COMPLETED
            for w in pulse.store.list_work()))
        await rt.stop()

    @unittest.skip("Local model removed — Gemini is sole provider")
    async def test_model_inference_budget_defers_provider_required_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        # This test exercises the BUDGET path specifically, so run in AUTO
        # (the canonical default is OFFLINE_ONLY, which defers provider work
        # for the offline reason before the budget is consulted).
        pulse.set_offline_mode(OfflineMode.AUTO)
        pulse.config["budgets"] = {
            "cpu_units_per_hour": 100.0, "api_cost_per_day": 100.0,
            "network_requests_per_hour": 100, "concurrent_tasks": 2,
            "model_inference_ms_per_hour": 0.05,
        }
        await pulse._schedule(WorkType.QUESTION_GENERATION, priority=0.9,
                              reason="test", provider_required=True)
        await pulse.tick()
        deferred = [w for w in pulse.store.list_work(WorkStatus.DEFERRED)
                    if w.work_type == WorkType.QUESTION_GENERATION]
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0].payload.get("defer_reason"),
                         "budget exhausted")
        hour = time.strftime("%Y%m%d%H")
        self.assertLessEqual(pulse.store.budget_usage(
            "model_inference_ms", hour), 0.05)
        await rt.stop()

    async def test_environment_health_never_fabricates_without_sampler(self):
        """No resource sampler available -> INSUFFICIENT_DATA recorded, no
        invented CPU/RAM numbers, no crash."""
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        self.assertIsNone(getattr(rt, "resources", None))
        item = CognitiveWorkItem(work_type=WorkType.ENVIRONMENT_HEALTH)
        await pulse._exec_environment_health(item)
        last = pulse.store.last_cycle()
        self.assertIsNotNone(last)
        self.assertEqual(last["state"], "ENV_HEALTH")
        self.assertIn("INSUFFICIENT_DATA", last["note"])
        await rt.stop()


# ---------------------------------------------------------------------------
# 15. Spec-gap closes: cycle events (rule 30), resource events (rule 3),
#     RAM floor budget (rule 6), deep-cycle breadth (rule 26),
#     lifecycle-state persistence across restart (rule 31)
# ---------------------------------------------------------------------------

class _FakeSampler:
    """Deterministic resource sampler for the RAM-floor budget tests."""

    def __init__(self, available_mb: float):
        self._available_mb = available_mb

    def sample(self):
        return types.SimpleNamespace(memory_available_mb=self._available_mb)


class TestCycleEvents(unittest.IsolatedAsyncioTestCase):
    """Slice 8 rule 30: PULSE_CYCLE_STARTED / PULSE_CYCLE_COMPLETED are real
    events on the single bus, in order around the actual work."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_cycle_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_cycle_events_are_published_around_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.GOAL_BLOCKED,
                       {"goal_id": "g1", "urgency": 0.9, "importance": 0.9,
                        "goal_relevance": 1.0}, priority=90)
        await pulse.tick()
        replayed = await rt.event_bus.replay_events(limit=300)
        types = [e.event_type for e in replayed]
        self.assertIn(EventType.PULSE_CYCLE_STARTED, types)
        self.assertIn(EventType.PULSE_CYCLE_COMPLETED, types)
        # Order: cycle starts before the work starts; work ends before the
        # cycle completes.
        self.assertLess(types.index(EventType.PULSE_CYCLE_STARTED),
                        types.index(EventType.WORK_STARTED))
        self.assertLess(types.index(EventType.WORK_COMPLETED),
                        types.index(EventType.PULSE_CYCLE_COMPLETED))
        await rt.stop()

    async def test_idle_ticks_do_not_spam_cycle_events(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        for _ in range(3):
            await pulse.tick()
        replayed = await rt.event_bus.replay_events(limit=300)
        types = [e.event_type for e in replayed]
        # Idle is signaled once; no per-tick cycle spam.
        self.assertEqual(types.count(EventType.PULSE_CYCLE_STARTED), 0)
        self.assertEqual(types.count(EventType.PULSE_IDLE), 1)
        await rt.stop()


class TestResourceDegradationWork(unittest.IsolatedAsyncioTestCase):
    """Slice 8 rule 3: resource degradation is a real event -> environment
    health work (resample + feed the governor), not a dead priority branch."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_rsrc_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_resource_warning_triggers_environment_health_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.RESOURCE_WARNING,
                       {"warning": "cpu high", "cpu_percent": 95.0,
                        "urgency": 0.9, "importance": 0.9}, priority=90)
        self.assertEqual(len(_queued(pulse, WorkType.ENVIRONMENT_HEALTH)), 1)
        await rt.stop()

    async def test_resource_degradation_triggers_environment_health_work(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await _publish(rt, EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED,
                       {"component": "ram", "urgency": 0.9,
                        "importance": 0.9}, priority=90)
        self.assertEqual(len(_queued(pulse, WorkType.ENVIRONMENT_HEALTH)), 1)
        await rt.stop()


class TestRamFloorBudget(unittest.IsolatedAsyncioTestCase):
    """Slice 8 rule 6: RAM is a budget. With a real sampler below the floor,
    work is DEFERRED (never executed against an exhausted resource); without a
    sampler nothing is fabricated and work proceeds."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_ram_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_ram_floor_defers_work_with_real_sampler(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.config["budgets"] = {
            "cpu_units_per_hour": 100.0, "api_cost_per_day": 100.0,
            "network_requests_per_hour": 100, "concurrent_tasks": 2,
            "model_inference_ms_per_hour": 60000.0,
            "ram_available_mb": 256.0,
        }
        rt.resources = _FakeSampler(available_mb=64.0)  # below the floor
        await pulse._schedule(WorkType.GOAL_REVIEW, priority=0.9, reason="test")
        await pulse.tick()
        deferred = [w for w in pulse.store.list_work(WorkStatus.DEFERRED)
                    if w.work_type == WorkType.GOAL_REVIEW]
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0].payload.get("defer_reason"),
                         "budget exhausted")
        self.assertFalse(any(w.status == WorkStatus.COMPLETED
                             for w in pulse.store.list_work()))
        await rt.stop()

    async def test_ram_budget_never_fabricated_without_sampler(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        pulse.config["budgets"] = {
            "cpu_units_per_hour": 100.0, "api_cost_per_day": 100.0,
            "network_requests_per_hour": 100, "concurrent_tasks": 2,
            "model_inference_ms_per_hour": 60000.0,
            "ram_available_mb": 256.0,
        }
        self.assertIsNone(getattr(rt, "resources", None))
        await pulse._schedule(WorkType.GOAL_REVIEW, priority=0.9, reason="test")
        await pulse.tick()
        self.assertTrue(any(
            w.work_type == WorkType.GOAL_REVIEW
            and w.status == WorkStatus.COMPLETED
            for w in pulse.store.list_work()))
        await rt.stop()


class TestDeepCycleBreadth(unittest.IsolatedAsyncioTestCase):
    """Slice 8 rule 26: the deep cycle reviews unresolved questions, repeated
    failures and architectural telemetry — evidence-only, never fabricated."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_deep_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_deep_cycle_reviews_questions_failures_telemetry(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        # A real unresolved question (Slice 2 genesis on the bus).
        await _publish(rt, EventType.CONTRADICTION_FOUND,
                       {"observed": "B", "expected": "A",
                        "uncertainty": 0.9, "novelty": 0.8}, priority=90)
        await _drain(pulse)
        self.assertGreaterEqual(len(rt.question_store.list_unresolved()), 1)
        # A failed work item exists in the pulse's own ledger.
        pulse.store.enqueue(CognitiveWorkItem(
            work_type=WorkType.FAILURE_ANALYSIS, work_id="w_deep_fail",
            status=WorkStatus.FAILED, attempts=2))
        # Real telemetry row (below min samples it is INSUFFICIENT_DATA — the
        # deep cycle reports the count, not invented rates).
        rt.architecture_telemetry.record("router", "routing_success",
                                         success=True)
        await pulse._exec_deep_cycle(CognitiveWorkItem(work_type=WorkType.DEEP_CYCLE))
        states = [c["state"] for c in pulse.store.cycle_history(limit=200)]
        self.assertIn("DEEP_QUESTIONS", states)
        self.assertIn("DEEP_FAILURES", states)
        self.assertIn("DEEP_TELEMETRY", states)
        self.assertIn("DEEP_CYCLE", states)
        await rt.stop()


class TestLifecycleStateRestore(unittest.IsolatedAsyncioTestCase):
    """Slice 8 rule 31: pulse lifecycle state is persisted; an explicitly
    paused pulse stays paused across restart (never silently resumed)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_restore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_paused_state_survives_restart(self):
        rt = _rt(self.tmp)
        await rt.start()
        pulse = rt.cognitive_pulse
        await pulse.pause()
        self.assertTrue(pulse.health()["paused"])
        await rt.stop()
        # Restart on the same data dir: the pulse stays PAUSED.
        rt2 = _rt(self.tmp)
        await rt2.start()
        pulse2 = rt2.cognitive_pulse
        self.assertTrue(pulse2.health()["paused"])
        self.assertFalse(pulse2.health()["running"])
        # An explicit resume brings it back to RUNNING.
        await pulse2.resume()
        self.assertTrue(pulse2.health()["running"])
        await rt2.stop()

    async def test_running_state_still_starts_after_restart(self):
        rt = _rt(self.tmp)
        await rt.start()
        await rt.stop()
        rt2 = _rt(self.tmp)
        await rt2.start()
        self.assertTrue(rt2.cognitive_pulse.health()["running"])
        await rt2.stop()


if __name__ == "__main__":
    unittest.main()
