"""
ZERION X — ASCENDANT ∞ deterministic end-to-end runtime proof (mission §18).

Drives one real path through the canonical runtime, hop by hop, with NO mocks
and NO fabricated values:

FAILURE
→ FAILURE CLASSIFICATION (CapabilityGapDetector.classify_failure)
→ QUESTION (QuestionGenesis.generate_from_problem)
→ HYPOTHESIS (declarative formulation from the classified gap)
→ STRATEGY CANDIDATE (CognitiveGenesisPipeline — real 10-stage pipeline,
  real sandbox stages 4/5/7, stage 8 honestly NOT_MEASURED)
→ SELF-EXPERIMENT (SelfExperimentationEngine with real measured control /
  treatment scores from sandbox execution; effect size derived from the
  measurement, never invented)
→ VALIDATION (decision + persisted trial record)
→ STRATEGY REGISTRATION (StrategyRegistry)
→ LINEAGE RECORD (record_lineage with the MEASURED benchmark gain)
→ GENOME/PHENOTYPE IMPACT (genome_manager.get_phenotype →
  AdaptiveCognitiveController.allocate_cognition — real allocation values
  derived from the phenotype)
→ RUNTIME EXECUTION (ExecutionSandbox on an unseen input)
→ OUTCOME (real pass/fail)
→ TELEMETRY (CognitiveTelemetryLogger trace + RuntimeEvidence snapshot)
"""

import shutil
import tempfile
import unittest

from zerion.capabilities.detector import GapType
from zerion.engine import AscendantEngine
from zerion.pressure.generator import ProblemCandidate
from zerion.runtime.evidence import collect_runtime_evidence
from zerion.telemetry.logger import CognitiveTelemetryRecord

# A real executable strategy that passes genesis stage 4 (no hard-coded score
# patterns) and sandbox stages 5/7. Honest confidence is None until a real
# invocation observes one.
STRATEGY_CODE = '''\
def execute_strategy(context):
    if not isinstance(context, dict):
        return {"success": False, "error": "Invalid context"}
    values = context.get("values", [])
    probe = context.get("probe", 0)
    resolved = any(v == probe for v in values)
    return {"success": True, "resolved_target": resolved,
            "strategy": "bloom_indexer_v1", "confidence": None}
'''

# Control: naive implementation that always misses the probe (no indexer).
NAIVE_CODE = '''\
def execute_strategy(context):
    return {"success": True, "resolved_target": False, "confidence": None}
'''


def harness(values, probe):
    """Test harness. The caller prepends the code under test, which must
    define ``execute_strategy`` — the harness never defines it itself."""
    return (
        'res = execute_strategy({"values": %r, "probe": %r})\n'
        'assert res["success"] is True, f"failed: {res}"\n'
        'assert res["resolved_target"] is True, f"missed: {res}"\n'
        'print("TESTS_PASSED")\n' % (values, probe))


