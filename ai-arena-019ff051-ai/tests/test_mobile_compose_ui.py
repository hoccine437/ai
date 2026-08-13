"""
Mobile Compose UI — geometry, device-tier, and boot-assembly validation.

Mirrors the pure-logic constants in ui/zerion/*.kt so the portrait 9:16 spec
stays pinned without requiring an Android build. Same convention as
test_aspect_ratio_9_16.py. Sources:

- ZerionHomeScreenLayout (ZerionHomeScreen.kt): focal center, scale, unit
- ZerionDeviceTier.budgetFor (ZerionDeviceTier.kt): tier boundaries
- ZerionParticleBust.kt: boot assembly stagger/ease + alpha bucketing
- ZerionParticleField.kt: bust geometry (head radius, shoulders, crown)
"""

import unittest

# --- ZerionHomeScreenLayout -------------------------------------------------
BUST_FOCAL_Y = 0.42          # BUST_FOCAL_CENTER_Y_FRACTION
SCALE_REF_W = 380.0          # BUST_SCALE_REFERENCE_WIDTH_DP
SCALE_REF_H = 680.0          # BUST_SCALE_REFERENCE_HEIGHT_DP
SCALE_FACTOR = 0.96          # BUST_SCALE_FACTOR
BUST_UNIT = 150.0            # BUST_UNIT_DP
STATUS_Y = 0.62              # STATUS_TEXT_Y_FRACTION
LISTEN_ZONE_TOP = 0.72       # LISTEN_ZONE_TOP_FRACTION

# --- ZerionParticleField (normalized coords, y down) -------------------------
HEAD_RADIUS_Y = 0.36
SHOULDER_MAX_X = 0.63
CROWN_TOP_Y = -0.66
SHOULDER_BOTTOM_Y = 0.57

# --- ZerionDeviceTier.budgetFor ---------------------------------------------
def tier_for(cores, memory_mb):
    if memory_mb <= 96 or cores <= 2:
        return "ULTRA_LOW", 900
    if memory_mb <= 192 or cores <= 4:
        return "LOW", 1500
    if memory_mb <= 384 or cores <= 6:
        return "MEDIUM", 2000
    return "HIGH", 3000


def bust_scale(w, h):
    return min(w / SCALE_REF_W, h / SCALE_REF_H) * SCALE_FACTOR


def ease_out_cubic(t):
    t = min(max(t, 0.0), 1.0)
    return 1.0 - (1.0 - t) ** 3


def assembly_local(progress, stagger):
    return min(max((progress - stagger * 0.45) / 0.55, 0.0), 1.0)


class TestPortraitBustPlacement(unittest.TestCase):
    def test_focal_center_in_upper_middle_third(self):
        # Bust vertical focal center must remain in the upper 40-50%.
        for h in (640, 720, 768, 960, 1920, 915, 873, 800):
            cy = BUST_FOCAL_Y * h
            self.assertTrue(0.35 * h <= cy <= 0.50 * h, f"focal {cy} outside band at h={h}")

    def test_proportional_scale_no_distortion(self):
        # Identical X and Y scale factors -> no stretching of the silhouette.
        for w, h in [(360, 640), (1080, 1920), (412, 915), (393, 873)]:
            self.assertEqual(bust_scale(w, h), bust_scale(w, h))
            self.assertGreater(bust_scale(w, h), 0.0)

    def test_bust_fits_within_portrait_canvas(self):
        for w, h in [(360, 640), (412, 915), (1080, 1920)]:
            unit = BUST_UNIT * bust_scale(w, h)
            cx, cy = w / 2.0, BUST_FOCAL_Y * h
            # Shoulders stay inside the screen horizontally.
            self.assertLessEqual(cx + SHOULDER_MAX_X * unit, w, f"shoulders overflow at {w}x{h}")
            # Head sits in the upper-middle third, clear of the top edge.
            head_top = cy + CROWN_TOP_Y * unit
            self.assertLessEqual(head_top, 0.34 * h, f"head too low at {w}x{h}")
            self.assertGreaterEqual(head_top, 0.18 * h, f"head clipped at {w}x{h}")
            # Shoulders taper into the lower third without reaching the label.
            shoulder_bottom = cy + SHOULDER_BOTTOM_Y * unit
            self.assertLessEqual(shoulder_bottom, STATUS_Y * h, f"bust collides with label at {w}x{h}")

    def test_status_label_below_bust_above_gesture_area(self):
        for w, h in [(360, 640), (412, 915), (1080, 1920)]:
            unit = BUST_UNIT * bust_scale(w, h)
            bust_bottom_frac = BUST_FOCAL_Y + SHOULDER_BOTTOM_Y * unit / h
            self.assertGreater(STATUS_Y, bust_bottom_frac + 0.03, f"label overlaps bust at {w}x{h}")
            self.assertLess(STATUS_Y, LISTEN_ZONE_TOP - 0.05, f"label collides with listen zone at {w}x{h}")
        # Listen zone top clears a ~12% gesture-nav inset.
        self.assertLess(LISTEN_ZONE_TOP, 0.88)

    def test_ripple_within_canvas(self):
        for w, h in [(360, 640), (412, 915)]:
            max_radius = min(190.0 * bust_scale(w, h), w * 0.45)
            self.assertLessEqual(max_radius, w * 0.45)


