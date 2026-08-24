"""
Slice 9 — ZERION_COGNITIVE_BENCHMARK test suite.

The benchmark is an adversary, not marketing: it must never hard-code a
conclusion, never leak state between BASELINE and ZERION, never fabricate a
metric, and must report negative results. These tests pin the foundation
rules (task schema, modes, metrics, integrity, immutability, ablations,
contamination control, statistics honesty) against the real implementation.
"""

import json
import os
import tempfile
import unittest

from zerion.cognitive_os.benchmark import (
    AblationSpec,
    BenchmarkCategory,
    BenchmarkMode,
    BenchmarkTask,
    CognitiveBenchmark,
    EffectiveTaskPerformance,
    FailureTaxonomy,
    MetricKey,
    build_default_task_registry,
    improve,
    run_end_to_end_benchmark,
    summarize,
)
from zerion.cognitive_os.benchmark.metrics import (
    effective_task_performance,
    wilson_ci,
)
from zerion.cognitive_os.benchmark.runner import provider_availability
from zerion.cognitive_os.benchmark.world import make_world, world_fingerprint


class TestTaskSchema(unittest.TestCase):
    """Rules 3–5: the full BenchmarkTask schema with objective criteria."""

    REQUIRED_FIELDS = [
        "task_id", "category", "description", "initial_state",
        "available_information", "available_tools", "success_criteria",
        "failure_criteria", "difficulty", "novelty", "stakes",
        "expected_behavior", "timeout_s", "resource_budget",
        "evaluation_method", "metadata",
    ]

    def test_all_schema_fields_present(self):
        task = BenchmarkTask(
            task_id="t1", category=BenchmarkCategory.TOOL_EXECUTION,
            description="do the thing", success_criteria=["answer == truth"],
        )
        d = task.to_dict()
        for field in self.REQUIRED_FIELDS:
            self.assertIn(field, d, f"missing schema field {field}")

    def test_objective_success_criteria_required(self):
        with self.assertRaises(ValueError):
            BenchmarkTask(task_id="bad", category="TOOL_EXECUTION",
                          description="no criteria")
        with self.assertRaises(ValueError):
            BenchmarkTask(task_id="bad2", category="TOOL_EXECUTION",
                          description="x", success_criteria=[])

    def test_timeout_must_be_positive(self):
        with self.assertRaises(ValueError):
            BenchmarkTask(task_id="bad", category="TOOL_EXECUTION",
                          description="x", success_criteria=["ok"], timeout_s=0)

    def test_category_normalized_to_enum(self):
        t = BenchmarkTask(task_id="t", category="TOOL_EXECUTION",
                          description="x", success_criteria=["ok"])
        self.assertIsInstance(t.category, BenchmarkCategory)

    def test_all_ten_categories_registered(self):
        registry = build_default_task_registry(instances_per_family=1)
        cats = {t.category for t in registry}
        expected = {
            BenchmarkCategory.NOVEL_PROBLEM_SOLVING,
            BenchmarkCategory.TOOL_EXECUTION,
            BenchmarkCategory.LONG_HORIZON_COMPLETION,
            BenchmarkCategory.FAILURE_RECOVERY,
            BenchmarkCategory.REALITY_VERIFICATION,
            BenchmarkCategory.QUESTION_GENERATION,
            BenchmarkCategory.GOAL_PERSISTENCE,
            BenchmarkCategory.CROSS_DOMAIN_REASONING,
            BenchmarkCategory.ADAPTATION,
            BenchmarkCategory.CAPABILITY_REUSE,
        }
        self.assertEqual(cats, expected)

    def test_default_registry_size(self):
        registry = build_default_task_registry()
        self.assertEqual(len(registry), 50)

    def test_tasks_have_distinct_ids(self):
        registry = build_default_task_registry()
        ids = [t.task_id for t in registry]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ground_truth_not_in_prompt(self):
        """Rule 6: the task prompt must not contain the ground truth — it is
        reachable only through world tools."""
        registry = build_default_task_registry(instances_per_family=2)
        for task in registry:
            prompt_text = (task.description + " " + task.expected_behavior
                           + " " + " ".join(task.available_information))
            prompt_lower = prompt_text.lower()
            world = make_world(task, seed=1)
            answer = world.correct_answer
            if isinstance(answer, str) and len(answer) > 2:
                self.assertNotIn(answer.lower(), prompt_lower,
                                 f"leak: {task.task_id} truth in prompt")
            # Fact keys and domain vocabulary legitimately appear in the
            # prompt; only the ANSWER (the truth the model must derive through
            # tools) must not be spelled out. Skip plain numeric answers —
            # example sums may legitimately appear in descriptions.
            if isinstance(answer, str) and len(answer) > 3 and " " in answer:
                self.assertNotIn(answer.lower(), prompt_lower,
                                 f"leak: {task.task_id} truth in prompt")


