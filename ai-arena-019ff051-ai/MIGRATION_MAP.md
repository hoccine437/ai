# ZERION UI TOTAL REPLACEMENT — Migration Map
**Project:** ZERION-X GENESIS  
**Date:** 2026-08-11  

---

## Migration Mapping Table

```
OLD UI COMPONENT (actual file/class)            →  NEW UI COMPONENT / OUTCOME
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
zerion/ui/index.html (Legacy Canvas UI)         →  zerion/ui/index.html (Unified Particle-Bust Cybernetic UI)
zerion/ui/state_bridge.py (UIStateBridge)       →  zerion/ui/state_bridge.py (Upgraded with 8-State Enum & RMS)
zerion/ui/server.py (GenesisWebServer)          →  zerion/ui/server.py (Enhanced REST + State Stream Server)
ui/zerion/ZerionHomeScreen.kt (Kotlin Spec)     →  ui/zerion/ZerionHomeScreen.kt (New Android Compose Target)
ui/zerion/ZerionVisualization.kt (Compose)      →  ui/zerion/ZerionVisualization.kt (New Particle Composable)
ui/zerion/ZerionParticleField.kt (Positions)    →  ui/zerion/ZerionParticleField.kt (Precomputed Bust Silhouette)
ui/zerion/ZerionGlowCore.kt (Radial Glow)       →  ui/zerion/ZerionGlowCore.kt (Wave-Stack Face/Neck Glow)
ui/zerion/ZerionHud.kt (Telemetry HUD)          →  ui/zerion/ZerionHud.kt (Monospace HUD & Top-Start Control)
ui/zerion/ZerionVisualizationState.kt (Enum)    →  ui/zerion/ZerionVisualizationState.kt (8 States Lifecycle)
ui/zerion/ZerionVisualizationViewModel.kt       →  ui/zerion/ZerionVisualizationViewModel.kt (StateFlow Bridge)
ui/zerion/ZerionAnimations.kt (Specs)           →  ui/zerion/ZerionAnimations.kt (Interpolation & Easing Specs)
zerion/cli.py (CLI Dashboard commands)          →  zerion/cli.py (Non-UI logic preserved; --ui routes to unified UI)
zerion/benchmarks/scoreboard.py (ASCII HUD)     →  zerion/benchmarks/scoreboard.py (Non-UI logic preserved as logger)
```

---

## Validation Rule

No legacy visual shell remains reachable through normal navigation. The application has **exactly one primary user-facing UI**: the unified particle-based cybernetic humanoid visualization.
