# ZERION-X — GENESIS UI Architecture & State Protocol
**Subsystem:** `zerion/ui/`  
**Date:** 2026-08-11  

---

## 1. Clean Separation of Visuals and Cognition

The visual layer in `zerion/ui/` maintains a zero-business-logic boundary:
- **`zerion/ui/state_bridge.py`**: Subscribes to runtime flywheel events and translates execution traces into `CognitiveUIState`.
- **`zerion/ui/index.html`**: HTML5 Canvas rendering engine with double-buffered particle animations and hardware-accelerated volumetric glow.
- **`zerion/ui/server.py`**: Lightweight asynchronous HTTP server binding to `0.0.0.0:8080` to provide live previews across desktop, tablet, and mobile (Termux) environments.
