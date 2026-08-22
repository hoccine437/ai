"""
Slice 4 — Experience -> Distillation -> Validation -> Reuse test suite.

Covers: ExperienceEpisode model/store, DistilledExperience model/store,
FailureLearning (recurrence, root-cause lifecycle), ExperienceDistillation
(deterministic distillation + evidence-based validation), ExperienceReuse
(scored, bounded retrieval), the required E2E (tool succeeds once, fails on
expired auth four times -> recurrence -> failure records -> root cause ->
candidate prevention rule -> validated with provenance -> retrievable), and
adversarial cases. Runs entirely without an LLM.

Run with:
    python3 -m unittest tests.test_experience_foundation -v
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

from zerion.runtime.event_bus import AsyncEventBus
from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.episode import (
    EpisodeMode,
    EpisodeStatus,
    EpisodeStore,
    EpisodeStoreIntegrityError,
    EpisodeValidationError,
    ExperienceEpisode,
    episode_fingerprint,
)
from zerion.cognitive_os.distilled import (
    CausalityStatus,
    DistilledExperience,
    DistilledExperienceStore,
    DistilledStoreIntegrityError,
    DistilledType,
    DistilledValidationError,
    ValidationStatus,
)
from zerion.cognitive_os.failure_learning import (
    FailureClassification,
    FailureLearning,
    FailureRecord,
    FailureStore,
    FailureStoreIntegrityError,
    RootCauseStatus,
)
from zerion.cognitive_os.experience_distillation import ExperienceDistillation
from zerion.cognitive_os.knowledge_retrieval import ExperienceReuse
from zerion.cognitive_os.evidence import Evidence, EvidenceMode, EvidenceVerdict, EvidenceStore, Provenance
from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
from zerion.cognitive_os.objective_manager import ObjectiveContinuityManager
from zerion.engine import AscendantEngine


AUTH_FAIL = {
    "action": "execute_tool",
    "error": "tool returned authentication error",
    "classification": FailureClassification.TOOL_FAILURE,
    "signals": ["authentication expired"],
    "recovery_attempt": "retry",
    "recovery_result": "failed",
}


def _episode(context="run deployment", success=False, actions=None, outcomes=None,
             mode=EpisodeMode.TEST, episode_id=None):
    return ExperienceEpisode(
        episode_id=episode_id or f"ep_{int(time.time()*1000)}",
        context=context,
        actions=actions or [],
        outcomes=outcomes or [],
        success=success,
        mode=mode,
        status=EpisodeStatus.COMPLETED,
        completed_at=time.time() + 1.0,
    )


# ---------------------------------------------------------------------------
# 1. EXPERIENCE EPISODE
# ---------------------------------------------------------------------------

class TestEpisodeModel(unittest.TestCase):
    def test_create_structured_episode(self):
        ep = _episode(context="run deployment", success=True,
                      actions=[{"action": "deploy", "at": 1.0}],
                      outcomes=[{"outcome": "deployed", "at": 2.0}])
        self.assertTrue(ep.episode_id.startswith("ep_"))
        self.assertEqual(ep.status, EpisodeStatus.COMPLETED)
        self.assertEqual(ep.mode, EpisodeMode.TEST)
        self.assertTrue(ep.fingerprint)

    def test_empty_context_rejected(self):
        with self.assertRaises(EpisodeValidationError):
            ExperienceEpisode(context="   ")

    def test_completed_before_started_rejected(self):
        with self.assertRaises(EpisodeValidationError):
            ExperienceEpisode(context="x", started_at=5.0, completed_at=1.0)

    def test_success_and_failure_have_different_fingerprints(self):
        ok = episode_fingerprint("deploy", ["run"], "success")
        bad = episode_fingerprint("deploy", ["run"], "failed")
        self.assertNotEqual(ok, bad)

    def test_serialization_roundtrip(self):
        ep = _episode(success=True, actions=[{"action": "a", "at": 1.0}])
        ep2 = ExperienceEpisode.from_dict(ep.to_dict())
        self.assertEqual(ep2.episode_id, ep.episode_id)
        self.assertEqual(ep2.actions, ep.actions)
        self.assertEqual(ep2.fingerprint, ep.fingerprint)


class TestEpisodeStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_epstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persistence_roundtrip_and_restart(self):
        db = os.path.join(self.tmp, "episodes.db")
        s1 = EpisodeStore(db_path=db, strict_load=True)
        ep = _episode(success=True)
        s1.put(ep)
        s2 = EpisodeStore(db_path=db, strict_load=True)
        loaded = s2.get(ep.episode_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.context, ep.context)
        self.assertEqual(s2.count(), 1)

    def test_duplicate_episodes_detectable_but_never_lost(self):
        db = os.path.join(self.tmp, "episodes.db")
        s = EpisodeStore(db_path=db, strict_load=True)
        a = _episode(context="same", success=False, episode_id="ep_a")
        b = _episode(context="same", success=False, episode_id="ep_b")
        self.assertEqual(a.fingerprint, b.fingerprint)  # flagged as duplicates
        s.put(a)
        s.put(b)
        self.assertEqual(s.count(), 2)  # both kept — no silent loss
        self.assertEqual(s.get_by_fingerprint(a.fingerprint).episode_id, a.episode_id)

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "episodes.db")
        s1 = EpisodeStore(db_path=db, strict_load=True)
        s1.put(_episode())
        conn = sqlite3.connect(db)
        conn.execute("UPDATE episodes SET payload = ?", ("not json{",))
        conn.commit()
        conn.close()
        with self.assertRaises(EpisodeStoreIntegrityError):
            EpisodeStore(db_path=db, strict_load=True)

    def test_corrupt_row_non_strict_not_silent(self):
        db = os.path.join(self.tmp, "episodes.db")
        s1 = EpisodeStore(db_path=db, strict_load=True)
        s1.put(_episode())
        conn = sqlite3.connect(db)
        conn.execute("UPDATE episodes SET payload = ?",
                     (json.dumps({"episode_id": "ep_x", "context": "",
                                  "started_at": 2.0, "completed_at": 1.0}),))
        conn.commit()
        conn.close()
        s2 = EpisodeStore(db_path=db, strict_load=False)
        self.assertGreaterEqual(len(s2.load_errors), 1)
        self.assertEqual(s2.count(), 0)


# ---------------------------------------------------------------------------
# 2. DISTILLED EXPERIENCE MODEL & STORE
# ---------------------------------------------------------------------------

class TestDistilledModel(unittest.TestCase):
    def test_create_structured_distilled(self):
        item = DistilledExperience(
            type=DistilledType.FAILURE_PREVENTION_RULE,
            statement="'execute_tool' fails when authentication expired.",
            conditions="deploy", action="check credentials before retry",
            expected_outcome="success", source_episodes=["ep_1"])
        self.assertEqual(item.validation_status, ValidationStatus.CANDIDATE)
        self.assertEqual(item.causality_status, CausalityStatus.CAUSAL_HYPOTHESIS)
        self.assertTrue(item.fingerprint)

    def test_empty_statement_rejected(self):
        with self.assertRaises(DistilledValidationError):
            DistilledExperience(statement="  ")

    def test_confidence_bounds(self):
        with self.assertRaises(DistilledValidationError):
            DistilledExperience(statement="x", confidence=1.5)

    def test_dedup_fingerprint(self):
        a = DistilledExperience(type=DistilledType.WARNING, statement="watch out",
                                conditions="deploy")
        b = DistilledExperience(type=DistilledType.WARNING, statement="watch out",
                                conditions="deploy")
        c = DistilledExperience(type=DistilledType.WARNING, statement="watch out",
                                conditions="rollback")
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, c.fingerprint)


class TestDistilledStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_dstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persistence_restart_with_history(self):
        db = os.path.join(self.tmp, "distilled.db")
        s1 = DistilledExperienceStore(db_path=db, strict_load=True)
        item = DistilledExperience(type=DistilledType.WARNING, statement="s",
                                   conditions="c", validation_status=ValidationStatus.VALIDATING,
                                   confidence=0.5,
                                   revision_history=[{"event": "validation"}])
        s1.put(item)
        s2 = DistilledExperienceStore(db_path=db, strict_load=True)
        loaded = s2.get(item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.validation_status, ValidationStatus.VALIDATING)
        self.assertEqual(loaded.revision_history, [{"event": "validation"}])

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "distilled.db")
        s1 = DistilledExperienceStore(db_path=db, strict_load=True)
        s1.put(DistilledExperience(statement="s", conditions="c"))
        conn = sqlite3.connect(db)
        conn.execute("UPDATE distilled SET payload = ?", ('{"broken',))
        conn.commit()
        conn.close()
        with self.assertRaises(DistilledStoreIntegrityError):
            DistilledExperienceStore(db_path=db, strict_load=True)


# ---------------------------------------------------------------------------
# 3. FAILURE LEARNING
# ---------------------------------------------------------------------------

class TestFailureLearning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_failure_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fl(self):
        return FailureLearning(FailureStore(db_path=os.path.join(self.tmp, "f.db"),
                                            strict_load=True))

    def test_first_failure_creates_record(self):
        fl = self._fl()
        res = fl.record_failure(episode_id="ep_1", action="run", error="boom",
                                signals=["s1"], classification=FailureClassification.TOOL_FAILURE)
        self.assertTrue(res["created"])
        self.assertEqual(res["repeat_count"], 1)
        self.assertFalse(res["escalated"])
        self.assertEqual(res["root_cause"].status, RootCauseStatus.UNCONFIRMED)
        self.assertIn("s1", res["root_cause"].signals)

    def test_repeated_identical_failure_detects_recurrence(self):
        fl = self._fl()
        for i in range(1, 5):
            res = fl.record_failure(episode_id=f"ep_{i}", action="run", error="boom",
                                    signals=["s1"])
        self.assertEqual(res["repeat_count"], 4)
        self.assertEqual(res["failure"].episodes, ["ep_1", "ep_2", "ep_3", "ep_4"])
        self.assertTrue(res["escalated"])  # crossed the escalation threshold

    def test_root_cause_not_assumed_on_first_occurrence(self):
        fl = self._fl()
        res = fl.record_failure(episode_id="ep_1", action="run", error="boom",
                                signals=["mystery signal"])
        rc = res["root_cause"]
        self.assertEqual(rc.status, RootCauseStatus.UNCONFIRMED)
        self.assertEqual(len(rc.supporting_episodes), 1)
        # The statement references the OBSERVED signal — never a fabricated cause.
        self.assertIn("mystery signal", rc.statement)

    def test_root_cause_confirmed_by_recurrence_only(self):
        fl = self._fl()
        first = fl.record_failure(episode_id="ep_1", action="run", error="boom",
                                  signals=["s1"], signal_reliability=0.9)
        rc = first["root_cause"]
        self.assertEqual(rc.status, RootCauseStatus.UNCONFIRMED)
        for i in range(2, 6):
            fl.record_failure(episode_id=f"ep_{i}", action="run", error="boom",
                              signals=["s1"], signal_reliability=0.9)
        rc = fl.store.get_root_cause(rc.hypothesis_id)
        self.assertEqual(rc.status, RootCauseStatus.CONFIRMED)
        self.assertGreaterEqual(rc.confidence, 0.6)
        self.assertGreaterEqual(len(rc.revision_history), 2)  # history preserved

    def test_root_cause_rejected_by_counterexample(self):
        fl = self._fl()
        res = fl.record_failure(episode_id="ep_1", action="run", error="boom",
                                signals=["s1"], signal_reliability=0.9)
        fl.add_counterexample(res["failure"].failure_id, "ep_ok")
        rc = fl.store.get_root_cause(res["root_cause"].hypothesis_id)
        self.assertEqual(rc.status, RootCauseStatus.REJECTED)
        self.assertIn("ep_ok", rc.contradicting_episodes)

    def test_false_root_cause_single_episode_never_confirmed(self):
        fl = self._fl()
        res = fl.record_failure(episode_id="ep_1", action="run", error="boom",
                                signals=["s1"])
        rc = fl.store.get_root_cause(res["root_cause"].hypothesis_id)
        self.assertEqual(rc.status, RootCauseStatus.UNCONFIRMED)  # never PROPOSED-as-fact


class TestFailureStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_fstore_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persistence_restart_failures_and_root_causes(self):
        db = os.path.join(self.tmp, "f.db")
        s1 = FailureStore(db_path=db, strict_load=True)
        fl = FailureLearning(s1)
        res = fl.record_failure(episode_id="ep_1", action="run", error="boom",
                                signals=["s1"])
        s2 = FailureStore(db_path=db, strict_load=True)
        f = s2.get_failure(res["failure"].failure_id)
        rc = s2.get_root_cause(res["root_cause"].hypothesis_id)
        self.assertIsNotNone(f)
        self.assertIsNotNone(rc)
        self.assertEqual(f.repeat_count, 1)
        self.assertEqual(rc.status, RootCauseStatus.UNCONFIRMED)

    def test_corrupt_row_strict_raises(self):
        db = os.path.join(self.tmp, "f.db")
        s1 = FailureStore(db_path=db, strict_load=True)
        fl = FailureLearning(s1)
        fl.record_failure(episode_id="ep_1", action="run", error="boom")
        conn = sqlite3.connect(db)
        conn.execute("UPDATE failures SET payload = ?", ('"junk"',))
        conn.commit()
        conn.close()
        with self.assertRaises(FailureStoreIntegrityError):
            FailureStore(db_path=db, strict_load=True)


# ---------------------------------------------------------------------------
# 4. EXPERIENCE DISTILLATION + VALIDATION
# ---------------------------------------------------------------------------

class _DistillHarness:
    def __init__(self, tmp):
        self.tmp = tmp
        self.episodes = EpisodeStore(db_path=os.path.join(tmp, "ep.db"), strict_load=True)
        self.distilled = DistilledExperienceStore(db_path=os.path.join(tmp, "d.db"),
                                                  strict_load=True)
        self.failures = FailureStore(db_path=os.path.join(tmp, "f.db"), strict_load=True)
        self.evidence = EvidenceStore(db_path=os.path.join(tmp, "ev.db"), strict_load=True)
        self.fl = FailureLearning(self.failures)
        self.dist = ExperienceDistillation(episode_store=self.episodes,
                                           distilled_store=self.distilled,
                                           failure_store=self.failures,
                                           evidence_store=self.evidence)

    def add_episode(self, success=False, failures=None, actions=None,
                    context="deploy", episode_id=None):
        ep = _episode(context=context, success=success, actions=actions or [],
                      episode_id=episode_id)
        self.episodes.put(ep)
        for f in failures or []:
            res = self.fl.record_failure(
                episode_id=ep.episode_id, action=f["action"], error=f["error"],
                classification=f.get("classification"),
                signals=f.get("signals"))
            ep.failures.append(res["failure"].failure_id)
        self.episodes.put(ep)
        return ep


class TestDistillationValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_dist_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_single_successful_episode_never_universal(self):
        h = _DistillHarness(self.tmp)
        ep = h.add_episode(success=True, actions=[{"action": "run", "at": 1.0}])
        produced = h.dist.distill_episode(ep)
        h.dist.validate_lessons()
        self.assertEqual(len(produced), 1)  # PROCEDURE
        item = h.distilled.get(produced[0].id)
        self.assertEqual(item.validation_status, ValidationStatus.CANDIDATE)
        self.assertNotEqual(item.validation_status, ValidationStatus.VALIDATED)
        self.assertLess(item.confidence, 0.7)  # never high from one episode

    def test_duplicate_lesson_merged_not_duplicated(self):
        h = _DistillHarness(self.tmp)
        for i in range(3):
            ep = h.add_episode(failures=[AUTH_FAIL], episode_id=f"ep_{i}")
            h.dist.distill_episode(ep)
        rules = [i for i in h.distilled.list()
                 if i.type == DistilledType.FAILURE_PREVENTION_RULE]
        self.assertEqual(len(rules), 1)  # merged, never duplicated
        self.assertEqual(len(rules[0].source_episodes), 3)

    def test_prevention_rule_validated_after_repeatable_evidence(self):
        h = _DistillHarness(self.tmp)
        for i in range(4):
            ep = h.add_episode(failures=[AUTH_FAIL], episode_id=f"ep_{i}")
            h.dist.distill_episode(ep)
        h.dist.validate_lessons()
        rules = [i for i in h.distilled.list()
                 if i.type == DistilledType.FAILURE_PREVENTION_RULE]
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.validation_status, ValidationStatus.VALIDATED)
        self.assertGreaterEqual(rule.confidence, 0.7)
        self.assertEqual(len(rule.source_episodes), 4)
        self.assertEqual(rule.counterexamples, [])
        # Every validated rule references its origin evidence.
        self.assertIn("failure_id", rule.provenance)

    def test_counterexample_weakens_validated_rule(self):
        h = _DistillHarness(self.tmp)
        for i in range(4):
            ep = h.add_episode(failures=[AUTH_FAIL], episode_id=f"ep_{i}")
            h.dist.distill_episode(ep)
        h.dist.validate_lessons()
        rule = [i for i in h.distilled.list()
                if i.type == DistilledType.FAILURE_PREVENTION_RULE][0]
        # A contradictory episode: same action, same signal, but the tool worked.
        ok = h.add_episode(success=True, actions=[{"action": "execute_tool", "at": 1.0}],
                           episode_id="ep_ok")
        rule = h.dist.add_counterexample(rule.id, ok.episode_id, h.episodes)
        self.assertEqual(rule.validation_status, ValidationStatus.WEAKENED)
        self.assertIn(ok.episode_id, rule.counterexamples)

    def test_low_confidence_rule_never_validated(self):
        h = _DistillHarness(self.tmp)
        ep = h.add_episode(failures=[AUTH_FAIL], episode_id="ep_1")
        h.dist.distill_episode(ep)
        h.dist.validate_lessons()
        rule = [i for i in h.distilled.list()
                if i.type == DistilledType.FAILURE_PREVENTION_RULE][0]
        self.assertEqual(rule.validation_status, ValidationStatus.CANDIDATE)
        self.assertLess(rule.confidence, 0.7)

    def test_causal_claim_without_experiment_evidence_stays_hypothesis(self):
        h = _DistillHarness(self.tmp)
        ep = h.add_episode(success=True, actions=[{"action": "a", "at": 1.0}])
        ep.question_ids = ["q_1"]
        ep.hypothesis_ids = ["hyp_1"]
        h.episodes.put(ep)
        produced = h.dist.distill_episode(ep)
        causal = [i for i in produced if i.type == DistilledType.CAUSAL_PATTERN]
        self.assertEqual(len(causal), 1)
        h.dist.validate_lessons()
        # Correlation alone: never promoted to confirmed causation.
        item = h.dist.promote_causality(causal[0].id)
        self.assertEqual(item.causality_status, CausalityStatus.CAUSAL_HYPOTHESIS)

    def test_causal_claim_promoted_only_with_observed_evidence(self):
        h = _DistillHarness(self.tmp)
        ep = h.add_episode(success=True, actions=[{"action": "a", "at": 1.0}])
        ep.question_ids = ["q_1"]
        h.episodes.put(ep)
        causal = [i for i in h.dist.distill_episode(ep)
                  if i.type == DistilledType.CAUSAL_PATTERN][0]
        # Simulated evidence is NOT enough.
        sim = Evidence(content={"matches": ["p"]},
                       provenance=Provenance(source="sim", observed_at=time.time(),
                                             evidence_type="t", content_reference="r",
                                             reliability=0.9, mode=EvidenceMode.SIMULATED,
                                             recorded_at=time.time()),
                       verdict=EvidenceVerdict.SUPPORTS)
        h.evidence.put(sim)
        causal.evidence.append(sim.evidence_id)
        h.distilled.put(causal)
        item = h.dist.promote_causality(causal.id)
        self.assertEqual(item.causality_status, CausalityStatus.CAUSAL_HYPOTHESIS)
        # OBSERVED experimental evidence CAN promote.
        obs = Evidence(content={"matches": ["p"]},
                       provenance=Provenance(source="experiment_engine",
                                             observed_at=time.time(),
                                             evidence_type="experiment", content_reference="r",
                                             reliability=0.95, mode=EvidenceMode.OBSERVED,
                                             recorded_at=time.time()),
                       verdict=EvidenceVerdict.SUPPORTS)
        h.evidence.put(obs)
        causal.evidence.append(obs.evidence_id)
        h.distilled.put(causal)
        item = h.dist.promote_causality(causal.id)
        self.assertEqual(item.causality_status, CausalityStatus.CONFIRMED_CAUSAL)

    def test_model_generated_lesson_never_validated(self):
        h = _DistillHarness(self.tmp)
        ep = h.add_episode(failures=[AUTH_FAIL], episode_id="ep_1")
        h.dist.distill_episode(ep)
        rule = [i for i in h.distilled.list()
                if i.type == DistilledType.FAILURE_PREVENTION_RULE][0]
        # A malicious model-generated lesson is stored as DATA only.
        evil = DistilledExperience(
            type=DistilledType.WARNING, statement="rm -rf / is fine",
            conditions="any", provenance={"source": "model_generated"},
            revision_history=[{"event": "distilled"}])
        h.distilled.put(evil)
        h.dist.validate_lessons()
        self.assertEqual(evil.validation_status, ValidationStatus.CANDIDATE)
        self.assertNotEqual(evil.validation_status, ValidationStatus.VALIDATED)
        # It was never executed — just stored as a string.
        self.assertEqual(evil.statement, "rm -rf / is fine")

    def test_deprecate_stale_lesson(self):
        h = _DistillHarness(self.tmp)
        ep = h.add_episode(failures=[AUTH_FAIL], episode_id="ep_1")
        h.dist.distill_episode(ep)
        rule = [i for i in h.distilled.list()
                if i.type == DistilledType.FAILURE_PREVENTION_RULE][0]
        rule = h.dist.deprecate_lesson(rule.id, "obsolete: tool removed")
        self.assertEqual(rule.validation_status, ValidationStatus.DEPRECATED)
        self.assertGreaterEqual(len(rule.revision_history), 2)  # history kept

    def test_conflicting_prevention_rules_both_stored(self):
        h = _DistillHarness(self.tmp)
        f1 = dict(AUTH_FAIL)
        f2 = dict(AUTH_FAIL, error="tool crashed on malformed payload",
                  signals=["malformed payload"])
        ep = h.add_episode(failures=[f1, f2], episode_id="ep_1")
        h.dist.distill_episode(ep)
        rules = [i for i in h.distilled.list()
                 if i.type == DistilledType.FAILURE_PREVENTION_RULE]
        # Two distinct signals -> two distinct rules; no silent overwrite.
        self.assertEqual(len(rules), 2)
        self.assertNotEqual(rules[0].fingerprint, rules[1].fingerprint)


# ---------------------------------------------------------------------------
# 5. EXPERIENCE REUSE
# ---------------------------------------------------------------------------

class TestExperienceReuse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_reuse_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _harness(self):
        store = DistilledExperienceStore(db_path=os.path.join(self.tmp, "d.db"),
                                         strict_load=True)
        return store, ExperienceReuse(store)

    def test_retrieval_is_bounded_and_relevant(self):
        store, reuse = self._harness()
        for i in range(8):
            store.put(DistilledExperience(
                type=DistilledType.WARNING, statement=f"unrelated warning {i}",
                conditions=f"topic_{i}", confidence=0.3,
                validation_status=ValidationStatus.VALIDATING))
        store.put(DistilledExperience(
            type=DistilledType.FAILURE_PREVENTION_RULE,
            statement="'execute_tool' fails when authentication expired.",
            conditions="deploy pipeline", action="refresh credentials",
            confidence=0.85, validation_status=ValidationStatus.VALIDATED,
            source_episodes=["ep_1"]))
        hits = reuse.retrieve(failure_pattern="deploy authentication expired tool",
                              top_k=3)
        self.assertLessEqual(len(hits), 3)  # never everything
        self.assertEqual(hits[0]["type"], "FAILURE_PREVENTION_RULE")
        self.assertGreater(hits[0]["score"], 0.3)

    def test_retrieval_is_deterministic(self):
        store, reuse = self._harness()
        store.put(DistilledExperience(statement="rule one", conditions="deploy",
                                      confidence=0.6, validation_status=ValidationStatus.VALIDATED))
        store.put(DistilledExperience(statement="rule two", conditions="database",
                                      confidence=0.8, validation_status=ValidationStatus.VALIDATED))
        a = reuse.retrieve(problem="database connection", top_k=5)
        b = reuse.retrieve(problem="database connection", top_k=5)
        self.assertEqual(a, b)

    def test_historical_usefulness_increases_score(self):
        store, reuse = self._harness()
        store.put(DistilledExperience(
            id="dis_a", type=DistilledType.PROCEDURE,
            statement="procedure for deploy", conditions="deploy",
            confidence=0.5, validation_status=ValidationStatus.VALIDATED))
        before = reuse.retrieve(problem="deploy", top_k=5)[0]["score"]
        reuse.record_use("dis_a", success=True)
        reuse.record_use("dis_a", success=True)
        after = reuse.retrieve(problem="deploy", top_k=5)[0]["score"]
        self.assertGreater(after, before)

    def test_retrieve_nothing_when_nothing_matches(self):
        _, reuse = self._harness()
        hits = reuse.retrieve(failure_pattern="zzz nothing like this", top_k=5)
        self.assertEqual(hits, [])


# ---------------------------------------------------------------------------
# 6. RUNTIME INTEGRATION + REQUIRED E2E
# ---------------------------------------------------------------------------

class TestSlice4RuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_rt_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_required_e2e_tool_success_then_repeated_auth_failure(self):
        """Episode 1: tool succeeds. Episodes 2-5: tool fails when authentication
        has expired. The system records all episodes, detects recurrence, creates
        failure records + root-cause hypothesis, distills a candidate prevention
        rule, validates it from evidence, stores it with provenance, and makes it
        retrievable for a future matching situation. Nothing is hard-coded: the
        observed signal comes from the environment, the conclusion from evidence."""
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()

        # 1. Record ALL episodes (E1 success, E2-E5 failure).
        ep1 = await rt.start_episode("execute tool for deployment", mode=EpisodeMode.TEST)
        await rt.complete_episode(ep1.episode_id, success=True,
                                  actions=[{"action": "execute_tool", "at": time.time()}],
                                  outcomes=[{"outcome": "succeeded", "at": time.time()}])
        failed_episodes = []
        for i in range(4):
            ep = await rt.start_episode("execute tool for deployment", mode=EpisodeMode.TEST)
            await rt.complete_episode(ep.episode_id, success=False, failures=[AUTH_FAIL])
            failed_episodes.append(ep)
        self.assertEqual(rt.episode_store.count(), 5)

        # 2. Recurrence detected: one failure record, repeat_count 4.
        failures = rt.failure_store.list_failures()
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].repeat_count, 4)
        self.assertEqual(len(failures[0].episodes), 4)

        # 3. Repeated failure escalated into an investigation question that
        #    competed for Slice 1 attention (no endless silent repetition).
        replayed = await rt.event_bus.replay_events(limit=400)
        types = [e.event_type for e in replayed]
        self.assertGreaterEqual(types.count(EventType.FAILURE_REPEATED), 3)
        self.assertIn(EventType.REPEATED_FAILURE_DETECTED, types)
        repeat_qs = [q for q in rt.question_store.list()
                     if q.source == "REPEATED_FAILURE"]
        self.assertGreaterEqual(len(repeat_qs), 1)
        q = repeat_qs[0]
        self.assertEqual(q.status.value, "INVESTIGATING")  # attention selected it
        self.assertIn("failures", rt.state.current_focus)

        # 4. Root-cause hypothesis generated; evidence determined its status.
        causes = rt.failure_store.list_root_causes()
        self.assertEqual(len(causes), 1)
        rc = causes[0]
        self.assertIn("authentication expired", rc.statement)
        self.assertEqual(rc.status, RootCauseStatus.CONFIRMED)  # recurrence + no counterexamples
        self.assertGreaterEqual(len(rc.revision_history), 2)
        self.assertEqual(rc.supporting_episodes, [e.episode_id for e in failed_episodes])

        # 5-6. Candidate prevention rule distilled, then VALIDATED from evidence.
        rules = [i for i in rt.distilled_store.list()
                 if i.type == DistilledType.FAILURE_PREVENTION_RULE]
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.validation_status, ValidationStatus.VALIDATED)
        self.assertGreaterEqual(rule.confidence, 0.7)
        self.assertEqual(rule.counterexamples, [])

        # 7. Stored with provenance and episode relationships.
        self.assertEqual(rule.source_episodes, [e.episode_id for e in failed_episodes])
        self.assertEqual(rule.provenance["source"], "experience_distillation")
        self.assertIn("failure_id", rule.provenance)
        self.assertEqual(rule.provenance["signals"], ["authentication expired"])
        self.assertIn(EventType.LESSON_VALIDATED, types)
        self.assertIn(EventType.PREVENTION_RULE_CREATED, types)

        # 8. Retrievable for a future matching situation (bounded, relevant).
        hits = rt.retrieve_experiences(failure_pattern="execute tool auth expired deploy",
                                       top_k=3)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], rule.id)
        self.assertLessEqual(len(hits), 3)

        # A single successful episode did NOT become universal knowledge.
        procedures = [i for i in rt.distilled_store.list()
                      if i.type == DistilledType.PROCEDURE]
        self.assertEqual(len(procedures), 1)
        self.assertEqual(procedures[0].validation_status, ValidationStatus.CANDIDATE)
        await rt.stop()

    async def test_no_endless_repetition_escalation(self):
        """Running the same failed strategy repeatedly must escalate instead of
        endlessly repeating: recurrence -> FAILURE_REPEATED -> investigation
        question -> attention selection -> hypotheses."""
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()
        for i in range(4):
            ep = await rt.start_episode("retry strategy", mode=EpisodeMode.TEST)
            await rt.complete_episode(ep.episode_id, success=False, failures=[AUTH_FAIL])
        qs = [q for q in rt.question_store.list() if q.source == "REPEATED_FAILURE"]
        self.assertGreaterEqual(len(qs), 1)
        q = qs[0]
        self.assertEqual(q.status.value, "INVESTIGATING")
        # The question produced competing hypotheses (the system investigates,
        # not blindly retries).
        self.assertGreaterEqual(len(rt.hypothesis_store.list_by_question(q.question_id)), 2)
        # The failure record shows the escalation was driven by evidence counts.
        failure = rt.failure_store.list_failures()[0]
        self.assertEqual(failure.repeat_count, 4)
        await rt.stop()

    async def test_restart_preserves_episodes_failures_lessons(self):
        dir1 = os.path.join(self.tmp, "data")
        rt1 = CognitiveRuntime(data_dir=dir1)
        await rt1.start()
        ep = await rt1.start_episode("deploy", mode=EpisodeMode.TEST)
        await rt1.complete_episode(ep.episode_id, success=False, failures=[AUTH_FAIL])
        rule_ids = [i.id for i in rt1.distilled_store.list()]
        fail_count = rt1.failure_store.count_failures()
        await rt1.stop()

        rt2 = CognitiveRuntime(data_dir=dir1)
        await rt2.start()
        self.assertEqual(rt2.episode_store.count(), 1)
        loaded_ep = rt2.episode_store.get(ep.episode_id)
        self.assertIsNotNone(loaded_ep)
        self.assertEqual(loaded_ep.status, EpisodeStatus.COMPLETED)
        self.assertEqual(len(loaded_ep.failures), 1)
        self.assertEqual(rt2.failure_store.count_failures(), fail_count)
        self.assertEqual([i.id for i in rt2.distilled_store.list()], rule_ids)
        # Relationships survive: failure -> episode, lesson -> failure.
        failure = rt2.failure_store.list_failures()[0]
        self.assertEqual(failure.episode_id, ep.episode_id)
        await rt2.stop()

    async def test_contradictory_experiences_weaken_lesson_in_runtime(self):
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()
        for i in range(4):
            ep = await rt.start_episode("deploy", mode=EpisodeMode.TEST)
            await rt.complete_episode(ep.episode_id, success=False, failures=[AUTH_FAIL])
        rule = [i for i in rt.distilled_store.list()
                if i.type == DistilledType.FAILURE_PREVENTION_RULE][0]
        self.assertEqual(rule.validation_status, ValidationStatus.VALIDATED)
        # Contradictory experience: same action + same signal, but success.
        ok = await rt.start_episode("deploy", mode=EpisodeMode.TEST)
        await rt.complete_episode(ok.episode_id, success=True,
                                  actions=[{"action": "execute_tool", "at": time.time()}])
        rule = rt.experience_distillation.add_counterexample(rule.id, ok.episode_id,
                                                             rt.episode_store)
        self.assertEqual(rule.validation_status, ValidationStatus.WEAKENED)
        await rt.stop()

    async def test_repeated_failure_same_fingerprint_no_duplicate_records(self):
        rt = CognitiveRuntime(data_dir=os.path.join(self.tmp, "data"))
        await rt.start()
        for i in range(3):
            ep = await rt.start_episode("x", mode=EpisodeMode.TEST)
            await rt.complete_episode(ep.episode_id, success=False, failures=[AUTH_FAIL])
        self.assertEqual(rt.failure_store.count_failures(), 1)  # deduped by fingerprint
        await rt.stop()


class TestSlice4EngineIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slice4_engine_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_engine_wires_experience_layer(self):
        engine = AscendantEngine(data_dir=self.tmp)
        await engine.start()
        rt = engine.cognitive_runtime
        self.assertIsNotNone(rt.episode_store)
        self.assertIsNotNone(rt.experience_distillation)
        self.assertIsNotNone(rt.failure_learning)
        ep = await rt.start_episode("engine episode", mode=EpisodeMode.TEST)
        await rt.complete_episode(ep.episode_id, success=True,
                                  actions=[{"action": "cycle", "at": time.time()}])
        self.assertEqual(rt.episode_store.count(), 1)
        await engine.stop()


if __name__ == "__main__":
    unittest.main()
