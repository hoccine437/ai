package ui.zerion

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

/**
 * Top-level Unified Zerion Home Screen.
 * Hosts the particle bust visualization as the primary central element.
 * Secondary interaction and tools surface contextually as overlays.
 *
 * Mobile (portrait 9:16): fullscreen, edge-to-edge behind the status/nav bars,
 * immersive/screensaver-like. The only chrome is the low-opacity EXIT affordance
 * (top-left), the monospace status label beside the right shoulder at chest
 * height (photo-fidelity placement — the holographic bust mock places
 * `STATUS: LISTENING` at the lower right, next to the shoulder), and the
 * invisible manual-listen tap zone over the lower third with a subtle mic glyph.
 */
object ZerionHomeScreenLayout {
    const val REFERENCE_WIDTH_DP = 412
    const val VISUALIZATION_CANVAS_HEIGHT_DP = 420
    const val BUST_HEIGHT_RATIO = 0.75f
    const val RIPPLE_MAX_RADIUS_DP = 190f
    const val HUD_CONTROL_WIDTH_DP = 56
    const val HUD_CONTROL_HEIGHT_DP = 28
    const val HUD_CONTROL_RADIUS_DP = 8
    const val HUD_CONTROL_INSET_DP = 16

    // 9:16 portrait bust geometry (mirrored by tests/test_mobile_compose_ui.py
    // and test_aspect_ratio_9_16.py). Uniform scale => no distortion.
    const val BUST_FOCAL_CENTER_Y_FRACTION = 0.42f
    const val BUST_SCALE_REFERENCE_WIDTH_DP = 380f
    const val BUST_SCALE_REFERENCE_HEIGHT_DP = 680f
    const val BUST_SCALE_FACTOR = 0.96f
    const val BUST_UNIT_DP = 150f

    // Manual-listen zone placement (fraction of safe height).
    const val LISTEN_ZONE_TOP_FRACTION = 0.72f

    // Status label: right-aligned next to the right shoulder, at chest height.
    // 0.5h (vertical center) + this offset places it just below the shoulder
    // tip — the photo reference shows it beside the shoulder, not centered.
    const val STATUS_TEXT_OFFSET_Y_FRACTION = 0.07f
    const val STATUS_TEXT_END_PADDING_DP = 20f
}

/**
 * Create the renderer's controller with one-time device-tier detection.
 * The host orchestration layer keeps this instance and pushes runtime state
 * into it (see ZerionVisualizationController KDoc for the mapping).
 */
@Composable
fun rememberZerionVisualizationController(): ZerionVisualizationController {
    val context = LocalContext.current
    return remember { ZerionVisualizationController(ZerionDeviceTier.detect(context)) }
}

/**
 * Fullscreen portrait face screen for the Zerion holographic voice interface.
 *
 * @param controller the state API the orchestration layer pushes into
 *   (setState / setAudioLevel / setProgress); the screen only renders it.
 * @param onExit wired by the host to real back-navigation (this screen also
 *   respects Android system back via the host's back handler).
 * @param onManualListenToggle manual listen trigger for when wake-word
 *   detection is off or unavailable.
 */
@Composable
fun ZerionHomeScreen(
    controller: ZerionVisualizationController,
    onExit: () -> Unit = {},
    onManualListenToggle: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    // Lifecycle: the particle simulation runs only while the screen is in the
    // foreground. ON_PAUSE freezes the frame clock (no battery drain when the
    // UI is hidden); ON_RESUME restarts it. Leaving composition stops it.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, controller) {
        controller.start()
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_PAUSE -> controller.pause()
                Lifecycle.Event.ON_RESUME -> controller.resume()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            controller.stop()
        }
    }

    val uiState by controller.uiState.collectAsState()

    Box(modifier = modifier.fillMaxSize().background(Color(0xFF05070A))) {
        // Edge-to-edge particle field, behind the status bar / gesture nav.
        ZerionParticleBust(controller = controller, modifier = Modifier.fillMaxSize())

        // Content layer: respects safe areas (status bar, notch/cutout,
        // gesture nav bar) so nothing overlaps them.
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing),
        ) {
            // EXIT — top-left, minimal and unobtrusive.
            Text(
                text = "EXIT",
                color = Color.White.copy(alpha = 0.35f),
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                letterSpacing = 2.sp,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(16.dp)
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = onExit,
                    ),
            )

            // Status label: beside the right shoulder at chest height
            // (photo-fidelity placement), small cyan monospace.
            val statusText = if (uiState.visualizationState == ZerionVisualizationState.BOOTING) {
                "ASSEMBLING… ${uiState.assemblyPercentage}%"
            } else {
                "STATUS: ${uiState.visualizationState.label}"
            }
            Text(
                text = statusText,
                color = Color(0xFF4FD6FF),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                letterSpacing = 1.sp,
                textAlign = TextAlign.End,
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(end = ZerionHomeScreenLayout.STATUS_TEXT_END_PADDING_DP.dp)
                    .offset(y = maxHeight * ZerionHomeScreenLayout.STATUS_TEXT_OFFSET_Y_FRACTION),
            )

            // Manual listen trigger: a large invisible tap/hold zone over the
            // lower third, with a subtle mic glyph (lit while LISTENING).
            val listening = uiState.visualizationState == ZerionVisualizationState.LISTENING
            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .height(maxHeight * (1f - ZerionHomeScreenLayout.LISTEN_ZONE_TOP_FRACTION))
                    .pointerInput(Unit) {
                        detectTapGestures { onManualListenToggle() }
                    },
            ) {
                Text(
                    text = if (listening) "◉" else "○",
                    color = Color(0xFF4FD6FF).copy(alpha = if (listening) 0.95f else 0.30f),
                    fontSize = 26.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 20.dp),
                )
            }
        }
    }
}
