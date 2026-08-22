"""
ZERION — SLICE 10 tests: UI INTERACTION INTEGRATION.

Covers the spec's UI integration sections with REAL evidence only:
- UI starts, runtime starts, event stream works, real events reach the UI
- UI survives event bursts (bounded history, backpressure, rate limiting)
- UI survives runtime failure
- UI displays provider availability/failure honestly (no offline mode exists)
- UI does not fabricate state
- commands are validated
- UI cannot mutate protected cognitive state
- Gemini-only E2E: unavailable provider -> structured failure, never fake text
"""

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from zerion.engine import AscendantEngine
from zerion.runtime.events import Event, EventType
from zerion.ui.visualization_adapter import VisualizationStateAdapter


def _fake_engine(runtime=None, resources=None,
                 learning_to_learn=None, ui_bridge=None, termux=None):
    """Minimal engine stand-in for adapter unit tests (no full boot)."""
    class _E:
        pass
    e = _E()
    e.cognitive_runtime = runtime
    e.resources = resources
    e.learning_to_learn = learning_to_learn
    e.ui_bridge = ui_bridge
    e.termux = termux
    return e


class TestSlice10UI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="s10_ui_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_ui_starts_runtime_starts_event_stream_receives_real_events(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            snap = engine.ui_adapter.snapshot()
            self.assertEqual(snap["system"]["runtime_status"], "RUNNING")
            self.assertIn("health", snap)
            self.assertIn("presentation", snap)

            types = [h["event_type"] for h in engine.ui_adapter.event_history(200)]
            self.assertIn("RUNTIME_STARTED", types)

            # The stream delivers a real event.
            q = engine.ui_adapter.subscribe_stream()
            await engine.event_bus.publish(Event(
                event_type=EventType.WATCHDOG_HEARTBEAT,
                payload={"ok": True}, source="test"), dispatch_immediately=True)
            rec = await asyncio.wait_for(q.get(), timeout=2.0)
            self.assertEqual(rec["event_type"], "WATCHDOG_HEARTBEAT")
            engine.ui_adapter.unsubscribe_stream(q)
        finally:
            await engine.stop()

    async def test_ui_survives_event_bursts_bounded_history_and_backpressure(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            # Rate limiting: identical events inside the window collapse.
            collapsing = VisualizationStateAdapter(
                engine, engine.event_bus, max_history=50, burst_window_s=60.0)
            collapsing.attach()
            # Bounded history with no collapse: every event is a record.
            bounded = VisualizationStateAdapter(
                engine, engine.event_bus, max_history=50, burst_window_s=0.0)
            bounded.attach()

            # 100 identical events -> ONE history entry with count=100.
            for i in range(100):
                await engine.event_bus.publish(Event(
                    event_type=EventType.WATCHDOG_HEARTBEAT,
                    payload={"i": i}, source="burst"),
                    dispatch_immediately=True)
            hist = collapsing.event_history(200)
            matching = [h for h in hist
                        if h["event_type"] == "WATCHDOG_HEARTBEAT"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["count"], 100)

            # 120 events (no collapse) -> history hard-capped at max_history.
            for i in range(120):
                await engine.event_bus.publish(Event(
                    event_type=EventType.WATCHDOG_HEARTBEAT,
                    payload={"i": i}, source="burst2"),
                    dispatch_immediately=True)
            self.assertEqual(len(bounded.event_history(500)), 50)

            # Backpressure: a tiny subscriber queue drops oldest, never raises.
            tiny = asyncio.Queue(maxsize=3)
            bounded._subscribers.append(tiny)
            for i in range(10):
                await engine.event_bus.publish(Event(
                    event_type=EventType.WATCHDOG_HEARTBEAT,
                    payload={"i": i}, source="bp"),
                    dispatch_immediately=True)
            self.assertEqual(tiny.qsize(), 3)
            self.assertEqual(tiny.get_nowait()["payload"]["i"], 7)
        finally:
            await engine.stop()

    async def test_ui_survives_runtime_failure(self):
        class _BrokenRuntime:
            @property
            def state(self):
                raise RuntimeError("runtime exploded")

        engine = _fake_engine(runtime=_BrokenRuntime())
        adapter = VisualizationStateAdapter(engine, None)
        snap = adapter.snapshot()
        self.assertIn("system", snap)
        self.assertIn("health", snap)
        # The adapter reports the failure instead of crashing the snapshot.
        self.assertIn("error", snap["health"])

    async def test_ui_does_not_fabricate_state(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            snap = engine.ui_adapter.snapshot()
            pres = snap["presentation"]
            # No hard-coded intelligence claims (confidence starts unmeasured).
            self.assertTrue(pres.get("confidence") is None)
            # The served UI no longer contains the fabricated defaults.
            html = (Path(__file__).parent.parent / "zerion" / "ui"
                    / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("2.57X", html)
            self.assertNotIn("12.5% CPU", html)
            self.assertNotIn("Continuous Anomaly and Inefficiency Discovery",
                             html)
            # Voice INPUT is removed entirely: the snapshot reports that
            # honestly instead of pretending a microphone exists.
            self.assertTrue(snap["voice"]["removed"])
            # Model count must be a non-negative integer from real discovery.
            self.assertIsInstance(snap["models"]["count"], int)
            self.assertGreaterEqual(snap["models"]["count"], 0)
        finally:
            await engine.stop()

    async def test_ui_displays_provider_availability_honestly(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            snap = engine.ui_adapter.snapshot()
            # Provider statuses come from REAL health tracking, and there is
            # no offline-mode field anywhere in the UI state.
            self.assertIn("providers", snap["system"])
            self.assertNotIn("offline_mode", snap["system"])
        finally:
            await engine.stop()

    async def test_ui_displays_provider_failure_correctly(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            # Trip the Gemini circuit breaker with REAL recorded failures so
            # this test never depends on (or touches) the network.
            for _ in range(4):
                engine.cognitive_runtime.cognitive_router.health.record_failure(
                    "gemini", timeout=True, error="timeout")
            from zerion.cognitive_os.router_types import Task
            task = Task(description="no providers should be available",
                        required_capabilities=set())
            result = await engine.cognitive_runtime.execute_task(
                task, "tell me about quantum physics")
            self.assertIn(result.status.value,
                          ("ROUTING_FAILED", "MODEL_LOAD_FAILURE",
                           "PROVIDER_UNAVAILABLE"))
            self.assertIsNone(result.output)
            self.assertTrue(result.errors)
            snap = engine.ui_adapter.snapshot()
            # Provider statuses come from real health tracking, not UI claims.
            self.assertIn("providers", snap["system"])
        finally:
            await engine.stop()

    async def test_commands_are_validated(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            r = await engine.command_api.execute("NOT_A_COMMAND")
            self.assertEqual(r["status"], "VALIDATION_ERROR")

            r = await engine.command_api.execute("CREATE_GOAL", {})
            self.assertEqual(r["status"], "VALIDATION_ERROR")

            r = await engine.command_api.execute(
                "CREATE_GOAL", {"objective": "Investigate the signal"})
            self.assertEqual(r["status"], "OK")
            goal_id = r["result"]["goal_id"]
            goals = engine.cognitive_runtime.objectives.list_active_objectives()
            self.assertTrue(any(g.objective_id == goal_id for g in goals))

            r = await engine.command_api.execute("PAUSE_PULSE")
            self.assertEqual(r["status"], "OK")
            self.assertEqual(
                engine.cognitive_runtime.cognitive_pulse.state.value, "PAUSED")
            r = await engine.command_api.execute("RESUME_PULSE")
            self.assertEqual(r["status"], "OK")

            r = await engine.command_api.execute(
                "SET_OFFLINE_MODE", {"mode": "BOGUS"})
            self.assertEqual(r["status"], "VALIDATION_ERROR")
            r = await engine.command_api.execute(
                "SET_OFFLINE_MODE", {"mode": "OFFLINE_ONLY"})
            # SET_OFFLINE_MODE is removed entirely: unknown commands are
            # rejected by validation, never executed.
            self.assertEqual(r["status"], "VALIDATION_ERROR")
        finally:
            await engine.stop()

    async def test_ui_cannot_mutate_protected_cognitive_state(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            snap1 = engine.ui_adapter.snapshot()
            snap1["cognitive"]["active_goal"] = "HACKED"
            snap1["presentation"]["active_goal"] = "HACKED"
            snap1["last_events"].append({"event_type": "FORGED"})
            snap2 = engine.ui_adapter.snapshot()
            self.assertNotEqual(snap2["cognitive"]["active_goal"], "HACKED")
            self.assertNotEqual(snap2["presentation"]["active_goal"], "HACKED")
            self.assertFalse(any(e.get("event_type") == "FORGED"
                                for e in snap2["last_events"]))
            # The real runtime state is untouched.
            self.assertNotEqual(
                getattr(engine.cognitive_runtime.state, "current_focus", None),
                "HACKED")
        finally:
            await engine.stop()







class TestSlice10GeminiOnlyE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end on the Gemini-only runtime: an unavailable provider yields
    a structured, honest failure through commands and direct execution —
    never fabricated text. There is no local-model or offline path left."""
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="s10_e2e_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def _engine_with_no_provider(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        for _ in range(4):
            engine.cognitive_runtime.cognitive_router.health.record_failure(
                "gemini", timeout=True, error="timeout")
        return engine

    async def test_command_run_task_unavailable_provider_structured_failure(self):
        engine = await self._engine_with_no_provider()
        try:
            r = await engine.command_api.execute("RUN_TASK", {
                "prompt": "Summarize the model", "task_type": "REASONING"})
            self.assertEqual(r["status"], "OK")
            result = r["result"]
            self.assertIn(result["status"], ("ROUTING_FAILED", "MODEL_LOAD_FAILURE"))
            self.assertIsNone(result["output"])
            self.assertTrue(result["errors"])
        finally:
            await engine.stop()

    async def test_gemini_end_to_end_requires_real_key(self):
        if not os.environ.get("GEMINI_API_KEY"):
            self.skipTest(
                "NOT_TESTABLE_IN_ENVIRONMENT: GEMINI_API_KEY not set")
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            from zerion.cognitive_os.router_types import Task
            task = Task(description="gemini e2e", required_capabilities=set())
            result = await engine.cognitive_runtime.execute_task(
                task, "say hi")
            self.assertEqual(result.status.value, "SUCCESS")
            self.assertIsNotNone(result.output)
        finally:
            await engine.stop()


class TestSlice10ServerStream(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="s10_srv_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_sse_stream_endpoint_delivers_real_events(self):
        from zerion.ui.server import GenesisWebServer
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        server = GenesisWebServer(engine=engine, host="127.0.0.1", port=8997)
        await server.start()
        reader, writer = None, None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 8997)
            writer.write(b"GET /api/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()

            # Headers arrive first.
            head = await asyncio.wait_for(reader.read(512), timeout=3.0)
            self.assertIn(b"200 OK", head)
            self.assertIn(b"text/event-stream", head)

            # A real event then arrives as an SSE data frame.
            await engine.command_api.execute("PAUSE_PULSE")
            buf = b""
            deadline = asyncio.get_event_loop().time() + 5.0
            while asyncio.get_event_loop().time() < deadline:
                chunk = await asyncio.wait_for(reader.read(512), timeout=2.0)
                if not chunk:
                    break
                buf += chunk
                if b"PULSE_PAUSED" in buf:
                    break
            self.assertIn(b"PULSE_PAUSED", buf)
            await engine.command_api.execute("RESUME_PULSE")
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
            await server.stop()
            # Unblock any lingering stream task so teardown is clean.
            await engine.event_bus.publish(Event(
                event_type=EventType.WATCHDOG_HEARTBEAT, payload={},
                source="test"), dispatch_immediately=True)
            await asyncio.sleep(0.2)
            await engine.stop()


if __name__ == "__main__":
    unittest.main()
