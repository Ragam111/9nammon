import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server on localhost only. /api goes to the FastAPI backend, so the session cookie stays same-origin
// and the browser never sees the model key. API_TARGET defaults to the backend dev port used elsewhere.
const API_TARGET = process.env.API_TARGET ?? "http://127.0.0.1:8000";
const PORT = Number(process.env.ADMIN_PORT ?? 5174);

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: PORT,
    strictPort: true,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
});
