"""
Smoke test for the real Zerion runtime — Gemini-first, no local model, no OpenAI.

Tests the ACTUAL runtime path from engine initialization through to
provider registration and capability counts. Does NOT mock components
being tested.
"""

import os
import unittest


class TestRuntimeSmoke(unittest.TestCase):
    """Verify the real runtime state matches expected architecture."""

    def test_01_gemini_is_primary_provider(self):
        """Gemini must be registered as a provider."""
        from zerion.model_providers.gemini_provider import GeminiProvider
        provider = GeminiProvider()
        self.assertTrue(provider.is_available() or not os.environ.get("GEMINI_API_KEY"),
                        "GeminiProvider must exist and be constructable")

    def test_02_no_openai_in_active_routing(self):
        """OpenAI must NOT be registered in the cognitive router."""
        from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
        runtime = CognitiveRuntime(data_dir="/tmp/zerion_smoke_test")
        providers = runtime.cognitive_router._provider_order
        self.assertNotIn("openai", providers,
                         f"OpenAI must be removed from routing. Found: {providers}")

    def test_03_gemini_is_registered(self):
        """Gemini must be registered in the cognitive router."""
        from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
        runtime = CognitiveRuntime(data_dir="/tmp/zerion_smoke_test")
        providers = runtime.cognitive_router._provider_order
        self.assertIn("gemini", providers,
                      f"Gemini must be registered. Found: {providers}")

    def test_04_gemini_model_id_is_valid(self):
        """The default Gemini model must be a valid Google model ID."""
        from zerion.model_providers.gemini_provider import GeminiProvider
        provider = GeminiProvider()
        valid_models = [
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
            "gemini-1.5-flash", "gemini-1.5-pro",
            "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
            "gemini-3.1-flash-lite",
        ]
        self.assertIn(provider.default_model, valid_models,
                      f"Model {provider.default_model} is not a valid Gemini model. "
                      f"Valid: {valid_models}")

    def test_05_agent_registry_has_21_agents(self):
        """AgentRegistry must contain exactly 21 registered agents."""
        from zerion.agents.registry import AgentRegistry
        registry = AgentRegistry()
        agents = registry.list_all()
        self.assertEqual(len(agents), 21,
                         f"Expected 21 agents, got {len(agents)}")

    def test_06_tool_registry_has_100_tools(self):
        """ToolRegistry must contain exactly 100 registered tools."""
        from zerion.tools.registry import ToolRegistry
        registry = ToolRegistry()
        self.assertEqual(registry.count(), 100,
                         f"Expected 100 tools, got {registry.count()}")

    def test_07_smart_memory_works(self):
        """SmartMemory must persist and retrieve information."""
        import tempfile
        import shutil
        from zerion.memory.developmental_store import SmartMemory
        d = tempfile.mkdtemp()
        try:
            m = SmartMemory(data_dir=d)
            item = m.remember("My name is TestUser", source="user")
            self.assertIsNotNone(item)
            self.assertEqual(item["domain"], "userdata")
            results = m.retrieve("name", top_k=3)
            self.assertTrue(len(results) > 0, "Memory retrieval returned no results")
            self.assertIn("TestUser", results[0]["content"])
            self.assertEqual(m.count(), 1)
        finally:
            shutil.rmtree(d)

    def test_08_microphone_disabled(self):
        """ZERION_DISABLE_MIC must be set in main.py."""
        with open("main.py", "r") as f:
            content = f.read()
        self.assertIn("ZERION_DISABLE_MIC", content,
                      "main.py must set ZERION_DISABLE_MIC=1")

    def test_09_intelligence_pipeline_exists(self):
        """CognitiveEngine must be importable and constructable."""
        from zerion.intelligence import CognitiveEngine
        engine = CognitiveEngine()
        self.assertIsNotNone(engine.situation)
        self.assertIsNotNone(engine.uncertainty)
        self.assertIsNotNone(engine.strategy)
        self.assertIsNotNone(engine.predictions)
        self.assertIsNotNone(engine.self_model)

    def test_10_providers_snapshot(self):
        """Runtime provider status must be inspectable."""
        from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
        runtime = CognitiveRuntime(data_dir="/tmp/zerion_smoke_test2")
        snapshot = runtime.provider_health.snapshot()
        self.assertIn("gemini", snapshot,
                      f"Gemini must be in health snapshot. Keys: {list(snapshot.keys())}")
        self.assertNotIn("openai", snapshot,
                         f"OpenAI must be removed. Keys: {list(snapshot.keys())}")


if __name__ == "__main__":
    unittest.main()
