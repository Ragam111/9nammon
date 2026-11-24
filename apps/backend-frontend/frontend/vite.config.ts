import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server stays on localhost only. /api goes to the FastAPI backend, so the session cookie is
// same-origin and the browser never needs the model key.
// Defaults match scripts/dev_server.py; the E2E run overrides both with its own isolated ports.
const API_TARGET = process.env.API_TARGET ?? "http://127.0.0.1:8010";
const PORT = Number(process.env.VITE_PORT ?? 5173);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: PORT,
    strictPort: true,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
});
