"""
ZERION-X ARCHITECTURAL FREEZE — Invariant Tests (I001–I025).

Each test executes a contract from ZERION_X_ARCHITECTURAL_FREEZE.md against the
REAL runtime code (no mocks of the system under test, no fabricated outcomes).
An invariant is "enforced" only when this file's test for it passes against the
actual implementation.

Mapping (document section 12):
  I001  MODEL_OUTPUT_CANNOT_BECOME_VERIFIED_FACT_WITHOUT_EVIDENCE
  I002  UI_CANNOT_MUTATE_CANONICAL_STATE_DIRECTLY
  I003  PROVIDER_CANNOT_MUTATE_COGNITIVE_STATE_DIRECTLY
  I004  VOICE_CANNOT_BYPASS_POLICY
  I005  TOOL_CANNOT_SELF_GRANT_PERMISSION
  I006  SIMULATION_CANNOT_BE_STORED_AS_OBSERVED_FACT
  I007  GOAL_STATE_HAS_ONE_CANONICAL_OWNER
  I008  EVENTS_ARE_IDEMPOTENT
  I009  CRITICAL_STATE_SURVIVES_RESTART
  I010  FAILED_EVOLUTION_CANNOT_REPLACE_KNOWN_GOOD_VERSION
  I011  MODEL_PROVIDER_SWITCH_PRESERVES_COGNITIVE_IDENTITY
  I012  SELF_MODIFICATION_CANNOT_DISABLE_ITS_OWN_GATE
  I013  FABRICATED_TELEMETRY_IS_REJECTED
  I014  UNKNOWN_METRICS_ARE_NOT_REPORTED_AS_SUCCESS
  I015  PERMISSION_ESCALATION_IS_REJECTED
  I016  CORRUPTED_MEMORY_DOES_NOT_CORRUPT_CANONICAL_STATE
  I017  DUPLICATE_EVENTS_DO_NOT_DUPLICATE_EFFECTS
  I018  INTERRUPTED_OPERATIONS_CAN_RECOVER
  I019  DEGRADED_MODE_DOES_NOT_FABRICATE_HEALTH
  I020  ROLLBACK_RESTORES_KNOWN_GOOD_STATE
Repository-discovered additions:
  I021  SINGLE_EVENT_BUS (no second bus in the live runtime)
  I022  OFFLINE_ONLY_NEVER_TOUCHES_CLOUD_PROVIDERS
  I023  IDENTITY_IS_IMMUTABLE_ACROSS_RESTART
  I024  PROPOSAL_LIFECYCLE_TRANSITIONS_ARE_ENFORCED
  I025  VOICE_STATE_MACHINE_ENFORCES_TRANSITIONS
"""

import asyncio
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from zerion.cognitive_os.belief import Belief, BeliefLifecycle, BeliefRevision
from zerion.cognitive_os.capability import (
    HIGH_RISK_PERMISSIONS,
    Permission,
    PermissionPolicy,
)
from zerion.cognitive_os.cognitive_router import CognitiveRouter
from zerion.cognitive_os.evidence import (
    Evidence,
    EvidenceMode,
    EvidenceVerdict,
    MODE_WEIGHT,
    Provenance,
)
from zerion.cognitive_os.genome import GenomeManager, GenomeStatus, GenomeStore
from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
from zerion.cognitive_os.improvement import (
    ImprovementProposal,
    ModificationType,
    RiskLevel,
)
from zerion.cognitive_os.provider_adapters import LegacyGeminiAdapter
from zerion.cognitive_os.provider_interface import (
    ModelInfo,
    ProviderStatus,
    RawProviderResponse,
)
from zerion.cognitive_os.provider_health import ProviderHealthTracker
from zerion.cognitive_os.pulse_store import (
    CognitiveWorkItem,
    PulseStore,
    WorkStatus,
    WorkType,
)
from zerion.cognitive_os.router_types import RoutingMode, Task, TaskType
from zerion.cognitive_os.self_modification_gate import (
    GatePolicy,
    SelfModificationGate,
)
from zerion.cognitive_os.snapshots import SnapshotStore
from zerion.cognitive_os.state import CognitiveState, StateIntegrityError, StateStore
from zerion.cognitive_os.telemetry import ArchitectureTelemetry
from zerion.identity.persistence import IdentityCore
from zerion.runtime.event_bus import AsyncEventBus, EventValidationError
from zerion.runtime.events import Event, EventType
from zerion.runtime.security import PermissionLevel, SecurityBoundary
from zerion.voice.state_machine import InvalidVoiceTransition, VoiceState, VoiceStateMachine

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def _source_text(module_path: str) -> str:
    root = Path(__file__).resolve().parent.parent
    return (root / module_path).read_text(encoding="utf-8")


def _no_banned_imports(module_paths, banned_substrings):
    """Boundary check: modules in `module_paths` must not import any
    banned target (dependency direction enforcement)."""
    problems = []
    for mod in module_paths:
        text = _source_text(mod)
        for banned in banned_substrings:
            if banned in text:
                problems.append(f"{mod} references {banned}")
    return problems


