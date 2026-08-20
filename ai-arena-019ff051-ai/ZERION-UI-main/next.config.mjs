/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Disable image optimization on Android (no Sharp in Termux)
  images: { unoptimized: true },
  // Compress responses for mobile networks
  compress: true,
  // Allow connections from Android phone's localhost and LAN
  allowedDevOrigins: ["http://localhost:*", "http://127.0.0.1:*"],
};

export default nextConfig;
