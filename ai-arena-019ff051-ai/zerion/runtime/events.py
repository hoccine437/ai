"""
Core Typed Events for ASCENDANT Runtime
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class EventType(str, Enum):
    # System Lifecycle
    SYSTEM_STARTUP = "SYSTEM_STARTUP"
    SYSTEM_SHUTDOWN = "SYSTEM_SHUTDOWN"
    RESOURCE_ALERT = "RESOURCE_ALERT"
    WATCHDOG_HEARTBEAT = "WATCHDOG_HEARTBEAT"
    
    # User Interaction
    USER_GOAL_CREATED = "USER_GOAL_CREATED"
    USER_INTERACTION = "USER_INTERACTION"
    SCREEN_CHANGED = "SCREEN_CHANGED"
    
    # Perception & Pressure
    OBSERVATION_RECORDED = "OBSERVATION_RECORDED"
    PREDICTION_MADE = "PREDICTION_MADE"
    PREDICTION_ERROR = "PREDICTION_ERROR"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    PRESSURE_SURGE = "PRESSURE_SURGE"
    
    # Question & Cognition
    QUESTION_CREATED = "QUESTION_CREATED"
    QUESTION_ANSWERED = "QUESTION_ANSWERED"
    COGNITIVE_PROGRAM_COMPILED = "COGNITIVE_PROGRAM_COMPILED"
    COGNITIVE_STEP_STARTED = "COGNITIVE_STEP_STARTED"
    COGNITIVE_STEP_COMPLETED = "COGNITIVE_STEP_COMPLETED"
    
    # Evidence & Belief
    EVIDENCE_ACQUIRED = "EVIDENCE_ACQUIRED"
    BELIEF_UPDATED = "BELIEF_UPDATED"
    CONTRADICTION_FOUND = "CONTRADICTION_FOUND"
    
    # Experimentation
    EXPERIMENT_STARTED = "EXPERIMENT_STARTED"
    EXPERIMENT_COMPLETED = "EXPERIMENT_COMPLETED"
    EXPERIMENT_FAILED = "EXPERIMENT_FAILED"
    
    # Capabilities & Learning
    CAPABILITY_GAP = "CAPABILITY_GAP"
    CAPABILITY_BORN = "CAPABILITY_BORN"
    CAPABILITY_VALIDATED = "CAPABILITY_VALIDATED"
    SKILL_DISTILLED = "SKILL_DISTILLED"
    TRANSFER_EVALUATED = "TRANSFER_EVALUATED"
    
    # Missions
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_CHECKPOINT = "MISSION_CHECKPOINT"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_FAILED = "MISSION_FAILED"
    
    # Evolution & Self-Improvement
    STRATEGY_MUTATED = "STRATEGY_MUTATED"
    ASCENSION_ATTEMPTED = "ASCENSION_ATTEMPTED"
    ASCENSION_PROMOTED = "ASCENSION_PROMOTED"
    ASCENSION_ROLLED_BACK = "ASCENSION_ROLLED_BACK"

    # --- Slice 1: Cognitive Foundation ---
    # Runtime lifecycle
    RUNTIME_STARTED = "RUNTIME_STARTED"
    RUNTIME_STOPPED = "RUNTIME_STOPPED"
    STATE_RECOVERED = "STATE_RECOVERED"
    # Perception
    PERCEPTION_RECEIVED = "PERCEPTION_RECEIVED"
    # Goals
    GOAL_CREATED = "GOAL_CREATED"
    GOAL_UPDATED = "GOAL_UPDATED"
    GOAL_BLOCKED = "GOAL_BLOCKED"
    GOAL_COMPLETED = "GOAL_COMPLETED"
    GOAL_ABANDONED = "GOAL_ABANDONED"
    # Attention
    ATTENTION_CANDIDATE_CREATED = "ATTENTION_CANDIDATE_CREATED"
    ATTENTION_SELECTED = "ATTENTION_SELECTED"
    ATTENTION_DEFERRED = "ATTENTION_DEFERRED"
    ATTENTION_DISCARDED = "ATTENTION_DISCARDED"
    # Resources & Tasks
    RESOURCE_WARNING = "RESOURCE_WARNING"
    # The canonical resource-degradation signal for the attention economy demo:
    # emitted by any subsystem that detects degradation, consumed by the runtime
    # exactly like RESOURCE_WARNING (attention candidate -> SELECT/DEFER/DISCARD).
    SYSTEM_RESOURCE_DEGRADATION_DETECTED = "SYSTEM_RESOURCE_DEGRADATION_DETECTED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    # Voice lifecycle (Slice 1 vocabulary plus Slice 10 additions). These are
    # valid bus events so the architecture can consume them; the cognitive
    # foundation does NOT subscribe to them, keeping cognition decoupled from
    # voice.
    VOICE_STARTED = "VOICE_STARTED"
    VOICE_TRANSCRIPT_PARTIAL = "VOICE_TRANSCRIPT_PARTIAL"
    VOICE_TRANSCRIPT_FINAL = "VOICE_TRANSCRIPT_FINAL"
    VOICE_INTERRUPTED = "VOICE_INTERRUPTED"
    VOICE_ENDED = "VOICE_ENDED"
    # --- Slice 10: voice + wake-word lifecycle (UI/voice integration) ---
    # Emitted by the voice layer; consumed by the VisualizationStateAdapter.
    WAKE_WORD_DETECTED = "WAKE_WORD_DETECTED"
    WAKE_WORD_MISDETECTED = "WAKE_WORD_MISDETECTED"
    VOICE_ERROR = "VOICE_ERROR"
    # A cognitive response is ready for voice output (runtime -> voice layer).
    VOICE_RESPONSE_READY = "VOICE_RESPONSE_READY"

    # --- Slice 10.1: always-available voice perception (continuous monitor) ---
    # Emitted by VoicePerceptionService; consumed by the VisualizationStateAdapter.
    # The service runs independently of the UI (engine-scoped, not server-scoped).
    VOICE_PERCEPTION_STARTED = "VOICE_PERCEPTION_STARTED"
    VOICE_PERCEPTION_STOPPED = "VOICE_PERCEPTION_STOPPED"
    VOICE_MIC_INITIALIZING = "VOICE_MIC_INITIALIZING"
    VOICE_MIC_ACTIVE = "VOICE_MIC_ACTIVE"
    VOICE_MIC_RECOVERING = "VOICE_MIC_RECOVERING"
    VOICE_MIC_UNAVAILABLE = "VOICE_MIC_UNAVAILABLE"
    VOICE_SPEECH_DETECTED = "VOICE_SPEECH_DETECTED"
    VOICE_MODE_CHANGED = "VOICE_MODE_CHANGED"
    VOICE_BARGE_IN = "VOICE_BARGE_IN"
    VOICE_STT_UNAVAILABLE = "VOICE_STT_UNAVAILABLE"
    VOICE_WATCHDOG_RESTARTED = "VOICE_WATCHDOG_RESTARTED"

    # --- Slice 2: Self-Questioning (Question Genesis & Hypothesis Engine) ---
    # Internal triggers consumed by QuestionGenesis. CONTRADICTION_FOUND,
    # ANOMALY_DETECTED, PREDICTION_ERROR, CAPABILITY_GAP and USER_INTERACTION
    # pre-date Slice 2; the *_DETECTED types below are the Slice 2 additions.
    UNCERTAINTY_DETECTED = "UNCERTAINTY_DETECTED"
    GOAL_GAP_DETECTED = "GOAL_GAP_DETECTED"
    MISSING_DEPENDENCY_DETECTED = "MISSING_DEPENDENCY_DETECTED"
    REPEATED_FAILURE_DETECTED = "REPEATED_FAILURE_DETECTED"
    # Question lifecycle flow
    QUESTION_GENERATED = "QUESTION_GENERATED"
    QUESTION_SELECTED = "QUESTION_SELECTED"
    HYPOTHESES_GENERATED = "HYPOTHESES_GENERATED"

    # --- Slice 3: Reality Feedback (Experiment, Evidence, Belief) ---
    # Experiment lifecycle. EXPERIMENT_STARTED / COMPLETED / FAILED pre-date
    # Slice 3; the remaining lifecycle events are the Slice 3 additions.
    EXPERIMENT_PROPOSED = "EXPERIMENT_PROPOSED"
    EXPERIMENT_APPROVED = "EXPERIMENT_APPROVED"
    EXPERIMENT_BLOCKED = "EXPERIMENT_BLOCKED"
    EXPERIMENT_CANCELLED = "EXPERIMENT_CANCELLED"
    # Evidence & belief feedback (EVIDENCE_ACQUIRED / BELIEF_UPDATED pre-date Slice 3)
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    EVIDENCE_REJECTED = "EVIDENCE_REJECTED"
    HYPOTHESIS_SUPPORTED = "HYPOTHESIS_SUPPORTED"
    HYPOTHESIS_WEAKENED = "HYPOTHESIS_WEAKENED"
    HYPOTHESIS_CONTRADICTED = "HYPOTHESIS_CONTRADICTED"

    # --- Slice 4: Experience -> Distillation -> Validation -> Reuse ---
    EPISODE_STARTED = "EPISODE_STARTED"
    EPISODE_COMPLETED = "EPISODE_COMPLETED"
    EXPERIENCE_DISTILLATION_STARTED = "EXPERIENCE_DISTILLATION_STARTED"
    EXPERIENCE_DISTILLED = "EXPERIENCE_DISTILLED"
    FAILURE_RECORDED = "FAILURE_RECORDED"
    FAILURE_REPEATED = "FAILURE_REPEATED"
    ROOT_CAUSE_PROPOSED = "ROOT_CAUSE_PROPOSED"
    LESSON_VALIDATED = "LESSON_VALIDATED"
    LESSON_WEAKENED = "LESSON_WEAKENED"
    PREVENTION_RULE_CREATED = "PREVENTION_RULE_CREATED"

    # --- Slice 5: Capability Genesis (NEED -> DESIGN -> GENERATE -> SANDBOX ->
    # TEST -> VALIDATE -> REGISTER -> MONITOR -> DEPRECATE) ---
    # CAPABILITY_GAP (the gap-detection signal, pre-dates Slice 5 and is already
    # consumed by Slice 2 QuestionGenesis -> Slice 1 attention) and
    # CAPABILITY_VALIDATED (pre-dates Slice 5) are reused.
    CAPABILITY_DESIGNED = "CAPABILITY_DESIGNED"
    CAPABILITY_GENERATED = "CAPABILITY_GENERATED"
    CAPABILITY_SANDBOXED = "CAPABILITY_SANDBOXED"
    CAPABILITY_TESTED = "CAPABILITY_TESTED"
    CAPABILITY_REGISTERED = "CAPABILITY_REGISTERED"
    CAPABILITY_DEGRADED = "CAPABILITY_DEGRADED"
    CAPABILITY_DEPRECATED = "CAPABILITY_DEPRECATED"
    CAPABILITY_ROLLBACK = "CAPABILITY_ROLLBACK"

    # --- Slice 7: Self-Improvement Gate (evidence-based, no unrestricted
    # self-modification) ---
    BOTTLENECK_DETECTED = "BOTTLENECK_DETECTED"
    IMPROVEMENT_PROPOSED = "IMPROVEMENT_PROPOSED"
    MODIFICATION_ANALYSIS_STARTED = "MODIFICATION_ANALYSIS_STARTED"
    MODIFICATION_REJECTED = "MODIFICATION_REJECTED"
    MODIFICATION_SANDBOXED = "MODIFICATION_SANDBOXED"
    MODIFICATION_TESTED = "MODIFICATION_TESTED"
    MODIFICATION_BENCHMARKED = "MODIFICATION_BENCHMARKED"
    MODIFICATION_APPROVED = "MODIFICATION_APPROVED"
    MODIFICATION_PROMOTED = "MODIFICATION_PROMOTED"
    MODIFICATION_ROLLED_BACK = "MODIFICATION_ROLLED_BACK"
    GENOME_CREATED = "GENOME_CREATED"
    GENOME_EVALUATED = "GENOME_EVALUATED"
    GENOME_PROMOTED = "GENOME_PROMOTED"
    GENOME_REJECTED = "GENOME_REJECTED"

    # --- Slice 6: Cognitive Routing (provider-independent model substrate) ---
    # The runtime must not care which provider supplies its cognitive substrate.
    ROUTING_STARTED = "ROUTING_STARTED"
    MODEL_SELECTED = "MODEL_SELECTED"
    PROVIDER_CALLED = "PROVIDER_CALLED"
    PROVIDER_SUCCEEDED = "PROVIDER_SUCCEEDED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    FAILOVER_STARTED = "FAILOVER_STARTED"
    FAILOVER_COMPLETED = "FAILOVER_COMPLETED"
    ROUTING_COMPLETED = "ROUTING_COMPLETED"
    ROUTING_FAILED = "ROUTING_FAILED"

    # --- Slice 8: CognitivePulse (persistent, event-driven cognitive loop) ---
    # The Pulse is the coordinator of the cognitive lifecycle on the single
    # bus; these events expose its state transitions and work queue.
    PULSE_STARTED = "PULSE_STARTED"
    PULSE_CYCLE_STARTED = "PULSE_CYCLE_STARTED"
    PULSE_CYCLE_COMPLETED = "PULSE_CYCLE_COMPLETED"
    PULSE_IDLE = "PULSE_IDLE"
    PULSE_PAUSED = "PULSE_PAUSED"
    PULSE_RESUMED = "PULSE_RESUMED"
    PULSE_DEGRADED = "PULSE_DEGRADED"
    PULSE_STOPPED = "PULSE_STOPPED"
    WORK_QUEUED = "WORK_QUEUED"
    WORK_STARTED = "WORK_STARTED"
    WORK_DEFERRED = "WORK_DEFERRED"
    WORK_COMPLETED = "WORK_COMPLETED"
    WORK_FAILED = "WORK_FAILED"
    UNFINISHED_TASK_DETECTED = "UNFINISHED_TASK_DETECTED"

    # --- Slice 8: continuous monitoring & controlled self-improvement loop ---
    # Emitted by MonitorScheduler (zerion/cognitive_os/monitor.py) and the
    # policy promotion path. REGRESSION_DETECTED fires when real post-promotion
    # telemetry drops below threshold; MONITOR_CYCLE_COMPLETED after every scan;
    # POLICY_APPLIED / POLICY_ROLLED_BACK when a gated policy promotion or its
    # rollback actually lands in the versioned runtime policy store.
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    MONITOR_CYCLE_COMPLETED = "MONITOR_CYCLE_COMPLETED"
    POLICY_APPLIED = "POLICY_APPLIED"
    POLICY_ROLLED_BACK = "POLICY_ROLLED_BACK"


@dataclass
class Event:
    event_type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "runtime"
    priority: int = 50  # 0 (lowest) to 100 (highest/critical)
    sequence: Optional[int] = None  # monotonically increasing order assigned by the bus on publish
    schema_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type),
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "priority": self.priority,
            "sequence": self.sequence,
            "schema_version": self.schema_version
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        event_type_str = data.get("event_type", EventType.OBSERVATION_RECORDED.value)
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            event_type = EventType.OBSERVATION_RECORDED
        return cls(
            event_type=event_type,
            payload=data.get("payload", {}),
            event_id=data.get("event_id", str(uuid.uuid4())),
            correlation_id=data.get("correlation_id"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            source=data.get("source", "runtime"),
            priority=data.get("priority", 50),
            sequence=data.get("sequence"),
            schema_version=data.get("schema_version", 1)
        )
