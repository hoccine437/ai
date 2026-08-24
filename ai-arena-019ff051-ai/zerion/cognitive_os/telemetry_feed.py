"""
Slice 8 — TelemetryFeed (live outcome -> architecture telemetry).

Feeds REAL routed-task outcomes (Slice 6 record_task_outcome) into the Slice 7
ArchitectureTelemetry so MODEL / ROUTING / VERIFICATION bottlenecks are driven
by live task data — not only by explicit record_telemetry calls. The feed only
writes what actually happened (success/failure, latency, verification); it
never invents measurements. Rates remain UNKNOWN / INSUFFICIENT_DATA until the
min-sample guard is satisfied (that is enforced by telemetry.py itself).

Mapping used by the bottleneck detector (_DETECTOR_MAP in bottlenecks.py):
  routing_success        -> ROUTING_LIMITATION
  model_success          -> MODEL_LIMITATION
  verification_success   -> VERIFICATION_LIMITATION
  latency (value)        -> RESOURCE_LIMITATION when above threshold
"""

from typing import Optional

from zerion.cognitive_os.telemetry import ArchitectureTelemetry

# Telemetry components fed by the runtime's task-outcome entry points.
ROUTER_COMPONENT = "router"
VERIFIER_COMPONENT = "verifier"


class TelemetryFeed:
    """Translates Slice 6 outcome records into Slice 7 telemetry records."""

    def __init__(self, telemetry: ArchitectureTelemetry):
        if telemetry is None:
            raise ValueError("TelemetryFeed requires an ArchitectureTelemetry")
        self.telemetry = telemetry

    def feed_outcome(self, *, provider: str, model: str,
                     latency_ms: Optional[float],
                     success: bool,
                     verified: Optional[bool] = None) -> None:
        """Record one real routed-task outcome.

        success is whether the provider returned a usable result (same
        definition as the Slice 6 performance ledger). verified, when not
        None, is whether that result later passed verification (Slice 3
        evidence-gated confirm_verified).
        """
        success = bool(success)
        # ROUTING signal on the router component (drives ROUTING_LIMITATION).
        self.telemetry.record(
            ROUTER_COMPONENT, "routing_success", success=success,
            latency_ms=latency_ms)
        # MODEL signal per provider (drives MODEL_LIMITATION). A provider that
        # keeps failing pushes its model component below threshold honestly.
        model_component = f"model:{provider}" if provider else ROUTER_COMPONENT
        self.telemetry.record(
            model_component, "model_success", success=success,
            latency_ms=latency_ms)
        # Latency as a value metric (drives RESOURCE_LIMITATION when slow).
        if latency_ms is not None:
            self.telemetry.record(ROUTER_COMPONENT, "latency",
                                  value=float(latency_ms))
        # Verification signal when the caller has real verification info.
        if verified is not None:
            self.feed_verification(component=VERIFIER_COMPONENT,
                                   success=verified)

    def feed_verification(self, *, component: str = VERIFIER_COMPONENT,
                          success: bool) -> None:
        """Record a real verification outcome (drives VERIFICATION_LIMITATION)."""
        self.telemetry.record(component, "verification_success",
                              success=bool(success))

    def feed_resource(self, *, component: str = ROUTER_COMPONENT,
                      usage: float) -> None:
        """Record a real resource-usage sample (drives RESOURCE_LIMITATION)."""
        self.telemetry.record(component, "resource_usage", value=float(usage))
