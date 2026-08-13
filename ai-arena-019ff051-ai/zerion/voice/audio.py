"""
Audio input substrate for the always-available voice perception service
(Slice 10.1).

Owns the raw side of the microphone pipeline only:

    MICROPHONE -> AudioInputMonitor -> AudioFrame -> RollingAudioBuffer

- ``RollingAudioBuffer`` is a BOUNDED rolling buffer: it never accumulates
  microphone audio indefinitely and never persists raw audio to disk.
- ``AudioInputMonitor`` is the interface every microphone source implements.
- ``NullMicrophoneMonitor`` reports exactly what it is: no audio backend is
  bound, so no listening is possible. It never fakes a microphone.
- ``SoundDeviceMicrophoneMonitor`` binds a REAL ``sounddevice`` stream when
  the optional package is installed; otherwise it is never constructed.
- ``SimulatedMicrophoneMonitor`` is an explicit, labeled simulation harness
  for deterministic tests and demos. Telemetry always reports ``simulated``
  so a simulation is never mistaken for hardware.

This module has no cognition, no wake/VAD/STT logic, and no UI coupling.
"""

from dataclasses import dataclass, field
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

# Optional real audio backend (never required; the core stays stdlib-only).
try:  # pragma: no cover - exercised only when sounddevice is installed
    import sounddevice as _sd  # type: ignore
    _HAS_SOUNDDEVICE = True
except Exception:  # noqa: BLE001
    _sd = None
    _HAS_SOUNDDEVICE = False


@dataclass
class AudioFrame:
    """One captured audio frame: RMS energy plus optional raw PCM samples.

    ``samples`` is optional because the energy-VAD path only needs RMS; STT
    engines receive the buffered segment's samples when the monitor supplies
    them. Raw samples are held in the bounded in-memory buffer only.
    """
    rms: float
    timestamp: float
    samples: Optional[bytes] = None
    source: str = "audio"

    def to_dict(self) -> Dict[str, Any]:
        return {"rms": round(float(self.rms), 4),
                "timestamp": self.timestamp,
                "has_samples": self.samples is not None,
                "source": self.source}