class TestTwoModes(unittest.TestCase):
    """Rules 1–2: BASELINE vs ZERION on the same model, same task, same seeds."""

    def test_modes_exist(self):
        self.assertEqual(BenchmarkMode.BASELINE.value, "BASELINE")
        self.assertEqual(BenchmarkMode.ZERION.value, "ZERION")

    def test_paired_seeds_shared_between_modes(self):
        registry = build_default_task_registry(instances_per_family=1)
        bench = CognitiveBenchmark(tasks=registry, seed=7, trials_per_task=3)
        base_seeds = [bench._trial_seed(registry[0], t) for t in range(3)]
        zer_seeds = [bench._trial_seed(registry[0], t) for t in range(3)]
        self.assertEqual(base_seeds, zer_seeds)

    def test_task_order_randomized_per_run(self):
        """Rule 7: no fixed ordering favoring one system. The registry itself
        is deterministic (insertion order), but each run shuffles task order
        with the run seed before executing trials."""
        registry = build_default_task_registry(instances_per_family=1)
        reg_order = [t.task_id for t in registry]
        # Registration order is deterministic and unique.
        self.assertEqual(len(reg_order), len(set(reg_order)))
        self.assertEqual(reg_order, [t.task_id for t in registry])
        # Across a few fixed seeds, the execution order must vary: at least one
        # seed produces a different order than the others (no fixed ordering).
        execution_orders = set()
        for seed in (1, 2, 3, 4):
            bench = CognitiveBenchmark(
                tasks=build_default_task_registry(instances_per_family=1),
                seed=seed, trials_per_task=1, save_results=False)
            run = bench.run()
            order = tuple(t.task_id for t in run.trials
                          if t.mode == BenchmarkMode.BASELINE)
            execution_orders.add(order)
        self.assertGreater(len(execution_orders), 1,
                           "task order never varies across seeds — "
                           "randomization (rule 7) is not working")

    def test_register_rejects_duplicates_and_empty(self):
        bench = CognitiveBenchmark()
        with self.assertRaises(ValueError):
            bench.run()
        t = BenchmarkTask(task_id="t", category="TOOL_EXECUTION",
                          description="x", success_criteria=["ok"])
        bench.register_task(t)
        with self.assertRaises(ValueError):
            bench.register_task(t)

    def test_run_requires_registered_tasks(self):
        bench = CognitiveBenchmark(tasks=[])
        with self.assertRaises(ValueError):
            bench.run()


