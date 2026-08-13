package ui.zerion

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PointMode
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.flow.first
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.sin

/**
 * ZerionParticleBust — GPU-friendly particle head/bust renderer for the
 * holographic voice interface (mobile / portrait).
 *
 * Rendering strategy (the Compose-idiomatic equivalent of a custom OpenGL ES
 * point-cloud shader):
 *  - one `drawPoints(PointMode.Points)` call per alpha bucket per frame —
 *    a handful of draw calls for thousands of particles, no polygons;
 *  - all particle state is preallocated in [ParticleBuffers] (positions,
 *    bucket indices, drift) — zero per-frame allocation in the draw loop;
 *  - the frame clock freezes while the app is backgrounded
 *    (`controller.active == false`), so a hidden screen does no simulation
 *    work and drains no battery.
 *
 * States driven by the real runtime via ZerionVisualizationController:
 *  - BOOTING   — particles fly from scatter positions into the silhouette,
 *                stagger-eased, with the blue boot orb low-center;
 *  - IDLE      — breathing + twinkle, faint sonar rings;
 *  - LISTENING — rings pulse faster, core brightens;
 *  - SPEAKING  — amber core intensity driven by live audio RMS (not a canned
 *                animation), rings ripple per syllable (audio-scaled);
 *  - THINKING  — faster inward swirl + amber->ice-violet core tint shift.
 *
 * Honesty note: the pure geometry/tier/boot logic is mirrored and regression
 * tested from Python (tests/test_mobile_compose_ui.py); the Compose file
 * itself is not build-verified in this repository (no Android/Gradle project
 * here) and no on-device FPS/battery measurement has been run — the 60fps
 * target and battery behavior must be verified on real hardware.
 */
@Composable
fun ZerionParticleBust(
    controller: ZerionVisualizationController,
    modifier: Modifier = Modifier,
) {
    val tier = controller.tier
    val field = remember(tier) { ZerionParticleField(tier.particleBudget) }
    val buffers = remember(field) { ParticleBuffers(field) }
    var clockMs by remember { mutableFloatStateOf(0f) }

    // Frame clock. The inner loop runs only while the controller is active
    // (foregrounded): pausing freezes the clock, so the hidden screen does no
    // simulation work and drains no battery (spec: pause on background).
    LaunchedEffect(controller) {
        while (true) {
            controller.active.first { it }
            while (controller.active.value) {
                withFrameNanos { ns ->
                    clockMs = ns / 1_000_000f
                }
            }
        }
    }

    Canvas(modifier = modifier) {
        drawBust(
            clockMs = clockMs,
            ui = controller.uiState.value,
            active = controller.active.value,
            tier = tier,
            field = field,
            buffers = buffers,
        )
    }
}

private fun DrawScope.drawBust(
    clockMs: Float,
    ui: ZerionUiViewState,
    active: Boolean,
    tier: ZerionDeviceTier,
    field: ZerionParticleField,
    buffers: ParticleBuffers,
) {
    // Full black (or near-black #05070a) backdrop, edge-to-edge.
    drawRect(Color(0xFF05070A))
    if (!active) return

    val state = ui.visualizationState
    val audio = ui.telemetry.audioRmsAmplitude
    val assembling = state == ZerionVisualizationState.BOOTING && ui.assemblyPercentage < 100

    // Portrait bust geometry (shared with ZerionHomeScreenLayout + Python tests):
    // focal center at 42% height, uniform scale (no distortion), unit in dp.
    val w = size.width
    val h = size.height
    val bustScale = min(
        w / ZerionHomeScreenLayout.BUST_SCALE_REFERENCE_WIDTH_DP,
        h / ZerionHomeScreenLayout.BUST_SCALE_REFERENCE_HEIGHT_DP
    ) * ZerionHomeScreenLayout.BUST_SCALE_FACTOR
    val unit = ZerionHomeScreenLayout.BUST_UNIT_DP * bustScale
    val cx = w / 2f
    val cy = h * ZerionHomeScreenLayout.BUST_FOCAL_CENTER_Y_FRACTION

    val dt = min(0.1f, (clockMs - buffers.lastClockMs) / 1000f)
    buffers.lastClockMs = clockMs

    if (!assembling) {
        if (tier.enableRings) {
            drawRings(state, audio, cx, cy, clockMs, bustScale)
        }
        if (tier.enableGlow) {
            drawCoreGlow(state, audio, cx, cy, unit)
        }
    }

    drawParticles(
        state = state,
        audio = audio,
        assembling = assembling,
        progress01 = if (assembling) ui.assemblyPercentage / 100f else 1f,
        dt = dt,
        clockMs = clockMs,
        tier = tier,
        field = field,
        buffers = buffers,
        cx = cx,
        cy = cy,
        unit = unit,
    )

    if (assembling) {
        drawBootOrb(cx, cy, unit)
    } else {
        drawNeckSpine(state, audio, cx, cy, unit, bustScale)
    }
}

