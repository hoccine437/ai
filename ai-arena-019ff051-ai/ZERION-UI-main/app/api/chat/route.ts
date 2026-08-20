import { NextResponse } from "next/server";

/**
 * ZERION Chat API — bridges the Next.js UI to the Python cognitive runtime.
 *
 * On Android/Termux, the ZERION backend runs as a Python process.
 * This API proxies chat messages to the backend's WebSocket or HTTP bridge.
 *
 * Fallback: if the backend is unreachable, returns a helpful offline message.
 */

const ZERION_BACKEND = process.env.ZERION_BACKEND_URL || "http://127.0.0.1:8080";

export async function POST(request: Request) {
  try {
    const { message } = await request.json();

    if (!message || typeof message !== "string") {
      return NextResponse.json({ reply: "Please send a message." }, { status: 400 });
    }

    // Try to connect to ZERION's Python cognitive runtime
    // The backend exposes a /chat endpoint when running with --ui
    const res = await fetch(`${ZERION_BACKEND}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal: AbortSignal.timeout(30000), // 30s timeout for model inference
    });

    if (res.ok) {
      const data = await res.json();
      return NextResponse.json({ reply: data.reply || data.output || data.response || "..." });
    }

    // Backend returned non-200 — try the WebSocket bridge format
    return NextResponse.json({
      reply: "ZERION runtime is active but the chat bridge returned an unexpected response.",
    });
  } catch (err: unknown) {
    // Backend unreachable — common on first launch or when the Python process isn't running
    const isTimeout = err instanceof Error && err.name === "TimeoutError";
    return NextResponse.json({
      reply: isTimeout
        ? "ZERION is processing a complex task — please try again in a moment."
        : "ZERION backend not reachable. On Android, start with: python main.py --ui",
    });
  }
}
