"""
Intention & Goal Formulator for Cognitive OS
Translates high-priority attention targets into actionable computational intentions.
"""

import time
from typing import Any, Dict, List, Optional
from zerion.cognitive_os.attention import AttentionItem, IntentionTarget


class IntentionManager:
    def __init__(self):
        self._active_intentions: List[IntentionTarget] = []
        self._completed_intentions: List[IntentionTarget] = []

    def formulate_intention(
        self,
        attention_item: AttentionItem,
        target_objective_id: Optional[str] = None
    ) -> IntentionTarget:
        intention = IntentionTarget(
            goal_statement=f"Resolve topic: {attention_item.topic}",
            target_objective_id=target_objective_id,
            attention_item=attention_item,
            expected_outcome=f"Reduced uncertainty and resolved state for {attention_item.topic}",
            commitment_level=max(0.5, min(1.0, attention_item.importance * 1.2))
        )
        self._active_intentions.append(intention)
        return intention

    def complete_intention(self, intention_id: str):
        for i, intent in enumerate(self._active_intentions):
            if intent.intention_id == intention_id:
                self._completed_intentions.append(self._active_intentions.pop(i))
                break

    def get_current_intention(self) -> Optional[IntentionTarget]:
        return self._active_intentions[0] if self._active_intentions else None
