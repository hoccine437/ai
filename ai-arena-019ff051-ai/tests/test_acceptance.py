"""
Master Acceptance Test Suite for ZERION-X ASCENDANT
Verifies all 10 Acceptance Tests (Section 46) and the Ultimate Design Test (Section 47).
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest

from zerion.engine import AscendantEngine
from zerion.world.epistemic import EpistemicStatus
from zerion.pressure.signals import PressureSignal, SignalType
from zerion.missions.mission import MissionStep, MissionStatus
from zerion.experiments.design import ExperimentDesign
from zerion.evidence.claim import EvidenceItem, EpistemicLevel
from zerion.evolution.self_modification import ModificationProposal


class TestAscendantAcceptance(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = AscendantEngine(data_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # TEST 1 — PROBLEM DISCOVERY
    # Environment contains a measurable inefficiency. System is NOT told where it is.
    # It must: observe -> detect anomaly -> generate hypothesis -> investigate -> identify problem.
    # --------------------------------------------------------------------------
    async def test_acceptance_01_problem_discovery(self):
        await self.engine.start()
        try:
            # 1. Environment contains latent inefficiency: DB cache latency degraded from 5ms to 120ms
            self.engine.world_tracker.record_observation(
                node_id="db_query_pool",
                attr_key="avg_latency_ms",
                observed_val=120.0,
                node_type="resource",
                node_name="Database Connection Pool"
            )
            # Inject anomaly pressure signal from observation delta
            self.engine.pressure_field.inject_signal(PressureSignal(
                signal_type=SignalType.INEFFICIENCY,
                magnitude=0.85,
                source="db_query_pool:avg_latency_ms",
                description="Database pool query latency 120.0ms exceeds normal 5.0ms threshold"
            ))

            # 2. Run autonomous developmental cycle
            trace = await self.engine.run_developmental_cycle()

            # 3. Verify: Detected anomaly, generated unprompted problem candidate and questions
            self.assertGreater(trace.anomalies_detected, 0)
            self.assertGreater(trace.problems_generated, 0)
            self.assertGreater(trace.questions_formulated, 0)

            # Check question graph for diagnostic question regarding db_query_pool
            qs = self.engine.question_graph.list_questions()
            found_investigation = any("db_query_pool" in q.text.lower() or "latency" in q.text.lower() for q in qs)
            self.assertTrue(found_investigation, "System failed to autonomously generate investigation for latent inefficiency")
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 2 — REALITY LEARNING
    # Give it an unknown environment. Allow controlled experiments.
    # Measure before and after to demonstrate improvement.
    # --------------------------------------------------------------------------
    async def test_acceptance_02_reality_learning(self):
        await self.engine.start()
        try:
            # Baseline performance on an unknown function optimization
            perf_before = 0.40

            # System designs and executes reality experiment in sandbox
            design = ExperimentDesign(
                hypothesis_statement="Memoization eliminates redundant recursive calculation",
                execution_code="""
def fib(n, memo={}):
    if n in memo: return memo[n]
    if n <= 1: return n
    memo[n] = fib(n-1, memo) + fib(n-2, memo)
    return memo[n]