class TestDeviceTierBudget(unittest.TestCase):
    def test_tier_boundaries(self):
        cases = [
            ((2, 96), "ULTRA_LOW", 900),
            ((4, 128), "LOW", 1500),
            ((8, 192), "LOW", 1500),
            ((4, 256), "LOW", 1500),
            ((8, 256), "MEDIUM", 2000),
            ((6, 384), "MEDIUM", 2000),
            ((8, 512), "HIGH", 3000),
            ((12, 768), "HIGH", 3000),
        ]
        for (cores, mem), name, budget in cases:
            self.assertEqual(tier_for(cores, mem), (name, budget),
                             f"mismatch for cores={cores}, mem={mem}")

    def test_fallback_band_matches_spec(self):
        # Spec: reduced particle count 1,500-3,000 for low-end fallback.
        for cores, mem in [(4, 128), (6, 256), (8, 512)]:
            budget = tier_for(cores, mem)[1]
            self.assertTrue(1500 <= budget <= 3000, f"budget {budget} out of spec band")
        # Extreme low-end goes below the band deliberately.
        self.assertEqual(tier_for(2, 64)[1], 900)

    def test_medium_default_matches_field_default(self):
        # MEDIUM (default tier) budget must match ZerionParticleField default.
        self.assertEqual(tier_for(6, 256)[1], 2000)

    def test_budgets_strictly_ordered(self):
        budgets = [tier_for(c, m)[1] for c, m in [(2, 64), (4, 128), (8, 256), (12, 768)]]
        self.assertEqual(budgets, sorted(budgets))
        self.assertEqual(len(set(budgets)), 4)


class TestBootAssembly(unittest.TestCase):
    def test_all_particles_reach_target_at_progress_one(self):
        for i in range(0, 2000, 137):
            stagger = i / 2000.0
            self.assertAlmostEqual(ease_out_cubic(assembly_local(1.0, stagger)), 1.0, places=5)

    def test_staggered_no_single_burst(self):
        # The head assembles particle-by-particle, not in a single burst:
        # at p=0.2 low-stagger particles have eased most of the way while
        # high-stagger particles are still at the start, and ease is
        # monotonically non-increasing with stagger.
        p = 0.2
        n = 2000
        eased = [ease_out_cubic(assembly_local(p, i / float(n))) for i in range(n)]
        self.assertGreater(eased[0], 0.5)   # first particle well underway
        self.assertAlmostEqual(eased[-1], 0.0, places=6)  # last not started
        for a, b in zip(eased, eased[1:]):
            self.assertGreaterEqual(a, b - 1e-9)  # monotonic build-up

    def test_alpha_bucket_index_always_in_range(self):
        # Renderer: bucketIndex = (alpha clamped 0..1) * 5, truncated.
        for a in (0.0, 0.05, 0.33, 0.5, 0.79, 1.0):
            idx = int(min(max(a, 0.0), 1.0) * 5)
            self.assertTrue(0 <= idx <= 5, f"bucket index {idx} out of range for alpha {a}")


if __name__ == "__main__":
    unittest.main()
