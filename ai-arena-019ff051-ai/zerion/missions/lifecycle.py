"""
Mission Lifecycle Manager with Crash Resilience & Replay
"""

import asyncio
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional
from zerion.missions.mission import Mission, MissionStep, MissionStatus, MissionCheckpoint


class MissionLifecycleManager:
    def __init__(self, db_path: Optional[str] = "data/missions.db"):
        self.db_path = db_path
        self._missions: Dict[str, Mission] = {}
        self._step_handlers: Dict[str, Callable[[MissionStep, Dict[str, Any]], Coroutine[Any, Any, Any]]] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    data_json TEXT,
                    status TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def register_step_handler(self, action_type: str, handler: Callable):
        self._step_handlers[action_type] = handler

    def create_mission(self, goal: str, objective_id: Optional[str] = None) -> Mission:
        mission = Mission(goal=goal, objective_id=objective_id)
        self._missions[mission.id] = mission
        self._persist_mission(mission)
        return mission

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        return self._missions.get(mission_id)

    def list_missions(self) -> List[Mission]:
        return list(self._missions.values())

    async def execute_mission(self, mission_id: str) -> bool:
        mission = self._missions.get(mission_id)
        if not mission:
            return False

        mission.status = MissionStatus.RUNNING
        self._persist_mission(mission)

        accumulated_state: Dict[str, Any] = {}

        # Restore from last checkpoint if exists
        if mission.checkpoints:
            last_chk = mission.checkpoints[-1]
            accumulated_state = dict(last_chk.state_snapshot)

        for step_id, step in list(mission.steps.items()):
            if step.status == "COMPLETED":
                accumulated_state[step_id] = step.result_data
                continue

            # Check dependencies
            deps_ok = all(
                mission.steps.get(d) and mission.steps[d].status == "COMPLETED"
                for d in step.dependencies
            )
            if not deps_ok:
                continue

            step.status = "RUNNING"
            step.started_at = time.time()

            handler = self._step_handlers.get(step.action_type, self._default_step_handler)
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(step, accumulated_state)
                else:
                    result = handler(step, accumulated_state)

                step.status = "COMPLETED"
                step.result_data = result
                step.completed_at = time.time()
                accumulated_state[step_id] = result

                # Create checkpoint
                completed_ids = [s.step_id for s in mission.steps.values() if s.status == "COMPLETED"]
                checkpoint = MissionCheckpoint(
                    mission_id=mission.id,
                    completed_step_ids=completed_ids,
                    state_snapshot=accumulated_state
                )
                mission.checkpoints.append(checkpoint)
                mission.updated_at = time.time()
                self._persist_mission(mission)

            except Exception as e:
                step.status = "FAILED"
                step.error_message = str(e)
                mission.failures.append({
                    "step_id": step_id,
                    "error": str(e),
                    "timestamp": time.time()
                })
                mission.status = MissionStatus.FAILED
                self._persist_mission(mission)
                return False

        all_completed = all(s.status == "COMPLETED" for s in mission.steps.values())
        mission.status = MissionStatus.COMPLETED if all_completed else MissionStatus.PAUSED
        mission.updated_at = time.time()
        self._persist_mission(mission)
        return all_completed

    async def _default_step_handler(self, step: MissionStep, state: Dict[str, Any]) -> Any:
        await asyncio.sleep(0.01)
        return {"step": step.name, "status": "executed", "params": step.parameters}

    def _persist_mission(self, mission: Mission):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO missions VALUES (?, ?, ?, ?)",
            (mission.id, json.dumps(mission.to_dict()), mission.status.value, mission.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT data_json FROM missions")
            for row in cursor.fetchall():
                mis = Mission.from_dict(json.loads(row[0]))
                self._missions[mis.id] = mis
            conn.close()
        except Exception:
            pass
