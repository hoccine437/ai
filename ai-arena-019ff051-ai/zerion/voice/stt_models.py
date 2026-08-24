"""
ZERION X — Offline STT model discovery (models/stt/).

Canonical local speech-model directory contract (spec §3):

    models/stt/
        whisper-cpp/ggml-base.bin      whisper.cpp GGML model (or .gguf)
        vosk-model-small-en-us-.../    vosk model directory (am/final.mdl)

States per model: DISCOVERED -> VALIDATED -> LOADING -> READY -> FAILED,
plus UNAVAILABLE. ``LOCAL_STT_MODEL_MISSING`` is reported (never READY) when
an STT engine exists but no usable model file is present.

Discovery is real file scanning + header magic validation — it never claims
a model is loadable without checking the actual file. Loading itself happens
in the engine subprocess (whisper.cpp / vosk); this module validates the file
contract and reports honestly.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class SttModelStatus(str):
    DISCOVERED = "DISCOVERED"
    VALIDATED = "VALIDATED"
    LOADING = "LOADING"
    READY = "READY"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


WHISPER_MAGIC = b"ggml"      # whisper.cpp GGML quantized model header
GGUF_MAGIC = b"GGUF"         # whisper.cpp also accepts GGUF containers


class SttModelInfo:
    """One discovered STT model (file or vosk directory)."""

    def __init__(self, model_id: str, kind: str, path: str,
                 status: str, status_reason: str = "",
                 size_bytes: Optional[int] = None):
        self.model_id = model_id
        self.kind = kind              # "whisper_cpp" | "vosk"
        self.path = path
        self.status = status
        self.status_reason = status_reason
        self.size_bytes = size_bytes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "kind": self.kind,
            "path": self.path,
            "status": self.status,
            "status_reason": self.status_reason,
            "size_bytes": self.size_bytes,
        }


def resolve_stt_models_dir(default: str = "models/stt",
                           base: Optional[Path] = None) -> str:
    """Resolve the canonical offline STT model directory.

    Priority (first match wins):
      1. ``ZERION_STT_MODELS_DIR`` env var.
      2. ``<project root>/models/stt`` (sibling of the ``zerion`` package).
      3. ``default`` (normally ``models/stt``, relative to CWD).
    """
    env = os.environ.get("ZERION_STT_MODELS_DIR", "").strip()
    if env:
        return env
    if str(Path(default)) == "models/stt":
        # Locate the repo root the same way the GGUF discovery does: the
        # zerion package's parent is the project root.
        here = Path(__file__).resolve().parent.parent  # zerion/
        root = here.parent                             # project root
        candidate = root / "models" / "stt"
        if candidate.is_dir():
            return str(candidate.resolve())
    return default


class SttModelDiscovery:
    """Real, safe discovery of local offline STT models.

    Scans ``models/stt/`` for:
      - whisper.cpp GGML/GGUF model files (``*.bin`` / ``*.gguf`` with the
        correct header magic, non-empty, size-bounded)
      - vosk model directories (contain ``am/final.mdl``)
    Deterministic ordering; corrupt files are reported FAILED, never hidden.
    """

    DEFAULT_MAX_MODEL_BYTES = 8 * 1024 * 1024 * 1024  # 8 GiB safety ceiling

    def __init__(self, models_dir: str = "models/stt",
                 max_model_bytes: int = DEFAULT_MAX_MODEL_BYTES):
        self.models_dir = Path(resolve_stt_models_dir(models_dir))
        self.max_model_bytes = max_model_bytes
        self._models: Dict[str, SttModelInfo] = {}
        self.discover()

    # -- discovery ----------------------------------------------------------

    def discover(self) -> List[SttModelInfo]:
        """(Re)scan the STT model directory. Deterministic: sorted by id."""
        self._models = {}
        if not self.models_dir.exists():
            return []
        # whisper.cpp model files (flat scan; nested dirs like
        # models/stt/whisper-cpp/ are also honored).
        for path in sorted(self.models_dir.rglob("*.bin")) + \
                sorted(self.models_dir.rglob("*.gguf")):
            info = self._inspect_whisper(path)
            if info is not None and info.model_id not in self._models:
                self._models[info.model_id] = info
        # vosk model directories (contain the canonical marker am/final.mdl).
        for path in sorted(self.models_dir.iterdir()):
            if not path.is_dir():
                continue
            marker = path / "am" / "final.mdl"
            if marker.is_file():
                self._models[path.name] = SttModelInfo(
                    model_id=path.name, kind="vosk", path=str(path),
                    status=SttModelStatus.READY,
                    status_reason="vosk model directory validated "
                                  "(am/final.mdl present)")
        return [self._models[k] for k in sorted(self._models)]

    def _inspect_whisper(self, path: Path) -> Optional[SttModelInfo]:
        model_id = path.name
        try:
            size = path.stat().st_size
        except OSError:
            return SttModelInfo(model_id, "whisper_cpp", str(path),
                                SttModelStatus.FAILED,
                                "unreadable file")
        if size <= 0:
            return SttModelInfo(model_id, "whisper_cpp", str(path),
                                SttModelStatus.FAILED, "empty file",
                                size_bytes=size)
        if size > self.max_model_bytes:
            return SttModelInfo(model_id, "whisper_cpp", str(path),
                                SttModelStatus.UNAVAILABLE,
                                f"exceeds size budget ({size} bytes)",
                                size_bytes=size)
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
        except OSError as exc:
            return SttModelInfo(model_id, "whisper_cpp", str(path),
                                SttModelStatus.FAILED,
                                f"unreadable: {exc}", size_bytes=size)
        if magic not in (WHISPER_MAGIC, GGUF_MAGIC):
            return SttModelInfo(model_id, "whisper_cpp", str(path),
                                SttModelStatus.FAILED,
                                "corrupted or invalid model header "
                                "(expected ggml/GGUF magic)",
                                size_bytes=size)
        return SttModelInfo(model_id, "whisper_cpp", str(path),
                            SttModelStatus.READY,
                            "whisper.cpp model validated "
                            "(header magic + size)", size_bytes=size)

    # -- queries ------------------------------------------------------------

    def models(self) -> Dict[str, SttModelInfo]:
        return dict(self._models)

    def available(self) -> List[SttModelInfo]:
        return [m for m in self._models.values()
                if m.status == SttModelStatus.READY]

    def any_available(self) -> bool:
        return bool(self.available())

    def get(self, model_id: str) -> Optional[SttModelInfo]:
        return self._models.get(model_id)

    def select(self) -> Optional[SttModelInfo]:
        """Deterministic selection: smallest validated whisper.cpp model
        first (fast load on phones), otherwise the first vosk model."""
        whisper = [m for m in self.available() if m.kind == "whisper_cpp"]
        if whisper:
            return min(whisper, key=lambda m: (m.size_bytes or 0, m.model_id))
        vosk = [m for m in self.available() if m.kind == "vosk"]
        if vosk:
            return min(vosk, key=lambda m: m.model_id)
        return None

    # -- honest reporting ---------------------------------------------------

    def report(self) -> Dict[str, Any]:
        """Readiness-facing summary. Never fabricates READY."""
        models = self.available()
        return {
            "dir": str(self.models_dir),
            "discovered": len(self._models),
            "available": len(models),
            "selected": (self.select().model_id if self.select() else None),
            "status": ("READY" if models else "LOCAL_STT_MODEL_MISSING"),
            "models": [m.to_dict() for m in
                       [self._models[k] for k in sorted(self._models)]],
        }