def _evidence(mode: EvidenceMode, verdict: EvidenceVerdict = EvidenceVerdict.SUPPORTS,
              reliability: float = 0.9) -> Evidence:
    return Evidence(
        content={"observation": "x"},
        provenance=Provenance(
            source="invariant_test",
            observed_at=time.time(),
            evidence_type="observation",
            content_reference="ref",
            reliability=reliability,
            mode=mode,
            recorded_at=time.time(),
        ),
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# I001 — model output cannot become verified fact without evidence
# ---------------------------------------------------------------------------


class TestI001ModelOutputIsNotFact(unittest.TestCase):
    def test_model_generated_evidence_never_revises_belief(self):
        belief = Belief(statement="A causes B", source="test",
                        confidence=0.3, status=BeliefLifecycle.HYPOTHESIS)
        model_evidence = _evidence(EvidenceMode.MODEL_GENERATED)
        belief, revision = BeliefRevision().apply(belief, model_evidence)

        self.assertFalse(revision["applied"])
        self.assertEqual(revision["reason"], "model output alone cannot revise a belief")
        self.assertEqual(belief.confidence, 0.3)  # unchanged
        self.assertNotIn(BeliefLifecycle.CONFIRMED, [belief.status])

    def test_model_generated_weight_is_zero(self):
        self.assertEqual(MODE_WEIGHT[EvidenceMode.MODEL_GENERATED], 0.0)

    def test_only_observed_evidence_can_confirm(self):
        belief = Belief(statement="A causes B", source="test",
                        confidence=0.5, status=BeliefLifecycle.HYPOTHESIS)
        rev = BeliefRevision()
        for _ in range(6):
            belief, _ = rev.apply(belief, _evidence(EvidenceMode.OBSERVED))
        self.assertEqual(belief.status, BeliefLifecycle.CONFIRMED)
        self.assertGreaterEqual(belief.confidence, 0.85)

    def test_simulated_evidence_cannot_confirm(self):
        belief = Belief(statement="A causes B", source="test",
                        confidence=0.98, status=BeliefLifecycle.SUPPORTED)
        belief, _ = BeliefRevision().apply(belief, _evidence(EvidenceMode.SIMULATED))
        self.assertNotEqual(belief.status, BeliefLifecycle.CONFIRMED)


# ---------------------------------------------------------------------------
# I002 — UI cannot mutate canonical state directly
# ---------------------------------------------------------------------------


class TestI002UiCannotMutateCanonicalState(unittest.TestCase):
    def test_ui_modules_never_import_or_write_canonical_state(self):
        problems = _no_banned_imports(
            [
                "zerion/ui/state_bridge.py",
                "zerion/ui/commands.py",
                "zerion/ui/server.py",
                "zerion/ui/visualization_adapter.py",
            ],
            [
                "from zerion.cognitive_os.state import",
                "cognitive_os.state import",
                "StateStore",
                "StateIntegrityError",
                ".persist_state(",
            ],
        )
        self.assertEqual(problems, [])

    def test_ui_state_is_presentation_derived_not_canonical(self):
        # The UI bridge is a mirror; the authoritative state read path is
        # runtime.snapshot() / the VisualizationStateAdapter.
        from zerion.cognitive_os.state import CognitiveState
        from zerion.ui.state_bridge import CognitiveUIState, UIStateMode

        ui = CognitiveUIState()
        canonical = CognitiveState()
        self.assertIsNot(ui, canonical)
        self.assertNotEqual(type(ui).__name__, type(canonical).__name__)
        # The bridge's defaults are honest UNKNOWNs, not fabricated numbers.
        self.assertIsNone(ui.confidence)
        self.assertEqual(ui.maturity_level, "UNKNOWN")
        self.assertEqual(ui.runtime_state, UIStateMode.BOOTING)

    def test_server_cognitive_state_endpoint_is_read_only(self):
        src = _source_text("zerion/ui/server.py")
        self.assertIn("cr.snapshot()", src)  # GET path reads snapshot only
        # The only mutation entry point is the validated CommandAPI.
        self.assertIn("self.engine.command_api.execute", src)


# ---------------------------------------------------------------------------
# I003 — provider cannot mutate cognitive state directly
# ---------------------------------------------------------------------------


class TestI003ProviderCannotMutateCognitiveState(unittest.TestCase):
    def test_provider_layer_has_no_state_imports(self):
        problems = _no_banned_imports(
            [
                "zerion/model_providers/provider.py",
                "zerion/model_providers/router.py",
                "zerion/model_providers/openai_provider.py",
                "zerion/model_providers/gemini_provider.py",
                "zerion/cognitive_os/provider_adapters.py",
                "zerion/cognitive_os/cognitive_router.py",
            ],
            [
                "from zerion.cognitive_os.state import",
                "cognitive_os.state import",
                "StateStore",
                "state_store.put",
            ],
        )
        self.assertEqual(problems, [])

    def test_router_emits_events_instead_of_mutating_state(self):
        # The canonical router has no reference to CognitiveState; its only
        # side channel is the emit() callback (event publication).
        router_src = _source_text("zerion/cognitive_os/cognitive_router.py")
        self.assertNotIn("CognitiveState", router_src)
        self.assertNotIn("StateStore", router_src)
        self.assertIn("def _emit", router_src)


# ---------------------------------------------------------------------------
# I004 — voice cannot bypass policy
# ---------------------------------------------------------------------------


class TestI004VoiceCannotBypassPolicy(unittest.TestCase):
    def test_voice_modules_do_not_touch_gate_or_canonical_state(self):
        problems = _no_banned_imports(
            [
                "zerion/voice/pipeline.py",
                "zerion/voice/perception_service.py",
                "zerion/voice/state_machine.py",
                "zerion/voice/session.py",
            ],
            [
                "self_modification_gate",
                "from zerion.cognitive_os.state import",
                "cognitive_os.state import",
                "StateStore",
                "genome_manager.promote",
                "self_modification_gate import SelfModificationGate",
            ],
        )
        self.assertEqual(problems, [])

    def test_voice_state_machine_rejects_invalid_transitions(self):
        sm = VoiceStateMachine()
        with self.assertRaises(InvalidVoiceTransition):
            sm.transition(VoiceState.SPEAKING, reason="not allowed from IDLE")


# ---------------------------------------------------------------------------
# I005 — tool cannot self-grant permission
# ---------------------------------------------------------------------------


class TestI005ToolCannotSelfGrantPermission(unittest.TestCase):
    def test_unheld_permission_level_denied(self):
        boundary = SecurityBoundary()
        self.assertFalse(boundary.authorize(
            "action", "target", PermissionLevel.SYSTEM_MUTATE, caller="tool"))

    def test_forbidden_paths_denied_even_with_write_permission(self):
        boundary = SecurityBoundary()
        self.assertFalse(boundary.authorize(
            "write_file", "/etc/shadow", PermissionLevel.WORKSPACE_WRITE,
            caller="tool"))

    def test_denials_are_audited(self):
        boundary = SecurityBoundary()
        boundary.authorize("escalate", "/etc/sudoers", PermissionLevel.SYSTEM_MUTATE,
                           caller="tool")
        trail = boundary.get_audit_trail(limit=1)
        self.assertEqual(len(trail), 1)
        self.assertFalse(trail[0]["granted"])

    def test_capability_policy_denies_high_risk_by_default(self):
        policy = PermissionPolicy()
        ok, denied = policy.check([Permission.SYSTEM_CONTROL, Permission.READ])
        self.assertFalse(ok)
        self.assertIn(Permission.SYSTEM_CONTROL, denied)
        self.assertIn(Permission.SELF_MODIFICATION, HIGH_RISK_PERMISSIONS)


# ---------------------------------------------------------------------------
# I006 — simulation cannot be stored as observed fact
# ---------------------------------------------------------------------------


class TestI006SimulationIsNotObservation(unittest.TestCase):
    def test_simulated_and_observed_are_distinct_statuses(self):
        from zerion.runtime.evidence import MeasurementStatus

        self.assertNotEqual(MeasurementStatus.SIMULATED, MeasurementStatus.OBSERVED)

    def test_simulated_evidence_keeps_simulated_mode_in_storage(self):
        store_path = tempfile.mktemp(suffix=".db")
        try:
            from zerion.cognitive_os.evidence import EvidenceStore

            store = EvidenceStore(db_path=store_path, strict_load=True)
            ev = _evidence(EvidenceMode.SIMULATED)
            store.put(ev)
            reloaded = EvidenceStore(db_path=store_path, strict_load=True)
            stored = reloaded.get(ev.evidence_id)
            self.assertEqual(stored.provenance.mode, EvidenceMode.SIMULATED)
        finally:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(store_path + suffix)
                except OSError:
                    pass

    def test_simulated_weight_cannot_confirm(self):
        self.assertLess(MODE_WEIGHT[EvidenceMode.SIMULATED], MODE_WEIGHT[EvidenceMode.OBSERVED])


# ---------------------------------------------------------------------------
# I007 — goal state has one canonical owner
# ---------------------------------------------------------------------------


class TestI007GoalStateSingleOwner(unittest.TestCase):
    def _runtime(self, tmp: str):
        from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime

        return CognitiveRuntime(data_dir=tmp)

    def test_goals_live_in_the_single_objective_store_and_state_is_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._runtime(tmp)
            _run(runtime.start())
            try:
                _run(runtime.create_goal("reduce cold-start latency"))
                store_counts = runtime.objectives.count_goals()
                self.assertEqual(store_counts["total"], 1)
                # CognitiveState.goals is a DERIVED view of the same store:
                # it must mirror count_goals(), never diverge.
                self.assertEqual(runtime.state.goals.total, store_counts["total"])
                self.assertEqual(runtime.state.goals.proposed,
                                 store_counts["PROPOSED"])
            finally:
                _run(runtime.stop())

    def test_engine_wires_one_goal_store_into_the_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            from zerion.engine import AscendantEngine

            engine = AscendantEngine(data_dir=tmp)
            # The engine's continuous objectives manager IS the runtime's
            # objectives manager — one canonical store, not two.
            self.assertIs(engine.continuous_objectives,
                          engine.cognitive_runtime.objectives)


# ---------------------------------------------------------------------------
# I008 — events are idempotent
# ---------------------------------------------------------------------------


class TestI008EventsAreIdempotent(unittest.TestCase):
    def test_duplicate_event_id_rejected(self):
        bus = AsyncEventBus(db_path=None)
        event = Event(event_type=EventType.GOAL_CREATED, payload={"goal_id": "g1"})
        _run(bus.publish(event, dispatch_immediately=True))
        with self.assertRaises(EventValidationError):
            _run(bus.publish(event, dispatch_immediately=True))  # same id

    def test_republishing_same_id_rejected(self):
        bus = AsyncEventBus(db_path=None)
        e1 = Event(event_type=EventType.GOAL_CREATED, payload={"goal_id": "g1"})
        _run(bus.publish(e1, dispatch_immediately=True))
        e2 = Event(event_type=EventType.GOAL_CREATED, payload={"goal_id": "g1"},
                   event_id=e1.event_id)
        with self.assertRaises(EventValidationError):
            _run(bus.publish(e2, dispatch_immediately=True))

    def test_drain_delivers_each_queued_event_once(self):
        bus = AsyncEventBus(db_path=None)
        delivered = []

        async def handler(event):
            delivered.append(event.event_id)

        bus.subscribe_all(handler)
        e1 = Event(event_type=EventType.GOAL_CREATED, payload={"goal_id": "g1"})
        e2 = Event(event_type=EventType.GOAL_CREATED, payload={"goal_id": "g2"})
        _run(bus.publish(e1))
        _run(bus.publish(e2))
        dispatched = _run(bus.drain_now())
        self.assertEqual(len(dispatched), 2)
        self.assertEqual(len(delivered), 2)
        self.assertEqual(len(set(delivered)), 2)


# ---------------------------------------------------------------------------
# I009 — critical state survives restart
# ---------------------------------------------------------------------------


class TestI009CriticalStateSurvivesRestart(unittest.TestCase):
    def test_cognitive_state_roundtrips_through_state_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "cognitive_state.db")
            store = StateStore(db_path=path)
            state = CognitiveState()
            state.runtime_status = __import__(
                "zerion.cognitive_os.state", fromlist=["RuntimeStatus"]
            ).RuntimeStatus.RUNNING
            state.current_focus = "survive-me"
            store.put(state)
            store.close()

            store2 = StateStore(db_path=path)
            loaded = store2.load()
            self.assertEqual(loaded.state_id, state.state_id)
            self.assertEqual(loaded.current_focus, "survive-me")

    def test_goals_survive_runtime_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime

            r1 = CognitiveRuntime(data_dir=tmp)
            _run(r1.start())
            _run(r1.create_goal("durable goal"))
            _run(r1.stop())

            r2 = CognitiveRuntime(data_dir=tmp)
            _run(r2.start())
            try:
                goals = r2.objectives.list_active_objectives()
                self.assertEqual(len(goals), 1)
                self.assertEqual(goals[0].title, "durable goal")
            finally:
                _run(r2.stop())


