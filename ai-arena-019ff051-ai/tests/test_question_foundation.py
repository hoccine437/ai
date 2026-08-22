"""
Slice 2 — Self-Questioning layer test suite.

Covers: Question model/store, QuestionGenesis (all sources), Hypothesis
model/store, HypothesisEngine (competing explanations), event -> question ->
attention -> hypotheses integration, goal relevance, persistence/restart,
and adversarial cases. Runs entirely without an LLM.

Run with:
    python3 -m unittest tests.test_question_foundation -v
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from zerion.runtime.event_bus import AsyncEventBus, EventValidationError
from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.question import (
    Question,
    QuestionLifecycle,
    QuestionSource,
    QuestionStore,
    QuestionStoreIntegrityError,
    QuestionValidationError,
    score_question,
)
from zerion.cognitive_os.hypothesis import (
    Hypothesis,
    HypothesisLifecycle,
    HypothesisStore,
    HypothesisStoreIntegrityError,
    HypothesisValidationError,
)
from zerion.cognitive_os.question_genesis import QuestionGenesis
from zerion.cognitive_os.hypothesis_engine import HypothesisEngine
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.cognitive_os.objective_manager import ObjectiveContinuityManager
from zerion.engine import AscendantEngine


def _trigger(etype, payload=None, priority=70):
    return Event(event_type=etype, payload=payload if payload is not None else {},
                 source="test", priority=priority)


# ---------------------------------------------------------------------------
# 1. QUESTION MODEL
# ---------------------------------------------------------------------------

class TestQuestionModel(unittest.TestCase):
    def test_create_structured_question(self):
        q = Question(question="What is the current state of the migration?",
                     source="MISSING_DEPENDENCY", uncertainty=0.8,
                     expected_information_gain=0.7, related_goal="goal_1")
        self.assertTrue(q.question_id.startswith("q_"))
        self.assertEqual(q.source_kind, QuestionSource.ZERION_GENERATED)
        self.assertEqual(q.status, QuestionLifecycle.QUEUED)
        self.assertTrue(q.fingerprint)

    def test_empty_question_rejected(self):
        with self.assertRaises(QuestionValidationError):
            Question(question="   ")

    def test_out_of_range_metrics_rejected(self):
        with self.assertRaises(QuestionValidationError):
            Question(question="x", uncertainty=2.0)
        with self.assertRaises(QuestionValidationError):
            Question(question="x", estimated_cost=-1.0)
        with self.assertRaises(QuestionValidationError):
            Question(question="x", risk=1.5)

    def test_serialization_roundtrip(self):
        q = Question(question="Why did the prediction fail?", source="PREDICTION_FAILURE",
                     related_beliefs=["b1"], related_hypotheses=["h1"],
                     parent_question="q_parent", resolution=None)
        q2 = Question.from_dict(q.to_dict())
        self.assertEqual(q2.question_id, q.question_id)
        self.assertEqual(q2.question, q.question)
        self.assertEqual(q2.related_beliefs, ["b1"])
        self.assertEqual(q2.related_hypotheses, ["h1"])
        self.assertEqual(q2.parent_question, "q_parent")
        self.assertEqual(q2.fingerprint, q.fingerprint)

    def test_fingerprint_is_deterministic(self):
        a = Question(question="What is the state of X?", source="UNCERTAINTY")
        b = Question(question="What is the state of X?", source="UNCERTAINTY")
        c = Question(question="What is the state of X?", source="UNCERTAINTY", related_goal="g1")
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, c.fingerprint)

    def test_control_characters_stripped(self):
        q = Question(question="what\x00\x1fstate?")
        self.assertNotIn("\x00", q.question)
        self.assertNotIn("\x1f", q.question)


class TestQuestionStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice2_qstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _store(self, db=None, strict=True):
        return QuestionStore(db_path=db or os.path.join(self.tmp, "questions.db"),
                             strict_load=strict)

    def test_persistence_roundtrip_and_restart(self):
        db = os.path.join(self.tmp, "questions.db")
        store1 = self._store(db)
        q = Question(question="What is the migration state?", source="MISSING_DEPENDENCY")
        store1.put(q)

        store2 = self._store(db)
        loaded = store2.get(q.question_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.question, q.question)
        self.assertEqual(loaded.source, "MISSING_DEPENDENCY")
        self.assertEqual(store2.count(), 1)

    def test_unresolved_filtering(self):
        store = self._store()
        q1 = Question(question="open question", source="UNCERTAINTY")
        q2 = Question(question="answered question", source="UNCERTAINTY",
                      status=QuestionLifecycle.ANSWERED, resolution="done")
        store.put(q1)
        store.put(q2)
        unresolved = store.list_unresolved()
        self.assertEqual([q.question_id for q in unresolved], [q1.question_id])

    def test_fingerprint_dedup_lookup(self):
        store = self._store()
        q = Question(question="What is the state of X?", source="UNCERTAINTY")
        store.put(q)
        self.assertIsNotNone(
            store.get_by_fingerprint(q.fingerprint, unresolved_only=True))
        q.status = QuestionLifecycle.ANSWERED
        store.put(q)
        self.assertIsNone(
            store.get_by_fingerprint(q.fingerprint, unresolved_only=True))

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "questions.db")
        store1 = self._store(db)
        store1.put(Question(question="keep me", source="UNCERTAINTY"))
        conn = sqlite3.connect(db)
        conn.execute("UPDATE questions SET payload = ?",
                     (json.dumps({"question_id": "q_x", "question": ""}),))
        conn.commit()
        conn.close()
        with self.assertRaises(QuestionStoreIntegrityError):
            self._store(db, strict=True)

    def test_corrupt_row_non_strict_not_silent(self):
        db = os.path.join(self.tmp, "questions.db")
        store1 = self._store(db)
        store1.put(Question(question="keep me", source="UNCERTAINTY"))
        conn = sqlite3.connect(db)
        conn.execute("UPDATE questions SET payload = ?", ("{broken json",))
        conn.commit()
        conn.close()
        store2 = self._store(db, strict=False)
        self.assertGreaterEqual(len(store2.load_errors), 1)  # recorded, never silent
        self.assertEqual(store2.count(), 0)


# ---------------------------------------------------------------------------
# 2. QUESTION GENESIS
# ---------------------------------------------------------------------------

class TestQuestionGenesis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice2_genesis_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _genesis(self, objectives=None, name="questions.db"):
        store = QuestionStore(db_path=os.path.join(self.tmp, name),
                              strict_load=True)
        return QuestionGenesis(question_store=store, objectives=objectives)

    def test_generate_from_uncertainty(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.UNCERTAINTY_DETECTED,
                                 {"subject": "the migration"}))
        self.assertEqual(len(qs), 1)
        self.assertIn("migration", qs[0].question)
        self.assertEqual(qs[0].source, "UNCERTAINTY")
        self.assertEqual(qs[0].source_kind, QuestionSource.ZERION_GENERATED)

    def test_generate_from_contradiction(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.CONTRADICTION_FOUND,
                                 {"subject": "A->B", "expected": "A", "observed": "B"}))
        self.assertEqual(len(qs), 1)
        self.assertIn("explain", qs[0].question.lower())
        self.assertIn("B", qs[0].question)
        self.assertEqual(qs[0].metadata["observed"], "B")

    def test_generate_from_anomaly(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.ANOMALY_DETECTED, {"entity": "host-3"}))
        self.assertEqual(len(qs), 1)
        self.assertIn("host-3", qs[0].question)
        self.assertEqual(qs[0].source, "ANOMALY")

    def test_generate_from_goal_gap(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.GOAL_GAP_DETECTED,
                                 {"objective": "finish deployment", "gap": "migration status unknown",
                                  "goal_id": "goal_1"}))
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].related_goal, "goal_1")
        self.assertEqual(qs[0].goal_relevance, 1.0)

    def test_generate_from_missing_dependency(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.MISSING_DEPENDENCY_DETECTED,
                                 {"objective": "finish deployment",
                                  "dependency": "the migration"}))
        self.assertEqual(len(qs), 1)
        self.assertIn("migration", qs[0].question)
        self.assertEqual(qs[0].source, "MISSING_DEPENDENCY")

    def test_generate_from_prediction_failure(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.PREDICTION_ERROR,
                                 {"subject": "cache", "predicted": "hit", "observed": "miss"}))
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].source, "PREDICTION_FAILURE")
        self.assertIn("hit", qs[0].question)

    def test_generate_from_repeated_failure(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.REPEATED_FAILURE_DETECTED,
                                 {"task": "database migration", "attempts": 4,
                                  "last_error": "timeout"}))
        self.assertEqual(len(qs), 1)
        self.assertIn("database migration", qs[0].question)
        self.assertEqual(qs[0].source, "REPEATED_FAILURE")

    def test_generate_from_capability_gap(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.CAPABILITY_GAP,
                                 {"task": "profile IO latency",
                                  "missing_capability": "io_profiler"}))
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].source, "CAPABILITY_GAP")

    def test_user_request_source_kind(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.USER_INTERACTION,
                                 {"transcript": "Zerion, open my tasks"}))
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].source_kind, QuestionSource.USER_REQUESTED)
        self.assertEqual(qs[0].source, "USER_REQUEST")
        self.assertEqual(qs[0].question, "Zerion, open my tasks")

    def test_empty_user_request_ignored(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.USER_INTERACTION, {"transcript": "  "}))
        self.assertEqual(qs, [])

    def test_unrecognized_event_ignored(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.VOICE_STARTED, {"session_id": "s"}))
        self.assertEqual(qs, [])

    def test_deduplication(self):
        g = self._genesis()
        ev = _trigger(EventType.CONTRADICTION_FOUND,
                      {"expected": "A", "observed": "B"})
        self.assertEqual(len(g.generate(ev)), 1)
        self.assertEqual(g.generate(ev), [])  # unresolved duplicate skipped

    def test_goal_relevance_boost_from_goal_field(self):
        objectives = ObjectiveContinuityManager(
            db_path=os.path.join(self.tmp, "goals.db"), strict_load=True)
        goal = objectives.create_goal(objective="Finish deployment", priority=90)
        objectives.activate(goal.objective_id)
        g = self._genesis(objectives=objectives)
        qs = g.generate(_trigger(EventType.UNCERTAINTY_DETECTED,
                                 {"subject": "the migration", "goal_id": goal.objective_id}))
        self.assertEqual(qs[0].goal_relevance, 1.0)

    def test_deterministic_identical_events(self):
        # Independent stores: identical events must yield identical questions.
        g = self._genesis(name="a.db")
        qs1 = g.generate(_trigger(EventType.CONTRADICTION_FOUND,
                                  {"expected": "A", "observed": "B"}))
        g2 = self._genesis(name="b.db")
        qs2 = g2.generate(_trigger(EventType.CONTRADICTION_FOUND,
                                   {"expected": "A", "observed": "B"}))
        self.assertEqual(len(qs1), 1)
        self.assertEqual(len(qs2), 1)
        self.assertEqual(qs1[0].question, qs2[0].question)
        self.assertEqual(qs1[0].fingerprint, qs2[0].fingerprint)

    def test_malformed_payload_tolerated(self):
        g = self._genesis()
        qs = g.generate(_trigger(EventType.ANOMALY_DETECTED,
                                 {"unexpected_key": "x", "question_metrics": {"urgency": 9.0}}))
        self.assertEqual(len(qs), 1)
        self.assertLessEqual(qs[0].urgency, 1.0)  # clamped by the model


# ---------------------------------------------------------------------------
# 3. HYPOTHESIS MODEL & ENGINE
# ---------------------------------------------------------------------------

class TestHypothesisModel(unittest.TestCase):
    def test_create_structured_hypothesis(self):
        h = Hypothesis(question_id="q_1", statement="A hidden cause produced B.",
                       assumptions=["hidden variable"], predictions=["p"],
                       expected_evidence=["e"], failure_conditions=["f"])
        self.assertEqual(h.status, HypothesisLifecycle.PROPOSED)
        self.assertLess(h.confidence, 1.0)
        self.assertTrue(h.hypothesis_id.startswith("hyp_"))

    def test_empty_statement_rejected(self):
        with self.assertRaises(HypothesisValidationError):
            Hypothesis(question_id="q_1", statement="   ")

    def test_missing_question_ref_rejected(self):
        with self.assertRaises(HypothesisValidationError):
            Hypothesis(question_id="", statement="anything")

    def test_serialization_roundtrip(self):
        h = Hypothesis(question_id="q_1", statement="s",
                       assumptions=["a"], predictions=["p"],
                       expected_evidence=["e"], failure_conditions=["f"])
        h2 = Hypothesis.from_dict(h.to_dict())
        self.assertEqual(h2.hypothesis_id, h.hypothesis_id)
        self.assertEqual(h2.assumptions, ["a"])
        self.assertEqual(h2.failure_conditions, ["f"])


class TestHypothesisStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice2_hstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persistence_roundtrip_and_restart(self):
        db = os.path.join(self.tmp, "hypotheses.db")
        store1 = HypothesisStore(db_path=db, strict_load=True)
        h = Hypothesis(question_id="q_1", statement="An unobserved cause produced B.",
                       assumptions=["hidden variable"], predictions=["re-observation"],
                       expected_evidence=["measurement"], failure_conditions=["ruled out"])
        store1.put(h)

        store2 = HypothesisStore(db_path=db, strict_load=True)
        loaded = store2.get(h.hypothesis_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.question_id, "q_1")
        self.assertEqual(loaded.assumptions, ["hidden variable"])
        self.assertEqual(store2.list_by_question("q_1"), [loaded])

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "hypotheses.db")
        store1 = HypothesisStore(db_path=db, strict_load=True)
        store1.put(Hypothesis(question_id="q_1", statement="keep me"))
        conn = sqlite3.connect(db)
        conn.execute("UPDATE hypotheses SET payload = ?", ('{"broken',))
        conn.commit()
        conn.close()
        with self.assertRaises(HypothesisStoreIntegrityError):
            HypothesisStore(db_path=db, strict_load=True)

    def test_corrupt_row_non_strict_not_silent(self):
        db = os.path.join(self.tmp, "hypotheses.db")
        store1 = HypothesisStore(db_path=db, strict_load=True)
        store1.put(Hypothesis(question_id="q_1", statement="keep me"))
        conn = sqlite3.connect(db)
        conn.execute("UPDATE hypotheses SET payload = ?",
                     (json.dumps({"hypothesis_id": "hyp_x", "question_id": "q_1",
                                  "statement": ""}),))
        conn.commit()
        conn.close()
        store2 = HypothesisStore(db_path=db, strict_load=False)
        self.assertGreaterEqual(len(store2.load_errors), 1)
        self.assertEqual(store2.count(), 0)


class TestHypothesisEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice2_hengine_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _engine(self):
        hstore = HypothesisStore(db_path=os.path.join(self.tmp, "h.db"), strict_load=True)
        qstore = QuestionStore(db_path=os.path.join(self.tmp, "q.db"), strict_load=True)
        return HypothesisEngine(hypothesis_store=hstore, question_store=qstore)

    def _setup(self, source="CONTRADICTION", metadata=None, question_text=None):
        """Return (engine, stored_question) so generate_for_question can resolve the ref."""
        engine = self._engine()
        q = Question(
            question=question_text or "What alternative variable could explain B?",
            source=source,
            metadata=metadata if metadata is not None else {"observed": "B", "expected": "A"},
        )
        engine.question_store.put(q)
        return engine, q

    def test_competing_hypotheses_for_contradiction(self):
        engine, q = self._setup()
        hyps = engine.generate_for_question(q)
        self.assertGreaterEqual(len(hyps), 2)
        statements = [h.statement for h in hyps]
        self.assertTrue(any("unobserved cause" in s for s in statements))      # H1 hidden cause
        self.assertTrue(any("observation" in s and "inaccurate" in s for s in statements))  # H2 bad observation
        for h in hyps:
            self.assertEqual(h.question_id, q.question_id)

    def test_each_hypothesis_has_full_structure(self):
        engine, q = self._setup()
        hyps = engine.generate_for_question(q)
        for h in hyps:
            self.assertTrue(h.assumptions, "assumptions missing")
            self.assertTrue(h.predictions, "predictions missing")
            self.assertTrue(h.expected_evidence, "expected evidence missing")
            self.assertTrue(h.failure_conditions, "failure conditions missing")

    def test_hypotheses_are_never_knowledge(self):
        engine, q = self._setup()
        hyps = engine.generate_for_question(q)
        for h in hyps:
            self.assertEqual(h.status, HypothesisLifecycle.PROPOSED)
            self.assertEqual(h.supporting_evidence, [])
            self.assertEqual(h.contradicting_evidence, [])
            self.assertLess(h.confidence, 1.0)  # never certainty

    def test_unknown_question_reference_rejected(self):
        engine = self._engine()
        q = Question(question="orphan question", source="UNCERTAINTY")
        with self.assertRaises(HypothesisValidationError):
            engine.generate_for_question(q)

    def test_duplicate_hypotheses_skipped(self):
        engine, q = self._setup()
        first = engine.generate_for_question(q)
        second = engine.generate_for_question(q)
        self.assertGreaterEqual(len(first), 2)
        self.assertEqual(second, [])  # all duplicates skipped
        self.assertEqual(len(engine.hypotheses.list_by_question(q.question_id)), len(first))

    def test_generic_fallback_for_other_sources(self):
        engine, q = self._setup(source="UNCERTAINTY", question_text="What is the state of X?")
        hyps = engine.generate_for_question(q)
        self.assertGreaterEqual(len(hyps), 2)

    def test_goal_gap_hypotheses(self):
        engine, q = self._setup(
            source="MISSING_DEPENDENCY",
            metadata={"dependency": "the migration", "goal_title": "finish deployment"},
            question_text="What is the current state of the migration for goal 'finish deployment'?",
        )
        hyps = engine.generate_for_question(q)
        self.assertGreaterEqual(len(hyps), 2)


# ---------------------------------------------------------------------------
# 4. RUNTIME INTEGRATION
# ---------------------------------------------------------------------------

class TestSlice2RuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice2_rt_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_event_to_question_to_attention_to_hypotheses(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        await rt.event_bus.publish(_trigger(EventType.CONTRADICTION_FOUND,
                                            {"expected": "A", "observed": "B"}),
                                   dispatch_immediately=True)
        # event -> question
        unresolved = rt.question_store.list_unresolved()
        self.assertEqual(len(unresolved), 1)
        q = unresolved[0]
        # question -> attention (selected -> INVESTIGATING after hypotheses)
        self.assertEqual(q.status, QuestionLifecycle.INVESTIGATING)
        self.assertGreaterEqual(rt.attention.stats()["selected_count"], 1)
        self.assertEqual(rt.state.current_focus, q.question)
        # selected question -> competing hypotheses
        hyps = rt.hypothesis_store.list_by_question(q.question_id)
        self.assertGreaterEqual(len(hyps), 2)
        self.assertEqual(q.related_hypotheses, [h.hypothesis_id for h in hyps])
        # full bus trail
        replayed = await rt.event_bus.replay_events(limit=200)
        types = [e.event_type for e in replayed]
        for expected in (EventType.CONTRADICTION_FOUND, EventType.QUESTION_GENERATED,
                         EventType.ATTENTION_CANDIDATE_CREATED, EventType.ATTENTION_SELECTED,
                         EventType.QUESTION_SELECTED, EventType.HYPOTHESES_GENERATED):
            self.assertIn(expected, types)
        await rt.stop()

    async def test_required_e2e_contradiction_scenario(self):
        """Known: A normally precedes B. Observed: B occurred but A did not."""
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        await rt.event_bus.publish(_trigger(EventType.CONTRADICTION_FOUND, {
            "subject": "sequence A->B",
            "expected": "A",
            "observed": "B",
            "description": "B occurred without A",
            "beliefs": ["A normally precedes B"],
        }), dispatch_immediately=True)

        # 1-2. inconsistency detected -> event -> internal question generated.
        qs = rt.question_store.list_unresolved()
        self.assertEqual(len(qs), 1)
        q = qs[0]
        self.assertEqual(q.source, "CONTRADICTION")
        # 3. scored via Slice 1 attention.
        self.assertGreater(q.priority, 0.0)
        # 4-5. attention selected it.
        self.assertEqual(q.status, QuestionLifecycle.INVESTIGATING)
        self.assertIn("B", rt.state.current_focus)
        # 6. at least 2 competing hypotheses, each fully structured.
        hyps = rt.hypothesis_store.list_by_question(q.question_id)
        self.assertGreaterEqual(len(hyps), 2)
        for h in hyps:
            self.assertTrue(h.assumptions and h.predictions
                            and h.expected_evidence and h.failure_conditions)
        # 7-8. nothing declared true, no experiments performed.
        self.assertFalse(any(h.status == HypothesisLifecycle.CONFIRMED for h in hyps))
        self.assertIsNone(q.resolution)
        self.assertEqual(rt.state.runtime_status.value, "RUNNING")
        await rt.stop()

    async def test_goal_relevance_via_goal_field(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        goal = await rt.create_goal(objective="Finish deployment", priority=90)
        await rt.activate_goal(goal.objective_id)
        await rt.event_bus.publish(_trigger(EventType.UNCERTAINTY_DETECTED, {
            "subject": "the migration", "goal_id": goal.objective_id,
        }), dispatch_immediately=True)
        qs = rt.question_store.list_unresolved()
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].related_goal, goal.objective_id)
        self.assertEqual(qs[0].goal_relevance, 1.0)
        await rt.stop()

    async def test_user_request_flow(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        await rt.event_bus.publish(_trigger(EventType.USER_INTERACTION,
                                            {"transcript": "Check the migration state"}),
                                   dispatch_immediately=True)
        qs = rt.question_store.list_unresolved()
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].source_kind.value, "USER_REQUESTED")
        self.assertEqual(qs[0].status, QuestionLifecycle.INVESTIGATING)
        await rt.stop()

    async def test_deduplication_at_runtime(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        # Two distinct events with identical payloads: genesis must produce one question.
        await rt.event_bus.publish(_trigger(EventType.ANOMALY_DETECTED, {"entity": "host-3"}),
                                   dispatch_immediately=True)
        await rt.event_bus.publish(_trigger(EventType.ANOMALY_DETECTED, {"entity": "host-3"}),
                                   dispatch_immediately=True)
        self.assertEqual(rt.question_store.count(), 1)
        await rt.stop()

    async def test_restart_preserves_questions_hypotheses_relationships(self):
        dir1 = os.path.join(self.tmp, "data")
        rt1 = CognitiveRuntime(data_dir=dir1)
        await rt1.start()
        await rt1.event_bus.publish(_trigger(EventType.CONTRADICTION_FOUND,
                                             {"expected": "A", "observed": "B"}),
                                    dispatch_immediately=True)
        q1 = rt1.question_store.list_unresolved()[0]
        hyp_ids = rt1.hypothesis_store.list_by_question(q1.question_id)
        self.assertGreaterEqual(len(hyp_ids), 2)
        await rt1.stop()

        rt2 = CognitiveRuntime(data_dir=dir1)
        await rt2.start()
        q2 = rt2.question_store.get(q1.question_id)
        self.assertIsNotNone(q2)
        self.assertEqual(q2.status, QuestionLifecycle.INVESTIGATING)
        self.assertEqual(q2.related_hypotheses, q1.related_hypotheses)
        hyps2 = rt2.hypothesis_store.list_by_question(q1.question_id)
        self.assertEqual(len(hyps2), len(hyp_ids))
        self.assertEqual(hyps2[0].assumptions, hyp_ids[0].assumptions)
        await rt2.stop()

    async def test_voice_events_do_not_generate_questions(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        for vt in (EventType.VOICE_STARTED, EventType.VOICE_TRANSCRIPT_PARTIAL,
                   EventType.VOICE_TRANSCRIPT_FINAL, EventType.VOICE_INTERRUPTED,
                   EventType.VOICE_ENDED):
            await rt.event_bus.publish(Event(event_type=vt, payload={"session_id": "s"},
                                             source="voice_pipeline"),
                                       dispatch_immediately=True)
        self.assertEqual(rt.question_store.count(), 0)
        self.assertEqual(rt.hypothesis_store.count(), 0)
        await rt.stop()

    async def test_malformed_event_payloads(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        # Non-dict payload is rejected at the bus boundary.
        with self.assertRaises(EventValidationError):
            await rt.event_bus.publish(Event(event_type=EventType.ANOMALY_DETECTED,
                                             payload="not a dict"),
                                       dispatch_immediately=True)
        # Empty trigger payloads fall back to defaults without crashing.
        await rt.event_bus.publish(_trigger(EventType.ANOMALY_DETECTED),
                                   dispatch_immediately=True)
        await rt.event_bus.publish(_trigger(EventType.GOAL_GAP_DETECTED),
                                   dispatch_immediately=True)
        self.assertGreaterEqual(rt.question_store.count(), 1)
        await rt.stop()

    async def test_malicious_generated_text_is_data_not_commands(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        evil = "import os; os.system('rm -rf /')"
        await rt.event_bus.publish(_trigger(EventType.USER_INTERACTION,
                                            {"transcript": evil}),
                                   dispatch_immediately=True)
        qs = rt.question_store.list_unresolved()
        self.assertEqual(len(qs), 1)
        # The text is stored as data; nothing was executed (no crash, no side effect).
        self.assertEqual(qs[0].question, evil)
        self.assertEqual(qs[0].source_kind.value, "USER_REQUESTED")
        await rt.stop()

    async def test_hallucinated_evidence_not_promoted(self):
        rt = CognitiveRuntime(data_dir=self.tmp)
        await rt.start()
        await rt.event_bus.publish(_trigger(EventType.CONTRADICTION_FOUND,
                                            {"expected": "A", "observed": "B"}),
                                   dispatch_immediately=True)
        q = rt.question_store.list_unresolved()[0]
        for h in rt.hypothesis_store.list_by_question(q.question_id):
            # expected_evidence is a plan of what would count, never recorded evidence.
            self.assertEqual(h.supporting_evidence, [])
            self.assertNotEqual(h.status, HypothesisLifecycle.SUPPORTED)
            self.assertNotEqual(h.status, HypothesisLifecycle.CONFIRMED)
        await rt.stop()


class TestSlice2EngineIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice2_engine_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_engine_wires_question_foundation(self):
        engine = AscendantEngine(data_dir=self.tmp)
        await engine.start()
        rt = engine.cognitive_runtime
        self.assertIsNotNone(rt.question_genesis)
        self.assertIsNotNone(rt.hypothesis_engine)
        # A real engine-level contradiction flows through the shared bus.
        await engine.event_bus.publish(_trigger(EventType.CONTRADICTION_FOUND,
                                                {"expected": "A", "observed": "B"}),
                                       dispatch_immediately=True)
        qs = rt.question_store.list_unresolved()
        self.assertGreaterEqual(len(qs), 1)
        self.assertGreaterEqual(
            len(rt.hypothesis_store.list_by_question(qs[0].question_id)), 2)
        await engine.stop()


if __name__ == "__main__":
    unittest.main()
