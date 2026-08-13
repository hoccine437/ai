# ZERION-X GENESIS ×10 — Mobile Runtime & Android/Termux Integration
**Subsystem:** `zerion/integration/android/`  
**Date:** 2026-08-11  

---

## 1. Mobile Power Profiles & Resource Governor

- **`ULTRA_LOW`:** Battery $< 15\%$, single concurrency worker, REFLEX compute mode.
- **`BATTERY_SAVER`:** Battery $< 30\%$, FAST mode, throttled background discovery.
- **`BALANCED`:** Standard mobile operation ($30\% - 80\%$), NORMAL compute allocation.
- **`PERFORMANCE`:** Plugged into AC, deep experimentation allowed.
- **`DEEP`:** Unrestricted compute on AC.