# ---------------------------------------------------------------------------
# I010 — failed evolution cannot replace known-good version
# ---------------------------------------------------------------------------


class TestI010FailedEvolutionCannotReplaceKnownGood(unittest.TestCase):
    def test_genome_reject_leaves_current_untouched(self):
        gm = GenomeManager(store=GenomeStore(db_path=None))
        before = gm.current()
        candidate = gm.propose_variation({"attention_policy": {"capacity_slots": 9}})
        gm.reject(candidate.genome_id, reason="benchmark regression")
        after = gm.current()
        self.assertEqual(before.genome_id, after.genome_id)
        self.assertEqual(before.configuration, after.configuration)
        self.assertEqual(gm.store.get(candidate.genome_id).status, GenomeStatus.REJECTED)

    def test_promote_requires_evaluation_evidence(self):
        gm = GenomeManager(store=GenomeStore(db_path=None))
        candidate = gm.propose_variation({"attention_policy": {"capacity_slots": 9}})
        with self.assertRaises(ValueError):
            gm.promote(candidate.genome_id)  # no evaluation evidence


# ---------------------------------------------------------------------------
# I011 — provider switch preserves cognitive identity
# ---------------------------------------------------------------------------


class _FakeLocalProvider:
    provider_name = "fake_local"
    is_local = True
    field_profile = None

    async def generate(self, call):
        return RawProviderResponse(output="local", success=True, latency_ms=1.0)

    async def stream(self, call):
        yield RawProviderResponse(output="local", success=True)

    async def health_check(self):
        return ProviderStatus.AVAILABLE

    def capabilities(self):
        return {"text"}

    def list_models(self):
        return [ModelInfo(model_id="fake-model", provider=self.provider_name,
                          capabilities={"text"}, status=ProviderStatus.AVAILABLE,
                          format="fake")]

    def model_info(self, model_id):
        return self.list_models()[0] if model_id == "fake-model" else None