/** Faint concentric sonar rings emanating horizontally from the bust center. */
private fun DrawScope.drawRings(
    state: ZerionVisualizationState,
    audio: Float,
    cx: Float,
    cy: Float,
    clockMs: Float,
    bustScale: Float,
) {
    val cycle = state.targetPulsePeriodMs * 1.6f
    val speed = when (state) {
        ZerionVisualizationState.LISTENING -> 1.5f
        ZerionVisualizationState.SPEAKING -> 1.3f
        ZerionVisualizationState.THINKING -> 1.15f
        else -> 1.0f
    }
    // Speaking: rings ripple outward per syllable (audio-scaled, not canned).
    val audioBoost = if (state == ZerionVisualizationState.SPEAKING) 0.5f + 0.5f * audio else 1f
    val maxAlpha = if (state == ZerionVisualizationState.LISTENING) 0.30f else 0.18f
    val maxRadius = min(
        ZerionHomeScreenLayout.RIPPLE_MAX_RADIUS_DP.dp.toPx() * bustScale,
        size.width * 0.45f
    )
    val color = Color(0xFF1EC8FF)
    for (k in 0 until 3) {
        val t = ((clockMs / (cycle / speed)) + k / 3f) % 1f
        val alpha = (1f - t) * maxAlpha * audioBoost
        if (alpha <= 0.01f) continue
        drawCircle(
            color = color,
            radius = t * maxRadius,
            center = Offset(cx, cy),
            style = Stroke(width = 1f.dp.toPx() * bustScale),
            alpha = alpha,
        )
    }
}

/**
 * Amber energy core visible through the face + thin neck spine conduit.
 * Speaking state: intensity is driven by live output-audio RMS.
 * Thinking state: brief amber -> ice-violet color shift.
 */
private fun DrawScope.drawCoreGlow(
    state: ZerionVisualizationState,
    audio: Float,
    cx: Float,
    cy: Float,
    unit: Float,
) {
    val faceX = cx + ZerionGlowCoreSpec.FACE_CENTER_X * unit
    val faceY = cy + ZerionGlowCoreSpec.FACE_CENTER_Y * unit
    val radius = ZerionGlowCoreSpec.FACE_RADIUS_X * unit * 2.4f

    val intensity = when (state) {
        ZerionVisualizationState.SPEAKING -> 0.70f + 0.90f * audio // live RMS
        ZerionVisualizationState.LISTENING -> 0.60f
        ZerionVisualizationState.THINKING -> 0.72f
        ZerionVisualizationState.EXECUTING,
        ZerionVisualizationState.LEARNING -> 0.66f
        ZerionVisualizationState.ERROR -> 0.35f
        else -> 0.45f
    }.coerceIn(0f, 1.2f)

    val colors = if (state == ZerionVisualizationState.THINKING) {
        listOf(
            Color(0xFFFF9A2E).copy(alpha = 0.45f * intensity),
            Color(0xFF8A6BFF).copy(alpha = 0.22f * intensity),
            Color.Transparent,
        )
    } else {
        listOf(
            Color(0xFFFFD060).copy(alpha = 0.85f * intensity),
            Color(0xFFFF9A2E).copy(alpha = 0.45f * intensity),
            Color.Transparent,
        )
    }
    drawRect(
        brush = Brush.radialGradient(colors, center = Offset(faceX, faceY), radius = radius),
        size = size,
    )
}

