package ui.zerion

import kotlin.math.*
import kotlin.random.Random

/**
 * Precomputes and maintains static point arrays for 2,000 particles
 * defining the cybernetic bust silhouette (head, neck, shoulders).
 * Zero per-frame allocations in the draw loop.
 */
class ZerionParticleField(val particleCount: Int = 2000) {

    // Precomputed normalized target positions [-1.0..1.0] relative to canvas center
    val targetX = FloatArray(particleCount)
    val targetY = FloatArray(particleCount)
    val isCrownParticle = BooleanArray(particleCount)
    val isFlowLine = BooleanArray(particleCount)
    val baseAlpha = FloatArray(particleCount)
    val scatterX = FloatArray(particleCount)
    val scatterY = FloatArray(particleCount)
    val staggerDelayMs = LongArray(particleCount)

    // Mobile renderer inputs (Slice 10.1): deterministic per-particle variety
    // seeds, boot-assembly stagger, and aura (evaporating) classification.
    // Added additively so existing consumers are unaffected.
    val phaseSeed = FloatArray(particleCount)
    val stagger = FloatArray(particleCount)
    val isAura = BooleanArray(particleCount)
    val auraSpeed = FloatArray(particleCount)

    init {
        val rng = Random(42) // Deterministic seed for reproducible geometry

        for (i in 0 until particleCount) {
            val ratio = i.toFloat() / particleCount

            phaseSeed[i] = rng.nextFloat()
            stagger[i] = ratio

            // 1. Layer A: Contour Flow Lines (40% of particles)
            if (ratio < 0.40f) {
                isFlowLine[i] = true
                isCrownParticle[i] = false
                baseAlpha[i] = 0.85f

                // Head contour perimeter
                val angle = (i.toFloat() / (particleCount * 0.40f)) * 2 * PI.toFloat()
                val radiusX = 0.28f * (1.0f - 0.15f * abs(sin(angle)))
                val radiusY = 0.36f
                targetX[i] = radiusX * cos(angle)
                targetY[i] = radiusY * sin(angle) - 0.10f
            }
            // 2. Layer B: Neck & Shoulders Flow Lines (25% of particles)
            else if (ratio < 0.65f) {
                isFlowLine[i] = true
                isCrownParticle[i] = false
                baseAlpha[i] = 0.70f

                val subRatio = (ratio - 0.40f) / 0.25f
                val side = if (i % 2 == 0) -1.0f else 1.0f
                val t = subRatio
                // Shoulder line sweep
                targetX[i] = side * (0.08f + 0.55f * t)
                targetY[i] = 0.22f + 0.35f * t
            }
            // 3. Layer C: Scattered Particles & Crown density (35% of particles)
            else {
                isFlowLine[i] = false
                val isCrown = rng.nextFloat() < 0.65f
                isCrownParticle[i] = isCrown
                // Crown + halo particles are the "dissolving aura": they drift
                // upward out of the silhouette and recycle.
                isAura[i] = true
                auraSpeed[i] = 0.16f + 0.34f * rng.nextFloat()

                if (isCrown) {
                    // Concentrated around the crown
                    val angle = rng.nextFloat() * PI.toFloat() + PI.toFloat()
                    val r = rng.nextFloat() * 0.32f
                    targetX[i] = r * cos(angle)
                    targetY[i] = r * sin(angle) * 0.7f - 0.30f
                    baseAlpha[i] = rng.nextFloat() * 0.3f + 0.45f
                } else {
                    // Drifting outer halo
                    val angle = rng.nextFloat() * 2 * PI.toFloat()
                    val r = rng.nextFloat() * 0.65f
                    targetX[i] = r * cos(angle)
                    targetY[i] = r * sin(angle) * 0.8f - 0.05f
                    baseAlpha[i] = rng.nextFloat() * 0.25f + 0.20f
                }
            }

            // Scatter burst coordinates for boot assembly animation
            val scatterAngle = rng.nextFloat() * 2 * PI.toFloat()
            val scatterDist = rng.nextFloat() * 1.5f + 0.5f
            scatterX[i] = scatterDist * cos(scatterAngle)
            scatterY[i] = scatterDist * sin(scatterAngle) - 0.8f // Diagonal upward sweep
            staggerDelayMs[i] = (rng.nextFloat() * 350f + 50f).toLong()
        }
    }
}
