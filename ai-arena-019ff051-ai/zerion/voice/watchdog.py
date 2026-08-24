"""
VoiceWatchdog — Slice 10.1.

Monitors every component of the always-listening voice pipeline via heartbeats:

    microphone capture / audio capture
    VAD
    wake-word detector
    STT
    TTS
    cognitive voice pipeline

If a component stops beating inside its timeout the watchdog restarts ONLY
that component (through a registered restart handler — which may be async),
verifies it, and the service returns to LISTENING. It never restarts the
ZERION runtime.

Restart frequency is rate-limited per time window so a failing component can
never trigger an infinite restart loop (bounded recovery, per spec 10/18).
"""

import time
from typing import Any, Callable, Dict, List, Optional


class VoiceWatchdog:
    COMPONENTS = ("mic_capture", "audio_capture", "vad", "wake", "stt", "tts",
                  "pipeline")

    def __init__(self, timeout_s: float = 10.0,
                 min_restart_interval_s: float = 5.0,
                 max_restarts_per_window: int = 3,
                 window_s: float = 60.0,
                 now_fn: Optional[Callable[[], float]] = None):
        self.timeout_s = timeout_s
        self.min_restart_interval_s = min_restart_interval_s
        self.max_restarts_per_window = max_restarts_per_window
        self.window_s = window_s
        self._now = now_fn or time.time

        self._last_beat: Dict[str, float] = {}
        self._restart_handlers: Dict[str, Callable[[], Any]] = {}
        self._verify_handlers: Dict[str, Callable[[], bool]] = {}
        self._restart_times: List[float] = []
        self._restart_count: Dict[str, int] = {}
        self._last_restart: Dict[str, float] = {}
        self._status: Dict[str, str] = {}

    # -- registration -------------------------------------------------------

    def register(self, component: str,
                 restart: Optional[Callable[[], Any]] = None,
                 verify: Optional[Callable[[], bool]] = None) -> None:
        if component not in self.COMPONENTS:
            raise ValueError(f"unknown voice component: {component}")
        if restart is not None:
            self._restart_handlers[component] = restart
        if verify is not None:
            self._verify_handlers[component] = verify

    def beat(self, component: str) -> None:
        if component in self.COMPONENTS:
            self._last_beat[component] = self._now()
            self._status[component] = "OK"

    # -- monitoring ---------------------------------------------------------

    def age(self, component: str) -> Optional[float]:
        if component not in self._last_beat:
            return None  # never started -> not "stuck", just unknown
        return max(0.0, self._now() - self._last_beat[component])

    def is_stuck(self, component: str) -> bool:
        age = self.age(component)
        if age is None:
            return False
        return age > self.timeout_s

    def _rate_limited(self) -> bool:
        now = self._now()
        self._restart_times = [t for t in self._restart_times
                               if now - t < self.window_s]
        return len(self._restart_times) >= self.max_restarts_per_window

    async def check(self) -> Dict[str, Any]:
        """Scan registered components; restart stuck ones (bounded, async).

        Returns {checked, stuck, restarted, suppressed, per_component,
                 restart_counts, restarts_in_window}.
        """
        now = self._now()
        checked, stuck, restarted, suppressed = [], [], [], []
        per = {}
        for component in self.COMPONENTS:
            if component not in self._restart_handlers:
                continue
            checked.append(component)
            age = self.age(component)
            per[component] = {"age_s": (round(age, 2) if age is not None
                                        else None),
                              "status": self._status.get(component, "UNKNOWN")}
            if not self.is_stuck(component):
                continue
            stuck.append(component)
            last = self._last_restart.get(component, 0.0)
            if now - last < self.min_restart_interval_s:
                suppressed.append({"component": component,
                                   "reason": "min restart interval"})
                per[component]["status"] = "STUCK_SUPPRESSED"
                continue
            if self._rate_limited():
                suppressed.append({"component": component,
                                   "reason": "per-window restart cap"})
                per[component]["status"] = "STUCK_SUPPRESSED"
                continue
            ok = await self._restart(component)
            if ok:
                restarted.append(component)
                per[component]["status"] = "RESTARTED"
            else:
                suppressed.append({"component": component,
                                   "reason": "restart/verify failed"})
                per[component]["status"] = "RESTART_FAILED"
        return {
            "checked": checked,
            "stuck": stuck,
            "restarted": restarted,
            "suppressed": suppressed,
            "per_component": per,
            "restart_counts": dict(self._restart_count),
            "restarts_in_window": len([
                t for t in self._restart_times if now - t < self.window_s]),
        }

    async def _restart(self, component: str) -> bool:
        now = self._now()
        handler = self._restart_handlers.get(component)
        if handler is None:
            return False
        try:
            result = handler()
            if hasattr(result, "__await__"):
                await result
        except Exception:  # noqa: BLE001 — restart must never kill the watchdog
            self._status[component] = "RESTART_FAILED"
            return False
        verify = self._verify_handlers.get(component)
        if verify is not None:
            try:
                if not verify():
                    self._status[component] = "RESTART_FAILED"
                    return False
            except Exception:  # noqa: BLE001
                self._status[component] = "RESTART_FAILED"
                return False
        self._last_beat[component] = now
        self._last_restart[component] = now
        self._restart_times.append(now)
        self._restart_count[component] = self._restart_count.get(component, 0) + 1
        self._status[component] = "RESTARTED"
        return True

    def health(self) -> Dict[str, Any]:
        per = {}
        for c in self.COMPONENTS:
            age = self.age(c)
            per[c] = {"status": self._status.get(c, "UNKNOWN"),
                      "age_s": (round(age, 2) if age is not None else None)}
        return {"per_component": per,
                "restart_counts": dict(self._restart_count),
                "timeout_s": self.timeout_s}

    def reset(self) -> None:
        self._last_beat = {}
        self._status = {}
        self._restart_times = []