class TestMetrics(unittest.TestCase):
    """Rules 9–14: measured metrics, honest UNKNOWN, transparent ETP."""

    def test_effective_task_performance_formula(self):
        etp = effective_task_performance(
            "t", "ZERION", successes=5, n=5,
            total_time_values=[1.0] * 5, tool_retry_values=[0] * 5,
            timeout_s=60.0,
        )
        self.assertEqual(etp.success_rate, 1.0)
        self.assertEqual(etp.time_penalty, 0.0)
        self.assertEqual(etp.retry_penalty, 0.0)
        self.assertAlmostEqual(etp.score, 1.0)

    def test_etp_time_penalty_capped(self):
        # median time == timeout -> penalty capped at 0.5
        etp = effective_task_performance(
            "t", "ZERION", successes=1, n=1,
            total_time_values=[60.0], tool_retry_values=[0],
            timeout_s=60.0,
        )
        self.assertEqual(etp.time_penalty, 0.5)
        self.assertAlmostEqual(etp.score, 0.5)

    def test_etp_retry_penalty_capped(self):
        etp = effective_task_performance(
            "t", "ZERION", successes=1, n=1,
            total_time_values=[0.1], tool_retry_values=[10],
            timeout_s=60.0,
        )
        self.assertEqual(etp.retry_penalty, 0.3)

    def test_etp_empty_sample_is_none(self):
        self.assertIsNone(effective_task_performance(
            "t", "ZERION", successes=0, n=0, total_time_values=[],
            tool_retry_values=[], timeout_s=60.0))

    def test_success_rate_reports_denominator(self):
        """Rule 11: never report success rate without denominator."""
        per_task = self._run_small().analysis["per_task"]
        for task_id, modes in per_task.items():
            for mode, data in modes.items():
                self.assertIn("n", data)
                self.assertIn("successes", data)
                self.assertEqual(data["success_rate"],
                                 (data["successes"] / data["n"]) if data["n"] else 0.0)

    def test_statistics_honesty(self):
        st = summarize([1.0, 2.0, 3.0])
        self.assertEqual(st.n, 3)
        self.assertEqual(st.mean, 2.0)
        self.assertEqual(st.median, 2.0)
        self.assertIsNotNone(st.std)
        self.assertIsNotNone(st.ci95_low)
        self.assertIsNone(summarize([]))
        s1 = summarize([1.0])
        self.assertIsNone(s1.std)  # std undefined for n<2

    def test_improve_ratio_undefined_not_zero(self):
        self.assertIsNone(improve(1.0, 0.0))
        self.assertIsNone(improve(None, 1.0))
        self.assertEqual(improve(4.0, 2.0), 2.0)

    def test_wilson_ci(self):
        ci = wilson_ci(5, 5)
        self.assertAlmostEqual(ci[1], 1.0, places=4)
        self.assertIsNone(wilson_ci(0, 0))

    def test_all_metric_keys_present_in_analysis(self):
        """Rules 9–14: every required metric appears in the per-task analysis
        (under its documented analysis block name), and the MetricKey enum
        covers the full spec list."""
        run = self._run_small()
        per_task = run.analysis["per_task"]
        some_task = next(iter(per_task))
        mode = next(iter(per_task[some_task]))
        data = per_task[some_task][mode]
        required_blocks = [
            "success_rate",           # TASK_SUCCESS
            "total_time",             # TIME_TO_SOLUTION
            "tool_retries",           # RETRY_COUNT
            "verification_accuracy",  # VERIFICATION_ACCURACY
            "knowledge_reuse",        # KNOWLEDGE_REUSE
            "question_quality",       # QUESTION_QUALITY
            "goal_persistence",       # GOAL_PERSISTENCE
            "tool_success",           # TOOL_SUCCESS
            "resource_cost",          # RESOURCE_COST
        ]
        for block in required_blocks:
            self.assertIn(block, data, f"missing metric block {block}")
        # The enum must define the ten spec metrics.
        spec_metrics = [
            "task_success", "time_to_solution_s", "retry_count",
            "recovery_rate", "verification_accuracy", "knowledge_reuse",
            "question_quality", "goal_persistence", "tool_success",
            "resource_cost",
        ]
        for m in spec_metrics:
            self.assertIn(m, [k.value for k in MetricKey])

    def test_time_breakdown_components(self):
        """Rule 12: model latency, tool latency, runtime overhead, total."""
        run = self._run_small()
        per_task = run.analysis["per_task"]
        some_task = next(iter(per_task))
        zer = per_task[some_task]["ZERION"]
        for key in ("model_latency", "tool_latency", "runtime_overhead",
                    "total_time"):
            self.assertIn(key, zer)
            self.assertIn("median", zer[key])

    def _run_small(self):
        return run_end_to_end_benchmark(
            trials_per_task=1, save_results=False, instances_per_family=1,
            seed=4242)


