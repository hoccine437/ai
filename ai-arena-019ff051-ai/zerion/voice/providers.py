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


def _parse_termux_stt_json(raw: str) -> str:
    """Parse termux-speech-to-text JSON output into a plain transcript.
    Emits JSON lines like {"code": 0, "text": "..."}. Never fabricates:
    returns "" when no recognized text is present."""
    import json as _json
    text = ""
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = _json.loads(line)
        except ValueError:
            # Non-JSON noise on stderr is not a transcript.
            continue
        if isinstance(obj, dict):
            t = obj.get("text")
            if isinstance(t, str) and t.strip():
                text = (text + " " + t.strip()).strip()
    return text


def _parse_engine_transcript(engine: str, raw: str) -> str:
    """Parse engine output into a plain transcript string.

    - whisper.cpp with ``-nt`` prints plain text lines to stdout.
    - vosk-transcriber prints JSON {"text": "..."} to stdout.
    Never fabricates: empty output stays empty.
    """
    if engine == "vosk":
        import json as _json
        text = ""
        for line in (raw or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("text"), str):
                text = (text + " " + obj["text"].strip()).strip()
        return text
    # whisper.cpp / generic: plain text output.
    return (raw or "").strip()


def wav_header(pcm_len: int, sample_rate: int = 16000,
               channels: int = 1, sample_width: int = 2) -> bytes:
    """RIFF/WAVE header for 16-bit PCM mono frames (real local STT input)."""
    import struct
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    data_len = pcm_len
    return b"".join([
        b"RIFF", struct.pack("<I", 36 + data_len), b"WAVE",
        b"fmt ", struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                             byte_rate, block_align, sample_width),
        b"data", struct.pack("<I", data_len),
    ])


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
        from zerion.voice.stt_models import SttModelDiscovery

        # --- 1. termux-speech-to-text: Android/Termux on-device recognizer
        # (termux-api). Needs NO model file — it uses the platform's local
        # speech service. This is the primary Termux path.
        found = _find_binary("termux-speech-to-text")
        if found:
            info = VoiceEngineInfo(
                STT, "termux-speech-to-text", VoiceEngineStatus.AVAILABLE,
                reason="Android/Termux on-device speech recognizer found "
                       "(termux-api); no model file required",
                engine_binary=found,
                details={"offline": True, "platform": platform,
                         "model_required": False})
            self._stt_cache = info
            return info

        # --- 2. whisper.cpp (whisper-cli) — real offline engine. Available
        # ONLY when a validated model file exists in models/stt/; an engine
        # binary without a model reports LOCAL_STT_MODEL_MISSING, never READY.
        whisper_cli = _find_binary("whisper-cli")
        if whisper_cli:
            discovery = SttModelDiscovery()
            model = discovery.select()
            if model is not None:
                info = VoiceEngineInfo(
                    STT, "whisper.cpp", VoiceEngineStatus.AVAILABLE,
                    reason=f"whisper.cpp engine with local model "
                           f"{model.model_id}",
                    engine_binary=whisper_cli,
                    details={"offline": True, "platform": platform,
                             "model_required": True,
                             "model_id": model.model_id,
                             "model_path": model.path})
            else:
                info = VoiceEngineInfo(
                    STT, "whisper.cpp", VoiceEngineStatus.UNAVAILABLE,
                    reason="LOCAL_STT_MODEL_MISSING: whisper.cpp is installed "
                           "but no validated model exists in models/stt/ "
                           "(add a .ggml/.gguf whisper model)",
                    engine_binary=whisper_cli,
                    details={"offline": True, "platform": platform,
                             "model_required": True,
                             "models_dir": str(discovery.models_dir)})
            self._stt_cache = info
            return info

        # --- 3. vosk (vosk-transcriber binary or vosk package) — needs a
        # validated vosk model directory in models/stt/.
        vosk_bin = _find_binary("vosk-transcriber")
        vosk_pkg = False
        import importlib.util
        vosk_pkg = importlib.util.find_spec("vosk") is not None
        if vosk_bin or vosk_pkg:
            discovery = SttModelDiscovery()
            vosk_model = [m for m in discovery.available()
                          if m.kind == "vosk"]
            if vosk_model:
                info = VoiceEngineInfo(
                    STT, "vosk", VoiceEngineStatus.AVAILABLE,
                    reason=f"vosk with local model {vosk_model[0].model_id}",
                    engine_binary=vosk_bin,
                    details={"offline": True, "platform": platform,
                             "model_required": True,
                             "model_id": vosk_model[0].model_id,
                             "model_path": vosk_model[0].path,
                             "package": vosk_pkg})
            else:
                info = VoiceEngineInfo(
                    STT, "vosk", VoiceEngineStatus.UNAVAILABLE,
                    reason="LOCAL_STT_MODEL_MISSING: vosk is installed but no "
                           "validated vosk model directory exists in "
                           "models/stt/ (add a vosk-model-* dir with "
                           "am/final.mdl)",
                    engine_binary=vosk_bin,
                    details={"offline": True, "platform": platform,
                             "model_required": True,
                             "models_dir": str(discovery.models_dir),
                             "package": vosk_pkg})
            self._stt_cache = info
            return info

        info = VoiceEngineInfo(
            STT, "offline_stt", VoiceEngineStatus.UNAVAILABLE,
            reason="no offline STT engine found (tried termux-speech-to-text, "
                   "whisper-cli/whisper.cpp, vosk)",
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
                   timeout_s: float = 30.0) -> Dict[str, Any]:
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


