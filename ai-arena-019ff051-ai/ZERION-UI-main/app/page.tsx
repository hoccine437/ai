"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ApexWorld from "@/components/ApexWorld";
import ApexOverviewPanel from "@/components/ApexOverviewPanel";

/**
 * ZERION-X ASCENDANT — Phone UI
 *
 * The main page wraps the orb world + chat input at the bottom.
 * On Android, the virtual keyboard pushes the input up; we detect this
 * and adapt the layout so the orb shrinks and the chat stays visible.
 */
export default function Home() {
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<{ role: string; text: string }[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  // Auto-scroll chat to latest message
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [chatMessages]);

  // Detect Android keyboard open/close via visualViewport
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;

    const onResize = () => {
      // If viewport height shrinks by more than 150px, keyboard is likely open
      const heightDiff = window.innerHeight - vv.height;
      setIsKeyboardOpen(heightDiff > 150);
    };

    vv.addEventListener("resize", onResize);
    return () => vv.removeEventListener("resize", onResize);
  }, []);

  // Show chat overlay when messages exist
  useEffect(() => {
    if (chatMessages.length > 0) setShowChat(true);
  }, [chatMessages]);

  const handleSend = useCallback(async () => {
    if (!chatInput.trim() || isProcessing) return;
    const userMsg = chatInput.trim();
    setChatInput("");
    setIsProcessing(true);

    setChatMessages((prev) => [...prev, { role: "user", text: userMsg }]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg }),
      });
      const data = await res.json();
      setChatMessages((prev) => [...prev, { role: "zerion", text: data.reply || "I'm thinking about that..." }]);
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: "zerion", text: "Connection to ZERION runtime unavailable. Make sure the Python backend is running." },
      ]);
    } finally {
      setIsProcessing(false);
    }
  }, [chatInput, isProcessing]);

  const handleInputFocus = () => {
    // Scroll chat into view when keyboard opens
    setTimeout(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }, 300);
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
        height: "100dvh", // fallback: older Android WebViews use 100vh via globals.css
        display: "flex",
        flexDirection: "column",
        // Prevent rubber-banding on Android
        overscrollBehavior: "none",
      }}
    >
      {/* Top-left overview HUD */}
      <ApexOverviewPanel />

      {/* The world: orb core + orbiting agent graph */}
      <section
        style={{
          position: "relative",
          flex: isKeyboardOpen ? "0 0 30%" : 1,
          minHeight: 0,
          transition: "flex 0.3s ease",
        }}
      >
        <ApexWorld />
      </section>

      {/* Chat messages overlay — shown when there are messages */}
      {showChat && (
        <div
          ref={chatRef}
          style={{
            position: "relative",
            maxHeight: isKeyboardOpen ? "20vh" : "35vh",
            overflowY: "auto",
            padding: "12px 16px",
            background: "rgba(4,8,15,0.7)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            borderTop: "1px solid rgba(0,229,255,0.08)",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            flexShrink: 0,
            transition: "max-height 0.3s ease",
            // Prevent overscroll on the chat list
            overscrollBehavior: "contain",
          }}
        >
          {chatMessages.map((msg, i) => (
            <div
              key={i}
              style={{
                alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "85%",
                padding: "8px 14px",
                borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                background: msg.role === "user" ? "rgba(0,229,255,0.15)" : "rgba(245,166,35,0.12)",
                border: `1px solid ${msg.role === "user" ? "rgba(0,229,255,0.25)" : "rgba(245,166,35,0.2)"}`,
                color: "#f0ede8",
                fontSize: 13,
                lineHeight: 1.5,
                wordBreak: "break-word",
              }}
            >
              {msg.text}
            </div>
          ))}
        </div>
      )}

      {/* Chat input bar — phone-style at the bottom, stays above keyboard */}
      <div
        style={{
          position: "relative",
          zIndex: 20,
          padding: "8px 12px",
          paddingBottom: "calc(8px + env(safe-area-inset-bottom, 0px))",
          background: "rgba(4,8,15,0.9)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          borderTop: "1px solid rgba(0,229,255,0.15)",
          flexShrink: 0,
        }}
      >
        <form
          ref={formRef}
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          style={{ display: "flex", gap: 8, alignItems: "center" }}
        >
          <input
            ref={inputRef}
            type="text"
            inputMode="text"
            autoComplete="off"
            autoCorrect="on"
            autoCapitalize="sentences"
            spellCheck
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onFocus={handleInputFocus}
            placeholder="Talk to ZERION..."
            style={{
              flex: 1,
              background: "rgba(0,229,255,0.06)",
              border: "1px solid rgba(0,229,255,0.2)",
              borderRadius: 20,
              padding: "10px 16px",
              color: "#f0ede8",
              fontSize: 16, // Minimum 16px prevents Android from zooming on focus
              fontFamily: "var(--font-mono)",
              outline: "none",
              transition: "border-color 0.2s",
              // Prevent iOS text size auto-adjust
              WebkitTextSizeAdjust: "100%",
            }}
            onFocusCapture={(e) => (e.currentTarget.style.borderColor = "rgba(0,229,255,0.5)")}
            onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(0,229,255,0.2)")}
          />
          <button
            type="submit"
            disabled={isProcessing || !chatInput.trim()}
            aria-label="Send message"
            style={{
              width: 44,
              height: 44,
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
              // Minimum touch target for Android (44px)
              minWidth: 44,
              minHeight: 44,
            }}
          >
            {isProcessing ? (
              <span style={{ animation: "pulse 1s infinite" }}>●</span>
            ) : (
              "↑"
            )}
          </button>
        </form>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 1; }
        }
      `}</style>
    </main>
  );
}
