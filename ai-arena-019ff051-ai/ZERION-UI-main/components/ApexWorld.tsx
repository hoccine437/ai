"use client";

/**
 * ZerionWorld — ZERION-X ASCENDANT's main screen.
 * Layers: app-blue backdrop → clickable orb core → ReasoningWeb → OrbStatusBar.
 * The orb's tap cycle drives the whole web (standby → thinking → speaking).
 * Agent roster reflects ZERION's 21 specialized AI agents.
 */

import { useEffect, useRef, useState } from "react";
import ApexHeroOrb, { type OrbState } from "./ApexHeroOrb";
import ReasoningWebJs from "./ReasoningWeb";
import ShaderBackgroundJs from "./ShaderBackground";
import OrbStatusBar from "./OrbStatusBar";

export type NodeSel = { name: string; key: string; color: string };

const ReasoningWeb = ReasoningWebJs as unknown as React.ComponentType<{
  state?: string; trace?: unknown; mode?: string; coreless?: boolean;
  onSelect?: (n: NodeSel) => void; light?: boolean;
}>;
const ShaderBackground = ShaderBackgroundJs as unknown as React.ComponentType<{
  opacity?: number; voiceActive?: boolean; gold?: boolean;
}>;

type AgentInfo = {
  role: string;
  caps: string[];
  asks?: string[];
  status: "online" | "standby" | "integration";
};

/* ZERION's 21 specialized AI agents */
export const ROSTER: { key: string; name: string; color: string }[] = [
  { key: "strategic",     name: "Strategic",     color: "#00e5ff" },
  { key: "deep_reason",   name: "Deep Reason",   color: "#00e5ff" },
  { key: "research",      name: "Research",      color: "#00e5ff" },
  { key: "coding",        name: "Coding",        color: "#00e5ff" },
  { key: "debugging",     name: "Debugging",     color: "#00e5ff" },
  { key: "security",      name: "Security",      color: "#00e5ff" },
  { key: "system",        name: "System",        color: "#00e5ff" },
  { key: "automation",    name: "Automation",    color: "#f5a623" },
  { key: "data_analysis", name: "Data Analysis", color: "#f5a623" },
  { key: "math",          name: "Math",          color: "#f5a623" },
  { key: "planning",      name: "Planning",      color: "#f5a623" },
  { key: "creative",      name: "Creative",      color: "#f5a623" },
  { key: "communication", name: "Communication", color: "#f5a623" },
  { key: "vision",        name: "Vision",        color: "#f5a623" },
  { key: "voice",         name: "Voice/Audio",   color: "#f5a623" },
  { key: "web",           name: "Web/Info",      color: "#f5a623" },
  { key: "financial",     name: "Financial",     color: "#7f9bb3" },
  { key: "simulation",    name: "Simulation",    color: "#7f9bb3" },
  { key: "verification",  name: "Verification",  color: "#7f9bb3" },
  { key: "learning",      name: "Learning",      color: "#7f9bb3" },
  { key: "recovery",      name: "Recovery",      color: "#7f9bb3" },
];

