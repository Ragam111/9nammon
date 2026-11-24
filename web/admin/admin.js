/**
 * Admin dashboard client for the local LCA backend.
 * Polls GET /api/v1/status. attachLiveStatus is the later live-push hook
 * and does not open a socket.
 */

export const DEFAULT_API_BASE = "http://127.0.0.1:8765";
export const HEALTH_PATH = "/health";
export const STATUS_PATH = "/api/v1/status";
export const OVERVIEW_PATH = "/api/v1/admin/overview";
export const POLL_MS = 5000;
export const HEALTH_STATES = Object.freeze(["up", "down", "degraded", "unknown"]);

export function normalizeApiBase(value) {
  const text = String(value == null ? "" : value).trim().replace(/\/+$/, "");
  return text || DEFAULT_API_BASE;
}

export function endpointUrl(apiBase, path) {
  return normalizeApiBase(apiBase) + path;
}

/**
 * Keep up, down, degraded, and unknown.
 * Any other reported value becomes unknown.
 */
export function normalizeHealthState(value) {
  const state = String(value == null ? "" : value).trim().toLowerCase();
  if (state === "up" || state === "down" || state === "degraded" || state === "unknown") {
    return state;
  }
  return "unknown";
}

export function readComponent(value) {
  const body = value && typeof value === "object" ? value : {};
  const detail = body.detail == null ? "" : String(body.detail);
  return {
    state: normalizeHealthState(body.state),
    detail,
  };
}

export function readOverview(payload) {
  const body = payload && typeof payload === "object" ? payload : {};
  const uptime = Number(body.uptime_seconds);
  const version = body.version == null ? "" : String(body.version);
  return {
    version,
    uptimeSeconds: Number.isFinite(uptime) && uptime >= 0 ? uptime : null,
    backend: readComponent(body.backend),
    frontend: readComponent(body.frontend),
  };
}

export function readHealth(payload) {
  const body = payload && typeof payload === "object" ? payload : {};
  return {
    status: body.status == null ? "" : String(body.status),
    service: body.service == null ? "" : String(body.service),
    version: body.version == null ? "" : String(body.version),
  };
}

export function formatUptime(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds)) || Number(seconds) < 0) {
    return "—";
  }
  const total = Math.floor(Number(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (part) => String(part).padStart(2, "0");
  const clock = pad(hours) + ":" + pad(minutes) + ":" + pad(secs);
  return days > 0 ? days + "d " + clock : clock;
}

export function formatTimestamp(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "—";
  return date.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, "Z");
}

export function buildDashboardView(sources) {
  const input = sources || {};
  const overview = readOverview(input.overview);
  const health = readHealth(input.health);
  return {
    serviceVersion: overview.version || health.version || "—",
    uptime: formatUptime(overview.uptimeSeconds),
    uptimeSeconds: overview.uptimeSeconds,
    backend: overview.backend,
    frontend: overview.frontend,
    lastUpdated: formatTimestamp(input.updatedAt),
  };
}

async function fetchJson(fetchFn, url) {
  try {
    const response = await fetchFn(url);
    if (!response || !response.ok) {
      const status = response && response.status ? response.status : 0;
      return { ok: false, error: "HTTP " + status };
    }
    return { ok: true, body: await response.json() };
  } catch (error) {
    const message = error && error.message ? error.message : "request failed";
    return { ok: false, error: message };
  }
}

export async function collectDashboard(apiBase, fetchImpl, now) {
  const fetchFn = fetchImpl || globalThis.fetch.bind(globalThis);
  const base = normalizeApiBase(apiBase);
  const healthUrl = endpointUrl(base, HEALTH_PATH);
  const statusUrl = endpointUrl(base, STATUS_PATH);
  const overviewUrl = endpointUrl(base, OVERVIEW_PATH);
  const [healthResult, statusResult, overviewResult] = await Promise.all([
    fetchJson(fetchFn, healthUrl),
    fetchJson(fetchFn, statusUrl),
    fetchJson(fetchFn, overviewUrl),
  ]);
  const errors = [];
  if (!healthResult.ok) errors.push(HEALTH_PATH + ": " + healthResult.error);
  if (!statusResult.ok) errors.push(STATUS_PATH + ": " + statusResult.error);
  if (!overviewResult.ok) errors.push(OVERVIEW_PATH + ": " + overviewResult.error);
  const updatedAt = typeof now === "function" ? now() : new Date();
  const view = buildDashboardView({
    health: healthResult.body,
    status: statusResult.body,
    overview: overviewResult.body,
    updatedAt,
  });
  if (!overviewResult.ok) {
    const reason = overviewResult.error || "overview unavailable";
    view.backend = { state: "unknown", detail: reason };
    view.frontend = { state: "unknown", detail: reason };
  }
  return {
    apiBase: base,
    health: healthResult.body || null,
    status: statusResult.body || null,
    overview: overviewResult.body || null,
    view,
    errors,
    urls: { health: healthUrl, status: statusUrl, overview: overviewUrl },
  };
}

