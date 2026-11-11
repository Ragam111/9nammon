import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { authAction, authStatusLabel, reduceAuth } from "../local_dashboard/web/js/auth-state.js";
import {
  CLUSTER_PATH,
  GOOGLE_CLIENT_ID,
  LOG_STREAM_PATH,
  MAX_CHUNK_BYTES,
  POLL_MS,
} from "../local_dashboard/web/js/config.js";
import {
  appendLogLines,
  createLineQueue,
  createRenderScheduler,
  createSseParser,
  forEachChunk,
  formatSseData,
  planLogTransport,
} from "../local_dashboard/web/js/log-buffer.js";
import { latencyText, normalizeCluster, roleLabel, rowsForTransport } from "../local_dashboard/web/js/nodes.js";
import { authRequestPath, createAuthController, interpretAuthPayload } from "../local_dashboard/web/js/oauth.js";
import { isAllowedOrigin, originBlockedMessage, redirectUriFor } from "../local_dashboard/web/js/origin.js";
import { startVisibilityPoll } from "../local_dashboard/web/js/poll.js";
import { parseRoute, stripOAuthParams } from "../local_dashboard/web/js/router.js";

const root = path.resolve(import.meta.dirname, "..");
const web = path.join(root, "local_dashboard", "web");

function flush() {
  return new Promise((resolve) => { setImmediate(resolve); });
}

function jsonResponse(status, body, extra) {
  return Object.assign({
    status: status,
    ok: status >= 200 && status < 300,
    type: "basic",
    headers: { get: () => "application/json" },
    json: async () => body,
  }, extra || {});
}

test("origins and redirect URIs use /auth/google", () => {
  assert.equal(isAllowedOrigin("http://localhost:8421"), true);
  assert.equal(isAllowedOrigin("http://127.0.0.1:8421"), true);
  assert.equal(isAllowedOrigin("http://localhost:8420"), false);
  assert.equal(redirectUriFor("http://127.0.0.1:8421"), "http://127.0.0.1:8421/auth/google");
  const message = originBlockedMessage("http://192.168.1.20:8421");
  assert.match(message, /origin_mismatch/);
  assert.match(message, /http:\/\/localhost:8421/);
});

test("router keeps known hashes and drops oauth params", () => {
  assert.equal(parseRoute(""), "/");
  assert.equal(parseRoute("#/logs"), "/logs");
  assert.equal(parseRoute("#/nodes/"), "/nodes");
  assert.equal(parseRoute("#/missing"), null);
  assert.equal(
    stripOAuthParams("http://127.0.0.1:8421/auth/google?code=abc&state=s#/account"),
    "/auth/google#/account",
  );
});

test("auth labels and start path carry the public client id only", () => {
  assert.equal(authStatusLabel(reduceAuth(null, { type: "signed-out" })), "ยังไม่ได้เข้าสู่ระบบ");
  assert.match(authStatusLabel(reduceAuth(null, { type: "signed-out", message: "offline" })), /offline/);
  assert.match(authStatusLabel(reduceAuth(null, { type: "signed-out", message: "not implemented" })), /not implemented/);
  assert.equal(authStatusLabel(reduceAuth(null, { type: "start" })), "กำลังเข้าสู่ระบบ…");
  assert.equal(
    authStatusLabel(reduceAuth(null, { type: "success", name: "นำมล", email: "a@b.c" })),
    "เข้าสู่ระบบแล้ว: นำมล",
  );
  assert.equal(authAction({ status: "signed_in" }, true).kind, "signout");
  assert.equal(authAction({ status: "signed_out" }, false).kind, "disabled");
  const start = authRequestPath("http://localhost:8421", "start");
  assert.equal(start.startsWith("/auth/google?"), true);
  assert.match(start, new RegExp("client_id=" + GOOGLE_CLIENT_ID.replace(/[.]/g, "\\.")));
  assert.match(decodeURIComponent(start), /redirect_uri=http:\/\/localhost:8421\/auth\/google/);
  assert.equal(start.includes("client_secret"), false);
  assert.equal(interpretAuthPayload(404, {}).kind, "missing");
  assert.equal(interpretAuthPayload(200, { authenticated: true, email: "a@b.c" }).kind, "signed_in");
});

