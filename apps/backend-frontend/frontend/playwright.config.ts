import { randomBytes } from "node:crypto";
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

// One random password per run, created here and shared with the API (seed) and the tests via the
// environment. Workers inherit the parent's environment, so they all see the same value.
process.env.E2E_PASSWORD ??= randomBytes(18).toString("base64url");

// Absolute, quoted paths: Windows cmd cannot run a command that starts with "../".
const BACKEND = resolve(process.cwd(), "../backend");
const PY_BIN = process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python";
const PYTHON = `"${resolve(BACKEND, PY_BIN)}"`;
const script = (name: string) => `"${resolve(BACKEND, "scripts", name)}"`;
const MODEL_PORT = 9101;
const API_PORT = 8011;
const WEB_PORT = 5174;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // the flows share one database and run in order
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    // Uses the Edge already installed on Windows, so no browser download is needed.
    channel: process.env.E2E_CHANNEL ?? "msedge",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${PYTHON} ${script("fake_model.py")} ${MODEL_PORT}`,
      url: `http://127.0.0.1:${MODEL_PORT}/v1/models`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `${PYTHON} ${script("e2e_server.py")}`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: { E2E_API_PORT: String(API_PORT), E2E_MODEL_PORT: String(MODEL_PORT) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npx vite",
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { API_TARGET: `http://127.0.0.1:${API_PORT}`, VITE_PORT: String(WEB_PORT) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
