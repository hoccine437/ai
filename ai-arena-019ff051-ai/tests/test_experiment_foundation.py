"""
Slice 3 — Reality Feedback (Experiment / Evidence / Belief) test suite.

Covers: Experiment model/store, controlled-testing contracts, Evidence &
Provenance (mode honesty, fabrication, dedup, staleness), Belief revision rules
(model output can't confirm, never overwrite history), RealityExperimentEngine
executors, safety gates, failure handling, the required end-to-end
QUESTION -> HYPOTHESES -> EXPERIMENT -> OBSERVATION -> COMPARISON -> BELIEF UPDATE
scenario, restart persistence and adversarial cases. Runs entirely without an LLM.

Run with:
    python3 -m unittest tests.test_experiment_foundation -v
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

from zerion.runtime.event_bus import AsyncEventBus
from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.experiment import (
    Experiment,
    ExperimentLifecycle,
    ExperimentStore,
    ExperimentStoreIntegrityError,
    ExperimentTransitionError,
    ExperimentType,
    ExperimentValidationError,
    transition,
)
from zerion.cognitive_os.evidence import (
    Evidence,
    EvidenceMode,
    EvidenceStore,
    EvidenceStoreIntegrityError,
    EvidenceValidationError,
    EvidenceVerdict,
    MODE_WEIGHT,
    Provenance,
)
from zerion.cognitive_os.belief import (
    Belief,
    BeliefLifecycle,
    BeliefRevision,
    BeliefStore,
    BeliefStoreIntegrityError,
)
from zerion.cognitive_os.experiment_engine import (
    ExperimentPermissions,
    RealityExperimentEngine,
    ExperimentExecutionError,
    ResourceUnavailableError,
    SafetyViolationError,
    ToolExecutionError,
)
from zerion.cognitive_os.hypothesis import (
    Hypothesis,
    HypothesisLifecycle,
    HypothesisStore,
)
from zerion.cognitive_os.question import Question, QuestionStore
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.engine import AscendantEngine


def _trigger(etype, payload=None, priority=70):
    return Event(event_type=etype, payload=payload if payload is not None else {},
                 source="test", priority=priority)


def _belief(statement="A normally precedes B.", conf=0.7, status=BeliefLifecycle.PREDICTED):
    return Belief(statement=statement, source="contradiction_detector",
                  confidence=conf, status=status,
                  predictions=["A should be observed before B"])


def _evidence(content=None, mode=EvidenceMode.OBSERVED, verdict=EvidenceVerdict.SUPPORTS,
              reliability=0.9, observed_at=None):
    now = time.time()
    return Evidence(
        content=content if content is not None else {"matches": ["pred"]},
        provenance=Provenance(source="test", observed_at=observed_at if observed_at is not None else now,
                              evidence_type="observation", content_reference="ref",
                              reliability=reliability, mode=mode, recorded_at=now),
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# 1. EXPERIMENT MODEL & STORE
# ---------------------------------------------------------------------------

class TestExperimentModel(unittest.TestCase):
    def _exp(self, **kw):
        defaults = dict(
            objective="Test: re-observation finds A present",
            hypothesis_ids=["hyp_1"],
            type=ExperimentType.SYSTEM_OBSERVATION,
            predictions=["Re-observation will find A present"],
            expected_evidence=["An independent re-observation records A"],
            success_conditions=["Observation matches the prediction"],
            failure_conditions=["Re-observation confirms A absent"],
            safety_constraints=["read-only observation", "no network"],
            mode=EvidenceMode.OBSERVED.value,
        )
        defaults.update(kw)
        return Experiment(**defaults)

    def test_create_structured_experiment(self):
        exp = self._exp()
        self.assertEqual(exp.status, ExperimentLifecycle.PROPOSED)
        self.assertTrue(exp.experiment_id.startswith("exp_"))
        self.assertEqual(exp.mode, EvidenceMode.OBSERVED.value)
        self.assertEqual(exp.attempts, 0)
        self.assertGreaterEqual(len(exp.safety_constraints), 1)
        # Conservative model default: an experiment without an explicit mode
        # claims SIMULATED, never OBSERVED.
        default_exp = Experiment(
            objective="x", hypothesis_ids=["h1"], predictions=["p"],
            success_conditions=["s"], failure_conditions=["f"])
        self.assertEqual(default_exp.mode, EvidenceMode.SIMULATED.value)

    def test_predictions_required_before_execution(self):
        with self.assertRaises(ExperimentValidationError):
            self._exp(predictions=[])
        with self.assertRaises(ExperimentValidationError):
            self._exp(predictions=["   "])

    def test_hypothesis_reference_required(self):
        with self.assertRaises(ExperimentValidationError):
            self._exp(hypothesis_ids=[])

    def test_success_and_failure_conditions_required(self):
        with self.assertRaises(ExperimentValidationError):
            self._exp(success_conditions=[])
        with self.assertRaises(ExperimentValidationError):
            self._exp(failure_conditions=[])

    def test_serialization_roundtrip(self):
        exp = self._exp(inputs={"expected": "A", "observed": "A"})
        exp2 = Experiment.from_dict(exp.to_dict())
        self.assertEqual(exp2.experiment_id, exp.experiment_id)
        self.assertEqual(exp2.inputs, {"expected": "A", "observed": "A"})
        self.assertEqual(exp2.type, ExperimentType.SYSTEM_OBSERVATION)

    def test_illegal_transitions_rejected(self):
        exp = self._exp()
        with self.assertRaises(ExperimentTransitionError):
            transition(exp, ExperimentLifecycle.RUNNING)  # PROPOSED -> RUNNING illegal
        transition(exp, ExperimentLifecycle.APPROVED)
        transition(exp, ExperimentLifecycle.RUNNING)
        transition(exp, ExperimentLifecycle.COMPLETED)
        with self.assertRaises(ExperimentTransitionError):
            transition(exp, ExperimentLifecycle.RUNNING)  # COMPLETED is terminal

    def test_retry_bounded_by_max_attempts(self):
        exp = self._exp(max_attempts=2)
        transition(exp, ExperimentLifecycle.APPROVED)
        transition(exp, ExperimentLifecycle.RUNNING)
        transition(exp, ExperimentLifecycle.FAILED)
        exp.attempts = 2
        with self.assertRaises(ExperimentTransitionError):
            transition(exp, ExperimentLifecycle.APPROVED)  # exhausted retries
        exp.attempts = 1
        transition(exp, ExperimentLifecycle.APPROVED)  # one more retry allowed


class TestExperimentStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_expstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _exp(self, status=ExperimentLifecycle.PROPOSED):
        return Experiment(
            objective="Test hidden cause", hypothesis_ids=["hyp_1"],
            type=ExperimentType.DATA_COMPARISON,
            predictions=["C correlates with B"],
            success_conditions=["match"], failure_conditions=["mismatch"],
            status=status)

    def test_persistence_roundtrip_and_restart(self):
        db = os.path.join(self.tmp, "experiments.db")
        s1 = ExperimentStore(db_path=db, strict_load=True)
        exp = self._exp()
        s1.put(exp)
        s2 = ExperimentStore(db_path=db, strict_load=True)
        loaded = s2.get(exp.experiment_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.objective, exp.objective)
        self.assertEqual(loaded.predictions, exp.predictions)
        self.assertEqual(s2.list_by_question("q_1"), [])

    def test_unresolved_experiments_not_lost(self):
        db = os.path.join(self.tmp, "experiments.db")
        s1 = ExperimentStore(db_path=db, strict_load=True)
        proposed = self._exp(ExperimentLifecycle.PROPOSED)
        failed = self._exp(ExperimentLifecycle.FAILED)
        done = self._exp(ExperimentLifecycle.COMPLETED)
        s1.put(proposed)
        s1.put(failed)
        s1.put(done)
        s2 = ExperimentStore(db_path=db, strict_load=True)
        unresolved = s2.list_unresolved()
        self.assertIn(proposed.experiment_id, [e.experiment_id for e in unresolved])
        self.assertIn(failed.experiment_id, [e.experiment_id for e in unresolved])
        self.assertNotIn(done.experiment_id, [e.experiment_id for e in unresolved])

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "experiments.db")
        s1 = ExperimentStore(db_path=db, strict_load=True)
        s1.put(self._exp())
        conn = sqlite3.connect(db)
        conn.execute("UPDATE experiments SET payload = ?", ('{"broken',))
        conn.commit()
        conn.close()
        with self.assertRaises(ExperimentStoreIntegrityError):
            ExperimentStore(db_path=db, strict_load=True)

    def test_corrupt_row_non_strict_not_silent(self):
        db = os.path.join(self.tmp, "experiments.db")
        s1 = ExperimentStore(db_path=db, strict_load=True)
        s1.put(self._exp())
        conn = sqlite3.connect(db)
        conn.execute("UPDATE experiments SET payload = ?",
                     (json.dumps({"experiment_id": "exp_x", "objective": "",
                                  "hypothesis_ids": [], "predictions": []}),))
        conn.commit()
        conn.close()
        s2 = ExperimentStore(db_path=db, strict_load=False)
        self.assertGreaterEqual(len(s2.load_errors), 1)
        self.assertEqual(s2.count(), 0)


# ---------------------------------------------------------------------------
# 2. EVIDENCE & PROVENANCE
# ---------------------------------------------------------------------------

class TestEvidenceAndProvenance(unittest.TestCase):
    def test_evidence_requires_provenance(self):
        with self.assertRaises(EvidenceValidationError):
            Evidence(content={"x": 1}, provenance=None)

    def test_reliability_bounds(self):
        now = time.time()
        with self.assertRaises(EvidenceValidationError):
            Provenance(source="s", observed_at=now, evidence_type="t",
                       content_reference="r", reliability=1.5,
                       mode=EvidenceMode.OBSERVED, recorded_at=now)

    def test_mode_weights_are_explicit(self):
        self.assertEqual(MODE_WEIGHT[EvidenceMode.OBSERVED], 1.0)
        self.assertEqual(MODE_WEIGHT[EvidenceMode.TEST], 0.4)
        self.assertEqual(MODE_WEIGHT[EvidenceMode.SIMULATED], 0.2)
        self.assertEqual(MODE_WEIGHT[EvidenceMode.MODEL_GENERATED], 0.0)

    def test_content_control_characters_stripped(self):
        ev = _evidence(content={"note": "ok\x00\x1f"})
        self.assertNotIn("\x00", ev.content["note"])

    def test_fingerprint_deterministic_and_dedup(self):
        a = _evidence(content={"matches": ["p"]})
        b = _evidence(content={"matches": ["p"]})
        self.assertEqual(a.fingerprint, b.fingerprint)
        c = _evidence(content={"matches": ["q"]})
        self.assertNotEqual(a.fingerprint, c.fingerprint)


class TestEvidenceStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_evstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persistence_restart(self):
        db = os.path.join(self.tmp, "evidence.db")
        s1 = EvidenceStore(db_path=db, strict_load=True)
        ev = _evidence(content={"matches": ["p"]})
        s1.put(ev)
        s2 = EvidenceStore(db_path=db, strict_load=True)
        loaded = s2.get(ev.evidence_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.verdict, EvidenceVerdict.SUPPORTS)
        self.assertEqual(loaded.provenance.mode, EvidenceMode.OBSERVED)
        self.assertEqual(s2.count(), 1)

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "evidence.db")
        s1 = EvidenceStore(db_path=db, strict_load=True)
        s1.put(_evidence())
        conn = sqlite3.connect(db)
        conn.execute("UPDATE evidence SET payload = ?", ("{nope",))
        conn.commit()
        conn.close()
        with self.assertRaises(EvidenceStoreIntegrityError):
            EvidenceStore(db_path=db, strict_load=True)


# ---------------------------------------------------------------------------
# 3. BELIEF & REVISION RULES
# ---------------------------------------------------------------------------

class TestBeliefRevision(unittest.TestCase):
    def test_model_output_cannot_confirm(self):
        b = _belief(conf=0.7)
        ev = _evidence(mode=EvidenceMode.MODEL_GENERATED, verdict=EvidenceVerdict.SUPPORTS)
        b2, rec = BeliefRevision().apply(b, ev)
        self.assertFalse(ev.applied)
        self.assertEqual(b2.confidence, 0.7)  # unchanged
        self.assertEqual(rec["reason"], "model output alone cannot revise a belief")
        self.assertEqual(len(b2.revision_history), 1)  # recorded, never dropped

    def test_supporting_evidence_increases_confidence(self):
        b = _belief(conf=0.5)
        ev = _evidence(verdict=EvidenceVerdict.SUPPORTS, reliability=0.8)
        b2, rec = BeliefRevision().apply(b, ev)
        expected = 0.5 + (1 - 0.5) * 0.8 * 0.5
        self.assertAlmostEqual(b2.confidence, expected, places=6)
        self.assertTrue(rec["applied"])
        self.assertIn(ev.evidence_id, b2.supporting_evidence)

    def test_contradicting_evidence_decreases_confidence(self):
        b = _belief(conf=0.8)
        ev = _evidence(verdict=EvidenceVerdict.CONTRADICTS, reliability=0.8)
        b2, _ = BeliefRevision().apply(b, ev)
        expected = 0.8 - 0.8 * 0.8 * 0.6
        self.assertAlmostEqual(b2.confidence, expected, places=6)

    def test_strong_contradiction_flips_status(self):
        b = _belief(conf=0.7)
        ev = _evidence(verdict=EvidenceVerdict.CONTRADICTS, reliability=0.9)
        b2, rec = BeliefRevision().apply(b, ev)
        self.assertEqual(b2.status, BeliefLifecycle.CONTRADICTED)
        self.assertIn(ev.evidence_id, b2.contradicting_evidence)
        self.assertEqual(len(b2.contradiction_history), 1)

    def test_revision_history_never_overwritten(self):
        b = _belief(conf=0.5)
        rev = BeliefRevision()
        b, _ = rev.apply(b, _evidence(verdict=EvidenceVerdict.SUPPORTS, reliability=0.8))
        b, _ = rev.apply(b, _evidence(verdict=EvidenceVerdict.CONTRADICTS, reliability=0.6))
        b, _ = rev.apply(b, _evidence(verdict=EvidenceVerdict.SUPPORTS, reliability=0.9))
        self.assertEqual(len(b.revision_history), 3)
        # Each revision recorded previous AND new state.
        for rec in b.revision_history:
            self.assertIn("previous_confidence", rec)
            self.assertIn("new_confidence", rec)
            self.assertIn("previous_status", rec)
            self.assertIn("new_status", rec)
            self.assertIn("timestamp", rec)
            self.assertIn("source", rec)

    def test_contradictory_observations_both_recorded(self):
        b = _belief(conf=0.5)
        rev = BeliefRevision()
        b, _ = rev.apply(b, _evidence(verdict=EvidenceVerdict.SUPPORTS, reliability=0.8))
        b, rec = rev.apply(b, _evidence(verdict=EvidenceVerdict.CONTRADICTS, reliability=0.9))
        self.assertEqual(len(b.supporting_evidence), 1)
        self.assertEqual(len(b.contradicting_evidence), 1)
        self.assertEqual(b.status, BeliefLifecycle.CONTRADICTED)  # strong contradiction wins

    def test_confirmation_requires_observed_evidence(self):
        b = _belief(conf=0.5)
        rev = BeliefRevision()
        # Even repeated SIMULATED/TEST support can never confirm.
        for _ in range(5):
            b, _ = rev.apply(b, _evidence(mode=EvidenceMode.SIMULATED,
                                          verdict=EvidenceVerdict.SUPPORTS, reliability=1.0))
        self.assertNotEqual(b.status, BeliefLifecycle.CONFIRMED)
        # One OBSERVED supporting evidence above threshold confirms.
        b2 = _belief(conf=0.75)
        b2, rec = rev.apply(b2, _evidence(mode=EvidenceMode.OBSERVED,
                                          verdict=EvidenceVerdict.SUPPORTS, reliability=1.0))
        self.assertAlmostEqual(b2.confidence, 0.75 + 0.25 * 1.0 * 0.5, places=6)
        self.assertEqual(b2.status, BeliefLifecycle.CONFIRMED)

    def test_stale_evidence_not_applied(self):
        b = _belief(conf=0.5)
        ev = _evidence(verdict=EvidenceVerdict.SUPPORTS,
                       observed_at=time.time() - 100000)
        ev.stale = True
        b2, rec = BeliefRevision().apply(b, ev)
        self.assertFalse(ev.applied)
        self.assertEqual(b2.confidence, 0.5)
        self.assertIn("stale", rec["reason"])

    def test_duplicate_evidence_not_double_applied(self):
        b = _belief(conf=0.5)
        rev = BeliefRevision()
        ev = _evidence(verdict=EvidenceVerdict.SUPPORTS, reliability=0.8)
        b, _ = rev.apply(b, ev)
        b2, rec = rev.apply(b, ev)  # same Evidence object: already applied
        self.assertFalse(rec["applied"])
        self.assertIn("duplicate", rec["reason"])

    def test_rule_belief_trajectory_weaken_then_restore(self):
        """The required belief trajectory: strong contradiction -> CONTRADICTED,
        then an independent OBSERVED verification restores SUPPORT."""
        b = _belief(conf=0.7)
        rev = BeliefRevision()
        b, r1 = rev.apply(b, _evidence(verdict=EvidenceVerdict.CONTRADICTS, reliability=0.8))
        self.assertEqual(r1["new_status"], BeliefLifecycle.CONTRADICTED.value)
        b, r2 = rev.apply(b, _evidence(verdict=EvidenceVerdict.SUPPORTS, reliability=0.9))
        self.assertEqual(r2["new_status"], BeliefLifecycle.SUPPORTED.value)
        self.assertGreater(b.confidence, 0.0)
        self.assertEqual(len(b.revision_history), 2)


class TestBeliefStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_bstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persistence_restart_with_history(self):
        db = os.path.join(self.tmp, "beliefs.db")
        s1 = BeliefStore(db_path=db, strict_load=True)
        b = _belief()
        rev = BeliefRevision()
        b, _ = rev.apply(b, _evidence(verdict=EvidenceVerdict.SUPPORTS, reliability=0.9))
        b, _ = rev.apply(b, _evidence(verdict=EvidenceVerdict.CONTRADICTS, reliability=0.6))
        s1.put(b)
        s2 = BeliefStore(db_path=db, strict_load=True)
        loaded = s2.get(b.belief_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.revision_history), 2)
        self.assertEqual(loaded.contradicting_evidence, b.contradicting_evidence)
        self.assertEqual(loaded.status, b.status)

    def test_dedup_by_fingerprint(self):
        db = os.path.join(self.tmp, "beliefs.db")
        s = BeliefStore(db_path=db, strict_load=True)
        s.put(_belief(statement="X is true"))
        self.assertIsNotNone(s.get_by_fingerprint("X is true", "contradiction_detector"))

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "beliefs.db")
        s1 = BeliefStore(db_path=db, strict_load=True)
        s1.put(_belief())
        conn = sqlite3.connect(db)
        conn.execute("UPDATE beliefs SET payload = ?", ('"not a dict"',))
        conn.commit()
        conn.close()
        with self.assertRaises(BeliefStoreIntegrityError):
            BeliefStore(db_path=db, strict_load=True)


# ---------------------------------------------------------------------------
# 4. REALITY EXPERIMENT ENGINE
# ---------------------------------------------------------------------------

class _EngineHarness:
    """Standalone engine with isolated tmp stores for unit tests."""

    def __init__(self, tmp, permissions=None):
        self.tmp = tmp
        self.experiments = ExperimentStore(db_path=os.path.join(tmp, "experiments.db"),
                                           strict_load=True)
        self.evidence = EvidenceStore(db_path=os.path.join(tmp, "evidence.db"),
                                      strict_load=True)
        self.beliefs = BeliefStore(db_path=os.path.join(tmp, "beliefs.db"),
                                   strict_load=True)
        self.hypotheses = HypothesisStore(db_path=os.path.join(tmp, "hyps.db"),
                                          strict_load=True)
        self.questions = QuestionStore(db_path=os.path.join(tmp, "questions.db"),
                                       strict_load=True)
        self.engine = RealityExperimentEngine(
            experiment_store=self.experiments,
            evidence_store=self.evidence,
            belief_store=self.beliefs,
            hypothesis_store=self.hypotheses,
            question_store=self.questions,
            permissions=permissions or ExperimentPermissions(),
        )

    def add_hypothesis(self, statement, predictions, question_id="q_1"):
        h = Hypothesis(question_id=question_id, statement=statement,
                       confidence=0.4, assumptions=["a"], predictions=predictions,
                       expected_evidence=["e"], failure_conditions=["f"])
        self.hypotheses.put(h)
        return h

    def add_question(self, source="CONTRADICTION", qid="q_1", metadata=None):
        q = Question(question_id=qid, question="What alternative variable could explain B?",
                     source=source, metadata=metadata or {"observed": "B", "expected": "A"})
        self.questions.put(q)
        return q


class TestPlanning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_plan_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_experiment_per_hypothesis_with_full_contract(self):
        h = _EngineHarness(self.tmp)
        h.add_question()
        h.add_hypothesis("An unobserved cause produced B.", ["C correlates with B"])
        h.add_hypothesis("The observation that A did not occur is inaccurate.",
                         ["Re-observation will find A present"])
        exps = h.engine.plan_for_question("q_1")
        self.assertEqual(len(exps), 2)
        for exp in exps:
            self.assertEqual(exp.status, ExperimentLifecycle.PROPOSED)
            self.assertTrue(exp.predictions)
            self.assertTrue(exp.expected_evidence)
            self.assertTrue(exp.success_conditions)
            self.assertTrue(exp.failure_conditions)
            self.assertTrue(exp.safety_constraints)
            self.assertEqual(exp.question_id, "q_1")
            self.assertEqual(len(exp.hypothesis_ids), 1)

    def test_observation_hypothesis_gets_system_observation(self):
        h = _EngineHarness(self.tmp)
        h.add_question()
        h.add_hypothesis("The observation that A did not occur is inaccurate.",
                         ["Re-observation will find A present"])
        exps = h.engine.plan_for_question("q_1")
        self.assertEqual(exps[0].type, ExperimentType.SYSTEM_OBSERVATION)
        self.assertEqual(exps[0].mode, EvidenceMode.OBSERVED.value)

    def test_no_duplicate_planning(self):
        h = _EngineHarness(self.tmp)
        h.add_question()
        h.add_hypothesis("An unobserved cause produced B.", ["C correlates with B"])
        first = h.engine.plan_for_question("q_1")
        second = h.engine.plan_for_question("q_1")
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])  # still unresolved — never re-planned

    def test_malformed_hypothesis_rejected(self):
        h = _EngineHarness(self.tmp)
        h.add_question()
        h.add_hypothesis("No predictions here.", [])
        with self.assertRaises(ExperimentValidationError):
            h.engine.plan_for_question("q_1")


class TestSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_safety_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unsafe_experiment_blocked_and_never_executed(self):
        h = _EngineHarness(self.tmp)
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("premise", ["p"])
        exp = h.engine.plan_for_question("q_1")[0]
        exp.type = ExperimentType.WEB_VERIFICATION
        exp.mode = EvidenceMode.OBSERVED.value
        h.experiments.put(exp)
        exp = h.engine.approve(exp)
        self.assertEqual(exp.status, ExperimentLifecycle.BLOCKED)
        self.assertIn("permission", exp.rollback_info)
        with self.assertRaises(ExperimentTransitionError):
            h.engine.run(exp)
        self.assertEqual(h.evidence.count(), 0)

    def test_tool_and_web_require_permissions(self):
        for etype, perm in ((ExperimentType.TOOL_EXECUTION, "allow_tools"),
                            (ExperimentType.WEB_VERIFICATION, "allow_network"),
                            (ExperimentType.CODE_TEST, "allow_code")):
            h = _EngineHarness(self.tmp)
            h.add_question(source="UNCERTAINTY")
            h.add_hypothesis("h", ["p"])
            exp = h.engine.plan_for_question("q_1")[0]
            exp.type = etype
            exp.mode = EvidenceMode.OBSERVED.value
            if etype == ExperimentType.CODE_TEST:
                exp.mode = EvidenceMode.TEST.value
            h.experiments.put(exp)
            blocked = h.engine.approve(exp)
            self.assertEqual(blocked.status, ExperimentLifecycle.BLOCKED, etype)
            self.assertIn(perm, blocked.rollback_info)

    def test_code_test_restricted_sandbox(self):
        h = _EngineHarness(self.tmp, permissions=ExperimentPermissions(allow_code=True))
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("h", ["p"])
        exp = h.engine.plan_for_question("q_1")[0]
        exp.type = ExperimentType.CODE_TEST
        exp.mode = EvidenceMode.TEST.value
        exp.inputs = {"code": "import os\nresult = {'passed': True}"}
        h.experiments.put(exp)
        exp = h.engine.approve(exp)
        exp, evidence = h.engine.run(exp)
        self.assertEqual(exp.status, ExperimentLifecycle.FAILED)
        self.assertTrue(any("SafetyViolationError" in e or "unsafe operation" in e
                            for e in exp.errors))
        self.assertIsNone(evidence)
        self.assertEqual(h.evidence.count(), 0)  # failure is data, no evidence fabricated

    def test_code_test_allowed_with_permission_is_test_evidence(self):
        h = _EngineHarness(self.tmp, permissions=ExperimentPermissions(allow_code=True))
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("h", ["p"])
        exp = h.engine.plan_for_question("q_1")[0]
        exp.type = ExperimentType.CODE_TEST
        exp.mode = EvidenceMode.TEST.value
        exp.inputs = {"code": "result = {'passed': 2 + 2 == 4}"}
        h.experiments.put(exp)
        exp = h.engine.approve(exp)
        exp, evidence = h.engine.run(exp)
        self.assertEqual(exp.status, ExperimentLifecycle.COMPLETED)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence.provenance.mode, EvidenceMode.TEST)  # mock evidence, marked

    def test_failed_tool_is_data(self):
        h = _EngineHarness(self.tmp, permissions=ExperimentPermissions(allow_tools=True))
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("h", ["p"])
        exp = h.engine.plan_for_question("q_1")[0]
        exp.type = ExperimentType.TOOL_EXECUTION
        exp.inputs = {"tool": "missing_tool", "params": {}}
        h.experiments.put(exp)
        exp = h.engine.approve(exp)
        exp, evidence = h.engine.run(exp)
        self.assertEqual(exp.status, ExperimentLifecycle.FAILED)
        self.assertIn("ToolExecutionError", exp.result["failure"])
        self.assertIsNone(evidence)
        self.assertEqual(h.evidence.count(), 0)


class TestExecutors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_exec_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, etype, inputs):
        h = _EngineHarness(self.tmp)
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("h", ["p"])
        exp = h.engine.plan_for_question("q_1")[0]
        exp.type = etype
        exp.mode = RealityExperimentEngine._mode_for(etype)
        exp.inputs = inputs
        h.experiments.put(exp)
        exp = h.engine.approve(exp)
        return h.engine.run(exp)

    def test_simulation_correlation_deterministic(self):
        exp, ev = self._run(ExperimentType.SIMULATION, {
            "simulation": {"name": "correlation",
                           "params": {"x": [1, 1, 1, 1], "y": [1, 1, 1, 1]}},
            "threshold": 0.5,
        })
        self.assertEqual(exp.status, ExperimentLifecycle.COMPLETED)
        self.assertEqual(ev.provenance.mode, EvidenceMode.SIMULATED)
        self.assertEqual(ev.verdict, EvidenceVerdict.SUPPORTS)
        # Identical inputs -> identical output.
        exp2, ev2 = self._run(ExperimentType.SIMULATION, {
            "simulation": {"name": "correlation",
                           "params": {"x": [1, 1, 1, 1], "y": [1, 1, 1, 1]}},
            "threshold": 0.5,
        })
        self.assertEqual(ev.content, ev2.content)

    def test_unknown_simulator_fails(self):
        exp, ev = self._run(ExperimentType.SIMULATION, {
            "simulation": {"name": "run_arbitrary_code", "params": {}},
        })
        self.assertEqual(exp.status, ExperimentLifecycle.FAILED)
        self.assertIn("Unknown simulator", exp.result["error"])

    def test_data_comparison_match_and_mismatch(self):
        exp, ev = self._run(ExperimentType.DATA_COMPARISON,
                            {"expected": "A present", "observed": "A present"})
        self.assertEqual(ev.verdict, EvidenceVerdict.SUPPORTS)
        self.assertEqual(ev.provenance.mode, EvidenceMode.OBSERVED)
        exp2, ev2 = self._run(ExperimentType.DATA_COMPARISON,
                              {"expected": "C correlates with B", "observed": "no correlation"})
        self.assertEqual(ev2.verdict, EvidenceVerdict.CONTRADICTS)

    def test_system_observation_unavailable_resource(self):
        exp, ev = self._run(ExperimentType.SYSTEM_OBSERVATION, {"observations": {}})
        self.assertEqual(exp.status, ExperimentLifecycle.FAILED)
        self.assertIn("ResourceUnavailableError", exp.result["failure"])
        self.assertIsNone(ev)

    def test_system_observation_records_what_observer_saw(self):
        exp, ev = self._run(ExperimentType.SYSTEM_OBSERVATION, {
            "observations": {"A": "present"},
            "matches": ["Re-observation will find A present"],
        })
        self.assertEqual(exp.status, ExperimentLifecycle.COMPLETED)
        self.assertEqual(ev.verdict, EvidenceVerdict.SUPPORTS)
        self.assertEqual(ev.provenance.mode, EvidenceMode.OBSERVED)
        self.assertEqual(ev.provenance.experiment_id, exp.experiment_id)

    def test_repeated_failure_bounded(self):
        h = _EngineHarness(self.tmp)
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("h", ["p"])
        exp = h.engine.plan_for_question("q_1")[0]
        exp.type = ExperimentType.SYSTEM_OBSERVATION
        exp.mode = EvidenceMode.OBSERVED.value
        exp.inputs = {"observations": {}}
        h.experiments.put(exp)
        exp = h.engine.approve(exp)
        exp, _ = h.engine.run(exp)
        self.assertEqual(exp.status, ExperimentLifecycle.FAILED)
        self.assertEqual(exp.attempts, 1)
        exp = h.engine.approve(exp)  # one retry allowed
        exp, _ = h.engine.run(exp)
        self.assertEqual(exp.status, ExperimentLifecycle.FAILED)
        self.assertEqual(exp.attempts, 2)
        with self.assertRaises(ExperimentTransitionError):
            h.engine.approve(exp)  # exhausted: no endless retries
        self.assertFalse(any("confirmation" in r.lower() for r in exp.result.values()
                             if isinstance(r, str)))
        self.assertEqual(h.evidence.count(), 0)  # failure never converted to confirmation


class TestEvidenceGatekeeping(unittest.TestCase):
    """Fabricated, duplicate, stale and mode-lying evidence is rejected/flagged."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_gate_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fabricated_experiment_reference_rejected(self):
        h = _EngineHarness(self.tmp)
        with self.assertRaises(EvidenceValidationError):
            h.engine.record_external_observation(
                content={"x": 1}, source="attacker", mode=EvidenceMode.OBSERVED,
                experiment_id="exp_does_not_exist")

    def test_fabricated_hypothesis_reference_rejected(self):
        h = _EngineHarness(self.tmp)
        with self.assertRaises(EvidenceValidationError):
            h.engine.record_external_observation(
                content={"x": 1}, source="attacker", mode=EvidenceMode.OBSERVED,
                hypothesis_ids=["hyp_ghost"])

    def test_fabricated_belief_reference_rejected(self):
        h = _EngineHarness(self.tmp)
        with self.assertRaises(EvidenceValidationError):
            h.engine.record_external_observation(
                content={"x": 1}, source="attacker", mode=EvidenceMode.OBSERVED,
                belief_ids=["bel_ghost"])

    def test_simulation_presented_as_reality_rejected(self):
        h = _EngineHarness(self.tmp)
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("h", ["p"])
        exp = h.engine.plan_for_question("q_1")[0]
        exp.type = ExperimentType.SIMULATION
        exp.mode = EvidenceMode.SIMULATED.value
        h.experiments.put(exp)
        with self.assertRaises(EvidenceValidationError):
            h.engine.record_external_observation(
                content={"x": 1}, source="sneaky", mode=EvidenceMode.OBSERVED,
                experiment_id=exp.experiment_id)  # mode-lying

    def test_duplicate_external_evidence_rejected(self):
        h = _EngineHarness(self.tmp)
        h.add_question(source="UNCERTAINTY")
        h.add_hypothesis("h", ["p"])
        ev1 = h.engine.record_external_observation(
            content={"observation": "B occurred"}, source="perception",
            mode=EvidenceMode.OBSERVED, verdict=EvidenceVerdict.CONTRADICTS)
        with self.assertRaises(EvidenceValidationError):
            h.engine.record_external_observation(
                content={"observation": "B occurred"}, source="perception",
                mode=EvidenceMode.OBSERVED, verdict=EvidenceVerdict.CONTRADICTS)
        self.assertEqual(h.evidence.count(), 1)

    def test_stale_external_evidence_flagged(self):
        h = _EngineHarness(self.tmp)
        ev = h.engine.record_external_observation(
            content={"observation": "old"}, source="log",
            mode=EvidenceMode.OBSERVED, verdict=EvidenceVerdict.SUPPORTS,
            observed_at=time.time() - 100000)
        self.assertTrue(ev.stale)
        b = _belief(conf=0.5)
        b, rec = h.engine.revision.apply(b, ev)
        self.assertFalse(rec["applied"])
        self.assertIn("stale", rec["reason"])

    def test_model_generated_recorded_but_never_applied(self):
        h = _EngineHarness(self.tmp)
        ev = h.engine.record_external_observation(
            content={"claim": "B was caused by magic"}, source="llm",
            mode=EvidenceMode.MODEL_GENERATED, verdict=EvidenceVerdict.SUPPORTS)
        b = _belief(conf=0.5)
        b, rec = h.engine.revision.apply(b, ev)
        self.assertFalse(rec["applied"])
        self.assertEqual(b.confidence, 0.5)
        self.assertEqual(len(b.revision_history), 1)  # recorded, not dropped


