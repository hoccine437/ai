"""
Entity-Level Validation Test Suite for ZERION-X Singularity Architecture
Verifies:
- Model-Independent Persistent Identity & Values
- Cognitive Entity Lifecycle State Transitions
- Cognitive Autophagy (Replacing Inferior Cognitive Mechanisms with Validated Alternatives)
- Predictive Self-Modeling & Real Brier Calibration
- Continuous Master Development Loop
"""

import os
import shutil
import tempfile
import unittest

from zerion.entity.identity import CognitiveEntityIdentity
from zerion.entity.state import CognitiveEntityStateStore, EntityLifecycleState
from zerion.architecture.autophagy import CognitiveAutophagyEngine
from zerion.self_model.self_predictor import SelfPredictor
from zerion.engine import AscendantEngine


class TestSingularityEntity(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="singularity_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_entity_identity_and_commitments(self):
        # ONE canonical identity: the entity adapter resolves to the canonical
        # IdentityCore constants ("ZERION-X ASCENDANT") — never a second name.
        identity = CognitiveEntityIdentity()
        self.assertEqual(identity.entity_name, "ZERION-X ASCENDANT")
        self.assertEqual(identity.entity_id, "ascendant-core-v1")
        self.assertEqual(len(identity.commitments), 5)
        digest = identity.get_identity_digest()
        self.assertTrue(len(digest) > 20)

    def test_entity_identity_derives_from_canonical_core(self):
        from zerion.identity.persistence import IdentityCore
        core = IdentityCore(storage_path=os.path.join(self.temp_dir, "identity.json"))
        identity = CognitiveEntityIdentity(identity_core=core)
        self.assertEqual(identity.entity_name, core.system_name)
        self.assertEqual(identity.entity_id, core.system_id)
        self.assertEqual(identity.get_identity_digest(), core.get_identity_hash())

    def test_entity_state_store_and_snapshots(self):
        db_file = os.path.join(self.temp_dir, "entity.db")
        store = CognitiveEntityStateStore(db_path=db_file)

        # Valid transition path only: STANDBY -> BOOTING -> PERCEIVING.
        store.transition_state(EntityLifecycleState.BOOTING)
        store.transition_state(EntityLifecycleState.PERCEIVING)
        self.assertEqual(store.current_state, EntityLifecycleState.PERCEIVING)

        snap = store.capture_snapshot(objectives_count=2, strategies_count=4)
        self.assertEqual(snap.lifecycle_state, EntityLifecycleState.PERCEIVING)
        self.assertEqual(snap.active_strategies_count, 4)

    async def test_cognitive_autophagy_engine(self):
        db_file = os.path.join(self.temp_dir, "autophagy.db")
        autophagy = CognitiveAutophagyEngine(db_path=db_file)

        # Evaluate replacing an obsolete strategy compiler with a candidate
        record = await autophagy.evaluate_subsystem_replacement(
            subsystem_name="StrategyCompiler",
            current_impl_name="LegacySinglePathCompiler",
            candidate_impl_name="DynamicCognitiveCompiler3"
        )
        self.assertTrue(record.canary_passed)
        self.assertTrue(record.promoted)
        self.assertGreater(record.measured_gain, 0.0)

    def test_predictive_self_modeling_and_calibration(self):
        predictor = SelfPredictor()
        pred = predictor.predict_task_execution(
            task_id="task_calc_101",
            task_domain="database",
            task_difficulty=0.4,
            historical_strategy_reliability=0.92
        )
        self.assertGreater(pred.predicted_success_prob, 0.8)

        # Actual execution matches expectation
        delta = predictor.record_actual_outcome(
            prediction=pred,
            actual_strategy="strategy_database",
            actual_success=True,
            actual_latency_ms=15.0
        )
        self.assertTrue(delta.strategy_matched)
        self.assertLess(delta.brier_penalty, 0.05)

    async def test_singularity_master_engine_cycle(self):
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            trace = await engine.run_developmental_cycle()
            self.assertIsNotNone(trace.cycle_id)
            self.assertGreater(len(engine.entity_state.identity.commitments), 0)
        finally:
            await engine.stop()


if __name__ == "__main__":
    unittest.main()
