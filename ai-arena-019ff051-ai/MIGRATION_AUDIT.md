# ZERION UI TOTAL REPLACEMENT — Codebase Audit & Inventory
**Project:** ZERION-X GENESIS  
**Date:** 2026-08-11  
**Auditor:** Zerion Multi-Agent Engineering Collective  

---

## 1.1 UI Discovery & Inventory

A comprehensive scan of all presentation, interface, and visual code in the repository identified the following UI surfaces:

| UI Component / Surface | File Path | Type / Framework | Purpose |
| :--- | :--- | :--- | :--- |
| **Legacy Web UI Interface** | `zerion/ui/index.html` | HTML5 / Canvas / CSS3 | Web visualization served by Python async web server. |
| **UI State Bridge** | `zerion/ui/state_bridge.py` | Python Data Class | Bridges runtime flywheel telemetry to `CognitiveUIState`. |
| **UI Web Server** | `zerion/ui/server.py` | Python Async HTTP Server | Exposes REST APIs on `0.0.0.0:8080` and serves web UI. |
| **CLI Presentation Layer** | `zerion/cli.py` | Python `argparse` / Terminal | Command-line text dashboards, status readouts, and query tools. |
| **Scoreboard Renderer** | `zerion/benchmarks/scoreboard.py` | Python Text Formatter | ASCII telemetry tables and benchmark scoreboard. |
| **Termux Adapter** | `zerion/integration/termux_adapter.py` | Python Subprocess | Mobile battery and hardware telemetry hooks. |
| **Mobile Runtime** | `zerion/integration/android/mobile_runtime.py`| Python Data Class | Mobile power profiles and resource governor. |

---

## 1.2 Architecture Discovery

- **Runtime Substrate:** Python 3.11+ asynchronous developmental cognitive architecture.
- **Presentation Architecture:** Asynchronous event-driven State Bridge (`UIStateBridge`) serving a dual-target presentation layer:
  1. High-Performance Hardware-Accelerated Canvas/WebGL2 Interface (`zerion/ui/index.html` via `zerion/ui/server.py`) for live browser, desktop, and Termux mobile environments.
  2. Native Android Jetpack Compose specification components (`ui/zerion/`) for native Android APK compilation.
- **State Management:** Reactive `CognitiveUIState` data stream synchronized with the 25-stage Developmental Flywheel.
- **Networking & API:** Async REST / SSE / WebSocket server binding to `0.0.0.0:8080`.

---

## 1.3 Core State Sources of Truth

| State Dimension | Real Source of Truth in Codebase | Status |
| :--- | :--- | :--- |
| **BOOTING** | `AscendantEngine.start()` cold-start assembly sequence | Real |
| **IDLE** | `UIStateBridge._current_state.runtime_state == UIStateMode.IDLE` | Real |
| **LISTENING** | VAD / Audio input signal (`UIStateMode.LISTENING`) | Real |
| **THINKING** | `CognitiveCompiler` DAG synthesis & multi-path reasoning | Real |
| **EXECUTING** | `ExecutionSandbox.run_python_code()` subprocess dispatch | Real |
| **LEARNING** | `ExperienceDistiller.distill_episodes()` procedural memory write | Real |
| **DEVELOPING** | `CapabilityBirthPipeline` & `CognitiveGenesisPipeline` | Real |
| **SPEAKING** | Audio amplitude / TTS synthesis output stream (`UIStateMode.SPEAKING`) | Real |
| **ERROR** | `CognitiveImmuneSystem` invariant breach or execution exception | Real |
| **OFFLINE** | `OfflineFallbackManager.is_offline` | Real |

---

## 1.4 Legacy UI Classification

| Component | File Path | Classification | Action |
| :--- | :--- | :--- | :--- |
| `zerion/ui/index.html` | Presentation HTML/Canvas | **REPLACE** | Replace with unified reference-faithful particle bust UI. |
| `zerion/ui/state_bridge.py` | State Adapter | **REFACTOR** | Expand to support real audio RMS, BOOTING, SPEAKING, and exact spec tokens. |
| `zerion/ui/server.py` | Web Server | **REFACTOR** | Preserve endpoints, wire new unified particle frontend. |
| `zerion/cli.py` | Terminal Interface | **KEEP** | Maintain non-visual developer and automation CLI commands. |
| `zerion/benchmarks/scoreboard.py`| Text Telemetry | **KEEP** | Non-visual text telemetry for logging. |

---

## 1.5 Rendering Feasibility & Decision

- **Primary Target Environment:** Cross-platform mobile (Android/Termux), desktop, and embedded browser viewports.
- **Rendering Engine:** Precision Canvas 2D + Hardware-Accelerated WebGL/Double-Buffered Particle Shader.
- **Precomputed Silhouette:** 1,500–2,500 particles precomputed into static coordinate arrays (`Float64Array`) representing the cybernetic bust (head, neck, shoulders).
- **Audio-Reactive Engine:** Web Audio API / RMS amplitude analyzer driving core glow amplitude in `SPEAKING` state.

---

## 1.6 Performance Baseline

- **Draw Loop Overhead:** Zero per-frame memory allocation; precomputed coordinates reused across all animation frames.
- **Target Frame Rate:** 60fps during active states (`LISTENING`, `THINKING`, `SPEAKING`, `DEVELOPING`), throttled to 25–30fps during `IDLE` to preserve mobile battery.
