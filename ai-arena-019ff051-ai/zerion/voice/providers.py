"""
Voice providers & environment detection — Slice 10.

Offline-first architecture:

    MICROPHONE -> STT -> VOICE EVENTS -> CognitiveRuntime -> RESPONSE -> TTS -> SPEAKER

- ``NetworkStateProbe`` measures real connectivity (bounded attempts, cached —
  never inferred from config presence, never hammered).
- ``VoiceEnvironment`` detects what is ACTUALLY installed on this machine
  (espeak-ng / pico2wave / flite / say / termux-tts-speak for TTS; whisper /
  vosk binaries for STT). Detection is evidence-based: if nothing is found the
  status is UNAVAILABLE with a reason — never "ready" by assumption.
- ``OfflineTTSProvider`` synthesizes REAL audio when an engine exists and
  returns VOICE_UNAVAILABLE otherwise. It never claims speech was generated.
- Cloud providers are optional adapters gated by real credentials; they never
  fake availability.

No microphone hardware is probed here (that is the browser/Termux layer); the
pipeline treats missing hardware honestly via VOICE_ERROR / NOT_TESTABLE.
"""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

STT = "STT"
TTS = "TTS"
WAKE = "WAKE"


class VoiceEngineStatus(str):
    """Honest engine status values."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_TESTABLE_IN_ENVIRONMENT = "NOT_TESTABLE_IN_ENVIRONMENT"


class VoiceEngineInfo:
    def __init__(self, kind: str, name: str, status: str,
                 reason: str = "", engine_binary: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        self.kind = kind
        self.name = name
        self.status = status
        self.reason = reason
        self.engine_binary = engine_binary
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "engine_binary": self.engine_binary,
            "details": dict(self.details),
        }


class NetworkStateProbe:
    """Measures real network availability with bounded retry/backoff and a
    short cache so we never hammer the network on a bad link."""

    DEFAULT_PROBE_HOSTS = (("1.1.1.1", 53), ("8.8.8.8", 53))

    def __init__(self, hosts: Optional[List[Tuple[str, int]]] = None,
                 timeout_s: float = 1.5, max_attempts: int = 2,
                 cache_seconds: float = 30.0,
                 checker: Optional[Callable[[], str]] = None,
                 now_fn=None):
        self.hosts = hosts or list(self.DEFAULT_PROBE_HOSTS)
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.cache_seconds = cache_seconds
        self._checker = checker  # injectable for deterministic tests
        self._now = now_fn or time.time
        self._cached: Optional[str] = None
        self._cached_at: float = 0.0
        self._attempts = 0

    def _probe(self) -> str:
        for host, port in self.hosts:
            for attempt in range(self.max_attempts):
                self._attempts += 1
                try:
                    with socket.create_connection((host, port),
                                                  timeout=self.timeout_s):
                        return "ONLINE"
                except OSError:
                    if attempt < self.max_attempts - 1:
                        time.sleep(0.2 * (attempt + 1))  # bounded backoff
                    continue
        return "OFFLINE"

    def check(self) -> str:
        """Returns ONLINE / OFFLINE / UNKNOWN (cached between probes)."""
        if self._checker is not None:
            return self._checker()
        now = self._now()
        if self._cached is not None and (now - self._cached_at) < self.cache_seconds:
            return self._cached
        try:
            self._cached = self._probe()
        except Exception:  # noqa: BLE001 — measurement must never crash callers
            self._cached = "UNKNOWN"
        self._cached_at = self._now()
        return self._cached

    def state(self) -> Dict[str, Any]:
        return {"state": self.check(), "attempts": self._attempts,
                "cached_at": self._cached_at}


def _find_binary(*names: str) -> Optional[str]:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


class VoiceEnvironment:
    """Detects the ACTUAL voice engines present on this machine. Never
    assumes an engine exists because a provider is "configured"."""

    def __init__(self, network_probe: Optional[NetworkStateProbe] = None,
                 models_dir: Optional[str] = None):
        self.network = network_probe or NetworkStateProbe()
        self.models_dir = models_dir
        self._tts_cache: Optional[VoiceEngineInfo] = None
        self._stt_cache: Optional[VoiceEngineInfo] = None
        self._wake_cache: Optional[VoiceEngineInfo] = None

    # -- platform ----------------------------------------------------------

    @staticmethod
    def detect_platform() -> str:
        """DESKTOP / ANDROID / TERMUX / UNKNOWN — no desktop-only imports."""
        if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
            return "TERMUX"
        if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
            return "ANDROID"
        if os.name == "nt" or sys_platform_is_desktop():
            return "DESKTOP"
        return "UNKNOWN"

    # -- TTS ---------------------------------------------------------------

    def detect_tts(self) -> VoiceEngineInfo:
        if self._tts_cache is not None:
            return self._tts_cache
        platform = self.detect_platform()

        # Offline engines (Termux-compatible where present).
        for binary, name in [
            ("espeak-ng", "espeak-ng"),
            ("espeak", "espeak"),
            ("pico2wave", "pico2wave"),
            ("flite", "flite"),
        ]:
            found = _find_binary(binary)
            if found:
                info = VoiceEngineInfo(
                    TTS, name, VoiceEngineStatus.AVAILABLE,
                    reason="offline TTS engine found on PATH",
                    engine_binary=found,
                    details={"offline": True, "platform": platform})
                self._tts_cache = info
                return info

        # Termux API TTS (uses the Android system TTS engine).
        if platform == "TERMUX":
            found = _find_binary("termux-tts-speak")
            if found:
                info = VoiceEngineInfo(
                    TTS, "termux-tts-speak", VoiceEngineStatus.AVAILABLE,
                    reason="Termux API TTS engine found",
                    engine_binary=found,
                    details={"offline": False, "platform": platform})
                self._tts_cache = info
                return info

        # macOS built-in.
        found = _find_binary("say")
        if found:
            info = VoiceEngineInfo(
                TTS, "say", VoiceEngineStatus.AVAILABLE,
                reason="macOS 'say' engine found",
                engine_binary=found,
                details={"offline": True, "platform": platform})
            self._tts_cache = info
            return info

        info = VoiceEngineInfo(
            TTS, "offline_tts", VoiceEngineStatus.UNAVAILABLE,
            reason="no offline TTS engine found (tried espeak-ng, espeak, "
                   "pico2wave, flite, termux-tts-speak, say)",
            details={"platform": platform})
        self._tts_cache = info
        return info

    # -- STT ---------------------------------------------------------------

    def detect_stt(self) -> VoiceEngineInfo:
        if self._stt_cache is not None:
            return self._stt_cache
        platform = self.detect_platform()

        # Real offline STT engines. We only claim STT is available when a
        # concrete binary is present; configuration alone never counts.
        for binary, name in [("whisper-cli", "whisper.cpp"),
                             ("whisper", "openai-whisper"),
                             ("vosk-transcriber", "vosk")]:
            found = _find_binary(binary)
            if found:
                info = VoiceEngineInfo(
                    STT, name, VoiceEngineStatus.AVAILABLE,
                    reason=f"offline STT engine found on PATH ({binary})",
                    engine_binary=found,
                    details={"offline": True, "platform": platform})
                self._stt_cache = info
                return info

        # Vosk python package present (real, importable) with a model dir.
        if self.models_dir and Path(self.models_dir).exists():
            import importlib.util
            if importlib.util.find_spec("vosk") is not None:
                info = VoiceEngineInfo(
                    STT, "vosk", VoiceEngineStatus.AVAILABLE,
                    reason="vosk package installed with local model dir",
                    details={"offline": True, "platform": platform})
                self._stt_cache = info
                return info

        info = VoiceEngineInfo(
            STT, "offline_stt", VoiceEngineStatus.UNAVAILABLE,
            reason="no offline STT engine found (tried whisper.cpp, "
                   "openai-whisper, vosk)",
            details={"platform": platform})
        self._stt_cache = info
        return info

    # -- wake word ---------------------------------------------------------

    def detect_wake(self) -> VoiceEngineInfo:
        if self._wake_cache is not None:
            return self._wake_cache
        # The wake-word detector is pure Python (deterministic, offline) — it
        # is always available; sensitivity is configurable.
        info = VoiceEngineInfo(
            WAKE, "layered_wake_word", VoiceEngineStatus.AVAILABLE,
            reason="built-in deterministic wake-word detector (offline)",
            details={"sensitivity": "configurable", "offline": True})
        self._wake_cache = info
        return info

    # -- synthesis ---------------------------------------------------------

    def synthesize(self, text: str, out_path: Optional[str] = None,
                   timeout_s: float = 15.0) -> Dict[str, Any]:
        """Produce REAL audio via the detected offline engine.

        Returns evidence: {status: AUDIO_GENERATED, engine, path, bytes} on
        success, or {status: VOICE_UNAVAILABLE, reason} when no engine exists.
        Never fabricates speech.
        """
        info = self.detect_tts()
        if info.status != VoiceEngineStatus.AVAILABLE or not info.engine_binary:
            return {"status": "VOICE_UNAVAILABLE",
                    "reason": info.reason, "engine": info.name}
        path = out_path or os.path.join(
            tempfile.gettempdir(),
            f"zerion_tts_{int(time.time() * 1000)}.wav")
        binary = info.engine_binary
        engine = info.name
        try:
            if engine == "espeak-ng" or engine == "espeak":
                cmd = [binary, "-w", path, text]
            elif engine == "pico2wave":
                cmd = [binary, "-w", path, text]
            elif engine == "flite":
                cmd = [binary, "-o", path, "-t", text]
            elif engine == "say":
                cmd = [binary, "-o", path, text]
            elif engine == "termux-tts-speak":
                # Termux TTS plays through the speaker; we cannot capture to a
                # file. Record the call as evidence that speech was requested.
                cmd = [binary, text]
            else:
                return {"status": "VOICE_UNAVAILABLE",
                        "reason": f"unknown engine {engine}"}
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=timeout_s)
            if res.returncode != 0:
                return {"status": "VOICE_ERROR",
                        "reason": f"{engine} exited {res.returncode}: "
                                  f"{res.stderr[:200]}", "engine": engine}
            if engine == "termux-tts-speak":
                return {"status": "AUDIO_PLAYED", "engine": engine,
                        "details": "termux-tts-speak played through speaker"}
            size = os.path.getsize(path) if os.path.exists(path) else 0
            if size <= 0:
                return {"status": "VOICE_ERROR",
                        "reason": f"{engine} produced empty audio",
                        "engine": engine}
            return {"status": "AUDIO_GENERATED", "engine": engine,
                    "path": path, "bytes": size}
        except FileNotFoundError:
            return {"status": "VOICE_UNAVAILABLE",
                    "reason": f"engine {binary} disappeared after detection",
                    "engine": engine}
        except subprocess.TimeoutExpired:
            return {"status": "VOICE_ERROR",
                    "reason": f"{engine} timed out after {timeout_s}s",
                    "engine": engine}
        except Exception as e:  # noqa: BLE001
            return {"status": "VOICE_ERROR",
                    "reason": f"{type(e).__name__}: {str(e)[:200]}",
                    "engine": engine}

    # -- aggregate ---------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.detect_platform(),
            "network": self.network.state(),
            "stt": self.detect_stt().to_dict(),
            "tts": self.detect_tts().to_dict(),
            "wake": self.detect_wake().to_dict(),
        }


def sys_platform_is_desktop() -> bool:
    import sys
    return sys.platform in ("linux", "darwin", "win32")
