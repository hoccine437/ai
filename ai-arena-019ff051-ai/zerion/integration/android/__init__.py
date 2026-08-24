"""
Android / Termux Mobile Runtime subsystem exports for ZERION-X GENESIS X10
"""

from zerion.integration.android.mobile_runtime import (
    MobilePowerProfile,
    MobileDeviceTelemetry,
    MobileResourceGovernor,
    ProcessSupervisor,
)

__all__ = [
    "MobilePowerProfile",
    "MobileDeviceTelemetry",
    "MobileResourceGovernor",
    "ProcessSupervisor",
]
