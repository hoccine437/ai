"""
Mission & Task Scheduler for ASCENDANT
"""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional


@dataclass(order=True)
class ScheduledTask:
    run_at: float
    task_id: str = field(compare=False)
    name: str = field(compare=False)
    coroutine_fn: Callable[[], Coroutine[Any, Any, None]] = field(compare=False)
    interval: Optional[float] = field(default=None, compare=False)
    recurring: bool = field(default=False, compare=False)


class MissionScheduler:
    def __init__(self):
        self._tasks: List[ScheduledTask] = []
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def schedule_once(self, name: str, delay_seconds: float, coroutine_fn: Callable[[], Coroutine[Any, Any, None]]) -> str:
        task_id = f"task_{time.time()}_{name}"
        async with self._lock:
            task = ScheduledTask(
                run_at=time.time() + delay_seconds,
                task_id=task_id,
                name=name,
                coroutine_fn=coroutine_fn,
                recurring=False
            )
            self._tasks.append(task)
            self._tasks.sort(key=lambda t: t.run_at)
        return task_id

    async def schedule_recurring(self, name: str, interval_seconds: float, coroutine_fn: Callable[[], Coroutine[Any, Any, None]]) -> str:
        task_id = f"rec_{time.time()}_{name}"
        async with self._lock:
            task = ScheduledTask(
                run_at=time.time() + interval_seconds,
                task_id=task_id,
                name=name,
                coroutine_fn=coroutine_fn,
                interval=interval_seconds,
                recurring=True
            )
            self._tasks.append(task)
            self._tasks.sort(key=lambda t: t.run_at)
        return task_id

    async def cancel(self, task_id: str) -> bool:
        async with self._lock:
            before_len = len(self._tasks)
            self._tasks = [t for t in self._tasks if t.task_id != task_id]
            return len(self._tasks) < before_len

    async def start(self):
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        while self._running:
            try:
                now = time.time()
                to_run: List[ScheduledTask] = []
                async with self._lock:
                    while self._tasks and self._tasks[0].run_at <= now:
                        t = self._tasks.pop(0)
                        to_run.append(t)
                        if t.recurring and t.interval:
                            t.run_at = now + t.interval
                            self._tasks.append(t)
                    self._tasks.sort(key=lambda t: t.run_at)

                for task in to_run:
                    asyncio.create_task(self._safe_execute(task))

                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)

    async def _safe_execute(self, task: ScheduledTask):
        try:
            await task.coroutine_fn()
        except Exception:
            pass
