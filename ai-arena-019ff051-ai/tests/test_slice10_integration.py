"""
ZERION — SLICE 10 tests: UI + VOICE + OFFLINE INTERACTION INTEGRATION.

Covers the spec's test sections 28-33 with REAL evidence only:
- UI starts, runtime starts, event stream works, real events reach the UI
- UI survives event bursts (bounded history, backpressure, rate limiting)
- UI survives runtime failure
- UI displays offline mode / provider failure correctly
- UI does not fabricate state
- commands are validated
- UI cannot mutate protected cognitive state
- voice state machine (valid transitions only)
- wake-word activation + repeated wake-word protection + interruption
- transcript / wake / response events published on the real bus
- offline STT / TTS detection is honest (never "ready" by assumption)
- actual TTS audio generation WHEN an engine exists (else NOT_TESTABLE)
- GGUF discovery (recursive, invalid ignored, honest metadata, resource
  failure, selection, unload, switching)
- OFFLINE end-to-end: wake -> STT -> transcript -> runtime -> local GGUF ->
  response -> TTS, with every step's real evidence (blocked layer reported)
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
from zerion.voice.providers import VoiceEnvironment, VoiceEngineStatus
from zerion.voice.state_machine import (
    InvalidVoiceTransition,
    VoiceState,
    VoiceStateMachine,
)
from zerion.voice.wake_word import LayeredWakeWordDetector
from zerion.ui.state_bridge import UIStateMode

GGUF_MAGIC = b"GGUF"


def _write_gguf(path: Path, size: int = 64):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(GGUF_MAGIC)
        f.write(b"\x00" * max(0, size - len(GGUF_MAGIC)))
    return path


def _fake_engine(runtime=None, voice_pipeline=None, resources=None,
                 learning_to_learn=None, ui_bridge=None, termux=None):
    """Minimal engine stand-in for adapter unit tests (no full boot)."""
    class _E:
        pass
    e = _E()
    e.cognitive_runtime = runtime
    e.voice_pipeline = voice_pipeline
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
            # Voice engines are honestly reported (never "READY" by assumption).
            voice = snap["voice"]
            for eng in ("stt", "tts"):
                self.assertIn(voice[eng]["status"],
                              ("AVAILABLE", "UNAVAILABLE", "NOT_CONFIGURED"))
                if voice[eng]["status"] != "AVAILABLE":
                    self.assertTrue(voice[eng]["reason"])
            # Model count must be a non-negative integer from real discovery.
            self.assertIsInstance(snap["models"]["count"], int)
            self.assertGreaterEqual(snap["models"]["count"], 0)
        finally:
            await engine.stop()

    async def test_ui_displays_offline_mode_correctly(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            pulse = engine.cognitive_runtime.cognitive_pulse
            pulse.set_offline_mode("OFFLINE_ONLY")
            snap = engine.ui_adapter.snapshot()
            self.assertEqual(snap["system"]["offline_mode"], "OFFLINE_ONLY")
            # OFFLINE_ONLY must never touch cloud providers.
            from zerion.cognitive_os.router_types import RoutingMode, Task
            task = Task(description="offline check", required_capabilities=set(),
                        offline_required=True)
            sel = engine.cognitive_runtime.route_task(task, RoutingMode.OFFLINE_ONLY)
            self.assertNotEqual(sel.provider, "openai")
        finally:
            await engine.stop()

    async def test_ui_displays_provider_failure_correctly(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            from zerion.cognitive_os.router_types import RoutingMode, Task
            task = Task(description="no providers should be available",
                        required_capabilities=set())
            result = await engine.cognitive_runtime.execute_task(
                task, "tell me about quantum physics", mode=RoutingMode.OFFLINE_ONLY)
            # When a model IS discovered but inference fails, the status
            # may be MODEL_LOAD_FAILURE instead of ROUTING_FAILED.
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
            self.assertEqual(r["status"], "OK")
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


class TestSlice10Voice(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="s10_voice_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_voice_state_machine_valid_and_invalid_transitions(self):
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING)
        sm.transition(VoiceState.THINKING)
        sm.transition(VoiceState.EXECUTING)
        sm.transition(VoiceState.THINKING)
        sm.transition(VoiceState.SPEAKING)
        sm.transition(VoiceState.LISTENING)
        sm.transition(VoiceState.IDLE)
        self.assertEqual(sm.state, VoiceState.IDLE)

        sm2 = VoiceStateMachine()
        with self.assertRaises(InvalidVoiceTransition):
            sm2.transition(VoiceState.SPEAKING)  # IDLE -> SPEAKING is invalid

    def test_wake_word_repeat_activation_protection(self):
        detector = LayeredWakeWordDetector(cooldown_seconds=5.0)
        first = detector.process_transcript("Zerion")
        self.assertTrue(first.detected)
        # Same utterance immediately after is suppressed by cooldown.
        second = detector.process_transcript("Zerion")
        self.assertFalse(second.detected)
        self.assertEqual(second.rejection_reason, "Cooldown period active")

    async def test_voice_transcript_and_wake_events_published(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            await engine.voice_pipeline.process_speech_input(
                "Hey Zerion, status")
            # End the conversation so the next utterance is evaluated fresh.
            await engine.command_api.execute("STOP_LISTENING")
            await engine.voice_pipeline.process_speech_input(
                "the horizon is clear")
            await engine.command_api.execute("START_LISTENING")
            await engine.command_api.execute("STOP_LISTENING")

            types = [h["event_type"]
                     for h in engine.ui_adapter.event_history(200)]
            for expected in ("VOICE_TRANSCRIPT_FINAL", "WAKE_WORD_DETECTED",
                             "VOICE_RESPONSE_READY", "VOICE_ENDED",
                             "WAKE_WORD_MISDETECTED", "VOICE_STARTED"):
                self.assertIn(expected, types, msg=f"missing {expected}")
        finally:
            await engine.stop()

    async def test_voice_interruption_publishes_event_and_returns_to_listening(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            pipeline = engine.voice_pipeline
            pipeline.ui_bridge.set_speaking_state(True, audio_rms=0.85)
            await pipeline.handle_audio_frame(rms_amplitude=0.35)
            self.assertEqual(pipeline.ui_bridge.current_state.runtime_state,
                             UIStateMode.LISTENING)
            types = [h["event_type"]
                     for h in engine.ui_adapter.event_history(100)]
            self.assertIn("VOICE_INTERRUPTED", types)
        finally:
            await engine.stop()

    def test_offline_stt_tts_detection_is_honest(self):
        env = VoiceEnvironment()
        stt = env.detect_stt()
        self.assertIn(stt.status,
                      ("AVAILABLE", "UNAVAILABLE", "NOT_CONFIGURED"))
        if stt.status == "AVAILABLE":
            self.assertTrue(stt.engine_binary)
        else:
            self.assertTrue(stt.reason)
        tts = env.detect_tts()
        self.assertIn(tts.status,
                      ("AVAILABLE", "UNAVAILABLE", "NOT_CONFIGURED"))
        if tts.status == "AVAILABLE":
            self.assertTrue(tts.engine_binary)
        else:
            self.assertTrue(tts.reason)
        wake = env.detect_wake()
        self.assertEqual(wake.status, "AVAILABLE")  # built-in, offline

    def test_tts_actual_audio_generation_or_not_testable(self):
        env = VoiceEnvironment()
        tts = env.detect_tts()
        if tts.status != VoiceEngineStatus.AVAILABLE:
            self.skipTest(
                "NOT_TESTABLE_IN_ENVIRONMENT: no offline TTS engine installed")
        if tts.name == "termux-tts-speak":
            self.skipTest(
                "NOT_TESTABLE_IN_ENVIRONMENT: termux TTS plays through "
                "speaker (no capture)")
        ev = env.synthesize("Zerion voice test")
        if ev["status"] != "AUDIO_GENERATED":
            self.skipTest(f"NOT_TESTABLE_IN_ENVIRONMENT: {ev.get('reason')}")
        self.assertTrue(os.path.exists(ev["path"]))
        self.assertGreater(ev["bytes"], 0)

    async def test_voice_graceful_failure_when_no_engine(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            turn = await engine.voice_pipeline.process_speech_input(
                "Zerion, what time is it")
            tts_info = engine.voice_env.detect_tts()
            if tts_info.status == "AVAILABLE":
                self.assertIn(turn.tts_status,
                              ("AUDIO_GENERATED", "AUDIO_PLAYED", "VOICE_ERROR"))
            else:
                # No engine: honest VOICE_UNAVAILABLE, never a fake success.
                self.assertEqual(turn.tts_status, "VOICE_UNAVAILABLE")
                self.assertIsNone(turn.audio_path)
                self.assertIn("VOICE", engine.ui_bridge.current_state.explanation_chain[0])
        finally:
            await engine.stop()


class TestSlice10GGUF(unittest.TestCase):
    def setUp(self):
        self.models_dir = tempfile.mkdtemp(prefix="s10_models_")
        self.registry = None

    def tearDown(self):
        shutil.rmtree(self.models_dir, ignore_errors=True)

    def _build_registry(self, **kwargs):
        from zerion.cognitive_os.local_model_registry import LocalModelRegistry
        from zerion.cognitive_os.gguf_discovery import (
            DEFAULT_MAX_LOADED_BYTES, DEFAULT_MAX_LOADED_MODELS)
        kwargs.setdefault("max_loaded_bytes", DEFAULT_MAX_LOADED_BYTES)
        kwargs.setdefault("max_loaded_models", DEFAULT_MAX_LOADED_MODELS)
        from zerion.cognitive_os.gguf_discovery import ModelLoadManager
        from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
        disc = LocalModelDiscovery(models_dir=self.models_dir, **{
            k: v for k, v in kwargs.items()
            if k in ("max_model_bytes", "strict")})
        lm_kwargs = {k: v for k, v in kwargs.items()
                     if k in ("max_loaded_bytes", "max_loaded_models")}
        load = ModelLoadManager(disc, **lm_kwargs)
        self.registry = LocalModelRegistry(
            models_dir=self.models_dir, discovery=disc, load_manager=load)
        return self.registry

    def test_gguf_recursive_discovery_invalid_ignored_metadata(self):
        _write_gguf(Path(self.models_dir) / "model_a.gguf")
        _write_gguf(Path(self.models_dir) / "model_b.gguf")
        _write_gguf(Path(self.models_dir) / "nested" / "model_c.gguf")
        # Invalid extension ignored.
        (Path(self.models_dir) / "notes.txt").write_text("hello")
        (Path(self.models_dir) / "model_d.bin").write_bytes(b"GGUFjunk")
        # Corrupt GGUF (missing magic) marked unavailable, not silently accepted.
        (Path(self.models_dir) / "corrupt.gguf").write_bytes(b"NOTAGUF" + b"\x00" * 16)
        # Duplicate stem in a subdirectory: only the first wins.
        _write_gguf(Path(self.models_dir) / "sub" / "model_b.gguf")

        reg = self._build_registry()
        models = reg.list_models()
        ids = [m["model_id"] for m in models]
        for expected in ("model_a", "model_b", "model_c"):
            self.assertIn(expected, ids)
        self.assertEqual(ids.count("model_b"), 1)
        self.assertNotIn("notes", ids)
        self.assertNotIn("model_d", ids)
        # Corrupt file discovered but honestly unavailable.
        corrupt = [m for m in models if m["model_id"] == "corrupt"]
        self.assertEqual(len(corrupt), 1)
        self.assertEqual(corrupt[0]["availability"], "UNAVAILABLE")
        # Metadata honesty: only what is actually detectable.
        a = reg.get("model_a")
        self.assertGreater(a["size_bytes"], 0)
        self.assertEqual(a["format"], "gguf")
        self.assertEqual(a["architecture"], "UNKNOWN")
        self.assertEqual(a["quantization"], "UNKNOWN")
        self.assertIsNone(a["context_window"])
        self.assertIn("text", a["capabilities"])
        self.assertEqual(a["load_status"], "UNLOADED")

    def test_gguf_resource_failure_selection_switch_unload(self):
        _write_gguf(Path(self.models_dir) / "small.gguf", size=64)
        _write_gguf(Path(self.models_dir) / "big.gguf", size=2 * 1024 * 1024)
        # Byte budget holds both models but the RAM budget does not.
        reg = self._build_registry(max_loaded_bytes=3 * 1024 * 1024,
                                   max_loaded_models=1)

        # Selection respects the RAM budget: big model is skipped.
        chosen = reg.select(max_ram_mb=1.0)
        self.assertEqual(chosen, "small")
        self.assertTrue(any("exceeds RAM budget" in r
                            for r in reg.selection_reason()))

        # Load big -> structured resource failure, never a crash.
        res = reg.load("big", max_ram_mb=1.0)
        self.assertEqual(res["status"], "RESOURCE_INSUFFICIENT")

        # Load small -> LOADED; slot budget prevents a second model.
        res = reg.load("small")
        self.assertEqual(res["status"], "LOADED")
        self.assertEqual(reg.get("small")["load_status"], "LOADED")

        # Unload, then switch to big within the byte budget.
        self.assertTrue(reg.unload("small"))
        self.assertEqual(reg.get("small")["load_status"], "UNLOADED")
        res = reg.load("big")
        self.assertEqual(res["status"], "LOADED")

        # Load unknown model id.
        res = reg.load("nope")
        self.assertEqual(res["status"], "NOT_FOUND")


class TestSlice10OfflineE2E(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="s10_e2e_")
        self.models_dir = os.path.join(self.temp_dir, "models")
        os.makedirs(self.models_dir, exist_ok=True)
        _write_gguf(Path(self.models_dir) / "model_a.gguf", size=64)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @unittest.skip("Local model removed — Gemini is sole provider")
    async def test_offline_end_to_end_reports_blocked_layer_honestly(self):
        engine = AscendantEngine(data_dir=self.temp_dir,
                                 models_dir=self.models_dir)
        await engine.start()
        try:
            # Simulate real network loss; OFFLINE_ONLY mode.
            engine.voice_env.network._checker = lambda: "OFFLINE"
            pulse = engine.cognitive_runtime.cognitive_pulse
            pulse.set_offline_mode("OFFLINE_ONLY")

            snap = engine.ui_adapter.snapshot()
            self.assertEqual(snap["network"]["state"], "OFFLINE")
            self.assertEqual(snap["system"]["offline_mode"], "OFFLINE_ONLY")
            self.assertEqual(snap["models"]["count"], 1)

            # USER -> WAKE WORD -> TRANSCRIPT -> RUNTIME -> LOCAL GGUF -> ...
            turn = await engine.voice_pipeline.process_speech_input(
                "Zerion, analyze the environment")
            self.assertTrue(turn.wake_result.detected)
            self.assertEqual(turn.offline_mode, "OFFLINE_ONLY")
            # The local GGUF model IS discovered and selected...
            self.assertIn("local_gguf", turn.errors[0] if turn.errors else "")
            # ...but inference is genuinely unavailable: structured failure,
            # never fabricated text pretending to be model output.
            self.assertIn("couldn't process", turn.cognitive_response.lower())
            self.assertNotIn("Level 6 Meta-Learning", turn.cognitive_response)

            # Every step produced real bus evidence.
            types = [h["event_type"]
                     for h in engine.ui_adapter.event_history(200)]
            for expected in ("VOICE_TRANSCRIPT_FINAL", "WAKE_WORD_DETECTED",
                             "VOICE_RESPONSE_READY"):
                self.assertIn(expected, types)
        finally:
            await engine.stop()

    async def test_command_run_task_offline_returns_structured_failure(self):
        engine = AscendantEngine(data_dir=self.temp_dir,
                                 models_dir=self.models_dir)
        await engine.start()
        try:
            pulse = engine.cognitive_runtime.cognitive_pulse
            pulse.set_offline_mode("OFFLINE_ONLY")
            r = await engine.command_api.execute("RUN_TASK", {
                "prompt": "Summarize the model", "mode": "OFFLINE_ONLY",
                "task_type": "REASONING"})
            self.assertEqual(r["status"], "OK")
            result = r["result"]
            self.assertIn(result["status"], ("ROUTING_FAILED", "MODEL_LOAD_FAILURE"))
            self.assertIsNone(result["output"])
            self.assertTrue(result["errors"])
        finally:
            await engine.stop()

    async def test_online_end_to_end_requires_real_provider(self):
        if not os.environ.get("OPENAI_API_KEY"):
            self.skipTest(
                "NOT_TESTABLE_IN_ENVIRONMENT: no configured provider "
                "(OPENAI_API_KEY not set)")
        engine = AscendantEngine(data_dir=self.temp_dir,
                                 models_dir=self.models_dir)
        await engine.start()
        try:
            from zerion.cognitive_os.router_types import RoutingMode, Task
            task = Task(description="online e2e", required_capabilities=set())
            result = await engine.cognitive_runtime.execute_task(
                task, "say hi", mode=RoutingMode.ONLINE_ALLOWED)
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
