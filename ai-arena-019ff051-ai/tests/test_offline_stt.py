"""
ZERION X — Offline STT repair protocol tests (spec section 16).

Covers the new local/offline speech-to-text surface:

- STT model discovery (models/stt/): whisper.cpp GGML/GGUF validation,
  vosk model directories, corruption/empty/missing handling, deterministic
  selection, honest report() (LOCAL_STT_MODEL_MISSING, never READY).
- Engine-aware detection: termux-speech-to-text, whisper.cpp (model-aware),
  vosk (model-aware) and the honest UNAVAILABLE fallback.
- Real engine transcription: whisper.cpp / vosk / termux invocations, STT_LANGUAGE
  observability, explicit STT_ERROR on failure — no fake transcripts.
- Parsing helpers and the WAV header used to feed file-based engines.

Production runtime never fakes a transcript; these tests only mock the
external engine subprocess, never the provider's decision logic.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zerion.voice.audio import AudioFrame
from zerion.voice.providers import (
    SpeechToTextProvider,
    VoiceEngineInfo,
    VoiceEngineStatus,
    VoiceEnvironment,
    _parse_engine_transcript,
    _parse_termux_stt_json,
    wav_header,
)
from zerion.voice.stt_models import SttModelDiscovery, SttModelStatus


def _tmp() -> str:
    return tempfile.mkdtemp(prefix="zerion_stt_test_")


def _write_model(dirpath: str, name: str, magic: bytes, size: int = 256) -> str:
    path = os.path.join(dirpath, name)
    with open(path, "wb") as f:
        f.write(magic + b"\x00" * size)
    return path


class TestSttModelDiscovery(unittest.TestCase):
    """models/stt/ discovery: real file validation, honest states."""

    def setUp(self) -> None:
        self.dir = _tmp()

    def test_whisper_ggml_model_validated(self) -> None:
        _write_model(self.dir, "ggml-base.bin", b"ggml")
        d = SttModelDiscovery(models_dir=self.dir)
        self.assertEqual(len(d.discover()), 1)
        m = d.select()
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.model_id, "ggml-base.bin")
        self.assertEqual(m.kind, "whisper_cpp")
        self.assertEqual(m.status, SttModelStatus.READY)
        self.assertTrue(d.any_available())

    def test_gguf_model_validated(self) -> None:
        _write_model(self.dir, "whisper-base.gguf", b"GGUF")
        d = SttModelDiscovery(models_dir=self.dir)
        m = d.select()
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.status, SttModelStatus.READY)

    def test_corrupted_model_reported_failed(self) -> None:
        _write_model(self.dir, "broken.bin", b"XXXX")
        d = SttModelDiscovery(models_dir=self.dir)
        m = d.get("broken.bin")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.status, SttModelStatus.FAILED)
        self.assertIn("corrupted", m.status_reason)
        self.assertFalse(d.any_available())
        # A broken model must NOT yield a READY report.
        self.assertEqual(d.report()["status"], "LOCAL_STT_MODEL_MISSING")

    def test_empty_model_reported_failed(self) -> None:
        _write_model(self.dir, "empty.bin", b"", size=0)
        d = SttModelDiscovery(models_dir=self.dir)
        m = d.get("empty.bin")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.status, SttModelStatus.FAILED)
        self.assertIn("empty", m.status_reason)

    def test_vosk_model_directory_validated(self) -> None:
        vosk_dir = os.path.join(self.dir, "vosk-model-small-en-us-0.15")
        os.makedirs(os.path.join(vosk_dir, "am"))
        Path(os.path.join(vosk_dir, "am", "final.mdl")).touch()
        d = SttModelDiscovery(models_dir=self.dir)
        m = d.get("vosk-model-small-en-us-0.15")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.kind, "vosk")
        self.assertEqual(m.status, SttModelStatus.READY)
        self.assertTrue(d.any_available())

    def test_missing_directory_reports_nothing(self) -> None:
        d = SttModelDiscovery(models_dir=os.path.join(self.dir, "nope"))
        self.assertEqual(d.discover(), [])
        self.assertFalse(d.any_available())
        report = d.report()
        self.assertEqual(report["discovered"], 0)
        self.assertEqual(report["status"], "LOCAL_STT_MODEL_MISSING")
        self.assertIsNone(report["selected"])

    def test_selection_deterministic_smallest(self) -> None:
        _write_model(self.dir, "ggml-large.bin", b"ggml", size=4096)
        _write_model(self.dir, "ggml-base.bin", b"ggml", size=512)
        d = SttModelDiscovery(models_dir=self.dir)
        # Deterministic: smallest validated model wins (fast phone loads).
        self.assertEqual(d.select().model_id, "ggml-base.bin")

    def test_report_shape_used_by_readiness(self) -> None:
        _write_model(self.dir, "ggml-base.bin", b"ggml")
        report = SttModelDiscovery(models_dir=self.dir).report()
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["available"], 1)
        self.assertEqual(report["selected"], "ggml-base.bin")
        self.assertEqual(len(report["models"]), 1)
        self.assertEqual(report["models"][0]["status"], SttModelStatus.READY)


class TestSttEngineDetection(unittest.TestCase):
    """Engine-aware detect_stt(): termux / whisper.cpp / vosk, model-gated."""

    def setUp(self) -> None:
        self.dir = _tmp()
        os.environ["ZERION_STT_MODELS_DIR"] = self.dir

    def tearDown(self) -> None:
        os.environ.pop("ZERION_STT_MODELS_DIR", None)

    def _patch_binaries(self, found: dict) -> mock._patch:
        return mock.patch(
            "zerion.voice.providers._find_binary",
            side_effect=lambda *names: next(
                (found[n] for n in names if n in found), None))

    def test_termux_stt_available_without_model(self) -> None:
        with self._patch_binaries({"termux-speech-to-text": "/fake/tstt"}):
            env = VoiceEnvironment()
            info = env.detect_stt()
        self.assertEqual(info.status, VoiceEngineStatus.AVAILABLE)
        self.assertEqual(info.name, "termux-speech-to-text")
        self.assertFalse(info.details["model_required"])

    def test_whisper_engine_without_model_reports_model_missing(self) -> None:
        # whisper.cpp installed but models/stt/ empty -> LOCAL_STT_MODEL_MISSING.
        with self._patch_binaries({"whisper-cli": "/fake/whisper-cli"}):
            env = VoiceEnvironment()
            info = env.detect_stt()
        self.assertEqual(info.name, "whisper.cpp")
        self.assertEqual(info.status, VoiceEngineStatus.UNAVAILABLE)
        self.assertIn("LOCAL_STT_MODEL_MISSING", info.reason)
        self.assertEqual(info.details["models_dir"], self.dir)

    def test_whisper_engine_with_model_available(self) -> None:
        _write_model(self.dir, "ggml-base.bin", b"ggml")
        with self._patch_binaries({"whisper-cli": "/fake/whisper-cli"}):
            env = VoiceEnvironment()
            info = env.detect_stt()
        self.assertEqual(info.status, VoiceEngineStatus.AVAILABLE)
        self.assertEqual(info.name, "whisper.cpp")
        self.assertEqual(info.details["model_id"], "ggml-base.bin")
        self.assertTrue(info.details["model_path"].endswith("ggml-base.bin"))

    def test_vosk_without_model_reports_model_missing(self) -> None:
        with self._patch_binaries({"vosk-transcriber": "/fake/vosk-t"}):
            env = VoiceEnvironment()
            info = env.detect_stt()
        self.assertEqual(info.name, "vosk")
        self.assertEqual(info.status, VoiceEngineStatus.UNAVAILABLE)
        self.assertIn("LOCAL_STT_MODEL_MISSING", info.reason)

    def test_vosk_with_model_available(self) -> None:
        vosk_dir = os.path.join(self.dir, "vosk-model-small")
        os.makedirs(os.path.join(vosk_dir, "am"))
        Path(os.path.join(vosk_dir, "am", "final.mdl")).touch()
        with self._patch_binaries({"vosk-transcriber": "/fake/vosk-t"}):
            env = VoiceEnvironment()
            info = env.detect_stt()
        self.assertEqual(info.status, VoiceEngineStatus.AVAILABLE)
        self.assertEqual(info.name, "vosk")
        self.assertEqual(info.details["model_id"], "vosk-model-small")

    def test_no_engine_reports_honest_unavailable(self) -> None:
        with self._patch_binaries({}):
            env = VoiceEnvironment()
            info = env.detect_stt()
        self.assertEqual(info.status, VoiceEngineStatus.UNAVAILABLE)
        self.assertEqual(info.name, "offline_stt")
        self.assertIn("no offline STT engine found", info.reason)


class TestOfflineSttTranscription(unittest.TestCase):
    """Real engine invocation (subprocess mocked): success, failure, language."""

    def _provider(self, name: str, binary: str,
                  details: dict | None = None) -> SpeechToTextProvider:
        env = VoiceEnvironment(models_dir=_tmp())
        env._stt_cache = VoiceEngineInfo(
            "STT", name, VoiceEngineStatus.AVAILABLE,
            reason="test fixture", engine_binary=binary,
            details=details or {})
        return SpeechToTextProvider(voice_env=env)

    def _frames(self, n_bytes: int = 3200) -> list:
        return [AudioFrame(rms=0.5, timestamp=0.0,
                           samples=b"\x00\x00" * (n_bytes // 2))]

    def test_whisper_cpp_real_invocation_success(self) -> None:
        provider = self._provider(
            "whisper.cpp", "/fake/whisper-cli",
            {"model_path": "/fake/models/ggml-base.bin"})
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["whisper-cli"], 0, stdout="hello zerion\n", stderr="")
            res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["transcript"], "hello zerion")
        self.assertEqual(res["provider"], "whisper.cpp")
        self.assertEqual(res["language"], "auto")
        args = run.call_args.args[0]
        self.assertEqual(args[0], "/fake/whisper-cli")
        self.assertIn("-m", args)
        self.assertEqual(args[args.index("-m") + 1],
                         "/fake/models/ggml-base.bin")
        self.assertIn("-f", args)
        self.assertIn("-nt", args)
        # A real WAV was written and cleaned up afterwards.
        wav = args[args.index("-f") + 1]
        self.assertTrue(wav.endswith(".wav"))
        self.assertFalse(os.path.exists(wav))

    def test_stt_language_observable_in_command(self) -> None:
        provider = self._provider(
            "whisper.cpp", "/fake/whisper-cli",
            {"model_path": "/fake/models/ggml-base.bin"})
        with mock.patch.dict(os.environ, {"STT_LANGUAGE": "ar"}):
            with mock.patch("subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    ["whisper-cli"], 0, stdout="مرحبا", stderr="")
                res = provider.transcribe(self._frames())
        args = run.call_args.args[0]
        self.assertIn("-l", args)
        self.assertEqual(args[args.index("-l") + 1], "ar")
        self.assertEqual(res["language"], "ar")

    def test_whisper_failure_is_explicit(self) -> None:
        provider = self._provider(
            "whisper.cpp", "/fake/whisper-cli",
            {"model_path": "/fake/models/ggml-base.bin"})
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["whisper-cli"], 1, stdout="", stderr="model load failed")
            res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "STT_ERROR")
        self.assertEqual(res["transcript"], "")
        self.assertIn("exited 1", res["reason"])
        self.assertIn("model load failed", res["reason"])

    def test_whisper_empty_output_is_error(self) -> None:
        provider = self._provider(
            "whisper.cpp", "/fake/whisper-cli",
            {"model_path": "/fake/models/ggml-base.bin"})
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["whisper-cli"], 0, stdout="", stderr="")
            res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "STT_ERROR")
        self.assertIn("empty output", res["reason"])

    def test_whisper_timeout_is_error(self) -> None:
        provider = self._provider(
            "whisper.cpp", "/fake/whisper-cli",
            {"model_path": "/fake/models/ggml-base.bin"})
        with mock.patch("subprocess.run",
                        side_effect=subprocess.TimeoutExpired("whisper-cli", 30)):
            res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "STT_ERROR")
        self.assertIn("timed out", res["reason"])

    def test_vosk_cli_json_transcript(self) -> None:
        provider = self._provider(
            "vosk", "/fake/vosk-transcriber",
            {"model_path": "/fake/models/vosk-model-small"})
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["vosk-transcriber"], 0,
                stdout='{"text": "open telegram"}\n', stderr="")
            res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["transcript"], "open telegram")
        self.assertEqual(res["provider"], "vosk")
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("-m") + 1],
                         "/fake/models/vosk-model-small")

    def test_termux_stt_json_transcript(self) -> None:
        provider = self._provider(
            "termux-speech-to-text", "/fake/termux-speech-to-text")
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["termux-speech-to-text"], 0,
                stdout='{"code": 0, "text": "zerion"}\n', stderr="")
            res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["transcript"], "zerion")
        # No WAV file is fed to termux — it records from the device mic.
        self.assertEqual(run.call_args.args[0], ["/fake/termux-speech-to-text"])

    def test_termux_failure_is_explicit(self) -> None:
        provider = self._provider(
            "termux-speech-to-text", "/fake/termux-speech-to-text")
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["termux-speech-to-text"], 3, stdout="", stderr="permission denied")
            res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "STT_ERROR")
        self.assertEqual(res["transcript"], "")
        self.assertIn("permission denied", res["reason"])

    def test_empty_segment_rejected_no_audio(self) -> None:
        provider = self._provider(
            "whisper.cpp", "/fake/whisper-cli",
            {"model_path": "/fake/models/ggml-base.bin"})
        res = provider.transcribe([])
        self.assertEqual(res["status"], "STT_UNAVAILABLE")
        self.assertEqual(res["transcript"], "")
        self.assertIn("no raw PCM samples", res["reason"])

    def test_no_engine_never_fabricates(self) -> None:
        env = VoiceEnvironment(models_dir=_tmp())
        env._stt_cache = VoiceEngineInfo(
            "STT", "offline_stt", VoiceEngineStatus.UNAVAILABLE,
            reason="no offline STT engine found (test env)")
        provider = SpeechToTextProvider(voice_env=env)
        res = provider.transcribe(self._frames())
        self.assertEqual(res["status"], "STT_UNAVAILABLE")
        self.assertEqual(res["transcript"], "")
        self.assertEqual(res["provider"], "NO_PROVIDER")
        self.assertIn("no offline STT engine", res["reason"])


class TestSttParsingAndWavHeader(unittest.TestCase):
    """Transcript parsers and the WAV container fed to file-based engines."""

    def test_termux_json_multi_line_with_noise(self) -> None:
        raw = '{"code": 0, "text": "zerion"}\nnot json\n{"code": 0, "text": "open telegram"}\n'
        self.assertEqual(_parse_termux_stt_json(raw), "zerion open telegram")

    def test_termux_json_empty_is_empty(self) -> None:
        self.assertEqual(_parse_termux_stt_json(""), "")
        self.assertEqual(_parse_termux_stt_json('{"code": 1, "text": ""}\n'), "")

    def test_vosk_json_parsing(self) -> None:
        raw = '{"text": "hello"}\n{"text": "world"}\nnoise\n'
        self.assertEqual(_parse_engine_transcript("vosk", raw), "hello world")

    def test_whisper_plain_text_parsing(self) -> None:
        self.assertEqual(_parse_engine_transcript("whisper.cpp", "  zerion ready \n"),
                         "zerion ready")
        self.assertEqual(_parse_engine_transcript("whisper.cpp", ""), "")

    def test_wav_header_valid_riff(self) -> None:
        import struct
        pcm = b"\x00\x00" * 800
        header = wav_header(len(pcm))
        # The header is the fixed 44-byte RIFF container; the caller writes
        # the raw PCM data after it.
        self.assertEqual(len(header), 44)
        self.assertEqual(header[:4], b"RIFF")
        self.assertEqual(header[8:12], b"WAVE")
        self.assertEqual(header[12:16], b"fmt ")
        self.assertEqual(struct.unpack("<I", header[4:8])[0], 36 + len(pcm))


if __name__ == "__main__":
    unittest.main()
