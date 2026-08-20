"use client";

/**
 * ZERION Overview panel — top-left HUD showing system status, clock, and agent count.
 * Shows ZERION's identity and live system information.
 */

import { useEffect, useState } from "react";
import { Cpu, Zap, Shield } from "lucide-react";

const ACCENT = "#00e5ff";

function Clock() {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(id);
  }, []);

  if (!now) return <div style={{ height: 48 }} />;
  const time = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const date = now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 20, flexWrap: "wrap" }}>
      <div>
        <div style={{ fontSize: 28, fontWeight: 300, letterSpacing: "0.04em", color: "#f0ede8", lineHeight: 1, textShadow: `0 0 22px ${ACCENT}33` }}>{time}</div>
        <div style={{ fontSize: 10, letterSpacing: "0.2em", color: "rgba(240,237,232,0.55)", marginTop: 4, textTransform: "uppercase" }}>{date}</div>
      </div>
    </div>
  );
}

type InfoTile = { icon: typeof Cpu; label: string; value: string };

const INFO_TILES: InfoTile[] = [
  { icon: Cpu, label: "AGENTS", value: "21" },
  { icon: Zap, label: "TOOLS", value: "100" },
  { icon: Shield, label: "MODE", value: "LOCAL" },
];

export default function ApexOverviewPanel() {
  const [open, setOpen] = useState(false);
  const FIL = open ? 380 : 260;
  const FIL_CAP = "calc(100vw - 40px)";

  const tileStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 10, padding: "9px 12px",
    background: "rgba(6,14,26,0.72)", border: `1px solid ${ACCENT}2a`,
    borderRadius: 10, cursor: "default",
    backdropFilter: "blur(8px)",
    color: "rgba(240,237,232,0.9)", width: "100%",
  };

  return (
    <div className="apex-overview" style={{ pointerEvents: "none" }}>
      {/* glow cone */}
      <div style={{
        position: "absolute", top: 14, left: 8, width: "min(420px, 94vw)", height: 200, pointerEvents: "none",
        background: `radial-gradient(ellipse 48% 70% at 46% 0%, ${ACCENT}${open ? "55" : "28"}, ${ACCENT}0a 46%, transparent 72%)`,
        filter: "blur(10px)", transition: "all .5s ease",
      }} />

      {/* filament + label */}
      <div
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen((o) => !o); } }}
        role="button" tabIndex={0} aria-label="Toggle ZERION info panel" aria-expanded={open}
        style={{ position: "relative", height: 40, cursor: "pointer", pointerEvents: "auto", userSelect: "none" }}
      >
        <div style={{
          position: "absolute", top: 14, left: 8, width: `min(${FIL}px, ${FIL_CAP})`, height: 2, borderRadius: 2,
          background: "#a5f3fc",
          boxShadow: `0 0 10px ${ACCENT}, 0 0 26px ${ACCENT}${open ? ", 0 0 54px " + ACCENT : ""}`,
          transition: "all .5s ease",
        }} />
        <div style={{
          position: "absolute", top: 11, left: open ? `min(${FIL}px, ${FIL_CAP})` : 6, width: 8, height: 8, borderRadius: "50%",
          background: "#e0fbff", boxShadow: `0 0 10px ${ACCENT}, 0 0 18px ${ACCENT}`,
          transition: "left .5s ease", pointerEvents: "none",
        }} />
        <span style={{
          position: "absolute", top: 20, left: 10, fontFamily: "var(--font-mono)", fontSize: 9, letterSpacing: "0.34em",
          color: `rgba(165,243,252,${open ? 0.9 : 0.55})`, transition: "color .4s",
        }}>ZERION-X</span>
      </div>

      {/* clock + info tiles */}
      <div style={{ paddingLeft: 14, paddingTop: 6, width: "fit-content", pointerEvents: "auto" }}>
        <Clock />

        {open && (
          <div style={{ marginTop: 12, width: 220, display: "flex", flexDirection: "column", gap: 6 }}>
            {INFO_TILES.map(({ icon: Icon, label, value }) => (
              <div key={label} style={tileStyle}>
                <span style={{ display: "flex", color: ACCENT }}><Icon size={14} /></span>
                <span style={{ flex: 1, fontSize: 10, letterSpacing: "0.08em", color: "rgba(240,237,232,0.6)" }}>{label}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: ACCENT, fontFamily: "var(--font-mono)" }}>{value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
