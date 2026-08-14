package ui.zerion

/**
 * Shared animation specifications for Zerion Visualization.
 * Standardizes interpolation curves, transitions, and timing constraints.
 *
 * Palette is aligned with the photo reference of the holographic bust:
 *  - electric cyan contour / rings (#00A2FF family);
 *  - warm amber voice-box core and throat tendrils (#FFAE00 family);
 *  - near-black screen background.
 */
object ZerionAnimations {
    const val LABEL_CROSSFADE_MS = 150
    const val PULSE_INTERPOLATION_MS = 300
    const val BOOT_ASSEMBLY_DURATION_MS = 5800L
    const val RIPPLE_CYCLE_MS = 2800L
    const val RIPPLE_PHASE_OFFSET_MS = 900L

    // Photo-reference color tokens
    const val COLOR_BACKGROUND = 0xFF05070A     // near-black screen
    const val COLOR_CYAN_BRIGHT = 0xFF00A2FF    // photo contour cyan
    const val COLOR_CYAN_DIM = 0xFF1EC8FF       // dim contour / rings
    const val COLOR_CYAN_EDGE = 0xFF4FD8FF      // bright rim highlight
    const val COLOR_CORE_WHITE = 0xFFFFFFFF
    const val COLOR_CORE_GOLD = 0xFFFFD060      // hot center of the voice-box
    const val COLOR_CORE_AMBER = 0xFFFFAE00     // photo voice-box amber
    const val COLOR_CORE_ORANGE = 0xFFFF9A2E    // outer amber falloff
    const val COLOR_SPINE_DARK = 0xFF3A2A10
    const val COLOR_STATUS_TEXT = 0xFF4FD6FF
    const val COLOR_HUD_BORDER = 0xFF3AA8D8
}
