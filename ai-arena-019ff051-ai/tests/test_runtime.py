"""
Unit tests for Runtime Layer
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from zerion.runtime.events import Event, EventType
from zerion.runtime.event_bus import AsyncEventBus
from zerion.runtime.queue import PriorityEventQueue
from zerion.runtime.resources import ResourceManager
from zerion.runtime.security import SecurityBoundary, PermissionLevel
from zerion.runtime.watchdog import Watchdog
from zerion.runtime.scheduler import MissionScheduler


class TestRuntime(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "events.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_priority_queue_and_dlq(self):
        pq = PriorityEventQueue(max_capacity=5)
        ev_low = Event(event_type=EventType.OBSERVATION_RECORDED, priority=10)
        ev_high = Event(event_type=EventType.RESOURCE_ALERT, priority=90)

        await pq.put(ev_low)
        await pq.put(ev_high)

        # Higher priority item should come out first
        first = await pq.get()
        self.assertEqual(first.priority, 90)
        second = await pq.get()
        self.assertEqual(second.priority, 10)

    async def test_event_bus_publish_subscribe_and_replay(self):
        bus = AsyncEventBus(db_path=self.db_path)
        await bus.start()

        received = []
        async def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.USER_GOAL_CREATED, handler)

        ev = Event(event_type=EventType.USER_GOAL_CREATED, payload={"goal": "Test goal"})
        await bus.publish(ev)

        # Allow dispatch
        await asyncio.sleep(0.05)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].payload["goal"], "Test goal")

        # Test persistence and replay
        replayed = await bus.replay_events(limit=10)
        self.assertTrue(len(replayed) >= 1)
        self.assertEqual(replayed[0].event_type, EventType.USER_GOAL_CREATED)

        await bus.stop()

    def test_resource_manager_sampling(self):
        rm = ResourceManager()
        snap = rm.sample()
        self.assertGreater(snap.memory_total_mb, 0)
        self.assertIn(snap.compute_tier, ["LOW", "MEDIUM", "HIGH"])
        mode = rm.get_recommended_compute_mode(task_priority=50, task_uncertainty=0.4)
        self.assertIn(mode, ["REFLEX", "FAST", "NORMAL", "DEEP", "EXTREME", "EXPERIMENTAL"])

    def test_security_boundary_authorization(self):
        sb = SecurityBoundary(workspace_root=self.temp_dir)
        # Permitted action
        self.assertTrue(sb.authorize("read_file", "notes.txt", PermissionLevel.READ_ONLY))
        # Forbidden path
        self.assertFalse(sb.authorize("write_file", "/etc/shadow", PermissionLevel.WORKSPACE_WRITE))
        audit = sb.get_audit_trail()
        self.assertEqual(len(audit), 2)


if __name__ == "__main__":
    unittest.main()
