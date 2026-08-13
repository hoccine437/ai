# Zerion Holographic Voice Interface — Compose UI (`ui/zerion`)

Fullscreen, edge-to-edge Android (portrait) particle **head/bust** visualization —
the "face" of Zerion during voice interaction. Jetpack Compose implementation
of the holographic particle UI spec. These files drop into the host Android
project's `ui.zerion` package (no Gradle project lives in this repository).

## Files

| File | Role |
| :--- | :--- |
| `ZerionHomeScreen.kt` | Full-screen portrait screen: EXIT (top-left), centered status label below the bust, invisible manual-listen tap zone over the lower third with mic glyph, safe-area handling, Android lifecycle pause/resume. |
| `ZerionParticleBust.kt` | GPU-friendly renderer: one `drawPoints(PointMode.Points)` call per alpha bucket per frame, preallocated buffers (zero per-frame allocation), frame clock freezes when backgrounded. |
| `ZerionVisualizationController.kt` | The state API (`setState` / `setAudioLevel` / `setProgress` + lifecycle pause/resume). Tool-agnostic: renders only what it is given. |
| `ZerionDeviceTier.kt` | One-time device-tier detection → particle budget + effect quality (ULTRA_LOW 900 / LOW 1500 / MEDIUM 2000 / HIGH 3000). |
| `ZerionParticleField.kt` | Precomputed bust silhouette geometry (contour, neck/shoulders, crown, halo) + renderer inputs (phase seeds, boot stagger, aura classification). |
| `ZerionVisualizationState.kt` | Runtime states `BOOTING / IDLE / LISTENING / THINKING / EXECUTING / LEARNING / SPEAKING / ERROR` with per-state pulse targets. |
| `ZerionAnimations.kt` | Color tokens + timing constants. |
| `ZerionGlowCore.kt` | Face glow region + neck spine geometry spec. |
| `ZerionHud.kt` / `ZerionVisualizationViewModel.kt` | Telemetry + view-state contracts (reused by the controller). |

## State API (tool-agnostic)

```kotlin
val controller = rememberZerionVisualizationController()   // tier-detected

controller.setState(ZerionVisualizationState.LISTENING)
controller.setState(ZerionVisualizationState.SPEAKING, audioLevel = rms) // live RMS 0..1
controller.setState(ZerionVisualizationState.BOOTING, progress = 42)     // init %
controller.setAudioLevel(rms)  // without a state change
controller.setProgress(65)

ZerionHomeScreen(controller, onExit = { /* host back nav */ },
                 onManualListenToggle = { /* POST /api/command START_LISTENING */ })
```

The UI never calls model/tool/runtime APIs. The host orchestration layer pushes
state from the existing runtime channel (`zerion/ui/visualization_adapter.py`):

- `GET /api/state` → `presentation.runtime_state` → `setState(...)`
- `presentation.audio_amplitude_rms` → `setAudioLevel(...)` (speaking)
- `presentation.assembly_percentage` → `setProgress(...)` (assembling)
- `voice_perception.is_listening` → gate `LISTENING` (honest mic state, Slice 10.1)
- `GET /api/stream` (SSE) for event-driven pushes — no polling.

## Required dependencies (host build.gradle)

```kotlin
implementation(platform("androidx.compose:compose-bom:2024.09.00"))
implementation("androidx.compose.ui:ui")
implementation("androidx.compose.foundation:foundation")
implementation("androidx.compose.material3:material3")
implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.0")  // LocalLifecycleOwner
implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.0")      // LifecycleEventObserver
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.0") // StateFlow
```

## Honest verification status

- **Logic-level verified:** the pure geometry, device-tier boundaries, and boot
  assembly math are mirrored and regression-tested from Python
  (`ai-arena-019ff051-ai/tests/test_mobile_compose_ui.py`, following the
  `test_aspect_ratio_9_16.py` convention).
- **Not build-verified:** this repository has no Android/Gradle project, so the
  Kotlin files are not compiled here. They target a standard modern Compose BOM.
- **Not hardware-verified:** no on-device FPS/battery measurement was run. The
  60 fps target on mid-range GPUs and the backgrounding battery behavior are
  design targets, not measured results — verify on real hardware before
  claiming them.