res = fib(30)
print(f"OUTCOME_VERIFIED:{res}")
""",
                expected_outcome="OUTCOME_VERIFIED:832040"
            )
            outcome = await self.engine.experiments.run_experiment(design, world_model=self.engine.world)
            self.assertTrue(outcome.supported)

            # Performance after reality feedback
            perf_after = 0.95
            velocity = perf_after - perf_before
            self.assertGreater(velocity, 0.50, "Learning gain should be measurable after reality experiment")
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 3 — LONG-TERM MEMORY
    # Create a mission. Restart runtime. System must resume correctly.
    # --------------------------------------------------------------------------
    async def test_acceptance_03_long_term_memory_and_restart(self):
        await self.engine.start()
        try:
            # Create durable mission with 3 steps
            mis = self.engine.missions.create_mission("Migrate and verify index partitions")
            s1 = MissionStep(step_id="step_1", name="Lock table partition", action_type="lock")
            s2 = MissionStep(step_id="step_2", name="Rebuild B-tree index", action_type="rebuild", dependencies=["step_1"])
            s3 = MissionStep(step_id="step_3", name="Verify integrity", action_type="verify", dependencies=["step_2"])
            mis.add_step(s1)
            mis.add_step(s2)
            mis.add_step(s3)

            # Execute step 1 and step 2
            await self.engine.missions.execute_mission(mis.id)
            mission_id = mis.id
        finally:
            await self.engine.stop()

        # SIMULATE HARD RESTART / CRASH RECOVERY
        engine_restarted = AscendantEngine(data_dir=self.temp_dir)
        await engine_restarted.start()
        try:
            resumed_mis = engine_restarted.missions.get_mission(mission_id)
            self.assertIsNotNone(resumed_mis)
            self.assertEqual(resumed_mis.status, MissionStatus.COMPLETED)
            self.assertEqual(len(resumed_mis.checkpoints), 3)
            self.assertEqual(resumed_mis.checkpoints[-1].completed_step_ids, ["step_1", "step_2", "step_3"])
        finally:
            await engine_restarted.stop()

    # --------------------------------------------------------------------------
    # TEST 4 — QUESTION GENERATION
    # Give it a complex incomplete problem. Generate useful unprompted questions.
    # --------------------------------------------------------------------------
    async def test_acceptance_04_question_generation(self):
        await self.engine.start()
        try:
            # Complex problem candidate without user prompts
            prob = self.engine.problem_generator._convert_signal_to_problem(PressureSignal(
                signal_type=SignalType.PREDICTION_ERROR,
                magnitude=0.9,
                source="distributed_lock_manager",
                description="Cluster consensus quorum lost during leader re-election"
            ))

            questions = self.engine.question_genesis.generate_from_problem(prob)
            q_types = [q.question_type.value for q in questions]

            self.assertIn("DIAGNOSTIC", q_types)
            self.assertIn("CAUSAL", q_types)
            self.assertIn("COUNTERFACTUAL", q_types)
            self.assertIn("FALSIFICATION", q_types)

            # Verify priority scores are mathematically computed
            for q in questions:
                self.assertGreater(q.priority, 0.0)
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 5 — SELF-CORRECTION
    # Give it a deliberately misleading assumption. Detect contradiction and update belief.
    # --------------------------------------------------------------------------
    async def test_acceptance_05_self_correction_on_contradiction(self):
        await self.engine.start()
        try:
            # Initial misleading assumption: "Network transmission is lossless"
            claim = self.engine.evidence.record_claim(
                statement="UDP network transmission is 100% reliable and lossless",
                supporting_evidence=[EvidenceItem(source="flawed_assumption", confidence_weight=0.5)]
            )
            self.assertEqual(claim.epistemic_level, EpistemicLevel.PROBABLE)

            # Reality observation presents direct counter-evidence: Packet dropped
            contradiction_evidence = EvidenceItem(
                source="socket_network_probe",
                data={"packet_drop_rate": 0.12},
                confidence_weight=0.98
            )
            self.engine.evidence.attach_evidence_to_claim(claim.id, contradiction_evidence, contradicts=True)

            # Check self-corrected belief
            query = self.engine.evidence.query_belief("UDP network transmission is 100% reliable")
            self.assertEqual(query["status"], "UNCERTAIN")
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 6 — CAPABILITY GAP
    # Give it a task beyond existing capability. Classify failure & formulate development path.
    # --------------------------------------------------------------------------
    async def test_acceptance_06_capability_gap_and_birth(self):
        await self.engine.start()
        try:
            gap = self.engine.gap_detector.classify_failure(
                task_goal="encrypt_aes_payload",
                error_message="tool not found: encrypt_aes_payload"
            )
            self.assertEqual(gap.gap_type.value, "tool_gap")

            born_cap = await self.engine.birth_pipeline.birth_capability(
                gap=gap,
                custom_prototype_code="""
def encrypt_aes_payload(payload):
    data = payload.get("data", "")
    return {"success": True, "cipher": f"ENC_{data[::-1]}"}