class TestI011ProviderSwitchPreservesIdentity(unittest.TestCase):
    def test_switching_providers_does_not_touch_state_or_goals(self):
        with tempfile.TemporaryDirectory() as tmp:
            from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime

            runtime = CognitiveRuntime(data_dir=tmp)
            _run(runtime.start())
            try:
                _run(runtime.create_goal("identity invariant goal"))
                state_id_before = runtime.state.state_id
                goal_count_before = len(runtime.objectives.list_active_objectives())

                runtime.cognitive_router.register_provider(
                    _FakeLocalProvider(), configured=True,
                    integration_implemented=True)

                self.assertEqual(runtime.state.state_id, state_id_before)
                self.assertEqual(len(runtime.objectives.list_active_objectives()),
                                 goal_count_before)
            finally:
                _run(runtime.stop())

    def test_identity_hash_stable_across_provider_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = IdentityCore(storage_path=str(Path(tmp) / "identity.json"))
            hash_before = core.get_identity_hash()
            router = CognitiveRouter(health=ProviderHealthTracker())
            router.register_provider(_FakeLocalProvider(), configured=True)
            self.assertEqual(core.get_identity_hash(), hash_before)
            self.assertIsNotNone(router.providers())


# ---------------------------------------------------------------------------
# I012 — self-modification cannot disable its own gate
# ---------------------------------------------------------------------------