class TestAscendantEndToEndRuntimeProof(unittest.IsolatedAsyncioTestCase):
    async def test_full_developmental_chain_is_real(self):
        tmp = tempfile.mkdtemp(prefix="asc_e2e_")
        engine = AscendantEngine(data_dir=tmp)
        try:
            await engine.start()

            # 1. FAILURE ----------------------------------------------------
            goal = "bloom_filter_indexer"
            err = "tool not found: bloom_filter"

            # 2. FAILURE CLASSIFICATION ------------------------------------
            gap = engine.gap_detector.classify_failure(goal, err)
            self.assertEqual(gap.gap_type, GapType.TOOL_GAP)
            self.assertTrue(gap.missing_capability_name)

            # 3. QUESTION ---------------------------------------------------
            questions = engine.question_genesis.generate_from_problem(
                ProblemCandidate(title=goal, description=err, urgency=0.9,
                                 source="failure_recovery"))
            self.assertTrue(questions)

            # 4. HYPOTHESIS -------------------------------------------------
            hypothesis = (
                f"Implementing a verified strategy for "
                f"'{gap.missing_capability_name}' resolves '{goal}' "
                f"(failure: {err})")

            # 5. STRATEGY CANDIDATE (real 10-stage genesis pipeline) --------
            synth = await engine.strategy_genesis.synthesize_strategy(
                problem_description=err, domain="indexing",
                custom_code_template=STRATEGY_CODE)
            self.assertTrue(synth.success, msg=synth.error_message)
            stages = {s.stage_name for s in synth.stages_log}
            self.assertIn("4_STATIC_ANALYSIS", stages)
            self.assertIn("5_SANDBOX_TESTS", stages)     # real sandbox exec
            self.assertIn("7_ADVERSARIAL_TEST", stages)  # real sandbox exec
            stage8 = [s for s in synth.stages_log
                      if s.stage_name == "8_BLIND_BENCHMARK"]
            self.assertTrue(stage8)
            self.assertIn("NOT_MEASURED", stage8[0].details)
            strategy = synth.strategy

            # 6. SELF-EXPERIMENT with REAL measured scores -------------------
            # Control/treatment scores come from actual sandbox pass/fail.
            ctrl_sb = await engine.sandbox.run_python_code(
                NAIVE_CODE + "\n" + harness([1, 2, 3], 2), timeout_seconds=5.0)
            treat_sb = await engine.sandbox.run_python_code(
                STRATEGY_CODE + "\n" + harness([1, 2, 3], 2),
                timeout_seconds=5.0)
            control_score = (1.0 if ctrl_sb.success
                             and "TESTS_PASSED" in ctrl_sb.stdout else 0.0)
            treatment_score = (1.0 if treat_sb.success
                               and "TESTS_PASSED" in treat_sb.stdout else 0.0)
            self.assertEqual(control_score, 0.0)
            self.assertEqual(treatment_score, 1.0)

            report = await engine.self_experimentation.run_architecture_experiment(
                hypothesis=hypothesis,
                target_dimension="bloom_filter_strategy",
                control_val={"score": control_score},
                treatment_val={"score": treatment_score},
                sample_size=3,
                target_phenotype="coding",
                eval_fn=lambda cfg: float(cfg["score"]),
            )

            # 7. VALIDATION --------------------------------------------------
            # Effect size is computed from the measured scores — not invented.
            self.assertEqual(report.decision, "ACCEPTED_FOR_PHENOTYPE")
            self.assertAlmostEqual(
                report.effect_size,
                treatment_score - control_score, places=4)
            self.assertIsNotNone(report.control_score)
            self.assertIsNotNone(report.treatment_score)
            # Persisted, queryable history (provenance).
            self.assertIn(
                report.experiment_id,
                [t.experiment_id
                 for t in engine.self_experimentation._trials_history])

            # 8. STRATEGY REGISTRATION ---------------------------------------
            sid = engine.strategy_registry.register_strategy(strategy)
            self.assertIsNotNone(engine.strategy_registry.get_strategy(sid))
            self.assertIn(
                strategy,
                engine.strategy_registry.find_strategy_for_domain("indexing"))

            # 9. LINEAGE RECORD (gain = measured experiment effect) ----------
            node = engine.strategy_evolution.record_lineage(
                sid, parent_id=None, derivation_type="self_experiment",
                gain=float(report.effect_size))
            self.assertEqual(node.derivation_type, "self_experiment")
            self.assertEqual(node.lineage_depth, 1)
            # benchmark_gain is the measured effect — INV-003.
            self.assertEqual(node.benchmark_gain, float(report.effect_size))

            # 10. GENOME/PHENOTYPE IMPACT ------------------------------------
            phenotype = engine.genome_manager.get_phenotype(strategy.domain)
            self.assertIsNotNone(phenotype)
            allocation = engine.adaptive_cognition.allocate_cognition(
                task_id="e2e_proof", uncertainty=0.7, difficulty=0.7,
                novelty=0.5, risk=0.5, phenotype=phenotype,
                available_compute_mb=1024, is_offline=False)
            # The genome's phenotype drives the real allocation: NORMAL mode
            # with phenotype-derived depth and (bounded) parallel width.
            self.assertEqual(allocation.selected_mode, "NORMAL")
            self.assertEqual(allocation.reasoning_depth,
                             phenotype.reasoning_depth)
            self.assertEqual(allocation.parallel_paths,
                             min(3, phenotype.parallel_width))

            # 11. RUNTIME EXECUTION + 12. OUTCOME (unseen input) -------------
            outcome_sb = await engine.sandbox.run_python_code(
                STRATEGY_CODE + "\n" + harness([9, 8, 7], 8),
                timeout_seconds=5.0)
            self.assertTrue(outcome_sb.success)
            self.assertIn("TESTS_PASSED", outcome_sb.stdout)

            # 13. TELEMETRY --------------------------------------------------
            engine.telemetry.record(CognitiveTelemetryRecord(
                strategy_id=sid,
                experiment_id=report.experiment_id,
                failure_class=gap.gap_type.value,
                result_status="SUCCESS",
                metadata={"effect_size": report.effect_size,
                          "decision": report.decision}))
            traces = engine.telemetry.get_recent_traces()
            self.assertTrue(any(t.strategy_id == sid for t in traces))
            evidence = collect_runtime_evidence(engine)
            self.assertEqual(evidence.source, "engine_live_state")
            self.assertGreaterEqual(evidence.flywheel_cycles, 0)
            self.assertEqual(evidence.brier_samples, 0)  # honest NOT_MEASURED
        finally:
            await engine.stop()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
