package ui.zerion

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/**
 * ZerionVisualizationController — the single state API for the particle bust UI.
 *
 * Tool-agnostic by design: this widget only renders the state it is given and
 * never calls model, tool, or runtime APIs itself. The host orchestration layer
 * pushes state here from the existing runtime channel (VisualizationStateAdapter:
 * `GET /api/state` / `GET /api/ui-state` / SSE `GET /api/stream`), mapping:
 *
 *   presentation.runtime_state       -> ZerionVisualizationState (setState)
 *   presentation.assembly_percentage -> progress (assembling / boot)
 *   presentation.audio_amplitude_rms -> audioLevel (speaking, live RMS)
 *   voice_perception.is_listening    -> LISTENING gating (honest mic state)
 *
 * State is event-pushed (no polling) and decoupled from rendering: the renderer
 * reads `uiState.value` once per frame with zero per-frame allocation.
 *
 * Lifecycle: `pause()` / `resume()` are wired automatically by ZerionHomeScreen
 * to the Android activity lifecycle (ON_PAUSE / ON_RESUME) so a backgrounded
 * app stops simulating and drains no battery.
 */
class ZerionVisualizationController(
    val tier: ZerionDeviceTier = ZerionDeviceTier.MEDIUM
) {
    private val _uiState = MutableStateFlow(ZerionUiViewState())
    private val _active = MutableStateFlow(true)

    /** Read-only snapshot of the latest pushed state + telemetry. */
    val uiState: StateFlow<ZerionUiViewState> = _uiState.asStateFlow()

    /** False while the screen is backgrounded (lifecycle pause). */
    val active: StateFlow<Boolean> = _active.asStateFlow()

    /**
     * Push a full state transition. `progress` (0..100, boot assembly) and
     * `audioLevel` (0..1, live RMS while speaking) are optional per-call.
     */
    fun setState(
        state: ZerionVisualizationState,
        progress: Int? = null,
        audioLevel: Float? = null
    ) {
        _uiState.update { current ->
            current.copy(
                visualizationState = state,
                assemblyPercentage = progress?.coerceIn(0, 100) ?: current.assemblyPercentage,
                telemetry = if (audioLevel != null) {
                    current.telemetry.copy(audioRmsAmplitude = audioLevel.coerceIn(0f, 1f))
                } else {
                    current.telemetry
                }
            )
        }
    }

    /** Live audio level (RMS 0..1) without a state change — drives the amber core. */
    fun setAudioLevel(rms: Float) {
        _uiState.update {
            it.copy(telemetry = it.telemetry.copy(audioRmsAmplitude = rms.coerceIn(0f, 1f)))
        }
    }

    /** Boot assembly progress 0..100 without a state change. */
    fun setProgress(percent: Int) {
        _uiState.update { it.copy(assemblyPercentage = percent.coerceIn(0, 100)) }
    }

    /** Pause the simulation (app backgrounded / screen hidden). */
    fun pause() {
        _active.value = false
    }

    /** Resume the simulation (app foregrounded). */
    fun resume() {
        _active.value = true
    }

    /** Called by the screen when it enters composition. */
    fun start() {
        _active.value = true
    }

    /** Called by the screen when it leaves composition. */
    fun stop() {
        _active.value = false
    }
}