test("missing /auth/google does not leave the page", async () => {
  let assigned = "";
  const calls = [];
  const auth = createAuthController({
    fetchImpl: async (url) => {
      calls.push(String(url));
      return jsonResponse(404, { error: "not implemented" });
    },
    assign: (url) => { assigned = url; },
  });
  const blocked = await auth.boot({ origin: "http://evil.test", search: "", pathname: "/" });
  assert.equal(blocked.status, "error");
  assert.equal(calls.length, 0);
  const state = await auth.boot({ origin: "http://127.0.0.1:8421", search: "", pathname: "/" });
  assert.equal(state.message, "not implemented");
  assert.equal(await auth.signIn({ origin: "http://127.0.0.1:8421", pathname: "/" }), null);
  assert.equal(assigned, "");
  assert.equal(calls.some((url) => url.startsWith("/auth/google")), true);
  assert.equal(calls.some((url) => url.includes("oauth2.googleapis.com")), false);
});

test("start follows a gateway redirect and status shows the signed-in name", async () => {
  const auth = createAuthController({
    fetchImpl: async (url) => {
      if (String(url).includes("mode=start")) return jsonResponse(302, null);
      return jsonResponse(200, { authenticated: true, name: "", email: "nammon@example.com" });
    },
    assign: () => {},
  });
  const target = await auth.signIn({ origin: "http://127.0.0.1:8421", pathname: "/" });
  assert.match(target, /^\/auth\/google\?/);
  assert.equal(auth.getState().status, "signing_in");
  const status = await auth.refreshStatus();
  assert.equal(status.status, "signed_in");
  assert.match(authStatusLabel(status), /nammon@example.com/);
});

test("log chunks stay within 32KB and old DOM nodes are dropped", () => {
  const sizes = [];
  const bytes = new Uint8Array(MAX_CHUNK_BYTES + 100);
  forEachChunk(bytes, (slice) => { sizes.push(slice.length); });
  assert.deepEqual(sizes, [MAX_CHUNK_BYTES, 100]);
  assert.throws(() => forEachChunk(bytes, () => {}, MAX_CHUNK_BYTES + 1), /chunk too large/);

  const parser = createSseParser();
  assert.deepEqual(parser.push("event: log\ndata: {\"text\":\"hel"), []);
  const events = parser.push("lo\"}\n\n");
  assert.equal(formatSseData(events[0].data), "info hello");

  const queue = createLineQueue(2);
  queue.pushMany(["a", "b", "c"]);
  assert.deepEqual(queue.drain(), ["b", "c"]);

  function makeNode(fragment) {
    const node = {
      fragment: !!fragment,
      className: "",
      textContent: "",
      childNodes: [],
      get firstChild() { return this.childNodes[0] || null; },
      appendChild(child) {
        if (child.fragment) {
          while (child.childNodes.length) this.childNodes.push(child.childNodes.shift());
        } else {
          this.childNodes.push(child);
        }
        return child;
      },
      removeChild(child) {
        const index = this.childNodes.indexOf(child);
        if (index >= 0) this.childNodes.splice(index, 1);
        return child;
      },
    };
    return node;
  }
  const doc = {
    createElement: () => makeNode(false),
    createDocumentFragment: () => makeNode(true),
  };
  const parent = makeNode(false);
  appendLogLines(doc, parent, ["1", "2", "3"], 2);
  assert.equal(parent.childNodes.length, 2);
  assert.equal(parent.childNodes[0].textContent, "2");
  assert.equal(parent.childNodes[1].textContent, "3");
});

