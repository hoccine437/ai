"""
Self-Curriculum Engine - Autonomous Mastery Pathways
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid
from zerion.capabilities.detector import CapabilityGap


@dataclass
class CurriculumStep:
    step_id: str
    step_type: str  # "prerequisite", "question", "experiment", "practice", "evaluation"
    description: str
    is_completed: bool = False
    evaluation_score: float = 0.0


@dataclass
class CurriculumTrack:
    id: str = field(default_factory=lambda: f"cur_{uuid.uuid4().hex[:8]}")
    target_weakness: str = ""
    domain: str = "general"
    steps: List[CurriculumStep] = field(default_factory=list)
    mastery_threshold: float = 0.85
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1.0 for s in self.steps if s.is_completed)
        return round(completed / len(self.steps), 3)

    @property
    def is_mastered(self) -> bool:
        if not self.steps:
            return False
        eval_steps = [s for s in self.steps if s.step_type == "evaluation"]
        if not eval_steps:
            return all(s.is_completed for s in self.steps)
        return all(s.is_completed and s.evaluation_score >= self.mastery_threshold for s in eval_steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "target_weakness": self.target_weakness,
            "domain": self.domain,
            "steps": [
                {
                    "step_id": s.step_id,
                    "step_type": s.step_type,
                    "description": s.description,
                    "is_completed": s.is_completed,
                    "evaluation_score": s.evaluation_score
                }
                for s in self.steps
            ],
            "progress": self.progress,
            "is_mastered": self.is_mastered,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class SelfCurriculumGenerator:
    def __init__(self):
        pass

    def build_curriculum_for_gap(self, gap: CapabilityGap, domain: str = "system") -> CurriculumTrack:
        """
        Weakness -> Prerequisites -> Questions -> Experiments -> Practice -> Evaluation -> Mastery
        """
        track = CurriculumTrack(
            target_weakness=gap.task_goal,
            domain=domain
        )

        steps = [
            CurriculumStep(
                step_id="step_1_prereq",
                step_type="prerequisite",
                description=f"Map prerequisite concepts for resolving: {gap.task_goal}"
            ),
            CurriculumStep(
                step_id="step_2_question",
                step_type="question",
                description=f"Formulate falsification and diagnostic questions for {gap.gap_type.value}"
            ),
            CurriculumStep(
                step_id="step_3_experiment",
                step_type="experiment",
                description="Design and run sandbox experiments to validate hypothesis"
            ),
            CurriculumStep(
                step_id="step_4_practice",
                step_type="practice",
                description="Execute 3 simulated problem variations to reinforce strategy"
            ),
            CurriculumStep(
                step_id="step_5_eval",
                step_type="evaluation",
                description="Run formal benchmark evaluation against baseline"
            ),
        ]
        track.steps = steps
        return track