class RollingAudioBuffer:
    """Bounded in-memory rolling audio buffer.

    Guarantees:
    - total frames never exceed ``max_frames`` (oldest dropped first)
    - total retained wall-time never exceeds ``max_duration_s``
    - ``extract_segment()`` returns a copy; the buffer never hands out live
      references that callers can grow unboundedly
    - nothing is ever written to disk by this class
    """

    def __init__(self, max_frames: int = 4096, max_duration_s: float = 8.0):
        self.max_frames = max(1, int(max_frames))
        self.max_duration_s = max(0.1, float(max_duration_s))
        self._frames: List[AudioFrame] = []

    def append(self, frame: AudioFrame) -> int:
        """Append a frame, enforcing the bound. Returns frames dropped."""
        self._frames.append(frame)
        dropped = 0
        while len(self._frames) > self.max_frames:
            self._frames.pop(0)
            dropped += 1
        if self._frames:
            oldest = self._frames[0].timestamp
            newest = self._frames[-1].timestamp
            span = max(0.0, newest - oldest)
            while span > self.max_duration_s and len(self._frames) > 1:
                self._frames.pop(0)
                dropped += 1
                oldest = self._frames[0].timestamp
                span = max(0.0, newest - oldest)
        return dropped

    def clear(self) -> None:
        self._frames = []

    def extract_segment(self) -> List[AudioFrame]:
        """Return a COPY of the buffered frames and clear the buffer."""
        seg = list(self._frames)
        self._frames = []
        return seg

    def samples_bytes(self) -> Optional[bytes]:
        """Concatenated raw samples of the current buffer (copy), if any."""
        parts = [f.samples for f in self._frames if f.samples is not None]
        if not parts:
            return None
        return b"".join(parts)

    @property
    def size(self) -> int:
        return len(self._frames)

    @property
    def retained_s(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return max(0.0, self._frames[-1].timestamp - self._frames[0].timestamp)

    def stats(self) -> Dict[str, Any]:
        return {
            "frames": self.size,
            "max_frames": self.max_frames,
            "retained_s": round(self.retained_s, 3),
            "max_duration_s": self.max_duration_s,
            "persisted_to_disk": False,
        }


class AudioInputMonitor:
    """Interface every microphone source implements.

    ``on_frame`` is an async callback invoked with each captured frame.
    ``heartbeat()`` must be called whenever audio is actually flowing so the
    VoiceWatchdog can distinguish "quiet but alive" from "stuck".
    """

    def __init__(self, on_frame: Optional[Callable[..., Any]] = None,
                 now_fn: Optional[Callable[[], float]] = None):
        import time
        self._now = now_fn or time.time
        self.on_frame = on_frame
        self._last_beat: float = 0.0
        self._init_attempts = 0
        self._running = False

    # -- lifecycle ----------------------------------------------------------

    def init(self) -> Dict[str, Any]:
        """Attempt to open the microphone. Returns honest evidence dict.

        {status: "OK", reason: "", device: ...} or
        {status: "UNAVAILABLE", reason: "..."} — never a fake OK.
        """
        raise NotImplementedError

    def start(self) -> None:
        self._running = True
        self._last_beat = self._now()

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        """Background capture loop (subclass responsibility)."""
        raise NotImplementedError

    # -- telemetry ----------------------------------------------------------

    def heartbeat(self) -> None:
        self._last_beat = self._now()

    def beat_age_s(self) -> float:
        return max(0.0, self._now() - self._last_beat)

    def is_active(self) -> bool:
        return self._running and self._last_beat > 0

    def describe(self) -> Dict[str, Any]:
        raise NotImplementedError


class NullMicrophoneMonitor(AudioInputMonitor):
    """No audio backend is bound (e.g. sounddevice not installed, or the OS
    denied access). Reports UNAVAILABLE with the exact reason — the service
    must never pretend to hear the user through this monitor."""

    def __init__(self, reason: str = "no audio input backend available "
                 "(sounddevice is not installed and no platform mic binding "
                 "exists in this environment)", now_fn=None):
        super().__init__(now_fn=now_fn)
        self._reason = reason

    def init(self) -> Dict[str, Any]:
        self._init_attempts += 1
        # transient=False: a missing backend is a permanent condition in this
        # environment — the caller must NOT retry in a backoff loop forever.
        return {"status": "UNAVAILABLE", "reason": self._reason,
                "device": None, "attempts": self._init_attempts,
                "transient": False}

    def describe(self) -> Dict[str, Any]:
        return {"kind": "null", "available": False, "simulated": False,
                "reason": self._reason, "init_attempts": self._init_attempts}


class SoundDeviceMicrophoneMonitor(AudioInputMonitor):
    """Real microphone via the optional ``sounddevice`` package.

    Only ever constructed when ``_HAS_SOUNDDEVICE`` is true. Binding failures
    (permission denied, device busy, device removed) return honest evidence
    dicts instead of raising into the caller."""

    def __init__(self, device: Optional[int] = None,
                 samplerate: int = 16000, channels: int = 1,
                 blocksize: int = 1600, on_frame: Optional[Callable] = None,
                 now_fn=None):
        super().__init__(on_frame=on_frame, now_fn=now_fn)
        self.device = device
        self.samplerate = samplerate
        self.channels = channels
        self.blocksize = blocksize
        self._stream: Any = None
        self._last_error: Optional[str] = None

    def init(self) -> Dict[str, Any]:
        if not _HAS_SOUNDDEVICE:
            return {"status": "UNAVAILABLE",
                    "reason": "sounddevice package is not installed",
                    "device": None, "transient": False}
        self._init_attempts += 1
        try:
            info = _sd.query_devices(self.device, "input")
        except Exception as e:  # noqa: BLE001
            self._last_error = str(e)
            return {"status": "UNAVAILABLE",
                    "reason": f"no input device: {type(e).__name__}: {e}",
                    "device": self.device, "transient": True}
        try:
            self._stream = _sd.InputStream(
                device=self.device, samplerate=self.samplerate,
                channels=self.channels, blocksize=self.blocksize,
                callback=self._callback)
            self._stream.start()
        except Exception as e:  # noqa: BLE001
            self._last_error = str(e)
            return {"status": "UNAVAILABLE",
                    "reason": f"stream open failed: {type(e).__name__}: {e}",
                    "device": self.device, "transient": True}
        return {"status": "OK", "reason": "", "device": self.device,
                "transient": False}

    def _callback(self, indata, frames, time_info, status):  # pragma: no cover
        import numpy  # type: ignore  # sounddevice implies numpy present
        self.heartbeat()
        rms = float(numpy.sqrt(numpy.mean(numpy.square(indata))))
        raw = indata.tobytes()
        if self.on_frame is not None and self._running:
            try:
                self.on_frame(AudioFrame(rms=rms, timestamp=self._now(),
                                         samples=raw, source="sounddevice"))
            except Exception:  # noqa: BLE001
                pass

    async def run(self) -> None:
        # sounddevice delivers frames via its own callback; this loop only
        # keeps the monitor alive until stopped.
        import asyncio
        while self._running:
            await asyncio.sleep(0.5)

    def stop(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:  # noqa: BLE001
            pass
        self._stream = None
        super().stop()

    def describe(self) -> Dict[str, Any]:
        return {"kind": "sounddevice", "available": _HAS_SOUNDDEVICE,
                "simulated": False, "device": self.device,
                "last_error": self._last_error}


class SimulatedMicrophoneMonitor(AudioInputMonitor):
    """DETERMINISTIC SIMULATION harness for tests and demos.

    Never used as a stand-in for real hardware in user-facing claims: every
    ``describe()``/telemetry payload marks ``simulated=True`` and the service
    reports the simulation explicitly. ``feed_frame`` lets tests push audio;
    ``run`` (optional) replays a scripted frame sequence at a fixed rate.
    """

    def __init__(self, script: Optional[List[Tuple[float, str]]] = None,
                 on_frame: Optional[Callable] = None, now_fn=None,
                 frame_interval_s: float = 0.05,
                 fail_init: int = 0,  # number of initial init() failures
                 device_changes: int = 0,  # device-change events to simulate
                 system_pauses: int = 0):  # external interruptions (calls)
        super().__init__(on_frame=on_frame, now_fn=now_fn)
        self.script = list(script or [])
        self.frame_interval_s = frame_interval_s
        self.fail_init = fail_init
        self.device_changes = device_changes
        self.system_pauses = system_pauses
        self._device_changes_emitted = 0
        self._system_pauses_emitted = 0
        self._failed_inits = 0
        self._paused = False
        self._device_change_pending = False
        self._script_index = 0

    def init(self) -> Dict[str, Any]:
        self._init_attempts += 1
        if self._failed_inits < self.fail_init:
            self._failed_inits += 1
            return {"status": "UNAVAILABLE",
                    "reason": "simulated microphone failure "
                              f"(attempt {self._init_attempts})",
                    "device": "simulated_input", "simulated": True}
        return {"status": "OK", "reason": "simulated monitor ready",
                "device": "simulated_input", "simulated": True}

    def feed_frame(self, rms: float, source: str = "simulated") -> AudioFrame:
        """Test/demo entry: push one audio frame through the monitor."""
        self.heartbeat()
        frame = AudioFrame(rms=rms, timestamp=self._now(), source=source)
        if self.on_frame is not None and self._running:
            try:
                self.on_frame(frame)
            except Exception:  # noqa: BLE001
                pass
        return frame

    def emit_device_change(self) -> bool:
        """Signal a device change; stays PENDING until the service confirms
        the re-initialization completed (so a frame can never swallow it)."""
        if self._device_changes_emitted >= self.device_changes:
            return False
        self._device_changes_emitted += 1
        self._paused = False
        self._device_change_pending = True
        return True

    def pending_device_change(self) -> bool:
        return self._device_change_pending

    def confirm_device_change(self) -> None:
        self._device_change_pending = False

    def emit_system_pause(self) -> bool:
        if self._system_pauses_emitted >= self.system_pauses:
            return False
        self._system_pauses_emitted += 1
        self._paused = True
        return True

    def resume_from_pause(self) -> None:
        self._paused = False

    def is_paused_by_system(self) -> bool:
        return self._paused

    async def run(self) -> None:
        import asyncio
        while self._running and self._script_index < len(self.script):
            rms, label = self.script[self._script_index]
            self._script_index += 1
            if self.on_frame is not None and not self._paused:
                self.feed_frame(rms, source=label)
            await asyncio.sleep(self.frame_interval_s)
        # Replay is finite; keep the monitor object alive until explicitly
        # stopped so telemetry stays coherent.
        while self._running:
            await asyncio.sleep(1.0)

    def describe(self) -> Dict[str, Any]:
        return {"kind": "simulated", "available": True, "simulated": True,
                "device": "simulated_input",
                "script_frames": len(self.script),
                "fail_init_budget": self.fail_init,
                "device_changes_remaining": max(
                    0, self.device_changes - self._device_changes_emitted),
                "system_pauses_remaining": max(
                    0, self.system_pauses - self._system_pauses_emitted)}


def default_microphone_monitor(on_frame: Optional[Callable] = None,
                               now_fn=None) -> AudioInputMonitor:
    """Pick the real monitor when the OS/backend permits it, else an honest
    Null monitor. Never fabricates a microphone."""
    if _HAS_SOUNDDEVICE:
        return SoundDeviceMicrophoneMonitor(on_frame=on_frame, now_fn=now_fn)
    return NullMicrophoneMonitor(now_fn=now_fn)
