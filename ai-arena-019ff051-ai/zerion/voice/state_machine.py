"""
Voice State Machine — Slice 10.

Explicit states: IDLE, LISTENING, THINKING, EXECUTING, SPEAKING, INTERRUPTED, ERROR.
Only valid transitions are allowed; an invalid transition raises
``InvalidVoiceTransition`` instead of silently corrupting the voice lifecycle.

Valid transitions:

    IDLE -> LISTENING | ERROR
    LISTENING -> THINKING | IDLE | ERROR | INTERRUPTED
    THINKING -> EXECUTING | SPEAKING | IDLE | ERROR | INTERRUPTED
    EXECUTING -> THINKING | SPEAKING | IDLE | ERROR | INTERRUPTED
    SPEAKING -> LISTENING | IDLE | INTERRUPTED | ERROR
    INTERRUPTED -> LISTENING | IDLE
    ERROR -> IDLE | LISTENING
"""

from dataclasses import dataclass
from enum import Enum
import time
from typing import Dict, Optional, Set, Tuple


class VoiceState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


_TRANSITIONS: Dict[VoiceState, Set[VoiceState]] = {
    VoiceState.IDLE: {VoiceState.LISTENING, VoiceState.ERROR},
    VoiceState.LISTENING: {VoiceState.THINKING, VoiceState.IDLE,
                           VoiceState.ERROR, VoiceState.INTERRUPTED},
    VoiceState.THINKING: {VoiceState.EXECUTING, VoiceState.SPEAKING,
                          VoiceState.IDLE, VoiceState.ERROR,
                          VoiceState.INTERRUPTED},
    VoiceState.EXECUTING: {VoiceState.THINKING, VoiceState.SPEAKING,
                           VoiceState.IDLE, VoiceState.ERROR,
                           VoiceState.INTERRUPTED},
    VoiceState.SPEAKING: {VoiceState.LISTENING, VoiceState.IDLE,
                          VoiceState.INTERRUPTED, VoiceState.ERROR},
    VoiceState.INTERRUPTED: {VoiceState.LISTENING, VoiceState.IDLE},
    VoiceState.ERROR: {VoiceState.IDLE, VoiceState.LISTENING},
}


class InvalidVoiceTransition(Exception):
    """Raised when a transition not in the allowed set is attempted."""


@dataclass
class VoiceStateInfo:
    state: VoiceState
    entered_at: float
    last_transition: str


class VoiceStateMachine:
    def __init__(self, initial_state: VoiceState = VoiceState.IDLE,
                 now_fn=None):
        self._now = now_fn or time.time
        self._state = VoiceState(initial_state)
        self._entered_at = self._now()
        self._last_transition = "INITIALIZE"
        self._transition_log: list = []

    @property
    def state(self) -> VoiceState:
        return self._state

    def transition(self, new_state: VoiceState, reason: str = "") -> VoiceState:
        new_state = VoiceState(new_state)
        if new_state == self._state:
            # Idempotent re-entry is allowed (e.g. stay LISTENING after a
            # rejected wake word); it is not a transition.
            return self._state
        allowed = _TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise InvalidVoiceTransition(
                f"invalid voice transition {self._state.value} -> {new_state.value}")
        old = self._state
        self._state = new_state
        self._entered_at = self._now()
        self._last_transition = f"{old.value}->{new_state.value}"
        self._transition_log.append({
            "from": old.value, "to": new_state.value,
            "reason": reason, "at": self._entered_at,
        })
        return self._state

    def can_transition(self, new_state: VoiceState) -> bool:
        return VoiceState(new_state) in _TRANSITIONS.get(self._state, set())

    def to_dict(self) -> dict:
        return {
            "state": self._state.value,
            "entered_at": self._entered_at,
            "last_transition": self._last_transition,
            "recent_transitions": self._transition_log[-10:],
        }

    def reset(self) -> None:
        self._state = VoiceState.IDLE
        self._entered_at = self._now()
        self._last_transition = "RESET"
