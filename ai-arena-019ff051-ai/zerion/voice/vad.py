"""
Voice Activity Detection (VAD) & Silence Tracker
Analyzes audio energy / RMS amplitude to detect speech boundaries, pauses, and turn completion.
"""

from dataclasses import dataclass
import time
from typing import Optional


@dataclass
class VADState:
    is_speech_active: bool
    current_rms: float
    silence_duration_s: float
    speech_duration_s: float
    turn_completed: bool


class VoiceActivityDetector:
    def __init__(
        self,
        energy_threshold: float = 0.05,
        silence_timeout_s: float = 2.0,
        max_turn_duration_s: float = 20.0,
        now_fn=None
    ):
        self.energy_threshold = energy_threshold
        self.silence_timeout_s = silence_timeout_s
        self.max_turn_duration_s = max_turn_duration_s
        self._now = now_fn or time.time

        self._speech_start_time: Optional[float] = None
        self._last_speech_time: Optional[float] = None
        self._is_active = False

    def process_frame(self, rms_amplitude: float) -> VADState:
        now = self._now()
        is_speech = rms_amplitude >= self.energy_threshold

        if is_speech:
            if not self._is_active:
                self._is_active = True
                self._speech_start_time = now
            self._last_speech_time = now
            silence_dur = 0.0
            speech_dur = now - (self._speech_start_time or now)
            turn_completed = False
        else:
            if self._is_active:
                silence_dur = now - (self._last_speech_time or now)
                speech_dur = (self._last_speech_time or now) - (self._speech_start_time or now)
                turn_completed = (silence_dur >= self.silence_timeout_s) or (speech_dur >= self.max_turn_duration_s)
                if turn_completed:
                    self._is_active = False
                    self._speech_start_time = None
                    self._last_speech_time = None
            else:
                silence_dur = 0.0
                speech_dur = 0.0
                turn_completed = False

        return VADState(
            is_speech_active=is_speech,
            current_rms=round(rms_amplitude, 4),
            silence_duration_s=round(silence_dur, 2),
            speech_duration_s=round(speech_dur, 2),
            turn_completed=turn_completed
        )

    def reset(self):
        self._is_active = False
        self._speech_start_time = None
        self._last_speech_time = None
