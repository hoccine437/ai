"""
Slice 6 — Local GGUF model discovery.

Discovers ``.gguf`` files under a configured models directory and describes
them (model_id, path, format, size, detectable capabilities/context, status).
Safety rules:
- non-``.gguf`` files are ignored
- files must exist and be readable
- a file without the GGUF magic header is marked CORRUPTED (never accepted)
- duplicate model names are marked DUPLICATE (only the first is usable)
- models above the configured size budget are marked OVERSIZED
- paths that resolve OUTSIDE the models directory (e.g. symlink escapes) are
  rejected before any read
- model files are DATA — they are never executed as code.

Loading is resource-aware (slot + byte budget) via ModelLoadManager. No model
is loaded into RAM unless explicitly loaded, and never all at once.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from zerion.cognitive_os.provider_interface import ModelInfo, TEXT
from zerion.cognitive_os.router_types import ProviderStatus

GGUF_MAGIC = b"GGUF"
DEFAULT_MAX_MODEL_BYTES = 8 * 1024 * 1024 * 1024      # 8 GiB
DEFAULT_MAX_LOADED_BYTES = 4 * 1024 * 1024 * 1024     # 4 GiB resident budget
DEFAULT_MAX_LOADED_MODELS = 1

# Canonical repo location of the local-model folder: ``<project root>/models``
# — a sibling of the ``zerion`` package (e.g. ``ai-arena-019ff051-ai/models``).
RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def resolve_models_dir(default: str = "models",
                       base: Optional[Path] = None) -> str:
    """Resolve the directory local GGUF models are scanned from.

    Priority (first match wins):

      1. ``ZERION_MODELS_DIR`` env var (absolute, or relative to ``base``/CWD).
      2. ``<project root>/models`` — the canonical repo folder (a sibling of
         the ``zerion`` package, e.g. ``ai-arena-019ff051-ai/models``) — when
         the caller is using the runtime's default ``"models"`` and that
         folder exists. ``base`` overrides the detected root (used by tests).
      3. ``default`` (normally ``models``, relative to the CWD).

    Explicit non-default paths pass through untouched (no auto-routing), so
    callers that opt into a specific directory always get exactly that
    directory.
    """
    env = os.environ.get("ZERION_MODELS_DIR", "").strip()
    if env:
        return env
    if str(Path(default)) == "models":
        root = base or RUNTIME_ROOT
        candidate = root / Path(default).name
        if candidate.is_dir():
            return str(candidate.resolve())
    return default


class LocalModelDiscovery:
    """Real, safe discovery of local GGUF models (no inference — describing
    files, never pretending to run them)."""

    def __init__(self, models_dir: str = "models",
                 max_model_bytes: int = DEFAULT_MAX_MODEL_BYTES,
                 strict: bool = True):
        # Resolve to an ABSOLUTE path so every discovered ``ModelInfo.path``
        # is the real filesystem path of the model file (never a relative
        # path reconstructed from a model name) and path-containment checks
        # work regardless of the caller's CWD.
        self.models_dir = Path(models_dir).resolve()
        self.max_model_bytes = max_model_bytes
        self.strict = strict
        self._models: Dict[str, ModelInfo] = {}
        self.discover()

    # -- discovery ----------------------------------------------------------

    def discover(self) -> List[ModelInfo]:
        """(Re)scan the models directory. Deterministic: sorted by model_id."""
        self._models = {}
        if not self.models_dir.exists():
            return []
        base = self.models_dir.resolve()
        seen_names: Set[str] = set()
        # Recursive scan: models may live in subdirectories; identical stems in
        # different directories are real duplicate names that must be handled.
        for path in sorted(self.models_dir.rglob("*.gguf")):
            info = self._inspect(path, base, seen_names)
            if info is not None and info.model_id not in self._models:
                # First occurrence wins deterministically; duplicate names are
                # detected and dropped, never silently overwriting the winner.
                self._models[info.model_id] = info
        # Deterministic ordering for routing and tests.
        return [self._models[k] for k in sorted(self._models)]

    def _inspect(self, path: Path, base: Path, seen_names: Set[str]) -> Optional[ModelInfo]:
        model_id = path.stem
        if model_id in seen_names:
            return ModelInfo(
                model_id=model_id, provider="local_gguf",
                status=ProviderStatus.UNAVAILABLE,
                status_reason="duplicate model name", format="gguf",
                path=str(path), size_bytes=path.stat().st_size if path.exists() else None,
            )
        seen_names.add(model_id)

        try:
            resolved = path.resolve()
        except OSError:
            return ModelInfo(model_id=model_id, provider="local_gguf",
                             status=ProviderStatus.UNAVAILABLE,
                             status_reason="unresolvable path", format="gguf",
                             path=str(path))
        # Path containment: reject anything that escapes the models dir.
        if not self._is_within(resolved, base):
            return ModelInfo(model_id=model_id, provider="local_gguf",
                             status=ProviderStatus.UNAVAILABLE,
                             status_reason="path outside models directory", format="gguf",
                             path=str(path))
        if not resolved.is_file():
            return ModelInfo(model_id=model_id, provider="local_gguf",
                             status=ProviderStatus.UNAVAILABLE,
                             status_reason="not a file", format="gguf",
                             path=str(path))
        size = resolved.stat().st_size
        if size <= 0:
            return ModelInfo(model_id=model_id, provider="local_gguf",
                             status=ProviderStatus.UNAVAILABLE,
                             status_reason="empty file", format="gguf",
                             path=str(path), size_bytes=size)
        if size > self.max_model_bytes:
            return ModelInfo(model_id=model_id, provider="local_gguf",
                             status=ProviderStatus.UNAVAILABLE,
                             status_reason=f"exceeds size budget ({size} bytes)",
                             format="gguf", path=str(path), size_bytes=size)
        # Lightweight integrity probe: GGUF format magic header.
        if not self._has_gguf_magic(resolved):
            return ModelInfo(model_id=model_id, provider="local_gguf",
                             status=ProviderStatus.UNAVAILABLE,
                             status_reason="corrupted or invalid GGUF header",
                             format="gguf", path=str(path), size_bytes=size)
        return ModelInfo(
            model_id=model_id, provider="local_gguf",
            capabilities=self._detect_capabilities(model_id),
            context_window=self._detect_context(model_id),
            size_bytes=size, status=ProviderStatus.AVAILABLE,
            status_reason="valid GGUF file", format="gguf", path=str(path),
            details={"filename": path.name},
        )

    @staticmethod
    def _is_within(resolved: Path, base: Path) -> bool:
        try:
            resolved.relative_to(base)
            return True
        except ValueError:
            return False

    @staticmethod
    def _has_gguf_magic(path: Path) -> bool:
        try:
            with open(path, "rb") as f:
                return f.read(4) == GGUF_MAGIC
        except OSError:
            return False

    @staticmethod
    def _detect_capabilities(model_id: str) -> Set[str]:
        """Only format-guaranteed capabilities: every GGUF text model at least
        produces text. Anything else (e.g. vision) is NOT inferred from the
        filename — that would be claiming capability from a name alone."""
        return {TEXT}

    @staticmethod
    def _detect_context(model_id: str) -> Optional[int]:
        """Context window when it is actually detectable from a naming
        convention (e.g. ``-8k`` / ``-32k``); otherwise unknown, not guessed."""
        low = model_id.lower()
        for token in ("32k", "16k", "8k", "4k", "2k", "1k"):
            if f"-{token}" in low or f"_{token}" in low:
                return int(token[:-1]) * 1024
        return None

    # -- accessors ----------------------------------------------------------

    def models(self) -> Dict[str, ModelInfo]:
        return dict(self._models)

    def available(self) -> List[ModelInfo]:
        return [m for m in self._models.values()
                if m.status == ProviderStatus.AVAILABLE]

    def get(self, model_id: str) -> Optional[ModelInfo]:
        return self._models.get(model_id)

    def any_available(self) -> bool:
        return any(m.status == ProviderStatus.AVAILABLE
                   for m in self._models.values())


class ModelLoadManager:
    """Resource-aware load/unload. Tracks how much is resident; refuses loads
    that would exceed the slot or byte budget. (No actual inference engine is
    wired here — this is the resource bookkeeping the engine hooks into.)"""

    def __init__(self, discovery: LocalModelDiscovery,
                 max_loaded_models: int = DEFAULT_MAX_LOADED_MODELS,
                 max_loaded_bytes: int = DEFAULT_MAX_LOADED_BYTES):
        self.discovery = discovery
        self.max_loaded_models = max_loaded_models
        self.max_loaded_bytes = max_loaded_bytes
        self._loaded: Dict[str, int] = {}  # model_id -> reserved bytes

    def load(self, model_id: str) -> Optional[ModelInfo]:
        info = self.discovery.get(model_id)
        if info is None or info.status != ProviderStatus.AVAILABLE:
            return None
        if model_id in self._loaded:
            return info  # already resident
        if len(self._loaded) >= self.max_loaded_models:
            return None  # slot budget exceeded
        size = info.size_bytes or 0
        if sum(self._loaded.values()) + size > self.max_loaded_bytes:
            return None  # byte budget exceeded
        self._loaded[model_id] = size
        return info

    def unload(self, model_id: str) -> bool:
        return self._loaded.pop(model_id, None) is not None

    def loaded(self) -> Dict[str, int]:
        return dict(self._loaded)

    def resident_bytes(self) -> int:
        return sum(self._loaded.values())