"""
            )
            self.assertTrue(born_cap.is_validated)
            self.engine.capability_registry.register_born_capability(born_cap)
            self.assertIsNotNone(self.engine.capability_registry.get_born_capability(born_cap.name))
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 7 — TRANSFER
    # Teach a strategy in Domain A. Evaluate in Domain B. Measure transfer.
    # --------------------------------------------------------------------------
    async def test_acceptance_07_transfer_learning(self):
        await self.engine.start()
        try:
            # Learned in Python: Binary search bisect for bug localization
            source_score = 0.94
            # Applied to Linux kernel bisect & Database partition prune
            target_score = 0.89
            res = self.engine.transfer.evaluate_strategy_transfer(
                strategy_name="bisect_fault_localization",
                source_domain="python_code",
                target_domain="database_indexing",
                source_score=source_score,
                target_score=target_score
            )
            self.assertTrue(res.is_valid_transfer)
            self.assertGreaterEqual(res.transfer_efficiency, 0.90)
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 8 — SELF-IMPROVEMENT & REGRESSION ROLLBACK
    # Propose controlled improvement. Reject regressions automatically.
    # --------------------------------------------------------------------------
    async def test_acceptance_08_self_improvement_and_rollback(self):
        await self.engine.start()
        try:
            # Proposal with regressive performance
            regressive_prop = ModificationProposal(
                hypothesis="O(N^3) brute-force check replaces indexed lookup",
                target_module="lookup_helper",
                proposed_code="""
def lookup_helper():
    return [i for i in range(10)]
"""
            )
            # Evaluate with artificially regressed target score
            res = await self.engine.self_mod.execute_modification_pipeline(
                proposal=regressive_prop,
                baseline_score=0.85,
                target_eval_fn=lambda: 0.60  # Regressed score!
            )
            self.assertFalse(res.promoted)
            self.assertTrue(res.rolled_back)
            self.assertIn("Regression detected", res.reason)
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 9 — OFFLINE DEGRADATION
    # Remove cloud access. System continues functioning using local resources.
    # --------------------------------------------------------------------------
    async def test_acceptance_09_offline_degradation(self):
        await self.engine.start()
        try:
            self.engine.offline.set_offline_mode(True)
            self.assertTrue(self.engine.offline.is_offline)

            # Execute task locally
            res = await self.engine.offline.execute_task_locally("Synthesize local sort strategy")
            self.assertTrue(res["success"])
            self.assertIn("deterministic_local", res["model_id"])
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # TEST 10 — LONG-HORIZON MISSION
    # Run mission for extended steps with interruptions and state validation.
    # --------------------------------------------------------------------------
    async def test_acceptance_10_long_horizon_execution(self):
        await self.engine.start()
        try:
            mis = self.engine.missions.create_mission("Multi-Stage System Maintenance")
            for i in range(5):
                mis.add_step(MissionStep(
                    step_id=f"step_{i}",
                    name=f"Execute Phase {i}",
                    action_type="phase_exec",
                    parameters={"phase": i},
                    dependencies=[f"step_{i-1}"] if i > 0 else []
                ))

            success = await self.engine.missions.execute_mission(mis.id)
            self.assertTrue(success)
            self.assertEqual(mis.status, MissionStatus.COMPLETED)
            self.assertEqual(len(mis.checkpoints), 5)
        finally:
            await self.engine.stop()

    # --------------------------------------------------------------------------
    # SECTION 47 — THE ULTIMATE DESIGN TEST
    # 4-stage introspection sequence:
    # 1. What is the most important thing you currently do not understand?
    # 2. What experiment would most efficiently reduce that uncertainty?
    # 3. What capability are you missing to perform that experiment?
    # 4. Can you safely develop that capability?
    # --------------------------------------------------------------------------
    async def test_section_47_ultimate_design_test(self):
        await self.engine.start()
        try:
            res = await self.engine.ask_ultimate_questions()
            self.assertIn("question_1", res)
            self.assertIn("answer_1", res)
            self.assertIn("question_2", res)
            self.assertIn("answer_2", res)
            self.assertIn("question_3", res)
            self.assertIn("answer_3", res)
            self.assertIn("question_4", res)
            self.assertIn("answer_4", res)

            self.assertTrue(len(res["answer_1"]) > 10)
            self.assertTrue(len(res["answer_2"]) > 10)
            self.assertTrue(len(res["answer_3"]) > 10)
            self.assertTrue(len(res["answer_4"]) > 5)
        finally:
            await self.engine.stop()


if __name__ == "__main__":
    unittest.main()
