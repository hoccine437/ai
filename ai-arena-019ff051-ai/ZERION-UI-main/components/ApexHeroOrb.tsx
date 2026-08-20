"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import ApexOrb from "./ApexOrb";
import "./apex-orb.css";

// three/fiber must never SSR
const ApexCore3D = dynamic(() => import("./ApexCore3D"), { ssr: false });

const STAGE_W = 900;
const STAGE_H = 900;

export type OrbState = "idle" | "thinking" | "speaking";

export default function ApexHeroOrb({ state: controlled, onStateChange, interactive = true }: { state?: OrbState; onStateChange?: (s: OrbState) => void; interactive?: boolean } = {}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.6);
  const [inner, setInner] = useState<OrbState>("idle");
  const state = controlled ?? inner;
  const [reducedMotion, setReducedMotion] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const update = (s: OrbState) => { setInner(s); onStateChange?.(s); };

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReducedMotion(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const measure = () => {
      setScale(Math.min(1.6, el.clientWidth / 560, el.clientHeight / 540));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const boost = () => {
    const next: OrbState = state === "idle" ? "thinking" : state === "thinking" ? "speaking" : "idle";
    update(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => update("idle"), 8000);
  };

  return (
    <div
      ref={boxRef}
      {...(interactive
        ? {
            onClick: boost,
            onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); boost(); } },
            onMouseDown: (e: React.MouseEvent) => e.preventDefault(),
            role: "button",
            tabIndex: 0,
            "aria-label": "ZERION core — tap to activate",
          }
        : { "aria-hidden": true as const })}
      style={{ position: "relative", width: "100%", height: "100%", cursor: interactive ? "pointer" : "default", pointerEvents: interactive ? "auto" : "none", borderRadius: "50%", userSelect: "none" }}
    >
      <div
        data-apex-stage
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          width: STAGE_W,
          height: STAGE_H,
          transform: `translate(-50%, -50%) scale(${scale})`,
        }}
      >
        <div style={{ position: "absolute", left: 0, top: (STAGE_H - 520) / 2, pointerEvents: "none" }}>
          <ApexOrb state={state} variant="frame" onRingClick={undefined} />
        </div>
        {!reducedMotion && <ApexCore3D state={state} variant="particles" contained onClick={undefined} />}
      </div>
    </div>
  );
}