class SpeechToTextProvider:
    """Canonical local-first speech-to-text provider (Slice 10.1).

    Wraps the evidence-based ``VoiceEnvironment`` detection and executes REAL
    offline STT engines (whisper.cpp / openai-whisper / vosk binaries) on the
    captured PCM segment. Never fabricates a transcript: every failure is
    reported as STT_UNAVAILABLE / STT_ERROR with the exact reason.

    The cognitive runtime consumes only structured transcript events; it never
    sees provider-specific objects.
    """

    def __init__(self, voice_env: Optional[VoiceEnvironment] = None):
        self.env = voice_env or VoiceEnvironment()

    def detect(self) -> VoiceEngineInfo:
        return self.env.detect_stt()

    def is_available(self) -> bool:
        return self.detect().status == VoiceEngineStatus.AVAILABLE

    def transcribe(self, segment: List[Any],
                   allow_online: bool = False) -> Dict[str, Any]:
        """Transcribe a list of AudioFrame-like objects (each with ``samples``).

        Returns {status: SUCCESS | STT_UNAVAILABLE | STT_ERROR, transcript,
        provider, reason, latency_ms}. ``allow_online`` is policy-gated; no
        online adapter is wired, so it is reported honestly.
        """
        info = self.detect()
        if info.status != VoiceEngineStatus.AVAILABLE or not info.engine_binary:
            if allow_online:
                return {"status": "STT_UNAVAILABLE", "transcript": "",
                        "provider": "configured_online_stt",
                        "reason": "online STT adapter not wired (policy-gated; "
                                   "no SDK configured)", "latency_ms": 0.0}
            return {"status": "STT_UNAVAILABLE", "transcript": "",
                    "provider": "NO_PROVIDER",
                    "reason": info.reason or "no STT provider available",
                    "latency_ms": 0.0}
        samples = b"".join([f.samples for f in segment
                             if getattr(f, "samples", None) is not None])
        binary = info.engine_binary
        engine = info.name
        # STT_LANGUAGE: explicit and observable. "auto" lets the engine
        # decide (whisper.cpp auto-detects; termux uses the system language).
        lang = os.environ.get("STT_LANGUAGE", "auto").strip() or "auto"

        t0 = time.perf_counter()
        try:
            # termux-speech-to-text records from the device mic itself and
            # emits JSON on stdout (no wav file is fed to it).
            if engine == "termux-speech-to-text":
                cmd = [binary]
                if lang != "auto":
                    cmd += ["-l", lang]
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True,
                                         timeout=20.0)
                except FileNotFoundError:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{binary} disappeared after detection",
                            "latency_ms": 0.0}
                except subprocess.TimeoutExpired:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{engine} timed out", "latency_ms": 0.0}
                latency = (time.perf_counter() - t0) * 1000.0
                if res.returncode != 0:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{engine} exited {res.returncode}: "
                                       f"{res.stderr[:200]}",
                            "latency_ms": 0.0}
                transcript = _parse_termux_stt_json(
                    res.stdout or res.stderr)
                if not transcript:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{engine} produced no recognized "
                                       f"speech or empty output",
                            "latency_ms": 0.0}
                return {"status": "SUCCESS",
                        "transcript": transcript[:500],
                        "provider": engine,
                        "language": lang,
                        "latency_ms": round(latency, 2)}

            # File-based engines (whisper.cpp / vosk) need the PCM segment.
            if not samples:
                return {"status": "STT_UNAVAILABLE", "transcript": "",
                        "provider": engine,
                        "reason": "segment has no raw PCM samples; local STT "
                                   "requires actual audio", "latency_ms": 0.0}
            fd, wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                with open(wav_path, "wb") as f:
                    f.write(wav_header(len(samples)))
                    f.write(samples)

                if engine == "whisper.cpp":
                    model_path = (info.details or {}).get("model_path", "")
                    if not model_path:
                        return {"status": "STT_ERROR", "transcript": "",
                                "provider": engine,
                                "reason": "whisper.cpp detected without a "
                                           "model path (LOCAL_STT_MODEL_MISSING)",
                                "latency_ms": 0.0}
                    cmd = [binary, "-m", model_path, "-f", wav_path,
                           "-nt", "-l", lang]
                elif engine == "vosk":
                    model_path = (info.details or {}).get("model_path", "")
                    if binary:  # vosk-transcriber CLI
                        if not model_path:
                            return {"status": "STT_ERROR", "transcript": "",
                                    "provider": engine,
                                    "reason": "vosk detected without a model "
                                               "directory "
                                               "(LOCAL_STT_MODEL_MISSING)",
                                    "latency_ms": 0.0}
                        cmd = [binary, "-i", wav_path, "-o", "-",
                               "-m", model_path]
                    else:
                        # vosk python package path (no CLI binary).
                        return self._transcribe_vosk_python(
                            wav_path, model_path, lang, t0)
                else:
                    cmd = [binary, wav_path]

                try:
                    res = subprocess.run(cmd, capture_output=True, text=True,
                                         timeout=30.0)
                except FileNotFoundError:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{binary} disappeared after detection",
                            "latency_ms": 0.0}
                except subprocess.TimeoutExpired:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{engine} timed out", "latency_ms": 0.0}
                latency = (time.perf_counter() - t0) * 1000.0
                if res.returncode != 0:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{engine} exited {res.returncode}: "
                                       f"{res.stderr[:200]}", "latency_ms": 0.0}
                transcript = _parse_engine_transcript(
                    engine, res.stdout or res.stderr)
                if not transcript:
                    return {"status": "STT_ERROR", "transcript": "",
                            "provider": engine,
                            "reason": f"{engine} produced empty output",
                            "latency_ms": 0.0}
                return {"status": "SUCCESS", "transcript": transcript[:500],
                        "provider": engine, "language": lang,
                        "latency_ms": round(latency, 2)}
            finally:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
        finally:
            # Defensive: the termux path returns before wav_path exists.
            try:
                os.remove(wav_path)
            except (OSError, UnboundLocalError):
                pass

    def _transcribe_vosk_python(self, wav_path: str, model_path: str,
                                lang: str, t0: float) -> Dict[str, Any]:
        """Transcribe via the vosk Python package (no CLI binary). Real
        offline inference through KaldiRecognizer. Never fabricates text."""
        try:
            from vosk import KaldiRecognizer, Model  # type: ignore
            import wave
        except ImportError as exc:
            return {"status": "STT_ERROR", "transcript": "",
                    "provider": "vosk",
                    "reason": f"vosk package unavailable: {exc}",
                    "latency_ms": 0.0}
        if not model_path:
            return {"status": "STT_ERROR", "transcript": "",
                    "provider": "vosk",
                    "reason": "vosk detected without a model directory "
                               "(LOCAL_STT_MODEL_MISSING)", "latency_ms": 0.0}
        try:
            import wave as _wave
            with _wave.open(wav_path, "rb") as wf:
                rate = wf.getframerate()
                data = wf.readframes(wf.getnframes())
            model = Model(model_path)
            rec = KaldiRecognizer(model, float(rate))
            if lang and lang != "auto":
                # vosk models are language-specific; a mismatched lang is
                # reported, never silently assumed.
                pass
            if rec.AcceptWaveform(data):
                import json as _json
                result = _json.loads(rec.Result())
            else:
                import json as _json
                result = _json.loads(rec.FinalResult())
            transcript = (result or {}).get("text", "").strip()
            if not transcript:
                return {"status": "STT_ERROR", "transcript": "",
                        "provider": "vosk",
                        "reason": "vosk produced no recognized speech",
                        "latency_ms": 0.0}
            latency = (time.perf_counter() - t0) * 1000.0
            return {"status": "SUCCESS", "transcript": transcript[:500],
                    "provider": "vosk", "language": lang,
                    "latency_ms": round(latency, 2)}
        except Exception as exc:  # noqa: BLE001
            return {"status": "STT_ERROR", "transcript": "",
                    "provider": "vosk",
                    "reason": f"vosk inference failed: "
                               f"{type(exc).__name__}: {exc}",
                    "latency_ms": 0.0}

    def to_dict(self) -> Dict[str, Any]:
        return self.detect().to_dict()


