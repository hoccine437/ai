import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ZERION-X ASCENDANT",
  description:
    "ZERION autonomous cognitive orb — 21 AI agents, 100 tools, local offline intelligence.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "ZERION",
  },
  // Prevent search engines from indexing a local app
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#04080f",
  viewportFit: "cover",
  // Prevent pull-to-refresh and overscroll
  interactiveWidget: "overlays-content",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Android Chrome PWA */}
        <meta name="mobile-web-app-capable" content="yes" />
        {/* iOS Safari PWA */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        {/* Prevent phone number detection */}
        <meta name="format-detection" content="telephone=no" />
        {/* Prevent email detection */}
        <meta name="format-detection" content="email=no" />
      </head>
      <body>{children}</body>
    </html>
  );
}
