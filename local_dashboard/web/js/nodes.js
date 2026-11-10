import { DASHBOARD_PORT, WORKER_PORT } from "./config.js";

const EXPECTED = Object.freeze([
  { port: WORKER_PORT, role: "worker" },
  { port: DASHBOARD_PORT, role: "dashboard" },
]);

export function nodeStateLabel(state) {
  if (state === "up") return "up";
  if (state === "not_implemented") return "not implemented";
  if (state === "checking") return "checking";
  return "down";
}

export function roleLabel(role) {
  if (role === "worker") return "โหนดงาน";
  if (role === "dashboard") return "แดชบอร์ด";
  return String(role || "");
}

export function emptyCluster() {
  return EXPECTED.map(function (item) {
    return { port: item.port, role: item.role, state: "checking", latencyMs: null };
  });
}

export function rowsForTransport(plan) {
  const state = plan === "missing" ? "not_implemented" : "down";
  return EXPECTED.map(function (item) {
    return { port: item.port, role: item.role, state: state, latencyMs: null };
  });
}

export function normalizeCluster(body) {
  const nodes = body && Array.isArray(body.nodes) ? body.nodes : [];
  return EXPECTED.map(function (item) {
    const found = nodes.find(function (node) { return Number(node && node.port) === item.port; });
    if (!found) return { port: item.port, role: item.role, state: "down", latencyMs: null };
    const raw = found.status;
    const state = raw === "up" || raw === "down" || raw === "not_implemented" ? raw : "down";
    const latency = Number.isFinite(found.latency_ms) ? Math.round(found.latency_ms) : null;
    return {
      port: item.port,
      role: found.role || item.role,
      state: state,
      latencyMs: state === "up" ? latency : latency,
    };
  });
}

export function latencyText(row) {
  if (!row || row.state !== "up" || row.latencyMs == null) return "—";
  return String(row.latencyMs) + " ms";
}
