# GGUF models — drop them here

This is the canonical local-model folder for Zerion. Save your `.gguf`
file(s) directly in this directory (subfolders like `models/qwen/` work too —
discovery is recursive).

```
zerion-compose-mobile-ui/models/your-model.gguf
```

## How the runtime finds this folder

`LocalGGUFProvider` / `LocalModelDiscovery` resolve the model directory in
this order:

1. `ZERION_MODELS_DIR` env var, if set (absolute or relative path).
2. `zerion-compose-mobile-ui/models` — this folder — when it exists
   (checked as a sibling of the Python runtime, and inside the current dir).
3. `models/` next to the runtime (legacy default).

So on Termux/desktop you can either drop the model here and run normally, or
point the runtime explicitly:

```bash
ZERION_MODELS_DIR="$HOME/zerion-compose-mobile-ui/models" python3 main.py --ui
```

## Verify it was picked up

From the runtime directory (`ai-arena-019ff051-ai/`):

```bash
python3 main.py --models
```

The file must be a real GGUF (starts with the `GGUF` magic header), ≤ 8 GiB,
or it is reported as CORRUPTED/OVERSIZED rather than silently used.
