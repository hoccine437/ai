"use client";

import { useState, useRef, useEffect } from "react";
import ApexWorld from "@/components/ApexWorld";
import ApexOverviewPanel from "@/components/ApexOverviewPanel";

export default function Home() {
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<{ role: string; text: string }[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll chat
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [chatMessages]);

  const handleSend = async () => {
    if (!chatInput.trim() || isProcessing) return;
    const userMsg = chatInput.trim();
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", text: userMsg }]);
    setIsProcessing(true);

    try {
      // Connect to ZERION cognitive runtime via the existing Python backend
      // On Android/Termux, the backend runs on localhost:8080
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg }),
      });
      const data = await res.json();
      setChatMessages((prev) => [...prev, { role: "zerion", text: data.reply || "I'm thinking about that..." }]);
    } catch {
      setChatMessages((prev) => [...prev, { role: "zerion", text: "Connection to ZERION runtime unavailable." }]);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <main
      id="main"
      style={{
        background: "#04080f",
        color: "#f0ede8",
        position: "relative",
        overflow: "hidden",
        width: "100vw",
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Top-left overview HUD */}
      <ApexOverviewPanel />

      {/* The world: orb core + orbiting agent graph */}
      <section style={{ position: "relative", flex: 1, minHeight: 0 }}>
        <ApexWorld />
      </section>

      {/* Chat input bar — phone-style at the bottom */}
      <div
        style={{
          position: "relative",
          zIndex: 20,
          padding: "8px 12px calc(8px + var(--safe-bottom, 0px))",
          background: "rgba(4,8,15,0.85)",
          backdropFilter: "blur(12px)",
          borderTop: "1px solid rgba(0,229,255,0.15)",
        }}
      >
        <form
          onSubmit={(e) => { e.preventDefault(); handleSend(); }}
          style={{ display: "flex", gap: 8, alignItems: "center" }}
        >
          <input
            ref={inputRef}
            type="text"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder="Talk to ZERION..."
            style={{
              flex: 1,
              background: "rgba(0,229,255,0.06)",
              border: "1px solid rgba(0,229,255,0.2)",
              borderRadius: 20,
              padding: "10px 16px",
              color: "#f0ede8",
              fontSize: 14,
              fontFamily: "var(--font-mono)",
              outline: "none",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(0,229,255,0.5)")}
            onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(0,229,255,0.2)")}
          />
          <button
            type="submit"
            disabled={isProcessing || !chatInput.trim()}
            style={{
              width: 40,
              height: 40,
              borderRadius: "50%",
              border: "1px solid rgba(0,229,255,0.3)",
              background: isProcessing ? "rgba(0,229,255,0.1)" : "rgba(0,229,255,0.15)",
              color: "#00e5ff",
              fontSize: 18,
              cursor: isProcessing ? "wait" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "all 0.2s",
              flexShrink: 0,
            }}
          >
            {isProcessing ? "..." : "↑"}
          </button>
        </form>
      </div>

      {/* Chat messages overlay — shown when there are messages */}
      {chatMessages.length > 0 && (
        <div
          ref={chatRef}
          style={{
            position: "absolute",
            bottom: 70,
            left: 0,
            right: 0,
            maxHeight: "40vh",
            overflowY: "auto",
            padding: "12px 16px",
            background: "rgba(4,8,15,0.7)",
            backdropFilter: "blur(8px)",
            zIndex: 19,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {chatMessages.map((msg, i) => (
            <div
              key={i}
              style={{
                alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "80%",
                padding: "8px 14px",
                borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                background: msg.role === "user"
                  ? "rgba(0,229,255,0.15)"
                  : "rgba(245,166,35,0.12)",
                border: `1px solid ${msg.role === "user" ? "rgba(0,229,255,0.25)" : "rgba(245,166,35,0.2)"}`,
                color: "#f0ede8",
                fontSize: 13,
                lineHeight: 1.5,
              }}
            >
              {msg.text}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
