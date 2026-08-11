"""
Android / Termux Integration and Low-Power Resource Adapter
"""

import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Optional


class TermuxAdapter:
    def __init__(self):
        self.is_termux = "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux")
        self.termux_api_available = shutil.which("termux-battery-status") is not None

    def get_battery_status(self) -> Dict[str, Any]:
        """
        Queries termux-battery-status if available, otherwise returns system fallback.
        """
        if self.termux_api_available:
            try:
                res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0:
                    return json.loads(res.stdout)
            except Exception:
                pass

        # Fallback reading
        return {
            "percentage": 100,
            "status": "CHARGING",
            "plugged": "PLUGGED_AC",
            "temperature": 25.0,
            "is_emulated": not self.is_termux
        }

    def adapt_runtime_profile(self) -> Dict[str, Any]:
        """
        Adjusts memory allocations and concurrency limits for mobile/Termux environments.
        """
        bat = self.get_battery_status()
        battery_pct = bat.get("percentage", 100)
        is_charging = bat.get("status") in ("CHARGING", "FULL")

        if battery_pct < 20 and not is_charging:
            # Extreme power saving mode
            return {
                "max_concurrency": 1,
                "preferred_compute_mode": "REFLEX",
                "disable_background_benchmarks": True,
                "power_state": "CRITICAL_SAVER"
            }
        elif self.is_termux:
            return {
                "max_concurrency": 2,
                "preferred_compute_mode": "FAST",
                "disable_background_benchmarks": False,
                "power_state": "MOBILE_OPTIMIZED"
            }
        else:
            return {
                "max_concurrency": 8,
                "preferred_compute_mode": "NORMAL",
                "disable_background_benchmarks": False,
                "power_state": "STANDARD_HOST"
            }
