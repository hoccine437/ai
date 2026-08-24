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
Freeze-blocker elimination additions:
  I026  ONE_CANONICAL_ZERION_IDENTITY (blocker 1)
  I027  SECURITY_BOUNDARY_WIRED_AND_CONTROLS_EXECUTION (blocker 2)
  I028  ENTITY_STATE_TRANSITIONS_ARE_ENFORCED (blocker 3)
  I029  FLYWHEEL_WRITES_CANONICAL_STORES_ONLY (blocker 4)
  I030  FABRICATED_METRIC_DEFAULTS_ARE_ELIMINATED (blocker 5)
"""

import asyncio
import json
import os
import shutil
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
        adapter = LegacyGeminiAdapter()
        resp = _run(adapter.generate(call))
        # Without GEMINI_API_KEY, adapter returns a structured failure
        # (not canned model text). Error message indicates the real reason.
        self.assertFalse(resp.success)
        self.assertIsNone(resp.output)
        self.assertTrue(resp.error)  # Error must explain why

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

# ---------------------------------------------------------------------------
# I026 — ONE canonical Zerion identity (freeze blocker 1)
# ---------------------------------------------------------------------------


class TestI026OneCanonicalZerionIdentity(unittest.TestCase):
    def test_engine_entity_identity_derives_from_canonical_core(self):
        from zerion.engine import AscendantEngine
        tmp = tempfile.mkdtemp(prefix="inv_identity_")
        try:
            engine = AscendantEngine(data_dir=tmp)
            core = engine.identity
            entity = engine.entity_state.identity
            self.assertEqual(core.system_name, "ZERION-X ASCENDANT")
            self.assertEqual(entity.entity_name, core.system_name)
            self.assertEqual(entity.entity_id, core.system_id)
            self.assertEqual(entity.get_identity_digest(), core.get_identity_hash())
            # The legacy "SINGULARITY" identity must not exist anywhere live.
            self.assertNotIn("SINGULARITY", entity.entity_name)
            self.assertNotIn("singularity", entity.entity_id)
            self.assertGreater(len(entity.commitments), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_identity_digest_stable_across_restart(self):
        from zerion.entity.state import CognitiveEntityStateStore
        from zerion.identity.persistence import IdentityCore
        tmp = tempfile.mkdtemp(prefix="inv_identity2_")
        try:
            db = os.path.join(tmp, "entity.db")
            core1 = IdentityCore(storage_path=os.path.join(tmp, "id.json"))
            store1 = CognitiveEntityStateStore(db_path=db, identity=core1)
            d1 = store1.identity.get_identity_digest()
            # Cold restart with a fresh core + fresh store on the same db.
            core2 = IdentityCore(storage_path=os.path.join(tmp, "id.json"))
            store2 = CognitiveEntityStateStore(db_path=db, identity=core2)
            self.assertEqual(store2.identity.get_identity_digest(), d1)
            self.assertEqual(store2.identity.entity_name, "ZERION-X ASCENDANT")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# I027 — SecurityBoundary is wired and controls execution (freeze blocker 2)
# ---------------------------------------------------------------------------


class _FakeVoiceState:
    value = "LISTENING"


class _FakeVoiceMachine:
    state = _FakeVoiceState()


class _FakeVoicePipeline:
    def __init__(self):
        self.state_machine = _FakeVoiceMachine()

    async def stop_listening(self):
        return None


class _GrantingEngineStub:
    def __init__(self):
        self.security = SecurityBoundary()
        self.voice_pipeline = _FakeVoicePipeline()


class _LockedBoundary(SecurityBoundary):
    """Test double: a boundary that holds only read/execute, never workspace
    write or system mutate — exercises the real authorize() decision logic."""

    def __init__(self):
        super().__init__()
        self._granted_permissions = {
            PermissionLevel.READ_ONLY,
            PermissionLevel.INTERNAL_EXECUTE,
        }


class _NoExecuteBoundary(SecurityBoundary):
    """Test double: holds only READ_ONLY — even internal code execution is
    denied, proving the sandbox gate controls execution."""

    def __init__(self):
        super().__init__()
        self._granted_permissions = {PermissionLevel.READ_ONLY}


class TestI027SecurityBoundaryWiredIntoExecution(unittest.TestCase):
    def test_authorized_command_dispatches(self):
        from zerion.ui.commands import CommandAPI
        api = CommandAPI(engine=_GrantingEngineStub())
        result = _run(api.execute("STOP_LISTENING"))
        self.assertEqual(result["status"], "OK")

    def test_denied_command_blocks_handler(self):
        from zerion.ui.commands import CommandAPI
        engine = _GrantingEngineStub()
        engine.security = _LockedBoundary()
        api = CommandAPI(engine=engine)
        # SELECT_MODEL requires WORKSPACE_WRITE, which the locked boundary
        # does not hold -> denied BEFORE the handler can run.
        result = _run(api.execute("SELECT_MODEL", {"provider": "x", "model": "y"}))
        self.assertEqual(result["status"], "SECURITY_DENIED")

    def test_unlisted_command_fails_closed(self):
        from zerion.ui.commands import CommandAPI
        api = CommandAPI(engine=_GrantingEngineStub())
        called = {"ran": False}

        async def _cmd_probe(self, payload):
            called["ran"] = True
            return {"probe": True}

        api._cmd_probe = _cmd_probe.__get__(api)
        result = _run(api.execute("PROBE"))
        self.assertEqual(result["status"], "SECURITY_DENIED")
        self.assertFalse(called["ran"])  # handler never invoked

    def test_model_cannot_bypass_command_authorization(self):
        from zerion.ui.commands import CommandAPI
        # The gate is caller-agnostic: a denied command is denied no matter who
        # issues it (model, tool, plugin or user).
        engine = _GrantingEngineStub()
        engine.security = _LockedBoundary()
        api = CommandAPI(engine=engine)
        result = _run(api.execute("RUN_TASK", {"prompt": "do something"}))
        self.assertEqual(result["status"], "SECURITY_DENIED")

    def test_sandbox_denial_blocks_execution(self):
        from zerion.experiments.sandbox import ExecutionSandbox
        locked = ExecutionSandbox(security=_NoExecuteBoundary())
        res = _run(locked.run_python_code("print('hi')"))
        self.assertFalse(res.success)
        self.assertIn("denied by security boundary", res.stderr)
        # Granting boundary actually executes.
        open_box = ExecutionSandbox(security=SecurityBoundary())
        ok = _run(open_box.run_python_code("print('hi')"))
        self.assertTrue(ok.success)

    def test_self_modification_gate_requires_authorization(self):
        from zerion.cognitive_os.improvement import ImprovementProposal, ModificationType
        from zerion.cognitive_os.self_modification_gate import GatePolicy, SelfModificationGate
        proposal = ImprovementProposal(
            target_component="router",
            modification_type=ModificationType.CONFIGURATION_CHANGE,
            proposed_change={"routing_policy": {"policy_version": 7}},
            rollback_plan="restore previous snapshot",
            scope=["router"],
        )
        proposal.analysis = {"passed": True, "tests_passed": True, "risk": "LOW"}
        proposal.test_results = [{"name": "t", "passed": True}]
        proposal.benchmark = {"verdict": "SUPPORTED",
                              "baseline": {"success_rate": 0.4},
                              "candidate": {"success_rate": 0.8}}
        # Without a security boundary the gate can approve (policy allows LOW).
        open_gate = SelfModificationGate(policy=GatePolicy(allow_low_auto=True))
        ok, _ = open_gate.approve(proposal)
        self.assertTrue(ok)
        # With the canonical boundary wired, SYSTEM_MUTATE is not held -> denied.
        gated = SelfModificationGate(policy=GatePolicy(allow_low_auto=True),
                                     security=SecurityBoundary())
        ok2, reason = gated.approve(proposal)
        self.assertFalse(ok2)
        self.assertIn("security boundary", reason)

    def test_legacy_sandbox_cannot_bypass_authorization(self):
        from zerion.experiments.sandbox import ExecutionSandbox
        # The legacy engine sandbox is the same class — with a boundary wired
        # it cannot execute without authorization.
        locked = ExecutionSandbox(security=_NoExecuteBoundary())
        res = _run(locked.run_python_code("import os; os.system('true')"))
        self.assertFalse(res.success)
        self.assertIn("denied", res.stderr)


# ---------------------------------------------------------------------------
# I028 — entity state machine transitions are enforced (freeze blocker 3)
# ---------------------------------------------------------------------------


class TestI028EntityStateTransitionsEnforced(unittest.TestCase):
    def _store(self, tmp):
        from zerion.entity.state import CognitiveEntityStateStore
        return CognitiveEntityStateStore(db_path=os.path.join(tmp, "entity.db"))

    def test_valid_transition_sequence(self):
        from zerion.entity.state import EntityLifecycleState as S
        tmp = tempfile.mkdtemp(prefix="inv_entity_")
        try:
            store = self._store(tmp)
            for state in (S.BOOTING, S.PERCEIVING, S.DELIBERATING, S.ACTING,
                          S.EVOLVING, S.CONSOLIDATING, S.STANDBY):
                store.transition_state(state)
            self.assertEqual(store.current_state, S.STANDBY)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_transition_rejected_and_state_unchanged(self):
        from zerion.entity.state import EntityLifecycleState as S, InvalidStateTransitionError
        tmp = tempfile.mkdtemp(prefix="inv_entity2_")
        try:
            store = self._store(tmp)
            with self.assertRaises(InvalidStateTransitionError):
                store.transition_state(S.PERCEIVING)  # STANDBY -> PERCEIVING illegal
            self.assertEqual(store.current_state, S.STANDBY)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_direct_mutation_attempt_rejected(self):
        from zerion.entity.state import EntityLifecycleState as S
        tmp = tempfile.mkdtemp(prefix="inv_entity3_")
        try:
            store = self._store(tmp)
            with self.assertRaises(AttributeError):
                store.current_state = S.ACTING
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_interruption_and_recovery(self):
        from zerion.entity.state import EntityLifecycleState as S
        tmp = tempfile.mkdtemp(prefix="inv_entity4_")
        try:
            store = self._store(tmp)
            store.transition_state(S.BOOTING)
            store.transition_state(S.PERCEIVING)
            store.transition_state(S.INTERRUPTED)
            store.transition_state(S.RECOVERING)
            store.transition_state(S.ACTING)
            self.assertEqual(store.current_state, S.ACTING)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cancellation_is_distinct_and_terminal(self):
        from zerion.entity.state import EntityLifecycleState as S, InvalidStateTransitionError
        tmp = tempfile.mkdtemp(prefix="inv_entity5_")
        try:
            store = self._store(tmp)
            store.transition_state(S.BOOTING)
            store.transition_state(S.PERCEIVING)
            store.transition_state(S.CANCELLED)
            # CANCELLED cannot jump back to an active state, only restart.
            with self.assertRaises(InvalidStateTransitionError):
                store.transition_state(S.ACTING)
            store.transition_state(S.STANDBY)
            store.transition_state(S.BOOTING)
            self.assertEqual(store.current_state, S.BOOTING)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_degraded_state_survives_restart(self):
        from zerion.entity.state import EntityLifecycleState as S
        tmp = tempfile.mkdtemp(prefix="inv_entity6_")
        try:
            store = self._store(tmp)
            store.transition_state(S.BOOTING)
            store.transition_state(S.DEGRADED)
            # Restart from persisted state must NOT silently resume healthy.
            store2 = self._store(tmp)
            self.assertEqual(store2.current_state, S.DEGRADED)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_restart_restores_persisted_state(self):
        from zerion.entity.state import EntityLifecycleState as S
        tmp = tempfile.mkdtemp(prefix="inv_entity7_")
        try:
            store = self._store(tmp)
            store.transition_state(S.BOOTING)
            store.transition_state(S.PERCEIVING)
            store2 = self._store(tmp)
            self.assertEqual(store2.current_state, S.PERCEIVING)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# I029 — flywheel writes canonical stores only (freeze blocker 4)
# ---------------------------------------------------------------------------


class TestI029FlywheelWritesCanonicalStores(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="inv_flywheel_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_flywheel_writes_canonical_episodes_and_evidence(self):
        from zerion.engine import AscendantEngine
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            ep_before = engine.cognitive_runtime.episode_store.count()
            ev_before = engine.cognitive_runtime.evidence_store.count()
            trace = await engine.run_developmental_cycle()
            self.assertIsNotNone(trace.cycle_id)
            self.assertGreater(engine.cognitive_runtime.episode_store.count(), ep_before)
            self.assertGreater(engine.cognitive_runtime.evidence_store.count(), ev_before)
            # Legacy stores must NOT be written by the live flywheel.
            self.assertEqual(len(engine.memory._episodes), 0)
            self.assertEqual(len(engine.evidence._evidence), 0)
        finally:
            await engine.stop()

    def test_legacy_species_runtime_and_ascension_not_wired(self):
        from zerion.engine import AscendantEngine
        engine = AscendantEngine(data_dir=self.temp_dir)
        self.assertFalse(hasattr(engine, "species_runtime"))
        self.assertFalse(hasattr(engine, "run_species_pulse"))
        self.assertFalse(hasattr(engine, "ascension"))
        # The canonical pulse is the only orchestrator in the runtime.
        self.assertTrue(hasattr(engine.cognitive_runtime, "cognitive_pulse"))

    def test_engine_wires_canonical_security_boundary(self):
        from zerion.engine import AscendantEngine
        engine = AscendantEngine(data_dir=self.temp_dir)
        self.assertIs(engine.cognitive_runtime.self_modification_gate.security,
                      engine.security)
        self.assertIs(engine.sandbox.security, engine.security)


# ---------------------------------------------------------------------------
# I030 — fabricated metric defaults are eliminated (freeze blocker 5)
# ---------------------------------------------------------------------------


class TestI030NoFabricatedMetricDefaults(unittest.TestCase):
    def test_cold_start_entity_snapshot_reports_not_measured(self):
        from zerion.entity.state import CognitiveEntityStateStore
        tmp = tempfile.mkdtemp(prefix="inv_metrics_")
        try:
            store = CognitiveEntityStateStore(db_path=os.path.join(tmp, "entity.db"))
            snap = store.capture_snapshot()  # no measurements available
            self.assertIsNone(snap.brier_score)
            self.assertIsNone(snap.learning_acceleration)
            self.assertIsNone(snap.maturity_level)
            self.assertIsNone(snap.active_objectives_count)
            self.assertIsNone(snap.active_strategies_count)
            self.assertIsNone(snap.active_capabilities_count)
            self.assertIsNone(snap.memory_episodes_count)
            d = snap.to_dict()
            self.assertEqual(d["brier_score"]["measurement_status"], "NOT_MEASURED")
            self.assertEqual(d["maturity_level"]["measurement_status"], "NOT_MEASURED")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_measured_values_are_marked_measured(self):
        from zerion.entity.state import CognitiveEntityStateStore
        tmp = tempfile.mkdtemp(prefix="inv_metrics2_")
        try:
            store = CognitiveEntityStateStore(db_path=os.path.join(tmp, "entity.db"))
            snap = store.capture_snapshot(objectives_count=2, brier_score=0.41,
                                          learning_acceleration=1.2,
                                          maturity_level="L3_EMPIRICAL")
            d = snap.to_dict()
            self.assertEqual(d["brier_score"]["measurement_status"], "MEASURED")
            self.assertEqual(d["brier_score"]["value"], 0.41)
            self.assertEqual(d["active_objectives_count"]["value"], 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_legacy_placeholders_never_substituted(self):
        from zerion.entity.state import CognitiveEntityStateStore
        from zerion.evolution.timeline import DevelopmentSnapshot
        tmp = tempfile.mkdtemp(prefix="inv_metrics3_")
        try:
            store = CognitiveEntityStateStore(db_path=os.path.join(tmp, "entity.db"))
            snap = store.capture_snapshot()
            for blob in (json.dumps(snap.to_dict()), json.dumps(DevelopmentSnapshot().to_dict())):
                self.assertNotIn("0.02", blob)
                self.assertNotIn("2.57", blob)
                self.assertNotIn("L7_COGNITIVE_GENERATIVE", blob)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_telemetry_is_not_success(self):
        from zerion.entity.state import CognitiveEntityStateStore
        tmp = tempfile.mkdtemp(prefix="inv_metrics4_")
        try:
            store = CognitiveEntityStateStore(db_path=os.path.join(tmp, "entity.db"))
            snap = store.capture_snapshot()
            # None is not a score — unknown is never converted into 0.0/1.0.
            self.assertIsNone(snap.brier_score)
            self.assertIsNone(snap.learning_acceleration)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# I031 — Remaining live-path fabrication patterns eliminated (freeze blocker 5
# sweep): organism cycle acceleration, genesis pipeline benchmark score, and
# the ablation study reference table.
# ---------------------------------------------------------------------------


class TestI031RemainingFabricationPatternsEliminated(unittest.IsolatedAsyncioTestCase):
    async def test_organism_cycle_reports_unmeasured_acceleration_when_none_given(self):
        from zerion.cognitive_os.organism import CognitiveOrganism
        tmp = tempfile.mkdtemp(prefix="inv_org_metrics_")
        try:
            organism = CognitiveOrganism(data_dir=tmp)
            res = await organism.execute_organism_cycle({
                "resource_metrics": {"cpu_percent": 20.0, "memory_mb": 1024.0},
                "pressure_signals": []
            })
            # No measurement supplied -> the result must NOT invent a 2.57x.
            self.assertIsNone(res.learning_acceleration)
            self.assertIsNotNone(organism.reflection_engine._reflection_history)
            record = organism.reflection_engine._reflection_history[-1]
            self.assertEqual(record["status"], "UNMEASURED")
            self.assertIsNone(record["acceleration_ratio"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def test_organism_cycle_uses_supplied_measured_acceleration(self):
        from zerion.cognitive_os.organism import CognitiveOrganism
        tmp = tempfile.mkdtemp(prefix="inv_org_metrics2_")
        try:
            organism = CognitiveOrganism(data_dir=tmp)
            res = await organism.execute_organism_cycle({
                "resource_metrics": {"cpu_percent": 20.0, "memory_mb": 1024.0},
                "pressure_signals": [],
                "learning_acceleration": 1.35,
            })
            # A real measured value flows through verbatim.
            self.assertEqual(res.learning_acceleration, 1.35)
            record = organism.reflection_engine._reflection_history[-1]
            self.assertEqual(record["acceleration_ratio"], 1.35)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def test_genesis_pipeline_does_not_fabricate_benchmark_score(self):
        from zerion.cognitive_genesis.genesis_pipeline import CognitiveGenesisPipeline
        pipeline = CognitiveGenesisPipeline()
        res = await pipeline.synthesize_strategy(
            problem_description="Distributed deadlock resolution",
            domain="distributed_systems"
        )
        self.assertTrue(res.success)
        self.assertIsNotNone(res.strategy)
        # The "blind benchmark" stage never ran a benchmark -> NOT_MEASURED.
        bench = res.strategy.benchmark_results
        self.assertEqual(bench.get("measurement_status"), "NOT_MEASURED")
        self.assertIsNone(bench.get("accuracy"))
        # Measured sandbox latency is the only number reported.
        self.assertIsInstance(bench.get("sandbox_latency_ms"), float)
        self.assertEqual(res.strategy.latency_ms, bench["sandbox_latency_ms"])
        # The strategy's own code must not embed a fake confidence score.
        self.assertIn("confidence\": None", res.strategy.executable_code)
        self.assertNotIn("0.94", res.strategy.executable_code)
        # No fabricated benchmark score anywhere in the stage log.
        for stage in res.stages_log:
            self.assertNotIn("Benchmark score: 0.94", stage.details)
            self.assertNotIn("0.94", stage.details)

    async def test_ablation_study_is_explicitly_labeled_simulated(self):
        from zerion.experiments.ablation_study import AblationStudyRunner
        runner = AblationStudyRunner()
        report = await runner.run_ablation_matrix()
        self.assertEqual(len(report.ablation_results), 8)
        for r in report.ablation_results:
            self.assertEqual(r.measurement_status, "SIMULATED")
        self.assertIn("World Model", report.most_critical_component)


# ---------------------------------------------------------------------------
# I032 — The cognitive runtime loop actually EXECUTES in the live engine.
# Integration: flywheel events -> canonical pulse work -> persistent stores.
# A class existing is not evidence; these tests observe real runtime work.
# ---------------------------------------------------------------------------


class TestI032RuntimeLoopExecutesInLiveEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="inv_runtime_loop_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def _emit_anomaly(self, engine, description: str) -> None:
        from zerion.runtime.events import Event, EventType
        await engine.event_bus.publish(Event(
            event_type=EventType.ANOMALY_DETECTED,
            payload={"objective": description, "description": description,
                     "source": "i032_probe", "magnitude": 0.9},
            source="i032_probe", priority=60,
        ), dispatch_immediately=True)

    async def test_flywheel_cycle_executes_pulse_work(self):
        from zerion.engine import AscendantEngine
        from zerion.cognitive_os.pulse_store import WorkStatus
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            await engine.run_developmental_cycle()
            completed = engine.cognitive_runtime.cognitive_pulse.store.list_work(
                WorkStatus.COMPLETED)
            # The flywheel's real events (observations, perception) must have
            # driven the pulse to COMPLETED work — not just queued it.
            self.assertGreater(len(completed), 0)
            # A real anomaly event on the same bus generates canonical
            # questions through the runtime's QuestionGenesis (wired path).
            await self._emit_anomaly(engine, "Latency drift in i032 probe")
            self.assertGreater(engine.cognitive_runtime.question_store.count(), 0)
        finally:
            await engine.stop()

    async def test_pulse_work_persists_across_restart(self):
        from zerion.engine import AscendantEngine
        from zerion.cognitive_os.pulse_store import WorkStatus
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            await engine.run_developmental_cycle()
            await self._emit_anomaly(engine, "Persistent drift across restart")
            q_count = engine.cognitive_runtime.question_store.count()
            self.assertGreater(q_count, 0)
            completed = engine.cognitive_runtime.cognitive_pulse.store.list_work(
                WorkStatus.COMPLETED)
            self.assertGreater(len(completed), 0)
        finally:
            await engine.stop()
        # Cold restart on the same data dir: pulse work + questions survive.
        engine2 = AscendantEngine(data_dir=self.temp_dir)
        await engine2.start()
        try:
            self.assertEqual(engine2.cognitive_runtime.question_store.count(),
                             q_count)
            self.assertGreater(
                len(engine2.cognitive_runtime.cognitive_pulse.store.list_work(
                    WorkStatus.COMPLETED)), 0)
        finally:
            await engine2.stop()

    async def test_tick_pulse_is_bounded(self):
        from zerion.engine import AscendantEngine
        engine = AscendantEngine(data_dir=self.temp_dir)
        await engine.start()
        try:
            n = await engine.cognitive_runtime.tick_pulse(budget=2)
            self.assertLessEqual(n, 2)
        finally:
            await engine.stop()

    async def test_background_pulse_heartbeat_drives_the_loop(self):
        import os as _os
        from zerion.engine import AscendantEngine
        from zerion.runtime.events import Event, EventType
        prev = _os.environ.get("ZERION_PULSE_TICK_SECONDS")
        _os.environ["ZERION_PULSE_TICK_SECONDS"] = "0.2"
        try:
            engine = AscendantEngine(data_dir=self.temp_dir)
            await engine.start()
            try:
                self.assertIsNotNone(engine._pulse_driver_task)
                # A real world event enqueues pulse work; the heartbeat must
                # execute it without any explicit tick call from the test.
                await engine.event_bus.publish(Event(
                    event_type=EventType.OBSERVATION_RECORDED,
                    payload={"objective": "heartbeat probe",
                             "source": "i032_test"},
                    source="i032_test", priority=40,
                ), dispatch_immediately=True)
                await asyncio.sleep(0.7)
                history = engine.cognitive_runtime.cognitive_pulse.store.cycle_history()
                self.assertGreater(len(history), 0)
                work_states = {h["state"] for h in history}
                self.assertTrue(
                    any("WORK" in s for s in work_states)
                    or any("ATTENTION" in s for s in work_states))
            finally:
                await engine.stop()
        finally:
            if prev is None:
                _os.environ.pop("ZERION_PULSE_TICK_SECONDS", None)
            else:
                _os.environ["ZERION_PULSE_TICK_SECONDS"] = prev


if __name__ == "__main__":
    unittest.main()