/** The silhouette itself: thousands of point particles, zero per-frame allocation. */
private fun DrawScope.drawParticles(
    state: ZerionVisualizationState,
    audio: Float,
    assembling: Boolean,
    progress01: Float,
    dt: Float,
    clockMs: Float,
    tier: ZerionDeviceTier,
    field: ZerionParticleField,
    buffers: ParticleBuffers,
    cx: Float,
    cy: Float,
    unit: Float,
) {
    val n = field.particleCount
    for (b in 0 until buffers.bucketCount) buffers.bucketSizes[b] = 0

    val pulsePeriod = state.targetPulsePeriodMs.toFloat()
    val pulseAmp = state.targetPulseAmplitude
    val phase = clockMs / pulsePeriod * TAU
    val thinking = state == ZerionVisualizationState.THINKING
    val speaking = state == ZerionVisualizationState.SPEAKING
    val audioBoost = if (speaking) 1f + 0.30f * audio else 1f

    for (i in 0 until n) {
        var x: Float
        var y: Float
        var alpha: Float

        if (assembling) {
            // Boot: staggered scatter -> target with ease-out; density builds
            // particle by particle (progress driven by real init progress).
            val local = ((progress01 - field.stagger[i] * 0.45f) / 0.55f).coerceIn(0f, 1f)
            val e = easeOutCubic(local)
            x = lerpFloat(field.scatterX[i], field.targetX[i], e)
            y = lerpFloat(field.scatterY[i], field.targetY[i], e)
            alpha = field.baseAlpha[i] * e
        } else {
            x = field.targetX[i]
            y = field.targetY[i]
            val seed = field.phaseSeed[i]

            // Ambient breathing / shimmer — particles are never fully static.
            x += sin(phase + seed * TAU) * pulseAmp * 0.05f
            y += cos(phase * 0.7f + seed * TAU) * pulseAmp * 0.03f

            // Per-particle twinkle (random opacity flicker).
            alpha = field.baseAlpha[i] * (0.55f + 0.45f * sin(clockMs * 0.0021f + seed * 13.7f))

            if (thinking) {
                // THINKING: faster inward swirl + slight contraction so the
                // user can tell Zerion is working vs. idle.
                val ang = sin(clockMs * 0.0035f + seed * TAU) * 0.10f
                val r = hypot(x, y)
                val ca = cos(ang)
                val sa = sin(ang)
                val nx = x * ca - y * sa
                val ny = x * sa + y * ca
                val pull = 1f - 0.08f * (0.5f + 0.5f * sin(clockMs * 0.004f + seed * 31f)) * (1f - r)
                x = nx * pull
                y = ny * pull
                alpha *= 1.12f
            }

            if (field.isAura[i]) {
                // Dissolving aura: drift upward out of the head, recycle below
                // the shoulders; gentle lateral wobble.
                buffers.driftY[i] -= field.auraSpeed[i] * dt
                if (buffers.driftY[i] < -0.85f) {
                    buffers.driftY[i] = 0.95f * (0.55f + 0.45f * sin(seed * 57f))
                }
                y += buffers.driftY[i]
                x += sin(clockMs * 0.002f + seed * 40f) * 0.03f
            }

            if (speaking) alpha *= audioBoost
        }

        // Alpha bucketization -> a handful of drawPoints calls (one per bucket),
        // each a single GPU point-cloud draw. No per-frame allocation.
        val bucketIndex = (alpha.coerceIn(0f, 1f) * (buffers.bucketCount - 1)).toInt()
        val bucket = buffers.bucketPoints[bucketIndex]
        val at = buffers.bucketSizes[bucketIndex] * 2
        bucket[at] = cx + x * unit
        bucket[at + 1] = cy + y * unit
        buffers.bucketSizes[bucketIndex]++
    }

    val strokeWidth = (1.8f * tier.qualityScale).dp.toPx()
    for (b in 0 until buffers.bucketCount) {
        val count = buffers.bucketSizes[b]
        if (count == 0) continue
        drawPoints(
            points = buffers.bucketPoints[b],
            pointMode = PointMode.Points,
            color = BUCKET_COLORS[b],
            strokeWidth = strokeWidth,
            cap = StrokeCap.Round,
        )
    }
}

