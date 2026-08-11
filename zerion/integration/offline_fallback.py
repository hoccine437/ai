"""
Offline Degradation and Pure-Local Fallback Manager
"""

from typing import Any, Dict, List, Optional
from zerion.cognition.model_fabric import ModelFabric


class OfflineFallbackManager:
    def __init__(self, model_fabric: ModelFabric):
        self.fabric = model_fabric
        self._offline_mode = False

    @property
    def is_offline(self) -> bool:
        return self._offline_mode

    def set_offline_mode(self, offline: bool):
        self._offline_mode = offline
        # Mark cloud models unavailable if offline
        for mid, desc in self.fabric._registry.items():
            if desc.tier.startswith("cloud"):
                desc.is_available = not offline

    async def execute_task_locally(self, task_prompt: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes cognitive task strictly on local deterministic / heuristic engines without external network calls.
        """
        best_model = self.fabric.select_best_model(task_type="reasoning", require_local=True)
        return await self.fabric.invoke(best_model, task_prompt, context or {})
