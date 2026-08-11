package ui.zerion

/**
 * Telemetry and HUD data specifications.
 * Monospace typography, status text 11-12sp / 500 weight / 0.5sp tracking.
 * HUD control: 56x28dp, 8dp corner radius, 16dp inset.
 */
data class ZerionHudTelemetry(
    val stateLabel: String = "IDLE",
    val activeObjective: String = "Continuous Anomaly Discovery",
    val currentStrategy: String = "AdversarialInvariantDefense",
    val confidencePercent: Float = 95.0f,
    val learningAcceleration: String = "2.57x",
    val maturityLevel: String = "L6_META_LEARNING",
    val cpuUsagePercent: Float = 12.5f,
    val memoryUsageMb: Float = 850.0f,
    val audioRmsAmplitude: Float = 0.0f
)
