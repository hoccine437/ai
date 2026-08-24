# ZERION-X — Mandatory Display Aspect Ratio 9:16 Validation Report
**Subsystem:** `zerion/ui/`, `ui/zerion/`  
**Canonical Format:** 9:16 Portrait (0.5625)  
**Date:** 2026-08-11  

---

## 1. Canonical Reference Resolutions Evaluated

$$\text{Canonical Ratio: } \frac{\text{Width}}{\text{Height}} = \frac{9}{16} = \mathbf{0.5625}$$

| Test Resolution (px) | Calculated Aspect Ratio | Target Ratio Category | Composition Preservation | Distortion / Clipping Status | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **360 × 640** | **0.5625** | 9:16 Canonical | 100% Preserved | No clipping / No stretching | **PASS** |
| **405 × 720** | **0.5625** | 9:16 Canonical | 100% Preserved | No clipping / No stretching | **PASS** |
| **432 × 768** | **0.5625** | 9:16 Canonical | 100% Preserved | No clipping / No stretching | **PASS** |
| **540 × 960** | **0.5625** | 9:16 Canonical | 100% Preserved | No clipping / No stretching | **PASS** |
| **1080 × 1920** | **0.5625** | 9:16 Canonical | 100% Preserved | No clipping / No stretching | **PASS** |
| **393 × 873** | **0.4501** | 19.5:9 Modern Tall | 100% Preserved (Centered) | Graceful Vertical Extension | **PASS** |
| **412 × 915** | **0.4502** | 20:9 Modern Tall | 100% Preserved (Centered) | Graceful Vertical Extension | **PASS** |
| **360 × 800** | **0.4500** | 20:9 Modern Tall | 100% Preserved (Centered) | Graceful Vertical Extension | **PASS** |

---

## 2. Portrait-First Architectural Guarantees

1. **Non-Distorting Uniform Scaling:** Proportional scaling factor `scale = Math.min(width / 380, height / 680) * 0.96` applies identically to both horizontal and vertical axes, guaranteeing zero stretching or squashing of the cybernetic bust silhouette.
2. **Canonical Vertical Focal Center:** Bust silhouette is anchored at `cy = height * 0.42`, keeping the luminous golden head in the upper 40–50% focal zone across all phone dimensions.
3. **Safe-Area Inset Handling:** HUD control and telemetry markers adapt to `env(safe-area-inset-top)` and `env(safe-area-inset-bottom)`, preventing notch or home-indicator collisions.
4. **Desktop / Tablet Enclosure:** On wider landscape/desktop screens, the UI is cleanly framed in a centered 9:16 smartphone viewport (`max-width: calc(100vh * (9 / 16))`), preventing landscape layout degradation.