class TestI012SelfModCannotDisableItsOwnGate(unittest.TestCase):
    def _gate_proposal(self):
        return ImprovementProposal(
            target_component="zerion/cognitive_os/self_modification_gate.py",
            modification_type=ModificationType.ARCHITECTURE_CHANGE,
            affected_capabilities=["self_modification", "security_policy"],
            proposed_change="{'self_modification_gate': {'allow_auto': True}}",
            rollback_plan="restore previous snapshot",
            scope=["zerion/cognitive_os"],
        )

    def test_gate_touching_self_escalates_to_critical(self):
        gate = SelfModificationGate(policy=GatePolicy(allow_low_auto=True,
                                                      allow_medium_auto=True))
        proposal = self._gate_proposal()
        risk = gate.risk_assessment(proposal)
        self.assertIn(risk, (RiskLevel.HIGH, RiskLevel.CRITICAL))

    def test_high_and_critical_never_auto_approved(self):
        gate = SelfModificationGate(policy=GatePolicy(allow_low_auto=True,
                                                      allow_medium_auto=True))
        proposal = self._gate_proposal()
        proposal.analysis = {"passed": True, "tests_passed": True, "risk": "CRITICAL"}
        proposal.benchmark = {"verdict": "SUPPORTED"}
        ok, reason = gate.approve(proposal)
        self.assertFalse(ok)
        self.assertIn("explicit", reason)

    def test_critical_requires_named_approver(self):
        gate = SelfModificationGate(policy=GatePolicy(allow_low_auto=True,
                                                      allow_medium_auto=True))
        proposal = self._gate_proposal()
        proposal.analysis = {"passed": True, "tests_passed": True, "risk": "CRITICAL"}
        proposal.benchmark = {"verdict": "SUPPORTED"}
        ok, _ = gate.approve(proposal, approval={"explicit": True})
        self.assertFalse(ok)  # explicit but no named approver


# ---------------------------------------------------------------------------
# I013 — fabricated telemetry is rejected
# ---------------------------------------------------------------------------


class TestI013FabricatedTelemetryIsRejected(unittest.TestCase):
    def test_rates_are_unknown_below_min_samples(self):
        telemetry = ArchitectureTelemetry(db_path=None, min_samples=3)
        telemetry.record("router", "routing_success", success=True)
        telemetry.record("router", "routing_success", success=True)
        self.assertIsNone(telemetry.rate("router", "routing_success"))

    def test_rate_reported_only_after_real_samples(self):
        telemetry = ArchitectureTelemetry(db_path=None, min_samples=3)
        for _ in range(3):
            telemetry.record("router", "routing_success", success=True)
        self.assertEqual(telemetry.rate("router", "routing_success"), 1.0)

    def test_metrics_require_component_and_name(self):
        telemetry = ArchitectureTelemetry(db_path=None)
        with self.assertRaises(ValueError):
            telemetry.record("", "routing_success", success=True)


