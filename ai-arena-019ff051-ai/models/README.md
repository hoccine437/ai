# ZERION X — LOCAL MODEL DIRECTORY (`models/`)

This directory is the **canonical local model directory**. ZERION scans it
automatically at startup (`LocalModelDiscovery`) and discovers every supported
model file whose name ends in `.gguf` (recursive scan, GGUF-magic validation,
duplicate/oversize/path-escape rejection).

## Usage

Drop one or more GGUF files here, for example:

```
models/
    qwen2.5-1.5b-q4_k_m.gguf
    llama-3.2-1b-q4_k_m.gguf
```

- No model filename is hard-coded anywhere — discovery is by extension.
- With one model, it is used. With several, selection is deterministic:
  explicit `model_id` wins, otherwise the smallest valid model (fastest load
  on constrained devices) is preferred; routing is observable in `reason`.
- If no `.gguf` file exists, the runtime reports
  `NO_LOCAL_MODEL_AVAILABLE` — it never pretends a model is loaded.

## Inference backend

`LocalGGUFProvider` (through the canonical `CognitiveModelProvider` boundary)
uses the first REAL backend it finds:

1. `llama-cpp-python` (`pip install llama-cpp-python`) — desktop/server,
2. `llama.cpp` CLI on `PATH` (`llama-cli` / `main`) — Termux/mobile:
   `pkg install llama-cpp` provides a prebuilt `llama-cli` (see
   `../TERMUX.md`; do NOT `pip install llama-cpp-python` on Termux — no
   Android aarch64 wheels, and pip's source build of cmake fails on iconv).

If neither backend exists, generation returns an honest structured
`MODEL_LOAD_FAILURE` naming the missing piece — never canned text.
