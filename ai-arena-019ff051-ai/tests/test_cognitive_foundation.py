"""
Slice 1 — Cognitive Foundation test suite.

Covers: Cognitive State, Cognitive Event Bus, Goal Field, Attention Economy,
resource awareness, persistence, runtime integration, the Slice 1 acceptance
scenario, and adversarial cases.

Run with:
    python3 -m unittest tests.test_cognitive_foundation -v
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from zerion.runtime.event_bus import AsyncEventBus, EventValidationError
from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.attention import (
    AttentionEconomy,
    AttentionFieldValidationError,
    AttentionItem,
    CognitivePriority,
)
from zerion.cognitive_os.objective_manager import (
    ContinuousObjective,
    GoalDependencyError,
    GoalTransitionError,
    ObjectiveContinuityManager,
    ObjectiveLifecycle,
    ObjectiveStoreIntegrityError,
)
from zerion.cognitive_os.state import (
    CognitiveState,
    RuntimeStatus,
    StateIntegrityError,
    StateStore,
    StateVersionError,
)
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime

from zerion.engine import AscendantEngine


# ---------------------------------------------------------------------------
# 1. COGNITIVE STATE
# ---------------------------------------------------------------------------

class TestCognitiveState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice1_state_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_state(self):
        s = CognitiveState()
        self.assertEqual(s.schema_version, CognitiveState.STATE_SCHEMA_VERSION)
        self.assertEqual(s.runtime_status, RuntimeStatus.INITIALIZING)
        self.assertEqual(s.goals.total, 0)
        self.assertEqual(s.attention.selected_count, 0)
        self.assertIsNotNone(s.state_id)

    def test_serialize_deserialize_roundtrip(self):
        s = CognitiveState()
        s.runtime_status = RuntimeStatus.RUNNING
        s.perception.cpu_percent = 42.0
        s.perception.compute_tier = "BALANCED"
        s.current_focus = "some focus"
        s.attention.selected_count = 3
        s.goals.active = 2
        s.pending_events = 1
        s.stale_events_discarded = 5
        d = s.to_dict()
        s2 = CognitiveState.from_dict(d)
        self.assertEqual(s2.runtime_status, RuntimeStatus.RUNNING)
        self.assertEqual(s2.perception.cpu_percent, 42.0)
        self.assertEqual(s2.perception.compute_tier, "BALANCED")
        self.assertEqual(s2.current_focus, "some focus")
        self.assertEqual(s2.attention.selected_count, 3)
        self.assertEqual(s2.goals.active, 2)
        self.assertEqual(s2.pending_events, 1)
        self.assertEqual(s2.stale_events_discarded, 5)
        self.assertEqual(s2.state_id, s.state_id)

    def test_version_validation_rejects_unknown_version(self):
        s = CognitiveState()
        d = s.to_dict()
        d["schema_version"] = 2
        with self.assertRaises(StateVersionError):
            CognitiveState.from_dict(d)
        d["schema_version"] = 0
        with self.assertRaises(StateVersionError):
            CognitiveState.from_dict(d)

    def test_state_persistence_roundtrip(self):
        db = os.path.join(self.tmp, "state.db")
        s = CognitiveState()
        s.runtime_status = RuntimeStatus.RUNNING
        s.perception.cpu_percent = 33.3
        s.current_focus = "persisted focus"
        s.attention.selected_count = 7
        store1 = StateStore(db_path=db)
        store1.put(s)
        store1.close()

        store2 = StateStore(db_path=db)
        loaded = store2.load()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.perception.cpu_percent, 33.3)
        self.assertEqual(loaded.current_focus, "persisted focus")
        self.assertEqual(loaded.attention.selected_count, 7)
        store2.close()

    def test_state_persistence_missing_row_returns_none(self):
        db = os.path.join(self.tmp, "fresh.db")
        store = StateStore(db_path=db)
        self.assertFalse(store.exists())
        self.assertIsNone(store.load())
        store.close()

    def test_state_persistence_corrupted_checksum_raises(self):
        db = os.path.join(self.tmp, "state.db")
        store = StateStore(db_path=db)
        store.put(CognitiveState())
        store.close()

        # Simulate a partial/corrupted write: tamper with the payload after commit.
        conn = sqlite3.connect(db)
        conn.execute("UPDATE cognitive_state SET payload = ? WHERE schema_version = 1",
                     (json.dumps({"schema_version": 1, "corrupted": True}),))
        conn.commit()
        conn.close()

        store2 = StateStore(db_path=db)
        with self.assertRaises(StateIntegrityError):
            store2.load()
        store2.close()

    def test_state_persistence_malformed_json_raises(self):
        db = os.path.join(self.tmp, "state.db")
        store = StateStore(db_path=db)
        store.put(CognitiveState())
        store.close()

        conn = sqlite3.connect(db)
        # Valid checksum computed over garbage payload: simulates a DB row written by a
        # different/corrupt writer whose JSON is not parseable.
        payload = "{not valid json"
        import hashlib
        checksum = hashlib.sha256(payload.encode()).hexdigest()
        conn.execute(
            "UPDATE cognitive_state SET payload = ?, checksum = ? WHERE schema_version = 1",
            (payload, checksum))
        conn.commit()
        conn.close()

        store2 = StateStore(db_path=db)
        with self.assertRaises(StateIntegrityError):
            store2.load()
        store2.close()


# ---------------------------------------------------------------------------
# 2. COGNITIVE EVENT BUS
# ---------------------------------------------------------------------------

class TestCognitiveEventBus(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice1_bus_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _event(self, etype, priority=50, payload=None, event_id=None, timestamp=None):
        return Event(event_type=etype, priority=priority,
                     payload=payload if payload is not None else {},
                     event_id=event_id or f"evt_{time.time_ns()}_{id(etype)}",
                     timestamp=timestamp or datetime.now(timezone.utc).isoformat())

    async def test_publish_subscribe_exact_type(self):
        bus = AsyncEventBus()
        received = []
        bus.subscribe(EventType.PERCEPTION_RECEIVED, lambda e: received.append(e.event_type))
        ev = self._event(EventType.PERCEPTION_RECEIVED)
        await bus.publish(ev, dispatch_immediately=True)
        self.assertEqual(received, [EventType.PERCEPTION_RECEIVED])

    async def test_subscribe_all_wildcard(self):
        bus = AsyncEventBus()
        received = []
        bus.subscribe_all(lambda e: received.append(e.event_type))
        await bus.publish(self._event(EventType.GOAL_CREATED), dispatch_immediately=True)
        await bus.publish(self._event(EventType.RESOURCE_WARNING), dispatch_immediately=True)
        self.assertEqual(received, [EventType.GOAL_CREATED, EventType.RESOURCE_WARNING])

    async def test_multiple_subscribers_all_receive(self):
        bus = AsyncEventBus()
        seen = []
        bus.subscribe(EventType.TASK_STARTED, lambda e: seen.append("a"))
        bus.subscribe(EventType.TASK_STARTED, lambda e: seen.append("b"))
        await bus.publish(self._event(EventType.TASK_STARTED), dispatch_immediately=True)
        self.assertEqual(sorted(seen), ["a", "b"])

    async def test_unsubscribe(self):
        bus = AsyncEventBus()
        seen = []

        def handler(e):
            seen.append(e.event_id)

        bus.subscribe(EventType.TASK_FAILED, handler)
        ev = self._event(EventType.TASK_FAILED, event_id="evt1")
        await bus.publish(ev, dispatch_immediately=True)
        bus.unsubscribe(EventType.TASK_FAILED, handler)
        await bus.publish(self._event(EventType.TASK_FAILED, event_id="evt2"), dispatch_immediately=True)
        self.assertEqual(seen, ["evt1"])

    async def test_ordering_priority_desc(self):
        bus = AsyncEventBus()
        order = []
        bus.subscribe_all(lambda e: order.append(e.payload["tag"]))
        await bus.publish(self._event(EventType.PERCEPTION_RECEIVED, priority=30, payload={"tag": "low"}))
        await bus.publish(self._event(EventType.RESOURCE_WARNING, priority=90, payload={"tag": "high"}))
        await bus.publish(self._event(EventType.GOAL_CREATED, priority=60, payload={"tag": "mid"}))
        await bus.drain_now()
        self.assertEqual(order, ["high", "mid", "low"])

    async def test_ordering_fifo_within_same_priority(self):
        bus = AsyncEventBus()
        order = []
        bus.subscribe_all(lambda e: order.append(e.payload["tag"]))
        for tag in ("a", "b", "c"):
            await bus.publish(self._event(EventType.GOAL_UPDATED, priority=50, payload={"tag": tag}))
        await bus.drain_now()
        self.assertEqual(order, ["a", "b", "c"])

    async def test_sequence_assignment_is_monotonic(self):
        bus = AsyncEventBus()
        seqs = []
        bus.subscribe_all(lambda e: seqs.append(e.sequence))
        for _ in range(3):
            await bus.publish(self._event(EventType.PERCEPTION_RECEIVED))
        await bus.drain_now()
        self.assertEqual(seqs, [1, 2, 3])

    async def test_deterministic_behavior(self):
        async def run():
            bus = AsyncEventBus()
            order = []
            bus.subscribe_all(lambda e: order.append((e.priority, e.payload["tag"])))
            for prio, tag in ((50, "x"), (90, "y"), (50, "z"), (10, "w")):
                await bus.publish(self._event(EventType.GOAL_UPDATED, priority=prio, payload={"tag": tag}))
            await bus.drain_now()
            return order
        self.assertEqual(await run(), await run())

    async def test_invalid_event_unknown_type_rejected(self):
        bus = AsyncEventBus()
        bad = Event(event_type="NOT_A_REAL_TYPE")
        with self.assertRaises(EventValidationError):
            await bus.publish(bad, dispatch_immediately=True)

    async def test_invalid_event_malformed_payload_rejected(self):
        bus = AsyncEventBus()
        bad = Event(event_type=EventType.GOAL_CREATED, payload="not a dict")
        with self.assertRaises(EventValidationError):
            await bus.publish(bad, dispatch_immediately=True)

    async def test_invalid_event_priority_out_of_range(self):
        bus = AsyncEventBus()
        with self.assertRaises(EventValidationError):
            await bus.publish(self._event(EventType.PERCEPTION_RECEIVED, priority=101), dispatch_immediately=True)
        with self.assertRaises(EventValidationError):
            await bus.publish(self._event(EventType.PERCEPTION_RECEIVED, priority=-1), dispatch_immediately=True)

    async def test_duplicate_event_id_rejected(self):
        bus = AsyncEventBus()
        ev = self._event(EventType.GOAL_CREATED, event_id="dup-1")
        await bus.publish(ev, dispatch_immediately=True)
        with self.assertRaises(EventValidationError):
            await bus.publish(Event(event_type=EventType.GOAL_CREATED, event_id="dup-1",
                                    payload={}), dispatch_immediately=True)

    async def test_persistence_replay(self):
        db = os.path.join(self.tmp, "events.db")
        bus = AsyncEventBus(db_path=db)
        await bus.publish(self._event(EventType.PERCEPTION_RECEIVED, priority=60))
        await bus.publish(self._event(EventType.RESOURCE_WARNING, priority=90))
        replayed = await bus.replay_events(limit=10)
        self.assertEqual(len(replayed), 2)
        self.assertEqual([r.event_type for r in replayed],
                         [EventType.PERCEPTION_RECEIVED, EventType.RESOURCE_WARNING])
        self.assertEqual([r.sequence for r in replayed], [1, 2])
        await bus.stop()

    async def test_pending_count_tracks_queued_events(self):
        bus = AsyncEventBus()
        await bus.publish(self._event(EventType.GOAL_CREATED))
        await bus.publish(self._event(EventType.GOAL_UPDATED))
        self.assertEqual(bus.pending_count, 2)
        await bus.drain_now()
        self.assertEqual(bus.pending_count, 0)

    async def test_voice_events_publishable_deterministically(self):
        """The VOICE_* vocabulary is first-class on the bus (future consumption)."""
        bus = AsyncEventBus()
        received = []
        bus.subscribe_all(lambda e: received.append(e.event_type))
        voice_types = [
            EventType.VOICE_STARTED,
            EventType.VOICE_TRANSCRIPT_PARTIAL,
            EventType.VOICE_TRANSCRIPT_FINAL,
            EventType.VOICE_INTERRUPTED,
            EventType.VOICE_ENDED,
        ]
        for vt in voice_types:
            await bus.publish(self._event(vt), dispatch_immediately=True)
        self.assertEqual(received, voice_types)

    async def test_system_resource_degradation_detected_publishable(self):
        bus = AsyncEventBus()
        received = []
        bus.subscribe(EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED,
                      lambda e: received.append(e.payload["cpu_percent"]))
        await bus.publish(self._event(EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED,
                                      payload={"cpu_percent": 97.2}),
                          dispatch_immediately=True)
        self.assertEqual(received, [97.2])


# ---------------------------------------------------------------------------
# 3. GOAL FIELD
# ---------------------------------------------------------------------------

class TestGoalField(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice1_goals_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mgr(self, db=None):
        return ObjectiveContinuityManager(db_path=db or os.path.join(self.tmp, "goals.db"),
                                          strict_load=True)

    def test_create_goal(self):
        mgr = self._mgr()
        g = mgr.create_goal(objective="Build a durable memory index", purpose="Long-horizon capability",
                            priority=90, next_action="Design schema")
        self.assertEqual(g.status, ObjectiveLifecycle.PROPOSED)
        self.assertEqual(g.purpose, "Long-horizon capability")
        self.assertTrue(g.objective_id.startswith("goal_"))
        self.assertEqual(mgr.list_goals(), [g])
        self.assertEqual(mgr.count_goals()["PROPOSED"], 1)

    def test_update_goal_progress_with_evidence(self):
        mgr = self._mgr()
        g = mgr.create_goal(objective="Ship the index")
        mgr.activate(g.objective_id)
        g = mgr.set_progress(g.objective_id, 0.5, note="phase 1 done", evidence="evt-1")
        self.assertEqual(g.progress, 0.5)
        self.assertEqual(len(g.progress_evidence), 1)
        self.assertEqual(g.progress_evidence[0]["evidence"], "evt-1")
        self.assertTrue(any(t["field"] == "progress" for t in g.trajectory))

    def test_priority_ordering(self):
        mgr = self._mgr()
        low = mgr.create_goal(objective="low", priority=20)
        high = mgr.create_goal(objective="high", priority=95)
        mid = mgr.create_goal(objective="mid", priority=50)
        self.assertEqual([g.objective_id for g in mgr.list_goals()],
                         [high.objective_id, mid.objective_id, low.objective_id])

    def test_dependencies_gate_activation(self):
        mgr = self._mgr()
        dep = mgr.create_goal(objective="prerequisite")
        goal = mgr.create_goal(objective="dependent", dependencies=[dep.objective_id])
        with self.assertRaises(GoalDependencyError):
            mgr.activate(goal.objective_id)
        mgr.activate(dep.objective_id)
        mgr.complete(dep.objective_id)
        activated = mgr.activate(goal.objective_id)
        self.assertEqual(activated.status, ObjectiveLifecycle.ACTIVE)

    def test_blockers_and_unblock(self):
        mgr = self._mgr()
        g = mgr.create_goal(objective="deploy")
        mgr.activate(g.objective_id)
        g = mgr.block(g.objective_id, "network partition")
        self.assertEqual(g.status, ObjectiveLifecycle.BLOCKED)
        self.assertEqual(len(g.blockers), 1)
        self.assertEqual(g.blocked_reason, "network partition")
        g = mgr.unblock(g.objective_id)
        self.assertEqual(g.status, ObjectiveLifecycle.ACTIVE)
        self.assertEqual(g.blockers, [])

    def test_completion_and_abandonment(self):
        mgr = self._mgr()
        g = mgr.create_goal(objective="finish")
        mgr.activate(g.objective_id)
        g = mgr.set_progress(g.objective_id, 1.0)
        self.assertEqual(g.status, ObjectiveLifecycle.COMPLETED)
        self.assertFalse(g.is_active)
        self.assertEqual(g.progress, 1.0)
        g2 = mgr.create_goal(objective="drop this")
        g2 = mgr.abandon(g2.objective_id, "no longer relevant")
        self.assertEqual(g2.status, ObjectiveLifecycle.ABANDONED)

    def test_impossible_goal_transitions_rejected(self):
        mgr = self._mgr()
        g = mgr.create_goal(objective="x")
        mgr.activate(g.objective_id)
        mgr.complete(g.objective_id)
        with self.assertRaises(GoalTransitionError):
            mgr.set_status(g.objective_id, ObjectiveLifecycle.ACTIVE)
        with self.assertRaises(GoalTransitionError):
            mgr.set_status(g.objective_id, ObjectiveLifecycle.PROPOSED)

        g2 = mgr.create_goal(objective="y")
        mgr.activate(g2.objective_id)
        mgr.abandon(g2.objective_id)
        with self.assertRaises(GoalTransitionError):
            mgr.set_status(g2.objective_id, ObjectiveLifecycle.PAUSED)

        g3 = mgr.create_goal(objective="z")
        mgr.activate(g3.objective_id)
        mgr.pause(g3.objective_id)
        with self.assertRaises(GoalTransitionError):
            mgr.set_status(g3.objective_id, ObjectiveLifecycle.PROPOSED)

    def test_invalid_priorities_rejected(self):
        mgr = self._mgr()
        with self.assertRaises(ValueError):
            mgr.create_goal(objective="bad", priority=150)
        with self.assertRaises(ValueError):
            mgr.create_goal(objective="bad", priority=-3)
        with self.assertRaises(ValueError):
            mgr.register_objective(ContinuousObjective(objective_id="legacy", title="t", priority=101))

    def test_invalid_progress_rejected(self):
        mgr = self._mgr()
        g = mgr.create_goal(objective="p")
        with self.assertRaises(ValueError):
            mgr.set_progress(g.objective_id, 1.5)

    def test_persistence_across_restart(self):
        db = os.path.join(self.tmp, "goals.db")
        mgr1 = self._mgr(db)
        g = mgr1.create_goal(objective="Durable goal", priority=80)
        mgr1.activate(g.objective_id)
        mgr1.set_progress(g.objective_id, 0.4, note="phase 1")

        # Simulate restart
        mgr2 = self._mgr(db)
        g2 = mgr2.get_goal(g.objective_id)
        self.assertIsNotNone(g2)
        self.assertEqual(g2.status, ObjectiveLifecycle.ACTIVE)
        self.assertEqual(g2.progress, 0.4)
        self.assertEqual(len(g2.progress_evidence), 1)
        self.assertGreaterEqual(len(g2.trajectory), 3)

        # Change progress, restart again
        mgr2.set_progress(g.objective_id, 0.8, note="phase 2")
        mgr3 = self._mgr(db)
        g3 = mgr3.get_goal(g.objective_id)
        self.assertEqual(g3.progress, 0.8)
        self.assertEqual(len(g3.progress_evidence), 2)
        self.assertGreaterEqual(len(g3.trajectory), 4)
        self.assertEqual(g3.history, g2.history)  # nothing lost

    def test_corrupt_store_strict_load_raises(self):
        db = os.path.join(self.tmp, "goals.db")
        mgr1 = self._mgr(db)
        mgr1.create_goal(objective="keep me")
        # Corrupt the persisted row
        conn = sqlite3.connect(db)
        conn.execute("UPDATE continuous_objectives SET data_json = ? WHERE objective_id LIKE 'goal_%'",
                     ('{"broken',))
        conn.commit()
        conn.close()
        with self.assertRaises(ObjectiveStoreIntegrityError):
            self._mgr(db)

    def test_corrupt_store_non_strict_is_not_silent(self):
        db = os.path.join(self.tmp, "goals.db")
        mgr1 = self._mgr(db)
        mgr1.create_goal(objective="keep me")
        conn = sqlite3.connect(db)
        conn.execute("UPDATE continuous_objectives SET data_json = ?", ('not json at all',))
        conn.commit()
        conn.close()

        mgr2 = ObjectiveContinuityManager(db_path=db, strict_load=False)
        self.assertEqual(mgr2.list_goals(), [])
        self.assertTrue(len(mgr2.load_errors) >= 1)  # recorded, not silent


# ---------------------------------------------------------------------------
# 4. ATTENTION ECONOMY
# ---------------------------------------------------------------------------

class TestAttentionEconomy(unittest.TestCase):
    def _item(self, urgency=0.5, importance=0.5, uncertainty=0.5, novelty=0.5,
              goal_relevance=0.5, gain=0.5, utility=0.5, risk=0.1, cost=0.5,
              api_cost=0.0, latency=0.0, topic="candidate"):
        return AttentionItem(
            topic=topic, urgency=urgency, importance=importance,
            uncertainty=uncertainty, novelty=novelty,
            objective_relevance=goal_relevance,
            expected_information_gain=gain, expected_utility=utility,
            risk=risk, resource_cost=cost, api_cost=api_cost,
            estimated_latency_ms=latency,
        )

    def test_candidate_creation_and_scoring(self):
        economy = AttentionEconomy()
        item = self._item(topic="resource check")
        economy.submit(item)
        self.assertIsNotNone(item.priority)
        self.assertGreater(item.priority, 0.0)
        self.assertEqual(economy.pending_candidates, 1)

    def test_scoring_is_deterministic(self):
        scorer = CognitivePriority()
        a = self._item()
        b = self._item()
        self.assertEqual(scorer.score(a), scorer.score(b))

    def test_scoring_exact_value(self):
        scorer = CognitivePriority()
        item = AttentionItem(urgency=0.5, importance=0.5, uncertainty=0.5, novelty=0.5,
                             objective_relevance=0.5, expected_information_gain=0.5,
                             expected_utility=0.5, risk=0.1, resource_cost=0.5)
        # positive = 0.5 * sum(weights) = 0.5 ; negative = 0.15*0.5 + 0.15*0.1 = 0.09
        self.assertAlmostEqual(scorer.score(item), 0.41, places=6)

    def test_priority_is_not_just_importance(self):
        scorer = CognitivePriority()
        importance_only = self._item(importance=1.0, urgency=0.0, goal_relevance=0.0,
                                     gain=0.0, utility=0.0, novelty=0.0, uncertainty=0.0,
                                     cost=0.0, risk=0.0)
        balanced = self._item(importance=0.5, urgency=1.0, goal_relevance=1.0,
                              utility=1.0, gain=0.0, novelty=0.0, uncertainty=0.0,
                              cost=0.0, risk=0.0)
        s1 = scorer.score(importance_only)
        s2 = scorer.score(balanced)
        self.assertNotEqual(s1, importance_only.importance)
        self.assertGreater(s2, s1)  # urgency + relevance + utility beat raw importance

    def test_goal_relevance_impact(self):
        economy = AttentionEconomy()
        low = economy.submit(self._item(goal_relevance=0.0))
        high = economy.submit(self._item(goal_relevance=1.0))
        self.assertGreater(high.priority, low.priority)

    def test_uncertainty_impact(self):
        economy = AttentionEconomy()
        low = economy.submit(self._item(uncertainty=0.0))
        high = economy.submit(self._item(uncertainty=1.0))
        self.assertGreater(high.priority, low.priority)

    def test_resource_cost_impact(self):
        economy = AttentionEconomy()
        cheap = economy.submit(self._item(cost=0.1))
        expensive = economy.submit(self._item(cost=0.9))
        self.assertGreater(cheap.priority, expensive.priority)

    def test_risk_impact(self):
        economy = AttentionEconomy()
        safe = economy.submit(self._item(risk=0.0))
        risky = economy.submit(self._item(risk=0.9))
        self.assertGreater(safe.priority, risky.priority)

    def test_priority_ordering_in_evaluate(self):
        economy = AttentionEconomy()
        economy.submit(self._item(urgency=0.9, importance=0.9, goal_relevance=0.9, topic="top"))
        economy.submit(self._item(urgency=0.2, importance=0.2, goal_relevance=0.2, topic="mid"))
        decision = economy.evaluate()
        priorities = [i.priority for i in decision.selected]
        self.assertEqual(priorities, sorted(priorities, reverse=True))
        self.assertEqual(decision.selected[0].topic, "top")

    def test_select_defer_discard(self):
        economy = AttentionEconomy()
        economy.submit(self._item(urgency=0.7, importance=0.7, goal_relevance=0.7,
                                  gain=0.7, utility=0.7, novelty=0.7, uncertainty=0.7,
                                  topic="select"))  # score 0.61 -> select
        economy.submit(self._item(urgency=0.4, importance=0.4, goal_relevance=0.4,
                                  gain=0.4, utility=0.4, novelty=0.4, uncertainty=0.4,
                                  topic="defer"))   # score 0.31 -> defer
        economy.submit(self._item(urgency=0.1, importance=0.1, goal_relevance=0.1,
                                  gain=0.1, utility=0.1, novelty=0.1, uncertainty=0.1,
                                  topic="discard"))  # score 0.01 -> discard
        decision = economy.evaluate()
        self.assertEqual([i.topic for i in decision.selected], ["select"])
        self.assertEqual([i.topic for i in decision.deferred], ["defer"])
        self.assertEqual([i.topic for i in decision.discarded], ["discard"])
        deferred_item = decision.deferred[0]
        discarded_item = decision.discarded[0]
        self.assertEqual(decision.reasons[deferred_item.item_id], "below_select_threshold")
        self.assertEqual(decision.reasons[discarded_item.item_id], "below_discard_threshold")

    def test_budget_blocks_selection(self):
        economy = AttentionEconomy()
        economy.set_budget(compute_units=0.2)
        item = economy.submit(self._item(urgency=0.9, importance=0.9, goal_relevance=0.9,
                                         gain=0.9, utility=0.9, novelty=0.9, uncertainty=0.9,
                                         cost=0.5, topic="too expensive"))
        decision = economy.evaluate()
        self.assertEqual([i.topic for i in decision.selected], [])
        self.assertEqual([i.topic for i in decision.deferred], ["too expensive"])
        self.assertEqual(decision.reasons[item.item_id], "insufficient_resource_budget")

    def test_budget_deducted_on_selection(self):
        economy = AttentionEconomy()
        economy.set_budget(compute_units=1.0, max_concurrent=1)
        economy.submit(self._item(urgency=0.7, importance=0.7, goal_relevance=0.7,
                                  gain=0.7, utility=0.7, novelty=0.7, uncertainty=0.7,
                                  cost=0.4, topic="a"))
        economy.evaluate()
        self.assertLess(economy.budget.compute_units, 1.0)
        self.assertEqual(economy.budget.concurrent_workload, 1)

    def test_negative_budget_rejected(self):
        economy = AttentionEconomy()
        with self.assertRaises(AttentionFieldValidationError):
            economy.set_budget(compute_units=-1.0)
        with self.assertRaises(AttentionFieldValidationError):
            economy.set_budget(api_calls=-5.0)
        with self.assertRaises(AttentionFieldValidationError):
            economy.set_budget(latency_ms=-1.0)

    def test_invalid_candidate_fields_rejected(self):
        scorer = CognitivePriority()
        with self.assertRaises(AttentionFieldValidationError):
            scorer.score(self._item(importance=2.0))
        with self.assertRaises(AttentionFieldValidationError):
            scorer.score(self._item(risk=-0.5))
        with self.assertRaises(AttentionFieldValidationError):
            scorer.score(self._item(cost=-1.0))

    def test_weights_configurable_and_inspectable(self):
        default = CognitivePriority()
        custom = CognitivePriority(weights={"importance": 0.5})
        item = self._item(importance=0.9, urgency=0.0, goal_relevance=0.0, gain=0.0,
                          utility=0.0, novelty=0.0, uncertainty=0.0, cost=0.0, risk=0.0)
        s_default = default.score(item)
        s_custom = custom.score(item)
        self.assertGreater(s_custom, s_default)
        explanation = custom.explain(item)
        self.assertIn("weights", explanation)
        self.assertIn("positive_contributions", explanation)
        self.assertIn("negative_contributions", explanation)
        self.assertAlmostEqual(
            sum(explanation["positive_contributions"].values())
            - sum(explanation["negative_contributions"].values()),
            explanation["score"], places=6)


# ---------------------------------------------------------------------------
# 5. RUNTIME INTEGRATION
# ---------------------------------------------------------------------------

class TestCognitiveRuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice1_rt_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_acceptance_resource_degradation_flow(self):
        """The Slice 1 acceptance scenario, entirely without an LLM."""
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()

        # A competing low-value candidate (what Zerion decides NOT to process).
        rt.attention.submit_candidate_fields(topic="background log rotation", urgency=0.1,
                                             importance=0.1, goal_relevance=0.1,
                                             expected_information_gain=0.1, expected_utility=0.1,
                                             novelty=0.1, uncertainty=0.1, risk=0.1,
                                             resource_cost=0.5)

        await rt.ingest_perception(cpu_percent=95.0, memory_mb=512.0,
                                   compute_tier="DEGRADED", source="resource_governor")

        # Event became an attention candidate, was evaluated, and selected.
        self.assertGreaterEqual(rt.attention.stats()["selected_count"], 2)
        self.assertGreaterEqual(rt.attention.stats()["discarded_count"], 1)  # the low-value one
        self.assertTrue(rt.state.current_focus)  # a candidate won focus
        self.assertIn("degradation", rt.state.current_focus.lower())
        # Runtime state was updated and the event is observable by the runtime.
        self.assertEqual(rt.state.perception.cpu_percent, 95.0)
        self.assertEqual(rt.state.last_event.event_type, EventType.ATTENTION_SELECTED.value)
        # The bus carries the whole trail.
        replayed = await rt.event_bus.replay_events(limit=100)
        types = [e.event_type for e in replayed]
        self.assertIn(EventType.PERCEPTION_RECEIVED, types)
        self.assertIn(EventType.RESOURCE_WARNING, types)
        self.assertIn(EventType.ATTENTION_CANDIDATE_CREATED, types)
        self.assertIn(EventType.ATTENTION_SELECTED, types)
        self.assertIn(EventType.ATTENTION_DISCARDED, types)
        await rt.stop()

    async def test_event_creates_attention_candidate(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        await rt.event_bus.publish(Event(
            event_type=EventType.PERCEPTION_RECEIVED,
            payload={"cpu_percent": 95.0, "memory_mb": 100.0, "compute_tier": "DEGRADED",
                     "source": "sensor", "attention_metrics": {"urgency": 1.0}},
            source="sensor", priority=60,
        ), dispatch_immediately=True)
        self.assertEqual(rt.attention.stats()["selected_count"], 1)
        self.assertEqual(rt.state.last_event.event_type, EventType.ATTENTION_SELECTED.value)
        await rt.stop()

    async def test_acceptance_system_resource_degradation_detected_flow(self):
        """Required demo: SYSTEM_RESOURCE_DEGRADATION_DETECTED -> EventBus ->
        AttentionCandidate -> CognitivePriority evaluation -> selected over
        lower-value candidates -> CognitiveState updated. No LLM."""
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()

        # A competing low-value candidate: what Zerion decides NOT to process.
        rt.attention.submit_candidate_fields(topic="background log rotation", urgency=0.1,
                                             importance=0.1, goal_relevance=0.1,
                                             expected_information_gain=0.1, expected_utility=0.1,
                                             novelty=0.1, uncertainty=0.1, risk=0.1,
                                             resource_cost=0.5)

        # The demo event arrives on the bus.
        await rt.event_bus.publish(Event(
            event_type=EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED,
            payload={
                "warning": "System resource degradation detected: cpu=97.2%",
                "cpu_percent": 97.2,
                "source": "resource_governor",
                "attention_metrics": {
                    "urgency": 1.0, "importance": 1.0, "uncertainty": 0.6,
                    "novelty": 0.5, "goal_relevance": 1.0,
                    "expected_information_gain": 0.8, "expected_utility": 1.0,
                    "risk": 0.2, "resource_cost": 0.2, "api_cost": 0.0,
                    "estimated_latency_ms": 5.0,
                },
            },
            source="resource_governor", priority=90,
        ), dispatch_immediately=True)

        # EventBus -> candidate -> evaluated -> selected over the low-value candidate.
        self.assertGreaterEqual(rt.attention.stats()["selected_count"], 1)
        self.assertGreaterEqual(rt.attention.stats()["deferred_count"]
                                + rt.attention.stats()["discarded_count"], 1)
        # The degradation candidate won focus — the low-value one did not.
        self.assertTrue(rt.state.current_focus)
        self.assertIn("degradation", rt.state.current_focus.lower())
        # CognitiveState updated and persisted (attention counters mirrored, no
        # pending candidates left, state document on disk).
        self.assertEqual(rt.state.attention.selected_count, rt.attention.stats()["selected_count"])
        self.assertEqual(rt.state.attention.pending_candidates, 0)
        self.assertIsNotNone(rt.state_store.load())
        # The whole trail is on the real bus: signal -> candidate -> selection.
        replayed = await rt.event_bus.replay_events(limit=100)
        types = [e.event_type for e in replayed]
        self.assertIn(EventType.SYSTEM_RESOURCE_DEGRADATION_DETECTED, types)
        self.assertIn(EventType.ATTENTION_CANDIDATE_CREATED, types)
        self.assertIn(EventType.ATTENTION_SELECTED, types)
        await rt.stop()

    async def test_voice_events_not_consumed_by_cognitive_runtime(self):
        """Voice events are valid bus events but the cognitive foundation does not
        couple to them: no attention candidates, no state change, no focus hijack."""
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        self.assertEqual(rt.state.last_event.event_type, EventType.RUNTIME_STARTED.value)

        await rt.event_bus.publish(Event(
            event_type=EventType.VOICE_STARTED,
            payload={"session_id": "s1"}, source="voice_pipeline", priority=50,
        ), dispatch_immediately=True)
        await rt.event_bus.publish(Event(
            event_type=EventType.VOICE_TRANSCRIPT_FINAL,
            payload={"transcript": "open tasks"}, source="voice_pipeline", priority=50,
        ), dispatch_immediately=True)
        await rt.event_bus.publish(Event(
            event_type=EventType.VOICE_ENDED,
            payload={"session_id": "s1"}, source="voice_pipeline", priority=50,
        ), dispatch_immediately=True)

        self.assertEqual(rt.attention.stats()["selected_count"], 0)
        self.assertEqual(rt.attention.stats()["pending_candidates"], 0)
        self.assertEqual(rt.state.last_event.event_type, EventType.RUNTIME_STARTED.value)
        self.assertEqual(rt.state.current_focus, "")
        await rt.stop()

    async def test_goal_changes_affect_attention(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        goal = await rt.create_goal(objective="Reduce cold-start latency", purpose="Product goal",
                                    priority=90, next_action="Profile first request")
        self.assertEqual(rt.state.goals.total, 1)
        self.assertEqual(rt.state.goals.proposed, 1)
        # GOAL_CREATED -> candidate -> selected, focus set to the goal's objective
        self.assertEqual(rt.state.current_focus, "Reduce cold-start latency")
        self.assertGreaterEqual(rt.attention.stats()["selected_count"], 1)
        await rt.stop()

    async def test_runtime_state_updates(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        self.assertEqual(rt.state.runtime_status, RuntimeStatus.RUNNING)
        await rt.ingest_perception(cpu_percent=50.0, memory_mb=2048.0, source="probe")
        self.assertEqual(rt.state.perception.cpu_percent, 50.0)
        self.assertEqual(rt.state.perception.source, "probe")
        self.assertEqual(rt.state.pending_events, 0)
        await rt.stop()
        self.assertEqual(rt.state.runtime_status, RuntimeStatus.STOPPED)

    async def test_restart_preserves_state(self):
        dir1 = os.path.join(self.tmp, "data")
        rt1 = CognitiveRuntime(data_dir=dir1)
        await rt1.start()
        await rt1.ingest_perception(cpu_percent=44.0, memory_mb=1024.0, source="probe")
        await rt1.create_goal(objective="Persistent objective")
        await rt1.stop()

        rt2 = CognitiveRuntime(data_dir=dir1)
        await rt2.start()
        self.assertEqual(rt2.state.runtime_status, RuntimeStatus.RUNNING)
        self.assertEqual(rt2.state.perception.cpu_percent, 44.0)
        self.assertEqual(rt2.state.goals.total, 1)
        await rt2.stop()

    async def test_goal_survives_restart_with_progress_and_history(self):
        dir1 = os.path.join(self.tmp, "data")
        rt1 = CognitiveRuntime(data_dir=dir1)
        await rt1.start()
        goal = await rt1.create_goal(objective="Long-horizon mission")
        await rt1.activate_goal(goal.objective_id)
        await rt1.set_goal_progress(goal.objective_id, 0.3, note="milestone A")
        await rt1.stop()

        rt2 = CognitiveRuntime(data_dir=dir1)
        await rt2.start()
        g = rt2.objectives.get_goal(goal.objective_id)
        self.assertEqual(g.status, ObjectiveLifecycle.ACTIVE)
        self.assertEqual(g.progress, 0.3)
        self.assertEqual(len(g.progress_evidence), 1)
        await rt2.set_goal_progress(goal.objective_id, 0.7, note="milestone B")
        await rt2.stop()

        rt3 = CognitiveRuntime(data_dir=dir1)
        await rt3.start()
        g = rt3.objectives.get_goal(goal.objective_id)
        self.assertEqual(g.progress, 0.7)
        self.assertEqual(len(g.progress_evidence), 2)
        self.assertGreaterEqual(len(g.trajectory), 4)  # history kept across restarts
        await rt3.stop()

    async def test_stale_events_are_discarded(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        await rt.event_bus.publish(Event(
            event_type=EventType.PERCEPTION_RECEIVED,
            payload={"cpu_percent": 99.0, "memory_mb": 1.0, "attention_metrics": {"urgency": 1.0}},
            source="sensor", priority=60, timestamp=old_ts,
        ), dispatch_immediately=True)
        self.assertEqual(rt.attention.stats()["selected_count"], 0)
        self.assertEqual(rt.state.stale_events_discarded, 1)
        await rt.stop()

    async def test_duplicate_events_rejected(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        ev = Event(event_type=EventType.GOAL_CREATED, event_id="dup-1", payload={})
        await rt.event_bus.publish(ev, dispatch_immediately=True)
        with self.assertRaises(EventValidationError):
            await rt.event_bus.publish(Event(event_type=EventType.GOAL_CREATED,
                                             event_id="dup-1", payload={}),
                                       dispatch_immediately=True)
        await rt.stop()

    async def test_corrupted_state_becomes_recovering_not_empty(self):
        dir1 = os.path.join(self.tmp, "data")
        rt1 = CognitiveRuntime(data_dir=dir1)
        await rt1.start()
        await rt1.create_goal(objective="still recoverable")
        await rt1.stop()

        # Corrupt the persisted cognitive state document.
        conn = sqlite3.connect(os.path.join(dir1, "cognitive_state.db"))
        conn.execute("UPDATE cognitive_state SET payload = ?", ('{"schema_version": 1, "x": 1}',))
        conn.commit()
        conn.close()

        rt2 = CognitiveRuntime(data_dir=dir1)
        self.assertEqual(rt2.state.runtime_status, RuntimeStatus.RECOVERING)
        self.assertIsNotNone(rt2.state.recovery_error)
        # Goals still load independently — state corruption is not silent empty state.
        await rt2.start()
        self.assertEqual(rt2.state.goals.total, 1)
        self.assertEqual(rt2.state.runtime_status, RuntimeStatus.RUNNING)
        await rt2.stop()


# ---------------------------------------------------------------------------
# 6. REAL ENGINE INTEGRATION
# ---------------------------------------------------------------------------

class TestEngineIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice1_engine_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_engine_runs_cognitive_foundation(self):
        engine = AscendantEngine(data_dir=self.tmp)
        await engine.start()
        self.assertEqual(engine.cognitive_runtime.state.runtime_status, RuntimeStatus.RUNNING)

        await engine.run_developmental_cycle()
        self.assertEqual(engine.cognitive_runtime.state.perception.source, "resource_governor")
        self.assertIsNotNone(engine.cognitive_runtime.state.last_event)

        await engine.stop()
        self.assertEqual(engine.cognitive_runtime.state.runtime_status, RuntimeStatus.STOPPED)

    async def test_engine_restart_preserves_foundation_state(self):
        engine1 = AscendantEngine(data_dir=self.tmp)
        await engine1.start()
        await engine1.run_developmental_cycle()
        await engine1.cognitive_runtime.create_goal(objective="Engine-level durable goal")
        await engine1.stop()

        engine2 = AscendantEngine(data_dir=self.tmp)
        await engine2.start()
        self.assertEqual(engine2.cognitive_runtime.state.runtime_status, RuntimeStatus.RUNNING)
        self.assertEqual(engine2.cognitive_runtime.state.goals.total, 1)
        self.assertEqual(engine2.cognitive_runtime.state.perception.source, "resource_governor")
        await engine2.stop()


if __name__ == "__main__":
    unittest.main()
