import { LOG_CAP, LOG_STREAM_PATH, POLL_MS } from "./config.js";
import { el } from "./dom.js";
import {
  appendLogLines,
  createLineQueue,
  createRenderScheduler,
  createSseParser,
  forEachChunk,
  formatSseData,
  planLogTransport,
} from "./log-buffer.js";

export function mountLogPanel(root, deps) {
  const fetchImpl = (deps && deps.fetchImpl) || fetch;
  const queue = createLineQueue(LOG_CAP);
  let follow = true;
  let disposed = false;
  let busy = false;
  let ctrl = null;
  let timer = 0;
  let stopRetry = false;

  const status = el("p", { id: "log-status", role: "status" }, "กำลังต่อล็อก…");
  const toggle = el("button", { type: "button", id: "log-follow", "aria-pressed": "true" }, "เลื่อนตามท้าย: เปิด");
  const view = el("div", { id: "log-view", role: "log" });
  view.tabIndex = 0;

  toggle.addEventListener("click", function () {
    follow = !follow;
    toggle.textContent = follow ? "เลื่อนตามท้าย: เปิด" : "เลื่อนตามท้าย: ปิด";
    toggle.setAttribute("aria-pressed", follow ? "true" : "false");
    if (follow) view.scrollTop = view.scrollHeight;
  });

  const bar = el("div", { class: "row" });
  bar.append(status, toggle);
  root.append(
    el("h2", null, "ล็อกเทอร์มินัล"),
    el("p", { class: "muted" }, "สตรีมจาก /api/logs/stream ทีละไม่เกิน 32KB ไม่เกิน " + LOG_CAP + " บรรทัดบนจอ"),
    bar,
    view,
  );

  const schedule = createRenderScheduler(function () {
    if (disposed) return;
    const lines = queue.drain();
    if (!lines.length) return;
    appendLogLines(document, view, lines, LOG_CAP);
    if (follow) view.scrollTop = view.scrollHeight;
  });

  function enqueue(lines) {
    if (!lines.length) return;
    queue.pushMany(lines);
    schedule();
  }

  function arm(ms) {
    clearTimeout(timer);
    if (disposed || stopRetry || document.hidden) return;
    timer = setTimeout(connect, ms);
  }

  async function readStream(res) {
    if (!res.body || !res.body.getReader) {
      status.textContent = "not implemented";
      stopRetry = true;
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parser = createSseParser();
    status.textContent = "พร้อม";
    while (!disposed) {
      const step = await reader.read();
      if (step.done) break;
      forEachChunk(step.value || new Uint8Array(), function (slice) {
        const events = parser.push(decoder.decode(slice, { stream: true }));
        const lines = [];
        for (let i = 0; i < events.length; i += 1) {
          const line = formatSseData(events[i].data);
          if (line) lines.push(line);
        }
        enqueue(lines);
      }, MAX_CHUNK_BYTES);
    }
  }

  async function connect() {
    clearTimeout(timer);
    if (disposed || document.hidden || busy || stopRetry) return;
    busy = true;
    ctrl = new AbortController();
    try {
      const res = await fetchImpl(LOG_STREAM_PATH, {
        headers: { Accept: "text/event-stream" },
        cache: "no-store",
        signal: ctrl.signal,
      });
      const plan = planLogTransport(res.status);
      if (plan === "missing") {
        status.textContent = "not implemented";
        stopRetry = true;
        return;
      }
      if (plan !== "ok") {
        status.textContent = "offline";
        arm(POLL_MS);
        return;
      }
      const ctype = (res.headers && res.headers.get && res.headers.get("content-type")) || "";
      if (ctype.indexOf("application/json") !== -1) {
        const data = await res.json();
        const list = data && Array.isArray(data.lines) ? data.lines : [];
        const lines = [];
        for (let i = 0; i < list.length; i += 1) {
          const line = formatSseData(typeof list[i] === "string" ? list[i] : JSON.stringify(list[i]));
          if (line) lines.push(line);
        }
        enqueue(lines);
        status.textContent = "พร้อม · " + view.childNodes.length + " บรรทัด";
        arm(POLL_MS);
        return;
      }
      await readStream(res);
      if (!disposed && !stopRetry) arm(POLL_MS);
    } catch (err) {
      if (disposed) return;
      if (err && err.name === "AbortError") {
        if (!document.hidden && !stopRetry) arm(POLL_MS);
        return;
      }
      status.textContent = "offline";
      arm(POLL_MS);
    } finally {
      busy = false;
      ctrl = null;
    }
  }

  function onVis() {
    if (document.hidden) {
      clearTimeout(timer);
      if (ctrl) ctrl.abort();
      return;
    }
    connect();
  }

  document.addEventListener("visibilitychange", onVis);
  connect();

  return function dispose() {
    disposed = true;
    clearTimeout(timer);
    if (ctrl) ctrl.abort();
    document.removeEventListener("visibilitychange", onVis);
  };
}
