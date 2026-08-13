"""
Slice 10 — LocalModelRegistry.

A single user-facing facade over the real Slice 6 machinery
(``LocalModelDiscovery`` + ``ModelLoadManager``):

    DISCOVER -> REGISTER -> SELECT -> LOAD -> USE -> UNLOAD

- Recursive discovery of every ``.gguf`` under the models directory (never a
  hard-coded filename).
- Metadata is only reported when actually detectable; everything else is
  UNKNOWN (architecture, quantization, context, capabilities). No capability
  is ever invented from a filename.
- Selection is deterministic and resource-aware: capability match first, then
  RAM budget (a model that does not fit is a structured RESOURCE_INSUFFICIENT
  failure — never a crash), never "the largest is best".
- Loading is resource-aware; ``unload`` releases reserved bytes.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from zerion.cognitive_os.gguf_discovery import (
    LocalModelDiscovery,
    ModelLoadManager,
)
from zerion.cognitive_os.provider_interface import TEXT
from zerion.cognitive_os.router_types import ProviderStatus


class LocalModelRegistry:
    def __init__(self, models_dir: str = "models",
                 discovery: Optional[LocalModelDiscovery] = None,
                 load_manager: Optional[ModelLoadManager] = None,
                 available_ram_mb: Optional[float] = None):
        self.models_dir = Path(models_dir)
        self.discovery = discovery or LocalModelDiscovery(models_dir=models_dir)
        self.load_manager = load_manager or ModelLoadManager(self.discovery)
        self.available_ram_mb = available_ram_mb
        self._selection_reason: List[str] = []

    # -- discovery / registration ------------------------------------------

    def discover(self) -> List[Dict[str, Any]]:
        infos = self.discovery.discover()
        return [self._describe(m) for m in infos]

    def _describe(self, info) -> Dict[str, Any]:
        """Honest per-model record. Undetectable fields are UNKNOWN."""
        loaded = info.model_id in self.load_manager.loaded()
        size = info.size_bytes
        return {
            "model_id": info.model_id,
            "path": info.path,
            "filename": (info.details or {}).get("filename")
                        or os.path.basename(info.path or ""),
            "size_bytes": size,
            "size_mb": round(size / (1024 * 1024), 2) if size else None,
            "format": info.format or "gguf",
            "architecture": "UNKNOWN",       # not detectable without reading headers
            "quantization": "UNKNOWN",       # not detectable from filename
            "context_window": info.context_window,  # None == UNKNOWN
            "capabilities": sorted(info.capabilities) if info.capabilities else [],
            "availability": info.status.value,
            "status_reason": info.status_reason,
            "load_status": "LOADED" if loaded else "UNLOADED",
            "resident_bytes": self.load_manager.loaded().get(info.model_id, 0),
        }

    def list_models(self) -> List[Dict[str, Any]]:
        return [self._describe(m) for m in self.discovery.models().values()]

    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        info = self.discovery.get(model_id)
        return self._describe(info) if info is not None else None

    def any_available(self) -> bool:
        return self.discovery.any_available()

    # -- selection ---------------------------------------------------------

    def select(self, task_type: str = "REASONING",
               required_capabilities: Optional[Set[str]] = None,
               max_ram_mb: Optional[float] = None) -> Optional[str]:
        """Deterministic, resource-aware selection.

        Criteria (in order): availability -> capability coverage -> fits in
        RAM -> smaller resident footprint preferred when RAM is tight ->
        larger context preferred when RAM allows. Not "largest is best".
        """
        required = required_capabilities or {TEXT}
        ram_budget = max_ram_mb or self.available_ram_mb
        self._selection_reason = []
        candidates = []
        for m in self.discovery.models().values():
            if m.status != ProviderStatus.AVAILABLE:
                continue
            caps = m.capabilities or {TEXT}
            if required and not (caps & required):
                continue
            size_mb = (m.size_bytes or 0) / (1024 * 1024)
            if ram_budget is not None and size_mb > ram_budget:
                self._selection_reason.append(
                    f"{m.model_id}: {size_mb:.0f}MB exceeds RAM budget "
                    f"{ram_budget:.0f}MB (RESOURCE_INSUFFICIENT)")
                continue
            candidates.append((m, size_mb))
        if not candidates:
            return None
        # Score: fit margin matters most under a tight budget; otherwise
        # prefer larger context (more capable) within budget.
        def key(item):
            m, size_mb = item
            ctx = m.context_window or 0
            if ram_budget is not None:
                fit = 1.0 - (size_mb / max(1.0, ram_budget))
                return (round(fit, 6), ctx, m.model_id)
            return (ctx, -size_mb, m.model_id)
        candidates.sort(key=key, reverse=True)
        chosen = candidates[0][0]
        self._selection_reason.append(
            f"selected {chosen.model_id} for {task_type}")
        return chosen.model_id

    def selection_reason(self) -> List[str]:
        return list(self._selection_reason)

    # -- load / unload -----------------------------------------------------

    def load(self, model_id: str, max_ram_mb: Optional[float] = None) -> Dict[str, Any]:
        """Resource-aware load. Returns a structured result, never crashes on
        insufficient RAM."""
        info = self.discovery.get(model_id)
        if info is None:
            return {"status": "NOT_FOUND", "model_id": model_id}
        if info.status != ProviderStatus.AVAILABLE:
            return {"status": "UNAVAILABLE", "model_id": model_id,
                    "reason": info.status_reason}
        ram_budget = max_ram_mb or self.available_ram_mb
        if ram_budget is not None and info.size_bytes:
            size_mb = info.size_bytes / (1024 * 1024)
            if size_mb > ram_budget:
                return {"status": "RESOURCE_INSUFFICIENT", "model_id": model_id,
                        "required_mb": round(size_mb, 2),
                        "available_mb": round(ram_budget, 2),
                        "reason": f"model needs {size_mb:.0f}MB, only "
                                  f"{ram_budget:.0f}MB available"}
        loaded = self.load_manager.load(model_id)
        if loaded is None:
            return {"status": "RESOURCE_INSUFFICIENT", "model_id": model_id,
                    "reason": "slot or byte budget exceeded",
                    "loaded_models": len(self.load_manager.loaded()),
                    "resident_bytes": self.load_manager.resident_bytes()}
        return {"status": "LOADED", "model_id": model_id,
                "resident_bytes": self.load_manager.resident_bytes(),
                "model": self._describe(loaded)}

    def unload(self, model_id: str) -> bool:
        return self.load_manager.unload(model_id)

    def loaded(self) -> Dict[str, int]:
        return self.load_manager.loaded()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "models_dir": str(self.models_dir),
            "count": len(self.discovery.models()),
            "available": len(self.discovery.available()),
            "loaded": len(self.load_manager.loaded()),
            "resident_bytes": self.load_manager.resident_bytes(),
            "models": self.list_models(),
        }
