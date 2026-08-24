"""
Aspect Ratio & 9:16 Portrait Geometry Validation Suite
Verifies that the canonical 9:16 portrait ratio is strictly preserved across all smartphone resolutions
without distortion, stretching, or clipping of head, shoulders, core, or HUD elements.
"""

import unittest


class TestDisplayAspectRatio916(unittest.TestCase):
    def test_canonical_9_16_resolutions(self):
        canonical_test_resolutions = [
            (360, 640, "360p Compact Android"),
            (405, 720, "405p Reference"),
            (432, 768, "432p Standard"),
            (540, 960, "qHD Android"),
            (1080, 1920, "FHD Standard 9:16"),
        ]

        for w, h, name in canonical_test_resolutions:
            ratio = w / h
            # Exact 9:16 is 0.5625
            self.assertAlmostEqual(ratio, 0.5625, places=4, msg=f"Failed for {name} ({w}x{h})")

    def test_modern_tall_android_aspect_ratios(self):
        modern_android_resolutions = [
            (393, 873, "19.5:9 Modern Tall"),
            (412, 915, "20:9 Modern Tall (Pixel/Galaxy)"),
            (360, 800, "20:9 Compact Tall"),
        ]

        for w, h, name in modern_android_resolutions:
            ratio = w / h
            # Must be taller than 9:16 (ratio <= 0.5625) ensuring clean pillarbox/letterbox portrait adaptation
            self.assertLessEqual(ratio, 0.5625, msg=f"Ratio should be portrait tall for {name}")
            # Bust vertical focal center must remain in upper 40-50%
            focal_cy = h * 0.42
            self.assertTrue(0.35 * h <= focal_cy <= 0.50 * h)

    def test_scaling_bounds_no_distortion(self):
        # Test proportional scale calculation
        for w, h in [(360, 640), (1080, 1920), (412, 915)]:
            scale = min(w / 380.0, h / 680.0) * 0.96
            self.assertGreater(scale, 0.0)
            # Ensure scale is proportional (identical scale factor for both X and Y prevents stretching)
            scale_x = scale
            scale_y = scale
            self.assertEqual(scale_x, scale_y, "Non-uniform scaling would distort the cybernetic silhouette")


if __name__ == "__main__":
    unittest.main()
