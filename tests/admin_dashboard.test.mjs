import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  DEFAULT_API_BASE,
  HEALTH_STATES,
  OVERVIEW_PATH,
  STATUS_PATH,
  attachLiveStatus,
  buildDashboardView,
  collectDashboard,
  normalizeHealthState,
  renderDashboard,
  startStatusPoll,
} from "../web/admin/admin.js";

const root = path.resolve(import.meta.dirname, "..");
const page = path.join(root, "web", "admin", "index.html");
const client = path.join(root, "web", "admin", "admin.js");

function flush() {
  return new Promise((resolve) => { setImmediate(resolve); });
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function fakeDocument() {
  const nodes = new Map();
  function make(id, withFields) {
    const node = {
      id,
      textContent: "",
      hidden: false,
      dataset: {},
      stateNode: { textContent: "" },
      detailNode: { textContent: "" },
      querySelector(selector) {
        if (!withFields) return null;
        if (selector === "[data-field=state]") return this.stateNode;
        if (selector === "[data-field=detail]") return this.detailNode;
        return null;
      },
    };
    nodes.set(id, node);
    return node;
  }
  for (const id of ["service-version", "uptime", "last-updated"]) make(id, false);
  for (const id of ["backend-health", "frontend-health"]) make(id, true);
  return {
    getElementById(id) { return nodes.get(id) || null; },
    nodes,
  };
}

test("page lists the monitor fields and the default API base", () => {
  const html = fs.readFileSync(page, "utf8");
  for (const id of [
    "api-base",
    "refresh",
    "service-version",
    "uptime",
    "backend-health",
    "frontend-health",
    "last-updated",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  for (const label of [
    "API base",
    "Refresh",
    "Service version",
    "Uptime",
    "Backend health",
    "Frontend health",
    "Last updated",
  ]) {
    assert.ok(html.includes(label), label);
  }
  assert.match(html, /value="http:\/\/127\.0\.0\.1:8765"/);
  assert.match(html, /src="\.\/admin\.js"/);
});

test("up, down, degraded, and unknown stay distinct", () => {
  assert.deepEqual(HEALTH_STATES, ["up", "down", "degraded", "unknown"]);
  const rendered = HEALTH_STATES.map((state) => {
    assert.equal(normalizeHealthState(state), state);
    assert.equal(normalizeHealthState(" " + state.toUpperCase() + " "), state);
    const view = buildDashboardView({
      overview: {
        version: "1.4.0",
        uptime_seconds: 3661,
        backend: { state, detail: "backend " + state },
        frontend: { state, detail: "frontend " + state },
      },
      health: { status: "ok", service: "lca", version: "0.0.0" },
      updatedAt: new Date("2026-11-24T01:02:03.000Z"),
    });
    assert.equal(view.serviceVersion, "1.4.0");
    assert.equal(view.uptime, "01:01:01");
    assert.equal(view.lastUpdated, "2026-11-24 01:02:03Z");
    assert.equal(view.backend.state, state);
    assert.equal(view.frontend.state, state);
    assert.equal(view.backend.detail, "backend " + state);
    assert.equal(view.frontend.detail, "frontend " + state);
    const doc = fakeDocument();
    renderDashboard(doc, view);
    assert.equal(doc.nodes.get("backend-health").dataset.state, state);
    assert.equal(doc.nodes.get("frontend-health").dataset.state, state);
    assert.equal(doc.nodes.get("backend-health").stateNode.textContent, state);
    assert.equal(doc.nodes.get("frontend-health").detailNode.textContent, "frontend " + state);
    return view.backend.state;
  });
  assert.deepEqual(rendered, ["up", "down", "degraded", "unknown"]);
});

test("unrecognized health values become unknown and keep their detail", () => {
  for (const value of ["", "ok", "offline", "UP!", null, undefined]) {
    assert.equal(normalizeHealthState(value), "unknown");
  }
  const view = buildDashboardView({
    overview: {
      version: "",
      uptime_seconds: -1,
      backend: { state: "offline", detail: "no route" },
      frontend: { detail: "" },
    },
    health: { status: "ok", service: "lca", version: "0.3.4" },
  });
  assert.equal(view.backend.state, "unknown");
  assert.equal(view.backend.detail, "no route");
  assert.equal(view.frontend.state, "unknown");
  assert.equal(view.frontend.detail, "");
  assert.equal(view.serviceVersion, "0.3.4");
  assert.equal(view.uptime, "—");
  const doc = fakeDocument();
  renderDashboard(doc, view);
  assert.equal(doc.nodes.get("backend-health").dataset.state, "unknown");
  assert.equal(doc.nodes.get("frontend-health").detailNode.textContent, "—");
  assert.equal(doc.nodes.get("service-version").textContent, "0.3.4");
});

test("collect and poll call status for each health state", async () => {
  const calls = [];
  let index = 0;
  const fetchImpl = async (url) => {
    const target = String(url);
    calls.push(target);
    if (target.endsWith("/health")) {
      return jsonResponse({ status: "ok", service: "lca", version: "9.9.9" });
    }
    if (target.endsWith(STATUS_PATH)) {
      return jsonResponse({ status: "ok" });
    }
    const state = HEALTH_STATES[index % HEALTH_STATES.length];
    index += 1;
    return jsonResponse({
      version: "2.0.0",
      uptime_seconds: 125,
      backend: { state, detail: "api " + state },
      frontend: { state, detail: "ui " + state },
    });
  };

  const seen = [];
  for (const state of HEALTH_STATES) {
    const snapshot = await collectDashboard(DEFAULT_API_BASE + "/", fetchImpl, () => new Date("2026-11-24T00:00:00.000Z"));
    assert.equal(snapshot.apiBase, DEFAULT_API_BASE);
    assert.equal(snapshot.urls.status, DEFAULT_API_BASE + STATUS_PATH);
    assert.equal(snapshot.urls.overview, DEFAULT_API_BASE + OVERVIEW_PATH);
    assert.equal(snapshot.view.backend.state, state);
    assert.equal(snapshot.view.frontend.state, state);
    assert.equal(snapshot.errors.length, 0);
    seen.push(state);
  }
  assert.deepEqual(seen, ["up", "down", "degraded", "unknown"]);

  const pending = [];
  let updates = 0;
  const stop = startStatusPoll({
    apiBase: "http://10.0.0.8:9000/",
    intervalMs: 1000,
    fetchImpl,
    setTimer: (fn) => {
      pending.push(fn);
      return pending.length;
    },
    clearTimer: () => {},
    onUpdate: (snapshot) => {
      updates += 1;
      assert.equal(snapshot.urls.status, "http://10.0.0.8:9000" + STATUS_PATH);
      assert.ok(HEALTH_STATES.includes(snapshot.view.backend.state));
      assert.ok(HEALTH_STATES.includes(snapshot.view.frontend.state));
    },
  });
  await flush();
  assert.equal(updates, 1);
  const statusCalls = () => calls.filter((url) => url.endsWith(STATUS_PATH)).length;
  const before = statusCalls();
  pending.shift()();
  await flush();
  assert.equal(statusCalls(), before + 1);
  assert.equal(updates, 2);
  stop();
});

test("a failed overview is unknown and the live hook opens nothing", () => {
  const source = fs.readFileSync(client, "utf8");
  assert.match(source, /function attachLiveStatus/);
  assert.equal(source.includes("WebSocket"), false);
  assert.equal(source.includes("EventSource"), false);
  const detach = attachLiveStatus({ apiBase: DEFAULT_API_BASE });
  assert.equal(typeof detach, "function");
  detach();
});

test("failed overview marks both sides unknown", async () => {
  const snapshot = await collectDashboard(DEFAULT_API_BASE, async (url) => {
    const target = String(url);
    if (target.endsWith(OVERVIEW_PATH)) return jsonResponse({}, 503);
    if (target.endsWith("/health")) {
      return jsonResponse({ status: "ok", service: "lca", version: "0.3.4" });
    }
    return jsonResponse({ status: "ok" });
  });
  assert.equal(snapshot.view.backend.state, "unknown");
  assert.equal(snapshot.view.frontend.state, "unknown");
  assert.match(snapshot.view.backend.detail, /HTTP 503/);
  assert.equal(snapshot.view.serviceVersion, "0.3.4");
  assert.equal(snapshot.errors.length, 1);
});
