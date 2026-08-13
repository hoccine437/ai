package ui.zerion

/**
 * Geometric and shader specifications for the Face Wave-Stack Glow
 * and Neck Spine Gold streaks.
 */
object ZerionGlowCoreSpec {
    // Face Glow Region bounds relative to bust scale
    const val FACE_CENTER_X = 0.0f
    const val FACE_CENTER_Y = -0.08f
    const val FACE_RADIUS_X = 0.18f
    const val FACE_RADIUS_Y = 0.22f

    // Horizontal wave-stack bands count
    const val WAVE_STACK_BANDS = 7

    // Neck gold streaks origin points
    const val NECK_ORIGIN_X = 0.0f
    const val NECK_ORIGIN_Y = 0.55f
    const val NECK_TOP_LEFT_X = -0.06f
    const val NECK_TOP_RIGHT_X = 0.06f
    const val NECK_TOP_Y = 0.22f
}
