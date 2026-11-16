import { LOG_CAP, MAX_CHUNK_BYTES, MIN_POLL_MS } from "./config.js";

export function assertPollInterval(ms) {
  if (ms < MIN_POLL_MS) throw new Error("poll interval too short");
  return ms;
}

export function forEachChunk(bytes, fn, maxBytes) {
  const limit = maxBytes == null ? MAX_CHUNK_BYTES : maxBytes;
  if (limit < 1 || limit > MAX_CHUNK_BYTES) throw new Error("chunk too large");
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes || 0);
  for (let offset = 0; offset < view.length; offset += limit) {
    fn(view.subarray(offset, Math.min(offset + limit, view.length)));
  }
}

export function formatLine(entry) {
  if (typeof entry === "string") return entry.replace(/[\r\n]+/g, " ");
  const ts = entry && entry.ts ? String(entry.ts) : "";
  const level = entry && entry.level ? String(entry.level) : "info";
  const text = entry && entry.text != null ? String(entry.text) : "";
  return (ts + " " + level + " " + text).trim().replace(/[\r\n]+/g, " ");
}

export function formatSseData(data) {
  const text = String(data || "").replace(/\r/g, "").trim();
  if (!text) return "";
  if (text.charAt(0) === "{") {
    try { return formatLine(JSON.parse(text)); } catch (err) { /* ใช้ข้อความตรง ๆ */ }
  }
  return text.replace(/[\n]+/g, " ");
}

export function createSseParser() {
  let carry = "";
  return {
    push: function (text) {
      carry += String(text || "");
      const events = [];
      let sep = carry.indexOf("\n\n");
      while (sep !== -1) {
        const raw = carry.slice(0, sep);
        carry = carry.slice(sep + 2);
        let eventName = "message";
        const dataLines = [];
        const rows = raw.split("\n");
        for (let i = 0; i < rows.length; i += 1) {
          const line = rows[i];
          if (!line || line.charAt(0) === ":") continue;
          if (line.indexOf("event:") === 0) eventName = line.slice(6).trim();
          else if (line.indexOf("data:") === 0) dataLines.push(line.slice(5).replace(/^ /, ""));
        }
        if (dataLines.length) events.push({ event: eventName, data: dataLines.join("\n") });
        sep = carry.indexOf("\n\n");
      }
      return events;
    },
  };
}

export function createLineQueue(cap) {
  const limit = cap == null ? LOG_CAP : cap;
  const lines = [];
  return {
    pushMany: function (list) {
      for (let i = 0; i < list.length; i += 1) {
        if (list[i]) lines.push(String(list[i]));
      }
      const overflow = lines.length - limit;
      if (overflow > 0) lines.splice(0, overflow);
    },
    drain: function () {
      const out = lines.slice();
      lines.length = 0;
      return out;
    },
    get length() { return lines.length; },
  };
}

/** เติมบรรทัดเข้า DocumentFragment แล้วตัดโหนดเก่าที่เกิน cap ทิ้ง */
export function appendLogLines(doc, parent, lines, cap) {
  const limit = cap == null ? LOG_CAP : cap;
  const frag = doc.createDocumentFragment();
  for (let i = 0; i < lines.length; i += 1) {
    const row = doc.createElement("div");
    row.className = "log-line";
    row.textContent = String(lines[i]);
    frag.appendChild(row);
  }
  parent.appendChild(frag);
  let dropped = 0;
  while (parent.childNodes.length > limit) {
    parent.removeChild(parent.firstChild);
    dropped += 1;
  }
  return dropped;
}

export function createRenderScheduler(render, raf) {
  const frame = raf || requestAnimationFrame;
  let pending = false;
  return function schedule() {
    if (pending) return;
    pending = true;
    frame(function () {
      pending = false;
      render();
    });
  };
}

export function planLogTransport(status) {
  if (status === 404 || status === 405 || status === 501) return "missing";
  if (status >= 200 && status < 300) return "ok";
  return "offline";
}
