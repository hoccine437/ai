package ui.zerion

/**
 * Real runtime states for the Zerion Visualization.
 * Directly driven by the Zerion cognitive engine, not synthetic timers.
 */
enum class ZerionVisualizationState(
    val label: String,
    val isInteractive: Boolean,
    val targetPulsePeriodMs: Long,
    val targetPulseAmplitude: Float
) {
    BOOTING("ASSEMBLING…", false, 1500L, 0.10f),
    IDLE("IDLE", true, 2000L, 0.12f),
    LISTENING("LISTENING", true, 1800L, 0.15f),
    THINKING("THINKING", false, 1100L, 0.22f),
    EXECUTING("EXECUTING", false, 800L, 0.25f),
    LEARNING("LEARNING", false, 1200L, 0.20f),
    SPEAKING("SPEAKING", true, 750L, 0.30f),
    ERROR("FAULT DETECTED", true, 500L, 0.35f)
}
