"""
Unit and Integration Tests for ZERION-X GENESIS UI & State Bridge
"""

import asyncio
import os
import shutil
import tempfile
import unittest

from zerion.ui.state_bridge import UIStateMode, CognitiveUIState, UIStateBridge
from zerion.ui.server import GenesisWebServer
from zerion.engine import AscendantEngine


class TestGenesisUI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ui_test_")
        self.engine = AscendantEngine(data_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ui_state_bridge_and_modes(self):
        bridge = UIStateBridge()
        self.assertEqual(bridge.current_state.runtime_state, UIStateMode.BOOTING)
        self.assertGreaterEqual(bridge.current_state.core_glow_intensity, 0.5)

        # Transition to Listening
        bridge.set_listening_state(True)
        self.assertEqual(bridge.current_state.runtime_state, UIStateMode.LISTENING)

        # Transition to Speaking
        bridge.set_speaking_state(True, audio_rms=0.75)
        self.assertEqual(bridge.current_state.runtime_state, UIStateMode.SPEAKING)
        self.assertEqual(bridge.current_state.audio_amplitude_rms, 0.75)

        # Update from cycle trace
        bridge.update_from_cycle({
            "strategy_selected": "IntervalBisectionDebugging",
            "cognitive_allocation_mode": "DEEP",
            "maturity_level": "L6_META_LEARNING",
            "anomalies_detected": 1,
            "duration_ms": 25.0,
            "learning_acceleration_ratio": 2.57
        })

        self.assertEqual(bridge.current_state.runtime_state, UIStateMode.THINKING)
        self.assertEqual(bridge.current_state.core_glow_intensity, 0.95)
        self.assertIn("IntervalBisectionDebugging", bridge.current_state.cognitive_state)

    async def test_ui_web_server_startup_and_endpoint_routing(self):
        await self.engine.start()
        server = GenesisWebServer(engine=self.engine, host="127.0.0.1", port=8999)
        await server.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 8999)
            writer.write(b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()

            res = await reader.read(4096)
            res_str = res.decode(errors="replace")
            self.assertIn("200 OK", res_str)
            self.assertIn("runtime_state", res_str)
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
            await self.engine.stop()

    async def test_cognitive_state_endpoint_serves_real_snapshot(self):
        """The /api/cognitive-state endpoint must serve the real CognitiveState
        document (Slice 1) — not UI presentation defaults."""
        await self.engine.start()
        server = GenesisWebServer(engine=self.engine, host="127.0.0.1", port=8998)
        await server.start()

        try:
            # Drive one real cycle so perception/attention counters are populated.
            await self.engine.run_developmental_cycle()

            reader, writer = await asyncio.open_connection("127.0.0.1", 8998)
            writer.write(b"GET /api/cognitive-state HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()

            res = await reader.read(65536)
            res_str = res.decode(errors="replace")
            self.assertIn("200 OK", res_str)
            body = res_str.split("\r\n\r\n", 1)[1]
            import json as _json
            data = _json.loads(body)
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("runtime_status", data)
            self.assertIn("perception", data)
            self.assertIn("attention", data)
            self.assertIn("goals", data)
            self.assertIn("resources", data)
            self.assertIn("current_focus", data)
            self.assertIn("last_event", data)
            # After a real cycle, perception must carry measured telemetry.
            self.assertGreater(data["perception"]["cpu_percent"], 0.0)
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
            await self.engine.stop()


if __name__ == "__main__":
    unittest.main()