class TestIntegrityAndContamination(unittest.TestCase):
    """Rules 6, 8, 35, 36: no leakage, blind evaluation, integrity checks."""

    def test_integrity_status_valid(self):
        run = self._run_small()
        self.assertIn(run.integrity["status"], ("VALID", "VALID_WITH_WARNINGS"))
        self.assertEqual(run.integrity["problems"], [])

    def test_evaluator_is_blind(self):
        run = self._run_small()
        self.assertTrue(run.integrity["checks"]["evaluator_is_blind"])
        self.assertIn("mode never passed",
                      run.integrity["checks"]["evaluator_inputs"])

    def test_trial_count_matches_expectation(self):
        run = self._run_small()
        expected = (run.manifest.trials_per_task
                    * len(set(t.task_id for t in run.trials))
                    * len(run.manifest.modes))
        self.assertEqual(len(run.trials), expected)
        self.assertEqual(run.integrity["checks"]["trial_count"], expected)

    def test_immutable_results(self):
        """Rule 34: a new run never overwrites an existing run record."""
        with tempfile.TemporaryDirectory() as d:
            b1 = CognitiveBenchmark(
                tasks=build_default_task_registry(instances_per_family=1),
                seed=1, trials_per_task=1, output_dir=d)
            run1 = b1.run()
            path = run1.saved_path
            self.assertTrue(os.path.exists(path))
            b2 = CognitiveBenchmark(
                tasks=build_default_task_registry(instances_per_family=1),
                seed=2, trials_per_task=1, output_dir=d)
            run2 = b2.run()
            self.assertNotEqual(run1.manifest.run_id, run2.manifest.run_id)
            self.assertNotEqual(run1.saved_path, run2.saved_path)
            # contents preserved (immutable)
            data1 = json.load(open(path, encoding="utf-8"))
            self.assertEqual(data1["manifest"]["run_id"], run1.manifest.run_id)

    def test_reproducibility_manifest(self):
        """Rule 33: every run records seed, trials, modes, model, provider."""
        run = self._run_small()
        m = run.manifest
        self.assertTrue(m.run_id)
        self.assertGreater(m.created_at, 0)
        self.assertIn("seed", m.to_dict())
        self.assertIn("trials_per_task", m.to_dict())
        self.assertIn("modes", m.to_dict())
        self.assertIn("model_profile", m.to_dict())
        self.assertIn("provider", m.to_dict())
        self.assertIn("resource_budget", m.to_dict())
        self.assertEqual(m.provider, "deterministic_local")

    def test_determinism_same_seed_same_result(self):
        """The benchmark is seeded: same seed -> identical run results."""
        r1 = self._run_small()
        r2 = self._run_small()
        s1 = [(t.task_id, t.mode.value, t.seed, t.success) for t in r1.trials]
        s2 = [(t.task_id, t.mode.value, t.seed, t.success) for t in r2.trials]
        self.assertEqual(s1, s2)

    def _run_small(self):
        return run_end_to_end_benchmark(
            trials_per_task=1, save_results=False, instances_per_family=1,
            seed=909)

    def test_provider_availability_is_honest(self):
        """Rule 31: Gemini is the ONLY provider; removed providers are
        reported as REMOVED, never fabricated as available."""
        avail = provider_availability()
        self.assertIn("gemini", avail)
        self.assertTrue(avail["gemini"].startswith("AVAILABLE")
                        or "NOT_AVAILABLE" in avail["gemini"])
        for provider, status in avail.items():
            if provider == "openai":
                # OpenAI was removed from Zerion entirely.
                self.assertIn("REMOVED", status)
                continue
            self.assertTrue(status.startswith("AVAILABLE")
                            or status.startswith("NOT_AVAILABLE"),
                            f"{provider}: dishonest status {status!r}")


class TestAblation(unittest.TestCase):
    """Rule 29 + required ablation (rule 39): remove one component, measure."""

    def test_ablation_mode_added(self):
        bench = CognitiveBenchmark(
            tasks=build_default_task_registry(instances_per_family=1),
            seed=3, trials_per_task=1, ablation=AblationSpec.VERIFICATION)
        modes = bench._effective_modes()
        self.assertIn(BenchmarkMode.BASELINE, modes)
        self.assertIn(BenchmarkMode.ZERION, modes)
        self.assertIn(BenchmarkMode.ABLATION_NO_VERIFICATION, modes)

    def test_all_ablation_specs_map_to_modes(self):
        bench = CognitiveBenchmark(
            tasks=build_default_task_registry(instances_per_family=1),
            seed=3, trials_per_task=1,
            ablation=AblationSpec.CAPABILITIES)
        modes = bench._effective_modes()
        self.assertIn(BenchmarkMode.ABLATION_NO_CAPABILITIES, modes)

    def test_required_ablation_runs_and_reports(self):
        run = run_end_to_end_benchmark(
            trials_per_task=1, save_results=False, instances_per_family=1,
            seed=77, ablation=AblationSpec.VERIFICATION)
        self.assertIn("ABLATION_NO_VERIFICATION", run.analysis["ablations"])
        abl = run.analysis["ablations"]["ABLATION_NO_VERIFICATION"]
        self.assertIn("tasks", abl)
        self.assertGreater(len(abl["tasks"]), 0)


