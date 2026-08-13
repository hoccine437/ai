"""
Unit tests for Reality Experiment Engine & Sandbox
"""

import unittest
from zerion.experiments.sandbox import ExecutionSandbox
from zerion.experiments.design import ExperimentDesign
from zerion.experiments.engine import ExperimentEngine


class TestExperiments(unittest.IsolatedAsyncioTestCase):
    async def test_sandbox_execution_success_and_timeout(self):
        sandbox = ExecutionSandbox()
        # Successful code
        res = await sandbox.run_python_code("print('TEST_OUTPUT_123')")
        self.assertTrue(res.success)
        self.assertEqual(res.stdout, "TEST_OUTPUT_123")

        # Timeout code
        res_timeout = await sandbox.run_python_code("import time; time.sleep(3.0)", timeout_seconds=0.5)
        self.assertFalse(res_timeout.success)
        self.assertTrue(res_timeout.timed_out)

    async def test_experiment_loop_hypothesis_verification(self):
        engine = ExperimentEngine()
        design = ExperimentDesign(
            hypothesis_statement="Sum of integers from 1 to 5 equals 15",
            execution_code="print(sum(range(1, 6)))",
            expected_outcome="15"
        )
        outcome = await engine.run_experiment(design)
        self.assertTrue(outcome.supported)
        self.assertEqual(outcome.observed_value, "15")
        self.assertIsNotNone(outcome.evidence_id)


if __name__ == "__main__":
    unittest.main()
