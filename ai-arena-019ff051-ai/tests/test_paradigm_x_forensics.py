"""
PARADIGM-X — STAGE 0 (repository truth) honesty regressions.

Pins the concrete Stage-0 fixes found by the repository forensics:

1. The engine's .env loader is a shared, injectable function (never-override,
   import-safe) — the old inline loop used `os.environ` without importing `os`,
   a latent NameError whenever a .env file exists.
2. `ask_ultimate_questions()` answer_4 reports the REAL born state instead of
   the canned "Yes. Verified via in-memory sandbox and invariant checks."
   fabrication.
3. `answer_hierarchy_level(4)` computes the strategy gap from the real registry
   instead of hard-coding a single missing domain.
4. `answer_hierarchy_level(1)` reports maturity from real evidence (cold start
   must NOT report L7).
5. Cycle telemetry counts real perception events instead of a hard-coded "2".

These are the §31 "identify fake telemetry / hard-coded claims" findings,
pinned so they cannot silently regress.
"""

import os
import tempfile
import unittest

from zerion.cognitive_genesis.strategy import CognitiveStrategy
import zerion.engine as engine_module
from zerion.engine import AscendantEngine, load_dotenv_files


class TestDotEnvLoader(unittest.TestCase):
    def test_loader_never_overrides_and_strips_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".env"), "w", encoding="utf-8") as f:
                f.write("ZERION_TEST_A=from_file\n")
                f.write("# a comment line\n")
                f.write("ZERION_TEST_B = 'quoted value'\n")
                f.write("ZERION_TEST_A=overwritten_by_later_line\n")
            env = {"ZERION_TEST_A": "already_set"}
            load_dotenv_files(environ=env, extra_dirs=[d])
            self.assertEqual(env["ZERION_TEST_A"], "already_set")  # never override
            self.assertEqual(env["ZERION_TEST_B"], "quoted value")

    def test_engine_module_imports_os(self):
        # Regression for the missing-`import os` NameError class: the loader is
        # reachable from the engine module and `os` is bound at module scope.
        self.assertTrue(hasattr(engine_module, "os"))
        self.assertTrue(callable(engine_module.load_dotenv_files))


class TestEngineHonestyRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = AscendantEngine(data_dir=self._tmp.name)
        await self.engine.start()

    async def asyncTearDown(self):
        await self.engine.stop()
        self._tmp.cleanup()

    async def test_level1_maturity_uses_real_evidence(self):
        # Cold start: 0 episodes / 0 rules / 0 born capabilities. The zero-arg
        # evaluate() default path used to always report L7; this must not.
        ans = self.engine.answer_hierarchy_level(1)
        self.assertIn("maturity", ans)
        self.assertIn("maturity_evidence_score", ans)
        self.assertNotEqual(ans["maturity"], "L7_COGNITIVE_GENERATIVE")

    async def test_level4_gap_computed_from_registry(self):
        ans = self.engine.answer_hierarchy_level(4)
        self.assertIn("domains_covered", ans)
        self.assertIn("missing_reason", ans)
        missing = ans["missing_strategy"]
        if not missing.startswith("None"):
            domain = missing[: -len("_strategy")]
            self.assertNotIn(domain, ans["domains_covered"])

    async def test_level4_reports_all_covered_when_registry_full(self):
        # Seed the registry with every canonical domain; the gap must vanish
        # (no hard-coded "distributed_consensus" answer).
        for d in ["general_cognition", "software_debugging", "distributed_consensus",
                  "data_processing", "mathematical_reasoning", "security_audit",
                  "mobile_optimization", "offline_cognition"]:
            self.engine.strategy_registry.register_strategy(
                CognitiveStrategy(name=f"strat_{d}", domain=d))
        ans = self.engine.answer_hierarchy_level(4)
        self.assertTrue(ans["missing_strategy"].startswith("None"))

    async def test_ultimate_answer4_reports_real_born_state(self):
        res = await self.engine.ask_ultimate_questions()
        self.assertIn("capability_born", res)
        self.assertIn("capability_name", res)
        # The old fabrication must never reappear, regardless of outcome.
        self.assertNotIn("Verified via in-memory sandbox", res["answer_4"])
        if not res["capability_born"]:
            self.assertIsNone(res["capability_name"])
            self.assertTrue(res["answer_4"].startswith(("No.", "No new capability")))

    async def test_cycle_perception_telemetry_is_measured(self):
        trace = await self.engine.run_developmental_cycle()
        # At minimum the single ingest_perception call counts; the value must
        # come from the real counter, not a hard-coded constant.
        self.assertGreaterEqual(trace.perceptions_ingested, 1)


if __name__ == "__main__":
    unittest.main()