# ---------------------------------------------------------------------------
# I014 — unknown metrics are not reported as success
# ---------------------------------------------------------------------------


class TestI014UnknownMetricsNotReportedAsSuccess(unittest.TestCase):
    def test_raw_provider_response_defaults_to_failure(self):
        resp = RawProviderResponse()
        self.assertFalse(resp.success)
        self.assertIsNone(resp.output)

    def test_gemini_adapter_returns_structured_failure_never_canned_text(self):
        from zerion.cognitive_os.provider_interface import ProviderCall

        call = ProviderCall(
            task=Task(type=TaskType.REASONING, description="d", difficulty=0.4,
                      uncertainty=0.4, novelty=0.4, stakes=0.2,
                      goal_relevance=0.5),
            prompt="hi", model_id="gemini-model")
        resp = _run(LegacyGeminiAdapter().generate(call))
        self.assertFalse(resp.success)
        self.assertIsNone(resp.output)
        self.assertIn("not implemented", resp.error)

    def test_offline_router_with_no_local_model_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = CognitiveRouter(
                health=ProviderHealthTracker(),
                local_models=LocalModelDiscovery(models_dir=tmp),
            )
            task = Task(type=TaskType.REASONING, description="d", difficulty=0.4,
                        uncertainty=0.4, novelty=0.4, stakes=0.2,
                        goal_relevance=0.5,
                        required_capabilities={"text"},
                        offline_required=True)
            result = _run(router.execute(task, "hello",
                                         mode=RoutingMode.OFFLINE_ONLY))
            self.assertNotEqual(result.status.value, "SUCCESS")
            self.assertIsNone(result.output)
            self.assertTrue(result.errors)


# ---------------------------------------------------------------------------
# I015 — permission escalation is rejected
# ---------------------------------------------------------------------------


class TestI015PermissionEscalationRejected(unittest.TestCase):
    def test_system_mutate_never_held_by_default(self):
        boundary = SecurityBoundary()
        self.assertNotIn(PermissionLevel.SYSTEM_MUTATE,
                         boundary._granted_permissions)

    def test_network_can_be_turned_off(self):
        boundary = SecurityBoundary(allow_network=False)
        self.assertFalse(boundary.authorize(
            "network", "https://example.com", PermissionLevel.NETWORK_ACCESS,
            caller="tool"))

    def test_high_risk_capability_permissions_denied_by_default(self):
        policy = PermissionPolicy()
        ok, denied = policy.check([Permission.FINANCIAL, Permission.SELF_MODIFICATION])
        self.assertFalse(ok)
        self.assertEqual(set(denied),
                         {Permission.FINANCIAL, Permission.SELF_MODIFICATION})


# ---------------------------------------------------------------------------
# I016 — corrupted memory does not corrupt canonical state
# ---------------------------------------------------------------------------


class TestI016CorruptedMemoryDoesNotCorruptCanonicalState(unittest.TestCase):
    def test_checksum_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "cognitive_state.db")
            store = StateStore(db_path=path)
            store.put(CognitiveState())
            store.close()
            conn = sqlite3.connect(path)
            conn.execute("UPDATE cognitive_state SET payload = '{\"broken\":'")
            conn.commit()
            conn.close()
            with self.assertRaises(StateIntegrityError):
                StateStore(db_path=path).load()

    def test_runtime_enters_recovering_not_corrupted_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "cognitive_state.db")
            store = StateStore(db_path=path)
            store.put(CognitiveState())
            store.close()
            conn = sqlite3.connect(path)
            conn.execute("UPDATE cognitive_state SET payload = 'not-json'")
            conn.commit()
            conn.close()

            from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
            from zerion.cognitive_os.state import RuntimeStatus

            runtime = CognitiveRuntime(data_dir=tmp)
            self.assertEqual(runtime.state.runtime_status, RuntimeStatus.RECOVERING)
            self.assertTrue(runtime.state.recovery_error)


# ---------------------------------------------------------------------------
# I017 — duplicate events do not duplicate effects
# ---------------------------------------------------------------------------


class TestI017DuplicateEventsDoNotDuplicateEffects(unittest.TestCase):
    def test_pulse_dedups_identical_events_within_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime

            runtime = CognitiveRuntime(data_dir=tmp)
            pulse = runtime.cognitive_pulse
            _run(pulse.start())
            try:
                e1 = Event(event_type=EventType.GOAL_CREATED,
                           payload={"goal_id": "g-dup", "objective": "dedup me"})
                e2 = Event(event_type=EventType.GOAL_CREATED,
                           payload={"goal_id": "g-dup", "objective": "dedup me"})
                _run(pulse._on_event(e1))
                _run(pulse._on_event(e2))
                queued = [w for w in pulse.store.list_work(WorkStatus.QUEUED)
                          if w.work_type == WorkType.GOAL_REVIEW]
                self.assertLessEqual(len(queued), 1)
            finally:
                _run(pulse.shutdown())

    def test_bus_rejects_duplicate_ids(self):
        bus = AsyncEventBus(db_path=None)
        e = Event(event_type=EventType.TASK_STARTED, payload={"task": "t1"})
        _run(bus.publish(e, dispatch_immediately=True))
        with self.assertRaises(EventValidationError):
            _run(bus.publish(e, dispatch_immediately=True))