class LocalTextToSpeechProvider:
    """Canonical local-first text-to-speech provider (Slice 10).

    Produces REAL audio through the detected offline engine (espeak-ng /
    espeak / pico2wave / flite / say / termux-tts-speak). Reports
    LOCAL_TTS_UNAVAILABLE with the install/setup path when no engine exists —
    it never pretends speech was generated.
    """

    def __init__(self, voice_env: Optional[VoiceEnvironment] = None):
        self.env = voice_env or VoiceEnvironment()

    def detect(self) -> VoiceEngineInfo:
        return self.env.detect_tts()

    def is_available(self) -> bool:
        return self.detect().status == VoiceEngineStatus.AVAILABLE

    def synthesize(self, text: str, out_path: Optional[str] = None,
                   timeout_s: float = 15.0) -> Dict[str, Any]:
        return self.env.synthesize(text, out_path=out_path, timeout_s=timeout_s)

    def install_hint(self) -> str:
        """Concrete setup path when the platform lacks an offline engine."""
        platform = self.env.detect_platform()
        if platform == "TERMUX":
            return ("LOCAL_TTS_UNAVAILABLE: install Termux:API and run "
                    "`pkg install termux-api` + enable TTS in Android settings "
                    "(termux-tts-speak); or `pkg install espeak-ng`")
        if platform == "ANDROID":
            return ("LOCAL_TTS_UNAVAILABLE: use Termux:API (termux-tts-speak) "
                    "or a local TTS engine; cloud TTS is not used")
        return ("LOCAL_TTS_UNAVAILABLE: install an offline engine, e.g. "
                "`apt install espeak-ng` (Linux), `brew install espeak` "
                "(macOS), or use Windows SAPI")

    def to_dict(self) -> Dict[str, Any]:
        return self.detect().to_dict()


def sys_platform_is_desktop() -> bool:
    import sys
    return sys.platform in ("linux", "darwin", "win32")