/** Thin amber line down the throat/neck (energy conduit). */
private fun DrawScope.drawNeckSpine(
    state: ZerionVisualizationState,
    audio: Float,
    cx: Float,
    cy: Float,
    unit: Float,
    bustScale: Float,
) {
    val glow = when (state) {
        ZerionVisualizationState.SPEAKING -> 0.50f + 0.50f * audio
        ZerionVisualizationState.THINKING -> 0.65f
        ZerionVisualizationState.LISTENING -> 0.55f
        else -> 0.38f
    }.coerceIn(0f, 1f)

    val y0 = cy + ZerionGlowCoreSpec.NECK_ORIGIN_Y * unit
    val y1 = cy + ZerionGlowCoreSpec.NECK_TOP_Y * unit
    val width = (2.2f * bustScale).coerceAtLeast(1.2f).dp.toPx()

    drawLine(
        color = Color(0xFFFF9A2E).copy(alpha = glow),
        start = Offset(cx, y0),
        end = Offset(cx, y1),
        strokeWidth = width,
        cap = StrokeCap.Round,
    )
    drawLine(
        color = Color(0xFFFFD060).copy(alpha = glow * 0.45f),
        start = Offset(cx - width * 0.5f, y0),
        end = Offset(cx + width * 0.5f, y1),
        strokeWidth = width * 0.35f,
        cap = StrokeCap.Round,
    )
}

/** Boot: single bright blue orb low-center while the head is assembling. */
private fun DrawScope.drawBootOrb(cx: Float, cy: Float, unit: Float) {
    val center = Offset(cx, cy + 0.62f * unit)
    val radius = 16f.dp.toPx()
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(Color.White, Color(0xFF1EC8FF), Color.Transparent),
            center = center,
            radius = radius * 2.2f,
        ),
        radius = radius,
        center = center,
    )
}

/** Preallocated render buffers — never re-allocated in the frame loop. */
private class ParticleBuffers(val field: ZerionParticleField) {
    val bucketCount = BUCKET_COUNT
    val bucketPoints = Array(bucketCount) { FloatArray(2 * field.particleCount) }
    val bucketSizes = IntArray(bucketCount)
    val driftY = FloatArray(field.particleCount)
    var lastClockMs: Float = 0f
}

private const val TAU = 6.2831853f

private fun easeOutCubic(t: Float): Float = 1f - (1f - t) * (1f - t) * (1f - t)

private fun lerpFloat(a: Float, b: Float, t: Float): Float = a + (b - a) * t

private fun lerpColor(a: Color, b: Color, t: Float): Color = Color(
    red = a.red + (b.red - a.red) * t,
    green = a.green + (b.green - a.green) * t,
    blue = a.blue + (b.blue - a.blue) * t,
    alpha = 1f,
)

/** Cyan ramp across buckets: dim #1EC8FF contour -> bright #4FD8FF edges. */
private val BUCKET_COLORS = List(BUCKET_COUNT) { i ->
    lerpColor(
        Color(0xFF1EC8FF),
        Color(0xFF4FD8FF),
        i / (BUCKET_COUNT - 1).toFloat(),
    )
}

private const val BUCKET_COUNT = 6