/**
 * Poll GET /api/v1/status, and refresh overview so version and health stay current.
 * Returns a stop function.
 */
export function startStatusPoll(options) {
  const opts = options || {};
  const intervalMs = opts.intervalMs == null ? POLL_MS : Number(opts.intervalMs);
  if (!Number.isFinite(intervalMs) || intervalMs < 1000) {
    throw new Error("poll interval too short");
  }
  const setTimer = opts.setTimer || ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = opts.clearTimer || ((id) => clearTimeout(id));
  let timer = null;
  let stopped = false;
  let inflight = false;

  async function tick() {
    if (timer != null) {
      clearTimer(timer);
      timer = null;
    }
    if (stopped || inflight) return;
    inflight = true;
    try {
      const rawBase = typeof opts.getApiBase === "function" ? opts.getApiBase() : opts.apiBase;
      const snapshot = await collectDashboard(rawBase, opts.fetchImpl, opts.now);
      if (stopped) return;
      if (snapshot.errors.length && typeof opts.onError === "function") {
        opts.onError(snapshot.errors.join("; "));
      }
      if (typeof opts.onUpdate === "function") opts.onUpdate(snapshot);
    } catch (error) {
      if (!stopped && typeof opts.onError === "function") {
        opts.onError(error && error.message ? error.message : "request failed");
      }
    } finally {
      inflight = false;
      if (!stopped) timer = setTimer(tick, intervalMs);
    }
  }

  tick();
  return function stopStatusPoll() {
    stopped = true;
    if (timer != null) clearTimer(timer);
    timer = null;
  };
}

/**
 * Hook for a later live-push client. Does not open a socket.
 * @returns {function(): void}
 */
export function attachLiveStatus(_options) {
  return function detachLiveStatus() {};
}

function textOrDash(value) {
  if (value == null || value === "") return "—";
  return String(value);
}

function setText(root, id, text) {
  const node = root.getElementById(id);
  if (node) node.textContent = text;
}

export function renderDashboard(doc, view) {
  const data = view || {};
  setText(doc, "service-version", textOrDash(data.serviceVersion));
  setText(doc, "uptime", textOrDash(data.uptime));
  setText(doc, "last-updated", textOrDash(data.lastUpdated));
  renderComponent(doc, "backend-health", data.backend);
  renderComponent(doc, "frontend-health", data.frontend);
}

function renderComponent(root, id, component) {
  const node = root.getElementById(id);
  if (!node) return;
  const part = readComponent(component);
  node.dataset.state = part.state;
  const stateNode = node.querySelector("[data-field=state]");
  const detailNode = node.querySelector("[data-field=detail]");
  if (stateNode) stateNode.textContent = part.state;
  if (detailNode) detailNode.textContent = part.detail ? part.detail : "—";
}

function boot() {
  const baseInput = document.getElementById("api-base");
  const form = document.getElementById("api-base-form");
  const errorNode = document.getElementById("error");

  function getApiBase() {
    return baseInput ? baseInput.value : "";
  }

  function showError(message) {
    if (!errorNode) return;
    if (!message) {
      errorNode.hidden = true;
      errorNode.textContent = "";
      return;
    }
    errorNode.hidden = false;
    errorNode.textContent = String(message);
  }

  async function refresh() {
    const snapshot = await collectDashboard(getApiBase());
    renderDashboard(document, snapshot.view);
    showError(snapshot.errors.length ? snapshot.errors.join("; ") : "");
  }

  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      refresh().catch((error) => {
        showError(error && error.message ? error.message : "request failed");
      });
    });
  }

  startStatusPoll({
    getApiBase,
    onUpdate(snapshot) {
      renderDashboard(document, snapshot.view);
      if (!snapshot.errors.length) showError("");
    },
    onError: showError,
  });
  attachLiveStatus({ getApiBase });
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
}
