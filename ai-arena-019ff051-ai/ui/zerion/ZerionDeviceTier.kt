package ui.zerion

import android.app.ActivityManager
import android.content.Context

/**
 * Device-tier detection for the Zerion particle bust renderer.
 *
 * The mobile performance budget is the primary constraint: thousands of
 * particles must run smoothly on mid-range GPUs without draining battery or
 * triggering thermal throttling. Instead of assuming top-tier hardware, the
 * renderer picks a particle budget and effect quality from this tier, detected
 * once at startup and never re-queried.
 *
 * Tier          Particle budget  Effects
 * ULTRA_LOW     900              rings/glow off, lowest quality scale
 * LOW           1500             rings off, reduced scale (spec fallback band)
 * MEDIUM        2000             default (matches ZerionParticleField default)
 * HIGH          3000             full effects (spec upper bound)
 *
 * The pure classification (`budgetFor`) is mirrored by
 * `tests/test_mobile_compose_ui.py` so the fallback band stays pinned to the
 * spec (1,500-3,000) without needing an Android build.
 */
enum class ZerionDeviceTier(
    val label: String,
    val particleBudget: Int,
    /** Scales point size / glow radii; also a proxy for internal render cost. */
    val qualityScale: Float,
    val enableRings: Boolean,
    val enableGlow: Boolean
) {
    ULTRA_LOW("ULTRA_LOW", 900, 0.55f, false, false),
    LOW("LOW", 1500, 0.70f, false, true),
    MEDIUM("MEDIUM", 2000, 0.90f, true, true),
    HIGH("HIGH", 3000, 1.00f, true, true);

    companion object {
        /**
         * Pure classification (no Android APIs) so the boundaries can be
         * mirrored and regression-tested from Python. Coarse buckets only;
         * memory class (heap MB) and core count are the two signals used.
         */
        fun budgetFor(cores: Int, memoryClassMb: Int): ZerionDeviceTier = when {
            memoryClassMb <= 96 || cores <= 2 -> ULTRA_LOW
            memoryClassMb <= 192 || cores <= 4 -> LOW
            memoryClassMb <= 384 || cores <= 6 -> MEDIUM
            else -> HIGH
        }

        /** One-time detection at startup; cheap Android API reads only. */
        fun detect(context: Context): ZerionDeviceTier {
            val cores = Runtime.getRuntime().availableProcessors()
            val manager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
            val memoryClassMb = manager?.memoryClass ?: 192
            return budgetFor(cores, memoryClassMb)
        }
    }
}