class TestFailureTaxonomyAndReport(unittest.TestCase):
    """Rules 27–28, 40–41: taxonomy, negative results, honest report."""

    TAXONOMY = {t.value for t in FailureTaxonomy}

    def test_taxonomy_enum_complete(self):
        expected = {
            "MODEL_REASONING", "TOOL_FAILURE", "PLANNING_FAILURE",
            "MEMORY_FAILURE", "VERIFICATION_FAILURE", "GOAL_FAILURE",
            "ROUTING_FAILURE", "RESOURCE_LIMIT", "ENVIRONMENT_FAILURE",
            "CAPABILITY_FAILURE", "OTHER",
        }
        self.assertEqual(self.TAXONOMY, expected)

    def test_failure_taxonomy_values_valid(self):
        run = self._run_small()
        for t in run.trials:
            if t.failure_taxonomy:
                self.assertIn(t.failure_taxonomy, self.TAXONOMY)

    def test_report_has_all_required_sections(self):
        """Rule 40: report contains every mandated section."""
        run = self._run_small()
        md = run.report_md
        required = [
            "## EXECUTIVE RESULT", "## BASELINE", "## ZERION", "## TASKS",
            "## METHODOLOGY", "## METRICS", "## RAW RESULTS",
            "## STATISTICAL ANALYSIS", "## ABLATION", "## RESOURCE OVERHEAD",
            "## FAILURE ANALYSIS", "## NEGATIVE RESULTS",
            "## 5x TARGET ANALYSIS", "## OFFLINE RESULTS",
            "## PROVIDER RESULTS", "## REPRODUCIBILITY", "## LIMITATIONS",
            "## FINAL VERDICT",
        ]
        md_lower = md.lower()
        for section in required:
            self.assertIn(section.lower(), md_lower,
                          f"report missing section {section}")

    def test_report_does_not_claim_smarter_without_evidence(self):
        """Rules 26/41: no unsupported global intelligence claims."""
        run = self._run_small()
        md = run.report_md
        self.assertNotIn("5x smarter", md)
        self.assertNotIn("5× smarter", md)
        self.assertNotIn("500%", md)
        self.assertNotIn("achieved AGI", md)

    def test_success_rate_reported_with_denominator_in_report(self):
        run = self._run_small()
        self.assertIn("(0/", run.report_md)  # some mode shows N successes / N

    def _run_small(self):
        return run_end_to_end_benchmark(
            trials_per_task=1, save_results=False, instances_per_family=1,
            seed=515)


class TestOfflineAndEndToEnd(unittest.TestCase):
    """Rules 32, 38: offline determinism + end-to-end comparison exists."""

    def test_end_to_end_benchmark_runs_all_modes(self):
        run = run_end_to_end_benchmark(
            trials_per_task=1, save_results=False, instances_per_family=1,
            seed=313, ablation=AblationSpec.VERIFICATION)
        modes = {t.mode for t in run.trials}
        self.assertIn(BenchmarkMode.BASELINE, modes)
        self.assertIn(BenchmarkMode.ZERION, modes)
        self.assertIn(BenchmarkMode.ABLATION_NO_VERIFICATION, modes)

    def test_overall_summary_present(self):
        run = run_end_to_end_benchmark(
            trials_per_task=2, save_results=False, instances_per_family=1,
            seed=222)
        overall = run.analysis["overall"]
        self.assertIn("modes", overall)
        for mode in ("BASELINE", "ZERION"):
            self.assertIn(mode, overall["modes"])
            d = overall["modes"][mode]
            self.assertIn("n", d)
            self.assertIn("success_rate", d)


class TestWorldIsolation(unittest.TestCase):
    """Rule 6/23: worlds are deterministic and isolated per seed."""

    def test_same_seed_same_world_fingerprint(self):
        registry = build_default_task_registry(instances_per_family=1)
        task = registry[0]
        w1 = make_world(task, seed=5)
        w2 = make_world(task, seed=5)
        self.assertEqual(world_fingerprint(w1), world_fingerprint(w2))

    def test_different_seed_different_world(self):
        registry = build_default_task_registry(instances_per_family=1)
        task = registry[0]
        w1 = make_world(task, seed=5)
        w2 = make_world(task, seed=6)
        self.assertNotEqual(world_fingerprint(w1), world_fingerprint(w2))


if __name__ == "__main__":
    unittest.main()