# ---------------------------------------------------------------------------
# I018 — interrupted operations can recover
# ---------------------------------------------------------------------------


class TestI018InterruptedOperationsCanRecover(unittest.TestCase):
    def test_running_work_is_requeued_on_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "pulse.db")
            store = PulseStore(db_path=db)
            item = CognitiveWorkItem(work_type=WorkType.GOAL_REVIEW, priority=0.9,
                                     source_event="test")
            store.enqueue(item)
            store.transition(item.work_id, WorkStatus.QUEUED, WorkStatus.RUNNING)

            store2 = PulseStore(db_path=db)
            recovered = store2.get_work(item.work_id)
            self.assertEqual(recovered.status, WorkStatus.QUEUED)

    def test_runtime_restart_returns_to_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
            from zerion.cognitive_os.state import RuntimeStatus

            r = CognitiveRuntime(data_dir=tmp)
            _run(r.start())
            _run(r.stop())
            self.assertEqual(r.state.runtime_status, RuntimeStatus.STOPPED)
            _run(r.start())
            self.assertEqual(r.state.runtime_status, RuntimeStatus.RUNNING)
            _run(r.stop())


# ---------------------------------------------------------------------------
# I019 — degraded mode does not fabricate health
# ---------------------------------------------------------------------------


class TestI019DegradedModeDoesNotFabricateHealth(unittest.TestCase):
    def test_degraded_pulse_stays_degraded_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "pulse.db")
            store = PulseStore(db_path=db)
            store.save_pulse_state("DEGRADED", "provider unavailable")

            from zerion.cognitive_os.pulse import CognitivePulse

            class _RuntimeStub:
                event_bus = AsyncEventBus(db_path=None)

            pulse = CognitivePulse(runtime=_RuntimeStub(), store=store)
            _run(pulse.start())
            self.assertEqual(pulse.state.value, "DEGRADED")
            self.assertIn("provider unavailable", pulse.degraded_reason)

    def test_offline_no_provider_returns_failure_not_fabricated_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = CognitiveRouter(
                health=ProviderHealthTracker(),
                local_models=LocalModelDiscovery(models_dir=tmp),
            )
            task = Task(type=TaskType.REASONING, description="d", difficulty=0.4,
                        uncertainty=0.4, novelty=0.4, stakes=0.2,
                        goal_relevance=0.5)
            result = _run(router.execute(task, "hello",
                                         mode=RoutingMode.OFFLINE_ONLY))
            self.assertIsNone(result.output)
            self.assertNotEqual(result.status.value, "SUCCESS")


# ---------------------------------------------------------------------------
# I020 — rollback restores known-good state
# ---------------------------------------------------------------------------


class TestI020RollbackRestoresKnownGoodState(unittest.TestCase):
    def test_gate_rollback_restores_previous_genome_configuration(self):
        gm = GenomeManager(store=GenomeStore(db_path=None))
        snapshots = SnapshotStore(db_path=None)
        gate = SelfModificationGate(policy=GatePolicy(allow_low_auto=True))
        original = dict(gm.current().configuration)

        proposal = ImprovementProposal(
            target_component="attention_policy",
            modification_type=ModificationType.CONFIGURATION_CHANGE,
            proposed_change={"attention_policy": {"capacity_slots": 7}},
            rollback_plan="restore previous snapshot",
            scope=["zerion/cognitive_os"],
        )
        proposal.analysis = {"passed": True, "tests_passed": True, "risk": "LOW"}
        proposal.test_results = [{"name": "config", "passed": True}]
        proposal.benchmark = {"verdict": "SUPPORTED",
                              "baseline": {"success_rate": 0.5},
                              "candidate": {"success_rate": 0.7}}

        result = gate.promote(proposal, gm, snapshots)
        self.assertTrue(result.ok)
        self.assertTrue(result.applied)
        self.assertIsNotNone(proposal.snapshot_version)
        promoted = gm.current()
        self.assertNotEqual(promoted.configuration, original)

        rollback = gate.rollback(proposal, gm, snapshots, reason="regression")
        self.assertTrue(rollback.ok)
        self.assertEqual(gm.current().configuration, original)


# ---------------------------------------------------------------------------
# I021 — single event bus (repository-discovered)
# ---------------------------------------------------------------------------


