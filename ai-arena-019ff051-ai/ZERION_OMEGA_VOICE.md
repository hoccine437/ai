# ZERION-X Ω — Voice-First & Gemini Audio Interface Substrate
**Subsystem:** `zerion/voice/`  
**Date:** 2026-08-11  

---

## 1. Gemini Voice & Interaction Architecture

- **Microphone $\to$ VAD $\to$ Layered Wake Word ("Zerion" / "Hey Zerion") $\to$ Intelligence Foundry Brain $\to$ Audio Output.**
- **Natural Interruption:** Speech energy $> 0.15\text{ RMS}$ during output audio immediately cancels active playback and transitions back to `LISTENING`.
- **Audio-Reactivity:** Output speech RMS directly drives the expansion and pulsation frequency of the warm golden cognitive core.