/* Overview data per agent */
export const INFO: Record<string, AgentInfo> = {
  strategic:     { role: "Strategy & Planning", status: "online",
    caps: ["Strategic planning", "Goal decomposition", "Decision optimization"],
    asks: ["Create a plan", "What approach?"] },
  deep_reason:   { role: "Deep Reasoning", status: "online",
    caps: ["Causal analysis", "Logical inference", "Hypothesis generation"],
    asks: ["Analyze deeply", "Why does this happen?"] },
  research:      { role: "Investigation", status: "online",
    caps: ["Information gathering", "Source verification", "Knowledge synthesis"],
    asks: ["Research this", "Find out about..."] },
  coding:        { role: "Programming", status: "online",
    caps: ["Code generation", "Algorithm design", "Code review"],
    asks: ["Write code", "Implement this"] },
  debugging:     { role: "Error Resolution", status: "online",
    caps: ["Bug detection", "Root cause analysis", "Fix verification"],
    asks: ["Debug this", "Fix the error"] },
  security:      { role: "Cybersecurity", status: "online",
    caps: ["Vulnerability scanning", "Permission audit", "Security hardening"],
    asks: ["Security audit", "Check permissions"] },
  system:        { role: "System Control", status: "online",
    caps: ["Process management", "Resource monitoring", "System diagnostics"],
    asks: ["Check system", "What's running?"] },
  automation:    { role: "Workflow Automation", status: "online",
    caps: ["Task automation", "Pipeline creation", "Batch processing"],
    asks: ["Automate this", "Create workflow"] },
  data_analysis: { role: "Data Intelligence", status: "online",
    caps: ["Statistical analysis", "Pattern detection", "Data visualization"],
    asks: ["Analyze data", "Find patterns"] },
  math:          { role: "Mathematics", status: "online",
    caps: ["Calculation", "Formula derivation", "Proof verification"],
    asks: ["Calculate", "Solve this equation"] },
  planning:      { role: "Project Planning", status: "online",
    caps: ["Timeline creation", "Resource allocation", "Milestone tracking"],
    asks: ["Plan this project", "Set timeline"] },
  creative:      { role: "Creative Reasoning", status: "online",
    caps: ["Brainstorming", "Innovation", "Lateral thinking"],
    asks: ["Brainstorm ideas", "Be creative"] },
  communication: { role: "Language & Translation", status: "online",
    caps: ["Translation", "Summarization", "Communication drafting"],
    asks: ["Translate", "Summarize this"] },
  vision:        { role: "Visual Analysis", status: "online",
    caps: ["Image analysis", "Screenshot reading", "Visual pattern detection"],
    asks: ["Analyze image", "Read screenshot"] },
  voice:         { role: "Voice & Audio", status: "online",
    caps: ["Text-to-speech", "Speech recognition", "Audio processing"],
    asks: ["Speak this", "Listen to..."] },
  web:           { role: "Web Intelligence", status: "online",
    caps: ["Web search", "URL fetching", "Content extraction"],
    asks: ["Search web", "Fetch this page"] },
  financial:     { role: "Financial Analysis", status: "standby",
    caps: ["Budget tracking", "Cost analysis", "Financial modeling"],
    asks: ["Analyze costs", "Track budget"] },
  simulation:    { role: "Experimentation", status: "standby",
    caps: ["Hypothesis testing", "Simulation runs", "A/B comparison"],
    asks: ["Test hypothesis", "Simulate outcome"] },
  verification:  { role: "Quality Assurance", status: "online",
    caps: ["Result verification", "Consistency checking", "Validation"],
    asks: ["Verify result", "Is this correct?"] },
  learning:      { role: "Knowledge Acquisition", status: "online",
    caps: ["Knowledge extraction", "Pattern learning", "Experience retention"],
    asks: ["Learn from this", "Remember this"] },
  recovery:      { role: "Error Recovery", status: "online",
    caps: ["Failure analysis", "Strategy adaptation", "Resilient retry"],
    asks: ["Recover from error", "Try another approach"] },
};

const STATUS_LINE: Record<AgentInfo["status"], { color: string; text: string }> = {
  online: { color: "#34d399", text: "Online — ZERION routes work to it automatically" },
  standby: { color: "#c9a84c", text: "Standby — available on demand" },
  integration: { color: "#7f9bb3", text: "Integration — wired into the core" },
};

