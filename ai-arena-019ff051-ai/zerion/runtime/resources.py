"""
Resource Governor and Environmental Awareness Engine
"""

from dataclasses import dataclass
import os
import platform
import shutil
import time
from typing import Any, Dict, Optional


@dataclass
class ResourceSnapshot:
    cpu_percent: float
    memory_available_mb: float
    memory_total_mb: float
    disk_available_mb: float
    is_battery_powered: bool
    battery_percent: Optional[float]
    is_thermal_throttled: bool
    platform_name: str
    is_termux: bool
    compute_tier: str  # "LOW", "MEDIUM", "HIGH"
    timestamp: float


class ResourceManager:
    def __init__(self, low_memory_threshold_mb: float = 256.0):
        self.low_memory_threshold_mb = low_memory_threshold_mb
        self.is_termux = "TERMUX_VERSION" in os.environ or "/data/data/com.termux" in os.environ.get("PATH", "")
        self.platform_name = platform.system()
        self._last_snapshot: Optional[ResourceSnapshot] = None
        self._api_budget_cents: float = 1000.0  # $10 default soft budget
        self._api_spent_cents: float = 0.0

    def sample(self) -> ResourceSnapshot:
        total_mem_mb = 1024.0
        avail_mem_mb = 512.0
        
        # Read Linux /proc/meminfo if available
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    lines = f.readlines()
                mem_dict = {}
                for line in lines:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        mem_dict[key] = int(val)
                if "MemTotal" in mem_dict:
                    total_mem_mb = mem_dict["MemTotal"] / 1024.0
                if "MemAvailable" in mem_dict:
                    avail_mem_mb = mem_dict["MemAvailable"] / 1024.0
            except Exception:
                pass

        # Disk info
        try:
            total_disk, used_disk, free_disk = shutil.disk_usage("/")
            disk_avail_mb = free_disk / (1024 * 1024)
        except Exception:
            disk_avail_mb = 10240.0

        # CPU load
        try:
            load1, _, _ = os.getloadavg()
            cpu_percent = min(100.0, load1 * 25.0)
        except Exception:
            cpu_percent = 10.0

        # Battery / Mobile
        is_battery = False
        battery_pct = None
        if os.path.exists("/sys/class/power_supply/BAT0/capacity"):
            try:
                with open("/sys/class/power_supply/BAT0/capacity") as f:
                    battery_pct = float(f.read().strip())
                is_battery = True
            except Exception:
                pass

        # Compute tier assessment
        if self.is_termux or total_mem_mb < 2048:
            compute_tier = "LOW"
        elif total_mem_mb < 8192:
            compute_tier = "MEDIUM"
        else:
            compute_tier = "HIGH"

        snapshot = ResourceSnapshot(
            cpu_percent=round(cpu_percent, 2),
            memory_available_mb=round(avail_mem_mb, 2),
            memory_total_mb=round(total_mem_mb, 2),
            disk_available_mb=round(disk_avail_mb, 2),
            is_battery_powered=is_battery,
            battery_percent=battery_pct,
            is_thermal_throttled=False,
            platform_name=self.platform_name,
            is_termux=self.is_termux,
            compute_tier=compute_tier,
            timestamp=time.time()
        )
        self._last_snapshot = snapshot
        return snapshot

    def can_afford_compute(self, estimated_cost_cents: float) -> bool:
        return (self._api_spent_cents + estimated_cost_cents) <= self._api_budget_cents

    def record_cost(self, cost_cents: float):
        self._api_spent_cents += cost_cents

    def get_recommended_compute_mode(self, task_priority: int, task_uncertainty: float) -> str:
        """
        Calculates recommended adaptive compute level based on resources and urgency:
        Returns one of: REFLEX, FAST, NORMAL, DEEP, EXTREME, EXPERIMENTAL
        """
        snapshot = self.sample()
        if snapshot.memory_available_mb < self.low_memory_threshold_mb or snapshot.compute_tier == "LOW":
            if task_priority > 80:
                return "FAST"
            return "REFLEX"

        if task_priority < 30 and task_uncertainty < 0.3:
            return "REFLEX"
        elif task_uncertainty < 0.5:
            return "FAST"
        elif task_uncertainty < 0.75:
            return "NORMAL"
        elif task_uncertainty < 0.9:
            return "DEEP"
        else:
            return "EXPERIMENTAL" if task_priority > 70 else "EXTREME"