test("scheduler flushes once per frame", () => {
  const frames = [];
  let paints = 0;
  const schedule = createRenderScheduler(() => { paints += 1; }, (fn) => { frames.push(fn); });
  schedule();
  schedule();
  assert.equal(frames.length, 1);
  frames[0]();
  assert.equal(paints, 1);
});

test("cluster status maps worker 8420 and dashboard 8421", () => {
  assert.equal(planLogTransport(200), "ok");
  assert.equal(planLogTransport(404), "missing");
  assert.equal(planLogTransport(503), "offline");
  const missing = rowsForTransport("missing");
  assert.equal(missing[0].role, "worker");
  assert.equal(missing[0].port, 8420);
  assert.equal(missing[1].role, "dashboard");
  assert.equal(missing[1].state, "not_implemented");
  assert.equal(roleLabel("worker"), "โหนดงาน");
  const rows = normalizeCluster({
    nodes: [
      { port: 8420, role: "worker", status: "up", latency_ms: 11.2 },
      { port: 8421, role: "dashboard", status: "down", latency_ms: null },
    ],
  });
  assert.equal(rows[0].state, "up");
  assert.equal(latencyText(rows[0]), "11 ms");
  assert.equal(latencyText(rows[1]), "—");
  assert.equal(CLUSTER_PATH, "/api/cluster/status");
  assert.equal(LOG_STREAM_PATH, "/api/logs/stream");
});

test("poll stays idle while hidden and rejects a short interval", async () => {
  assert.throws(() => startVisibilityPoll({ intervalMs: 1000, run: async () => {} }), /too short/);
  assert.ok(POLL_MS >= 5000);
  let hidden = true;
  let runs = 0;
  let listener = null;
  const pending = [];
  const stop = startVisibilityPoll({
    intervalMs: 8000,
    isHidden: () => hidden,
    run: async () => { runs += 1; },
    setTimer: (fn) => { pending.push(fn); return pending.length; },
    clearTimer: () => { pending.length = 0; },
    listen: (fn) => {
      listener = fn;
      return () => { listener = null; };
    },
  });
  await flush();
  assert.equal(runs, 0);
  hidden = false;
  listener();
  await flush();
  await flush();
  assert.equal(runs, 1);
  hidden = true;
  listener();
  await flush();
  assert.equal(runs, 1);
  stop();
});

test("dashboard sources call only the gateway routes and batch the log DOM", () => {
  const files = [];
  const stack = [web];
  while (stack.length) {
    const current = stack.pop();
    for (const name of fs.readdirSync(current)) {
      const full = path.join(current, name);
      if (fs.statSync(full).isDirectory()) stack.push(full);
      else files.push(full);
    }
  }
  const html = fs.readFileSync(path.join(web, "index.html"), "utf8");
  assert.match(html, /href="#\/logs"/);
  assert.match(html, /href="#\/nodes"/);
  assert.equal((html.match(/<button/g) || []).length, 0);
  const joined = files.map((file) => fs.readFileSync(file, "utf8")).join("\n");
  assert.match(joined, /\/auth\/google/);
  assert.match(joined, /\/api\/cluster\/status/);
  assert.match(joined, /\/api\/logs\/stream/);
  assert.match(joined, /createDocumentFragment/);
  assert.match(joined, /requestAnimationFrame/);
  assert.equal(joined.includes("localStorage"), false);
  assert.equal(joined.includes("client_secret"), false);
  assert.equal(joined.includes("oauth2.googleapis.com"), false);
  assert.equal(joined.includes("/api/health"), false);
  assert.equal(joined.includes("/api/nodes"), false);
  assert.equal(joined.includes("innerHTML"), false);
  assert.equal(joined.includes("backdrop-filter"), false);
  const sw = fs.readFileSync(path.join(web, "sw.js"), "utf8");
  assert.equal(sw.includes("caches"), false);
  const outside = fs.readdirSync(path.join(root, "local_dashboard")).sort();
  assert.deepEqual(outside, ["web"]);
});
