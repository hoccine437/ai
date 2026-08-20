# ZERION-UI

**ZERION-X ASCENDANT** — autonomous cognitive orb + reasoning-graph interface for Android/Termux.

The animated orb at the center represents ZERION's core intelligence. Tap it to cycle states (idle → thinking → speaking). The reasoning web shows ZERION's **21 specialized AI agents** orbiting the core. Click any agent node to see its capabilities.

Built with Next.js 15 + React 19. Runtime deps: `lucide-react`, `three`, `@react-three/fiber`, `@react-three/postprocessing`.

## Quick Start

```bash
npm install
npm run dev
# open http://localhost:3000
```

## What's Inside

| Piece | What it does |
|-------|--------------|
| `ApexOrb` | Golden ring frame, waveform and orbit dots (pure SVG) |
| `ApexCore3D` | Cyan particle core (`react-three-fiber` + bloom) |
| `ApexHeroOrb` | SVG ring + particle core, scaled to fit |
| `ReasoningWeb` | Agent constellation — 21 ZERION agents with circuit traces |
| `OrbStatusBar` | Equalizer + STANDBY cluster at the bottom |
| `ShaderBackground` | Animated WebGL plasma waves backdrop |
| `ApexWorld` | Composes everything; tap-state cycle + agent overview cards |
| `ApexOverviewPanel` | Top-left HUD: clock + system info |
| `/api/chat` | Bridge to ZERION Python cognitive runtime |
| `/api/weather` | Keyless open-meteo weather proxy |

## ZERION's 21 Agents

Strategic · Deep Reason · Research · Coding · Debugging · Security · System · Automation · Data Analysis · Math · Planning · Creative · Communication · Vision · Voice/Audio · Web/Info · Financial · Simulation · Verification · Learning · Recovery

## Phone UI

Designed for Android/Termux:
- Mobile-first viewport (no pinch zoom)
- Safe area insets for notched phones
- Touch-optimized tap targets
- Chat input at the bottom
- `100dvh` for proper mobile height

## License

MIT
