import { NextResponse } from "next/server";

/**
 * ZERION Chat API — bridges the Next.js UI to the Python cognitive runtime.
 *
 * On Android/Termux, the ZERION backend runs as a Python process.
 * This API proxies chat messages to the backend's HTTP endpoint.
 *
 * The Python backend must expose POST /api/chat with:
 *   Request:  { "message": "string" }
 *   Response: { "reply": "string" }
 *
 * Fallback: if the backend is unreachable, returns a helpful offline message.
 */

// On Termux/Android, the Python backend listens on this port
const ZERION_BACKEND = process.env.ZERION_BACKEND_URL || "http://127.0.0.1:8080";

// Also try the common alternate ports
const BACKEND_URLS = [
  ZERION_BACKEND,
  "http://127.0.0.1:8080",
  "http://127.0.0.1:5000",
  "http://127.0.0.1:3001",
];

async function tryBackend(message: string): Promise<string | null> {
  for (const base of BACKEND_URLS) {
    try {
      const res = await fetch(`${base}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: AbortSignal.timeout(45000), // 45s for model inference
      });

      if (res.ok) {
        const data = await res.json();
        return data.reply || data.output || data.response || data.text || null;
      }
    } catch {
      // This URL didn't work, try the next one
      continue;
    }
  }
  return null;
}

export async function POST(request: Request) {
  try {
    const { message } = await request.json();

    if (!message || typeof message !== "string") {
      return NextResponse.json({ reply: "Please send a message." }, { status: 400 });
    }

    // Try to connect to ZERION's Python cognitive runtime
    const reply = await tryBackend(message);

    if (reply) {
      return NextResponse.json({ reply });
    }

    // All backends unreachable
    return NextResponse.json({
      reply:
        "ZERION backend not reachable. On Android/Termux, start the backend first:\n" +
        "  cd ~/ai-arena-019ff051-ai && python main.py\n\n" +
        "Then open this UI in your browser.",
    });
  } catch (err: unknown) {
    const isTimeout = err instanceof Error && err.name === "TimeoutError";
    return NextResponse.json({
      reply: isTimeout
        ? "ZERION is processing a complex task — please try again in a moment."
        : "Error connecting to ZERION. Please check that the Python backend is running.",
    });
  }
}
