package ui.zerion

/**
 * Geometric and shader specifications for the Face Wave-Stack Glow
 * (photo-fidelity "voice-box": horizontal wavy amber lines) and the
 * branching Neck/Throat lightning tendrils.
 */
object ZerionGlowCoreSpec {
    // Face Glow Region bounds relative to bust scale
    const val FACE_CENTER_X = 0.0f
    const val FACE_CENTER_Y = -0.08f
    const val FACE_RADIUS_X = 0.18f
    const val FACE_RADIUS_Y = 0.22f

    // Face wave-stack (voice-box) geometry, in bust-unit fractions.
    // The stack is `WAVE_STACK_BANDS` horizontal sine lines centered on the
    // face, `WAVE_STACK_SPACING` apart, each `2 * WAVE_STACK_WIDTH` long with
    // a vertical sine amplitude of `WAVE_STACK_AMP` and `WAVE_STACK_WAVES`
    // humps across its width.
    const val WAVE_STACK_BANDS = 7
    const val WAVE_STACK_WIDTH = 0.17f
    const val WAVE_STACK_SPACING = 0.050f
    const val WAVE_STACK_TOP_Y = -0.24f
    const val WAVE_STACK_AMP = 0.014f
    const val WAVE_STACK_WAVES = 2f

    // Throat / upper-chest lightning tendrils (photo: branching yellow-orange
    // conduits descending from the voice-box). Branch points are given as
    // x/y offsets in bust-unit fractions from the bust center.
    const val NECK_ORIGIN_X = 0.0f
    const val NECK_ORIGIN_Y = 0.62f
    const val NECK_TOP_LEFT_X = -0.06f
    const val NECK_TOP_RIGHT_X = 0.06f
    const val NECK_TOP_Y = 0.22f
    const val TENDRILL_BRANCH_X = 0.11f
    const val TENDRILL_BRANCH_Y = 0.44f
    const val TENDRILL_BRANCH_X2 = 0.16f
    const val TENDRILL_BRANCH_Y2 = 0.58f
}
