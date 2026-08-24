"""
Watchdog and Liveness Monitor for ASCENDANT
"""

import asyncio
import time
from typing import Callable, Coroutine, Dict, Optional, Any


class Watchdog:
    def __init__(self, check_interval_seconds: float = 2.0, timeout_seconds: float = 10.0):
        self.check_interval = check_interval_seconds
        self.timeout = timeout_seconds
        self._heartbeats: Dict[str, float] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._recovery_callbacks: Dict[str, Callable[[str], Coroutine[Any, Any, None]]] = {}

    def heartbeat(self, component_name: str):
        self._heartbeats[component_name] = time.time()

    def register_component(self, name: str, recovery_cb: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None):
        self._heartbeats[name] = time.time()
        if recovery_cb:
            self._recovery_callbacks[name] = recovery_cb

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        while self._running:
            try:
                now = time.time()
                for name, last_time in list(self._heartbeats.items()):
                    if now - last_time > self.timeout:
                        # Component stalled
                        if name in self._recovery_callbacks:
                            try:
                                await self._recovery_callbacks[name](name)
                            except Exception:
                                pass
                        self._heartbeats[name] = now  # Reset after recovery attempt
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(self.check_interval)
