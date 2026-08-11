# ZERION-X Ω — Model Economy & GGUF Discovery Specification
**Subsystem:** `zerion/intelligence_forge/model_economy/`  
**Date:** 2026-08-11  

---

## 1. Multi-Tier Model Infrastructure

The `ModelEconomy` manages foundational AI models as interchangeable execution organs:
1. **OpenAI Intelligence Tier:** `openai_gpt4o` (deep reasoning) and `openai_gpt4o_mini` (fast structured output).
2. **Local GGUF Discovery:** Automatically discovers `.gguf` quantized models placed in `models/` directory.
3. **Deterministic Local Fallback:** `deterministic_local` executes invariant checks and procedural shortcuts with zero network dependency.