/* Agent overview card */
export function AgentOverview({ sel, onClose }: { sel: NodeSel; onClose: () => void }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const info = INFO[sel.key] ?? { role: "Specialist", status: "online" as const, caps: ["Part of ZERION core"] };
  const c = sel.color;
  const status = STATUS_LINE[info.status];

  useEffect(() => {
    setPos({ x: Math.max(8, window.innerWidth / 2 - 170), y: Math.max(90, window.innerHeight * 0.16) });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!pos) return;
    panelRef.current?.querySelector<HTMLElement>("button")?.focus();
  }, [pos]);

  if (!pos) return null;
  return (
    <div ref={panelRef} role="dialog" aria-modal="true" aria-label={`${sel.name} agent`} style={{
      position: "fixed", left: pos.x, top: pos.y,
      width: "min(340px, 92vw)", zIndex: 60,
      background: "rgba(4,3,12,0.92)",
      backdropFilter: "blur(24px)",
      border: `1px solid ${c}44`,
      borderRadius: 16,
      boxShadow: `0 0 40px ${c}18, 0 8px 32px rgba(0,0,0,0.6)`,
      overflow: "hidden",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10, padding: "14px 16px",
        borderBottom: `1px solid ${c}22`,
        background: `linear-gradient(135deg, ${c}0a 0%, transparent 100%)`,
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: "50%", background: `${c}14`,
          border: `1px solid ${c}44`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: c, boxShadow: `0 0 10px ${c}` }} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: "0.08em", color: c }}>{sel.name.toUpperCase()}</div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{info.role}</div>
        </div>
        <button onClick={onClose} aria-label="Close" style={{
          background: "none", border: "none", color: "rgba(255,255,255,0.3)", cursor: "pointer", fontSize: 18, padding: "6px 8px",
        }}>×</button>
      </div>

      <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div style={{ fontSize: 9, letterSpacing: "0.14em", color: `${c}99`, marginBottom: 8, fontFamily: "var(--font-mono)" }}>CAPABILITIES</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {info.caps.map((cap) => (
              <div key={cap} style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
                <div style={{ width: 3, height: 3, borderRadius: "50%", background: `${c}99`, marginTop: 6, flexShrink: 0 }} />
                <span style={{ fontSize: 11.5, color: "rgba(255,255,255,0.6)", lineHeight: 1.55 }}>{cap}</span>
              </div>
            ))}
          </div>
        </div>

        {info.asks && info.asks.length > 0 && (
          <div>
            <div style={{ fontSize: 9, letterSpacing: "0.14em", color: `${c}99`, marginBottom: 8, fontFamily: "var(--font-mono)" }}>EXAMPLE REQUESTS</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {info.asks.map((task) => (
                <span key={task} style={{
                  padding: "4px 10px", background: `${c}0d`, border: `1px solid ${c}2a`,
                  borderRadius: 20, fontSize: 10.5, color: `${c}cc`,
                }}>{task}</span>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 7, borderTop: `1px solid ${c}1a`, paddingTop: 12 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: status.color, boxShadow: `0 0 8px ${status.color}` }} />
          <span style={{ fontSize: 9.5, letterSpacing: "0.1em", color: "rgba(255,255,255,0.45)", textTransform: "uppercase" }}>{status.text}</span>
        </div>
      </div>
    </div>
  );
}

/* The ZERION world */
export default function ApexWorld() {
  const [selected, setSelected] = useState<NodeSel | null>(null);
  const [reduced, setReduced] = useState(false);
  const [showState, setShowState] = useState<OrbState>("idle");
  const showTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const orbState: OrbState = showState;

  const boost = () => {
    const next: OrbState = showState === "idle" ? "thinking" : showState === "thinking" ? "speaking" : "idle";
    setShowState(next);
    if (showTimer.current) clearTimeout(showTimer.current);
    showTimer.current = setTimeout(() => setShowState("idle"), 8000);
  };
  useEffect(() => () => { if (showTimer.current) clearTimeout(showTimer.current); }, []);

  const openAgent = (n: NodeSel) => setSelected(n);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const webState = orbState === "thinking" ? "processing" : orbState === "speaking" ? "speaking" : "standby";

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", userSelect: "none" }}>
      {/* backdrop */}
      <div aria-hidden="true" style={{
        position: "absolute", inset: 0,
        background: "radial-gradient(ellipse 95% 88% at 50% 42%, #122c43 0%, #0c1d30 38%, #07111f 72%, #050b14 100%)",
      }} />

      {/* background waves */}
      {!reduced && (
        <div aria-hidden="true" style={{ position: "absolute", inset: 0, zIndex: 0 }}>
          <ShaderBackground opacity={0.12} voiceActive={orbState === "speaking"} gold={false} />
        </div>
      )}

      {/* cyan LIGHT-CAST */}
      <div aria-hidden="true" style={{
        position: "absolute", inset: 0, zIndex: 1, pointerEvents: "none", mixBlendMode: "screen",
        background: `radial-gradient(circle at 50% 42%, rgba(13,210,255,${orbState === "speaking" ? 0.30 : 0.18}) 0%, rgba(13,170,228,0.08) 30%, rgba(8,17,31,0) 62%)`,
        transition: "background 0.6s ease",
      }} />

      {/* reasoning web — ZERION's 21 agents */}
      <div aria-hidden="true" style={{ position: "absolute", inset: 0, zIndex: 2, pointerEvents: "none" }}>
        <ReasoningWeb state={webState} mode="full" coreless onSelect={(n: NodeSel) => openAgent(n)} />
      </div>

      {/* accessible agent list */}
      <nav className="visually-hidden" aria-label="ZERION agents">
        <ul>
          {ROSTER.map((a) => (
            <li key={a.key}>
              <button type="button" onClick={() => openAgent({ key: a.key, name: a.name, color: a.color })}>
                {a.name} — {INFO[a.key]?.role ?? "Specialist"}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* the core orb */}
      <div style={{ position: "absolute", left: "50%", top: "50%", width: "min(560px, 58vw)", height: "min(500px, 56vw, 70vh)", transform: "translate(-50%, -50%)", zIndex: 3, pointerEvents: "none" }}>
        <ApexHeroOrb state={orbState} interactive={false} />
      </div>

      {/* central tap disc */}
      <div
        role="button"
        tabIndex={0}
        aria-label="ZERION core — tap to activate"
        onClick={boost}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); boost(); } }}
        onMouseDown={(e) => e.preventDefault()}
        style={{
          position: "absolute", left: "50%", top: "50%", transform: "translate(-50%, -50%)",
          width: "min(340px, 36vw)", height: "min(340px, 36vw)", borderRadius: "50%",
          zIndex: 4, cursor: "pointer", background: "transparent", border: "none",
        }}
      />

      {/* status bar */}
      <OrbStatusBar state={orbState} />

      {/* agent overview card */}
      {selected && <AgentOverview sel={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
