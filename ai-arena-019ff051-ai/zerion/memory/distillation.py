"""
Experience Distillation Engine - From Episodic Traces to Procedural Rules
"""

from collections import defaultdict
from typing import Dict, List, Optional
from zerion.memory.episodic import Episode
from zerion.memory.procedural import ProceduralRule


class ExperienceDistiller:
    def __init__(self, min_pattern_support: int = 2):
        self.min_pattern_support = min_pattern_support

    def distill_episodes(self, episodes: List[Episode]) -> List[ProceduralRule]:
        """
        Analyzes past successful episodes, discovers recurring sequences of actions
        associated with high rewards (>= 0.7), and synthesizes validated ProceduralRules.
        """
        successful_episodes = [ep for ep in episodes if ep.outcome_status == "SUCCESS" and ep.reward >= 0.7]
        if not successful_episodes:
            return []

        # Group by goal pattern / category
        pattern_groups = defaultdict(list)
        for ep in successful_episodes:
            # Extract simple keyword words
            words = [w for w in ep.goal.lower().replace("_", " ").split() if len(w) > 2]
            goal_key = "_".join(words[:4])
            actions_signature = " -> ".join(ep.actions_taken)
            pattern_groups[(goal_key, actions_signature)].append(ep)

        derived_rules: List[ProceduralRule] = []
        for (goal_key, actions_sig), matched_eps in pattern_groups.items():
            if len(matched_eps) >= self.min_pattern_support:
                rule_name = f"RULE_AUTO_{goal_key.upper()}"
                readable_pattern = goal_key.replace("_", " ")
                rule = ProceduralRule(
                    name=rule_name,
                    trigger_conditions=[
                        f"Goal matches pattern: {readable_pattern}",
                        readable_pattern,
                        "System has standard compute resources"
                    ],
                    action_procedure=actions_sig or "execute_standard_pipeline",
                    success_count=len(matched_eps),
                    attempt_count=len(matched_eps),
                    source_episodes=[ep.id for ep in matched_eps]
                )
                derived_rules.append(rule)

        return derived_rules
