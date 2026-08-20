"""
Cognitive Program Execution DAG Engine
"""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid
from zerion.cognition.cells import CognitiveCell, CellInput, CellOutput, CellType


@dataclass
class ProgramStep:
    id: str
    cell: CognitiveCell
    dependencies: List[str] = field(default_factory=list)
    output: Optional[CellOutput] = None
    executed: bool = False


class CognitiveProgram:
    def __init__(self, name: str, goal: str):
        self.program_id = f"prog_{uuid.uuid4().hex[:8]}"
        self.name = name
        self.goal = goal
        self.steps: Dict[str, ProgramStep] = {}
        self.execution_log: List[Dict[str, Any]] = []
        self.completed = False
        self.total_duration_ms = 0.0

    def add_step(self, cell: CognitiveCell, dependencies: Optional[List[str]] = None, step_id: Optional[str] = None) -> str:
        s_id = step_id or f"step_{len(self.steps)}_{cell.cell_type.value.lower()}"
        self.steps[s_id] = ProgramStep(
            id=s_id,
            cell=cell,
            dependencies=dependencies or []
        )
        return s_id

    async def execute(self, initial_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        start_time = time.perf_counter()
        context = dict(initial_context or {})
        last_output_data = None

        for step_id, step in self.steps.items():
            # Gather inputs from dependencies
            dep_outputs = {}
            for dep_id in step.dependencies:
                dep_step = self.steps.get(dep_id)
                if dep_step and dep_step.output:
                    dep_outputs[dep_id] = dep_step.output.data

            cell_input = CellInput(
                goal=self.goal,
                context={**context, "dep_outputs": dep_outputs},
                data=last_output_data
            )

            cell_output = await step.cell.execute(cell_input)
            step.output = cell_output
            step.executed = True
            last_output_data = cell_output.data

            self.execution_log.append({
                "step_id": step_id,
                "cell_type": step.cell.cell_type.value,
                "success": cell_output.success,
                "latency_ms": cell_output.latency_ms,
                "confidence": cell_output.confidence,
                "data_preview": str(cell_output.data)[:100]
            })

            if not cell_output.success:
                # Halt program on critical failure
                break

        self.total_duration_ms = (time.perf_counter() - start_time) * 1000.0
        self.completed = all(s.executed and s.output and s.output.success for s in self.steps.values())

        return {
            "program_id": self.program_id,
            "goal": self.goal,
            "completed": self.completed,
            "final_data": last_output_data,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "step_count": len(self.steps),
            "execution_log": self.execution_log
        }
