import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server stays on localhost only. /api goes to the FastAPI backend, so the session cookie is
// same-origin and the browser never needs the model key.
const API_TARGET = "http://127.0.0.1:8010"; // scripts/dev_server.py

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
});