# ---------------------------------------------------------------------------
# 5. RUNTIME INTEGRATION + REQUIRED E2E
# ---------------------------------------------------------------------------

class TestSlice3RuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_rt_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def _run_contradiction_flow(self, permissions=None):
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"),
                              experiment_permissions=permissions or ExperimentPermissions())
        await rt.start()
        await rt.event_bus.publish(_trigger(EventType.CONTRADICTION_FOUND, {
            "subject": "sequence A->B",
            "expected": "A",
            "observed": "B",
            "description": "B occurred without A",
            "beliefs": ["A normally precedes B"],
        }), dispatch_immediately=True)
        return rt

    async def test_required_e2e_question_hypotheses_experiment_observation_comparison_belief(self):
        """Known: A normally precedes B. Observed: B occurred but A did not.

        Slice 2 generates the Question + competing hypotheses; Slice 3 plans,
        approves and runs controlled experiments, records observations with
        provenance, compares them against predictions, scores the hypotheses by
        evidence (never opinion), and revises the relevant belief. The winner is
        determined by the evidence, not hard-coded."""
        rt = await self._run_contradiction_flow()

        # Slice 2: question + competing hypotheses.
        qs = rt.question_store.list_unresolved()
        self.assertEqual(len(qs), 1)
        q = qs[0]
        hyps = rt.hypothesis_store.list_by_question(q.question_id)
        self.assertGreaterEqual(len(hyps), 2)
        self.assertIn(q.question_id, [b.provenance.get("question_id") for b in rt.belief_store.list()
                                      if b.source == "hypothesis_engine"])

        # Slice 3.1: controlled experiments planned (PROPOSED), one per hypothesis,
        # with predictions / expected evidence / success / failure / safety fixed
        # BEFORE execution.
        exps = rt.experiment_store.list_by_question(q.question_id)
        self.assertGreaterEqual(len(exps), 2)
        for exp in exps:
            self.assertEqual(exp.status, ExperimentLifecycle.PROPOSED)
            self.assertTrue(exp.predictions and exp.success_conditions
                            and exp.failure_conditions and exp.safety_constraints)

        # Slice 3.2-3.3: approve + execute safe deterministic experiments.
        h1 = next(h for h in hyps if "unobserved cause" in h.statement)
        h2 = next(h for h in hyps if "inaccurate" in h.statement)
        exp1 = next(e for e in exps if h1.hypothesis_id in e.hypothesis_ids)
        exp2 = next(e for e in exps if h2.hypothesis_id in e.hypothesis_ids)

        # H1 experiment: compare the candidate-cause claim against recorded data.
        await rt.approve_experiment(exp1.experiment_id,
                                    inputs={"expected": "C correlates with B",
                                            "observed": "no correlation found",
                                            "reliability": 0.9})
        await rt.run_experiment(exp1.experiment_id)
        # H2 experiment: independent re-observation of the disputed signal.
        await rt.approve_experiment(exp2.experiment_id, inputs={
            "observations": {"A": "present"},
            "matches": ["Re-observation will find A present"],
            "reliability": 0.9})
        await rt.run_experiment(exp2.experiment_id)

        e1 = rt.experiment_store.get(exp1.experiment_id)
        e2 = rt.experiment_store.get(exp2.experiment_id)
        self.assertEqual(e1.status, ExperimentLifecycle.COMPLETED)
        self.assertEqual(e2.status, ExperimentLifecycle.COMPLETED)

        # Slice 3.4: observations recorded with full provenance.
        evs = rt.evidence_store.list()
        self.assertGreaterEqual(len(evs), 2)
        for ev in evs:
            prov = ev.provenance
            self.assertTrue(prov.source and prov.evidence_type
                            and prov.content_reference is not None)
            self.assertTrue(0.0 <= prov.reliability <= 1.0)
            self.assertEqual(prov.experiment_id, e1.experiment_id if ev.experiment_id == e1.experiment_id
                             else e2.experiment_id if ev.experiment_id == e2.experiment_id else None)

        # Slice 3.5-3.6: external observations (the anomaly + independent
        # verification) target the rule belief; the belief field records both.
        rule = rt.belief_store.get_by_fingerprint("A normally precedes B",
                                                  "contradiction_detector")
        self.assertIsNotNone(rule)
        await rt.record_observation(
            content={"observation": "B occurred without A"}, source="perception",
            reliability=0.8, mode=EvidenceMode.OBSERVED,
            verdict=EvidenceVerdict.CONTRADICTS, belief_ids=[rule.belief_id])
        await rt.record_observation(
            content={"observation": "independent re-observation records A present"},
            source="re_observer", reliability=0.9, mode=EvidenceMode.OBSERVED,
            verdict=EvidenceVerdict.SUPPORTS, belief_ids=[rule.belief_id])

        # Slice 3.7: comparison -> hypothesis scoring -> belief revision.
        result = await rt.evaluate_question(q.question_id)

        # Evidence determined the outcome, not opinion.
        h1_after = rt.hypothesis_store.get(h1.hypothesis_id)
        h2_after = rt.hypothesis_store.get(h2.hypothesis_id)
        self.assertGreater(h2_after.score, h1_after.score)
        self.assertEqual(h1_after.status, HypothesisLifecycle.CONTRADICTED)
        self.assertEqual(h2_after.status, HypothesisLifecycle.SUPPORTED)
        self.assertEqual(h1_after.supporting_evidence, [])
        self.assertGreaterEqual(len(h1_after.contradicting_evidence), 1)
        self.assertGreaterEqual(len(h2_after.supporting_evidence), 1)

        # The relevant belief was revised (weakened then restored), with the full
        # previous/new state recorded — never silently overwritten.
        rule_after = rt.belief_store.get(rule.belief_id)
        self.assertGreaterEqual(len(rule_after.revision_history), 2)
        first = rule_after.revision_history[0]
        self.assertTrue(first["applied"])
        self.assertEqual(first["verdict"], EvidenceVerdict.CONTRADICTS.value)
        self.assertEqual(first["new_status"], BeliefLifecycle.CONTRADICTED.value)
        last = rule_after.revision_history[-1]
        self.assertEqual(last["new_status"], BeliefLifecycle.SUPPORTED.value)
        self.assertEqual(len(rule_after.contradiction_history), 1)
        self.assertNotEqual(rule_after.confidence, 0.7)  # confidence changed

        # Provenance/history preserved in the result and stores.
        self.assertGreaterEqual(len(result["revisions"]), 3)
        await rt.stop()

    async def test_full_bus_trail(self):
        rt = await self._run_contradiction_flow()
        q = rt.question_store.list_unresolved()[0]
        hyps = rt.hypothesis_store.list_by_question(q.question_id)
        h1 = next(h for h in hyps if "unobserved cause" in h.statement)
        h2 = next(h for h in hyps if "inaccurate" in h.statement)
        for exp in rt.experiment_store.list_by_question(q.question_id):
            if h1.hypothesis_id in exp.hypothesis_ids:
                await rt.approve_experiment(exp.experiment_id,
                                            inputs={"expected": "C correlates with B",
                                                    "observed": "no correlation found"})
            else:
                await rt.approve_experiment(exp.experiment_id, inputs={
                    "observations": {"A": "present"},
                    "matches": ["Re-observation will find A present"]})
            await rt.run_experiment(exp.experiment_id)
        await rt.evaluate_question(q.question_id)
        replayed = await rt.event_bus.replay_events(limit=300)
        types = [e.event_type for e in replayed]
        for expected in (EventType.EXPERIMENT_PROPOSED, EventType.EXPERIMENT_APPROVED,
                         EventType.EXPERIMENT_STARTED, EventType.EXPERIMENT_COMPLETED,
                         EventType.OBSERVATION_RECORDED, EventType.EVIDENCE_ADDED,
                         EventType.BELIEF_UPDATED, EventType.HYPOTHESIS_SUPPORTED,
                         EventType.HYPOTHESIS_CONTRADICTED):
            self.assertIn(expected, types)
        await rt.stop()

    async def test_experiments_survive_restart(self):
        rt = await self._run_contradiction_flow()
        q = rt.question_store.list_unresolved()[0]
        exp_ids = [e.experiment_id for e in rt.experiment_store.list_by_question(q.question_id)]
        self.assertGreaterEqual(len(exp_ids), 2)
        await rt.stop()

        rt2 = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt2.start()
        for eid in exp_ids:
            loaded = rt2.experiment_store.get(eid)
            self.assertIsNotNone(loaded)  # no silent loss of unresolved experiments
            self.assertEqual(loaded.status, ExperimentLifecycle.PROPOSED)
            self.assertTrue(loaded.predictions)
        rule = rt2.belief_store.get_by_fingerprint("A normally precedes B",
                                                   "contradiction_detector")
        self.assertIsNotNone(rule)  # belief survived restart too
        await rt2.stop()

    async def test_simulation_evidence_cannot_confirm_in_runtime(self):
        rt = await self._run_contradiction_flow()
        q = rt.question_store.list_unresolved()[0]
        hyps = rt.hypothesis_store.list_by_question(q.question_id)
        rule_hyp = next(h for h in hyps if "rule" in h.statement and "incorrect" in h.statement)
        exp = next(e for e in rt.experiment_store.list_by_question(q.question_id)
                   if rule_hyp.hypothesis_id in e.hypothesis_ids)
        self.assertEqual(exp.type, ExperimentType.SIMULATION)
        await rt.approve_experiment(exp.experiment_id, inputs={
            "simulation": {"name": "rule_check",
                           "params": {"cases": [{"preceded": False}, {"preceded": False}]}},
            "threshold": 0.5})
        await rt.run_experiment(exp.experiment_id)
        ev = rt.evidence_store.get(rt.experiment_store.get(exp.experiment_id).evidence_ids[0])
        self.assertEqual(ev.provenance.mode, EvidenceMode.SIMULATED)
        await rt.evaluate_question(q.question_id)
        # SIMULATED support can inform, but the belief must NOT be CONFIRMED.
        beliefs = [b for b in rt.belief_store.list_for_hypothesis(rule_hyp.hypothesis_id)]
        self.assertTrue(beliefs)
        for b in beliefs:
            self.assertNotEqual(b.status, BeliefLifecycle.CONFIRMED)
        await rt.stop()

    async def test_unsafe_runtime_default_blocks_code(self):
        rt = await self._run_contradiction_flow()  # default permissions: all locked
        q = rt.question_store.list_unresolved()[0]
        hyps = rt.hypothesis_store.list_by_question(q.question_id)
        for h in hyps:
            for exp in rt.experiment_store.list_by_question(q.question_id):
                if h.hypothesis_id not in exp.hypothesis_ids:
                    continue
                exp.type = ExperimentType.CODE_TEST
                exp.mode = "TEST"
                exp.inputs = {"code": "result = {'passed': True}"}
                rt.experiment_store.put(exp)
                blocked = await rt.approve_experiment(exp.experiment_id)
                self.assertEqual(blocked.status, ExperimentLifecycle.BLOCKED)
                with self.assertRaises(Exception):
                    await rt.run_experiment(exp.experiment_id)
        await rt.stop()

    async def test_restart_preserves_evidence_and_belief_history(self):
        rt = await self._run_contradiction_flow()
        q = rt.question_store.list_unresolved()[0]
        rule = rt.belief_store.get_by_fingerprint("A normally precedes B",
                                                  "contradiction_detector")
        await rt.record_observation(
            content={"observation": "B occurred without A"}, source="perception",
            reliability=0.8, verdict=EvidenceVerdict.CONTRADICTS,
            belief_ids=[rule.belief_id])
        await rt.evaluate_question(q.question_id)
        ev_count = rt.evidence_store.count()
        await rt.stop()

        rt2 = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt2.start()
        self.assertEqual(rt2.evidence_store.count(), ev_count)
        rule2 = rt2.belief_store.get(rule.belief_id)
        self.assertIsNotNone(rule2)
        self.assertEqual(len(rule2.revision_history),
                         len(rt.belief_store.get(rule.belief_id).revision_history))
        await rt2.stop()

    async def test_contradicting_experiment_result_vs_current_belief(self):
        """An experiment result that contradicts the current belief must visibly
        weaken / contradict it, not be hidden."""
        rt = await self._run_contradiction_flow()
        q = rt.question_store.list_unresolved()[0]
        rule = rt.belief_store.get_by_fingerprint("A normally precedes B",
                                                  "contradiction_detector")
        # Strong, reliable contradiction from a real observation channel.
        await rt.record_observation(
            content={"observation": "repeated B-without-A cases"}, source="sensor",
            reliability=0.95, verdict=EvidenceVerdict.CONTRADICTS,
            belief_ids=[rule.belief_id])
        await rt.evaluate_question(q.question_id)
        rule2 = rt.belief_store.get(rule.belief_id)
        self.assertEqual(rule2.status, BeliefLifecycle.CONTRADICTED)
        self.assertGreaterEqual(len(rule2.contradiction_history), 1)
        await rt.stop()


class TestSlice3EngineIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice3_engine_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_engine_wires_reality_feedback(self):
        engine = AscendantEngine(data_dir=self.tmp)
        await engine.start()
        rt = engine.cognitive_runtime
        self.assertIsNotNone(rt.reality_experiments)
        self.assertIsNotNone(rt.experiment_store)
        await engine.event_bus.publish(_trigger(EventType.CONTRADICTION_FOUND, {
            "expected": "A", "observed": "B",
            "beliefs": ["A normally precedes B"],
        }), dispatch_immediately=True)
        qs = rt.question_store.list_unresolved()
        self.assertGreaterEqual(len(qs), 1)
        exps = rt.experiment_store.list_by_question(qs[0].question_id)
        self.assertGreaterEqual(len(exps), 2)
        # Default permissions are locked down: no experiment auto-executes.
        self.assertTrue(all(e.status == ExperimentLifecycle.PROPOSED for e in exps))
        await engine.stop()


if __name__ == "__main__":
    unittest.main()
