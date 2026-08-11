package ui.zerion

/**
 * State and Event contracts for Zerion UI presentation.
 */
data class ZerionUiViewState(
    val visualizationState: ZerionVisualizationState = ZerionVisualizationState.IDLE,
    val telemetry: ZerionHudTelemetry = ZerionHudTelemetry(),
    val assemblyPercentage: Int = 100,
    val isContextualInteractionOpen: Boolean = false,
    val currentInputText: String = ""
)