class TestI021SingleEventBus(unittest.TestCase):
    def test_live_runtime_shares_one_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            from zerion.engine import AscendantEngine

            engine = AscendantEngine(data_dir=tmp)
            self.assertIs(engine.event_bus, engine.cognitive_runtime.event_bus)
            self.assertIs(engine.event_bus, engine.ui_adapter.event_bus)
            self.assertIs(engine.event_bus, engine.voice_perception.event_bus)

    def test_subsystems_never_construct_their_own_bus(self):
        # UI adapter and voice service take the bus by injection; they never
        # build a second bus. (cognitive_runtime is excluded here: it MAY
        # construct a default bus when none is injected — the engine always
        # injects its own, proven by test_live_runtime_shares_one_bus.)
        problems = _no_banned_imports(
            [
                "zerion/ui/visualization_adapter.py",
                "zerion/voice/perception_service.py",
            ],
            ["AsyncEventBus(db_path=", "AsyncEventBus()"],
        )
        self.assertEqual(problems, [])


# ---------------------------------------------------------------------------
# I022 — OFFLINE_ONLY never touches cloud providers
# ---------------------------------------------------------------------------


class _FakeCloudProvider(_FakeLocalProvider):
    provider_name = "fake_cloud"
    is_local = False


class TestI022OfflineOnlyNeverTouchesCloud(unittest.TestCase):
    def test_offline_only_excludes_non_local_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = CognitiveRouter(
                health=ProviderHealthTracker(),
                local_models=LocalModelDiscovery(models_dir=tmp),
            )
            router.register_provider(_FakeLocalProvider(), configured=True)
            router.register_provider(_FakeCloudProvider(), configured=True)
            task = Task(type=TaskType.REASONING, description="d", difficulty=0.4,
                        uncertainty=0.4, novelty=0.4, stakes=0.2,
                        goal_relevance=0.5,
                        required_capabilities={"text"})
            selection = router.route(task, mode=RoutingMode.OFFLINE_ONLY)
            self.assertEqual(selection.provider, "fake_local")
            self.assertNotEqual(selection.provider, "fake_cloud")

    def test_offline_only_with_only_cloud_fails_honestly(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = CognitiveRouter(
                health=ProviderHealthTracker(),
                local_models=LocalModelDiscovery(models_dir=tmp),
            )
            router.register_provider(_FakeCloudProvider(), configured=True)
            task = Task(type=TaskType.REASONING, description="d", difficulty=0.4,
                        uncertainty=0.4, novelty=0.4, stakes=0.2,
                        goal_relevance=0.5,
                        required_capabilities={"text"})
            result = _run(router.execute(task, "hello",
                                         mode=RoutingMode.OFFLINE_ONLY))
            self.assertNotEqual(result.status.value, "SUCCESS")
            self.assertIsNone(result.output)


# ---------------------------------------------------------------------------
# I023 — identity is immutable across restart (repository-discovered)
# ---------------------------------------------------------------------------


class TestI023IdentityImmutableAcrossRestart(unittest.TestCase):
    def test_identity_core_survives_restart_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "identity.json")
            core1 = IdentityCore(storage_path=path)
            core1.add_objective(
                __import__("zerion.identity.objectives",
                           fromlist=["LongTermObjective"]).LongTermObjective(
                    id="OBJ_TEST", title="survive", description="d", priority=50))
            hash1 = core1.get_identity_hash()
            system_id1 = core1.system_id

            core2 = IdentityCore(storage_path=path)
            self.assertEqual(core2.get_identity_hash(), hash1)
            self.assertEqual(core2.system_id, system_id1)
            self.assertIsNotNone(core2.get_objective("OBJ_TEST"))


# ---------------------------------------------------------------------------
# I024 — proposal lifecycle transitions enforced (repository-discovered)
# ---------------------------------------------------------------------------


class TestI024ProposalTransitionsEnforced(unittest.TestCase):
    def test_invalid_proposal_transitions_rejected(self):
        from zerion.cognitive_os.improvement import ProposalStatus

        proposal = ImprovementProposal()
        with self.assertRaises(ValueError):
            proposal.transition(ProposalStatus.APPROVED)  # PROPOSED -> APPROVED illegal
        proposal.transition(ProposalStatus.ANALYZING)
        proposal.transition(ProposalStatus.REJECTED)
        with self.assertRaises(ValueError):
            proposal.transition(ProposalStatus.APPROVED)  # REJECTED is terminal


# ---------------------------------------------------------------------------
# I025 — voice state machine enforces transitions (repository-discovered)
# ---------------------------------------------------------------------------


class TestI025VoiceStateMachineEnforcesTransitions(unittest.TestCase):
    def test_idle_cannot_jump_to_speaking(self):
        sm = VoiceStateMachine()
        with self.assertRaises(InvalidVoiceTransition):
            sm.transition(VoiceState.SPEAKING, reason="jump")

    def test_valid_lifecycle_transition_works(self):
        sm = VoiceStateMachine()
        sm.transition(VoiceState.LISTENING, reason="wake")
        sm.transition(VoiceState.THINKING, reason="routing")
        sm.transition(VoiceState.SPEAKING, reason="utterance")
        self.assertEqual(sm.state, VoiceState.SPEAKING)


if __name__ == "__main__":
    unittest.main()
