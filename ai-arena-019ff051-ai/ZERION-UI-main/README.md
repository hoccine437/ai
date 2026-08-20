# ZERION-UI — Phone Interface

A phone-optimized Next.js 15 + React 19 web UI for ZERION-X ASCENDANT.

Based on [APEX-UI](https://github.com/RubenM1990/APEX-UI) (MIT), rebranded and adapted for ZERION.

## Features

- **Orb visualization** — animated 3D core with 21 orbiting agent nodes
- **Chat input** — talk to ZERION naturally from your phone
- **21 AI agents** — visual constellation of ZERION's specialized agents
- **100 tools** — system status overview
- **PWA** — install on your Android home screen
- **Offline-ready** — connects to local ZERION Python backend

## Setup on Android (Termux)

```bash
# 1. Install Node.js in Termux
pkg install nodejs

# 2. Navigate to the UI directory
cd ~/ai-arena-019ff051-ai/ZERION-UI-main

# 3. Install dependencies
npm install

# 4. Start the dev server (binds to 0.0.0.0 for phone access)
npm run dev

# 5. Open in your phone browser
# http://localhost:3000
```

## Start the ZERION Backend

The UI connects to ZERION's Python cognitive runtime on port 8080:

```bash
cd ~/ai-arena-019ff051-ai
python main.py
```

## Install as PWA

1. Open `http://localhost:3000` in Chrome
2. Tap the menu (⋮) → "Add to Home screen"
3. ZERION will appear as a standalone app

## Tech Stack

- Next.js 15 + React 19
- Three.js + React Three Fiber (3D orb)
- WebGL shader background
- Pure SVG reasoning web (21 agents)
- CSS animations + keyframes

## Credits

- Orb design: [APEX-UI](https://github.com/RubenM1990/APEX-UI) by RubenM1990 (MIT)
- Shader background: adapted from 21st.dev community component
