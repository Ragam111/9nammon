// Run app.js renderShell() against a fake DOM and a fake /api/me role (argv[2]).
// Prints JSON {links, chip, calls, interval, opened, closed}.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const role = process.argv[2] || "USER";
function mk(tag) {
  return { tagName: tag, children: [], attrs: {}, className: "", textContent: "", id: "",
    listeners: {}, classList: { toggle() {} },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children.splice(this.children.indexOf(c), 1); },
    get firstChild() { return this.children[0] || null; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    addEventListener(t, f) { this.listeners[t] = f; }, focus() {} };
}
const mount = mk("div");
const docListeners = {};
const document = { readyState: "loading", createElement: mk,
  getElementById: (id) => (id === "lca-shell" ? mount : null),
  addEventListener: (t, f) => { docListeners[t] = f; } };
const calls = []; let interval = null;
const localStorage = { getItem: () => "k", setItem() {}, removeItem() {} };
const window = { document, localStorage, location: { pathname: "/models", hash: "", search: "" },
  setInterval: (f, ms) => { interval = ms; },
  fetch: async (url, opts) => {
    calls.push({ url, method: (opts && opts.method) || "GET" });
    const body = url === "/api/health" ? { ollama: "up" }
      : { username: "u", role, tokens: { used: 5, limit: 100, reserved: 0 } };
    return { ok: true, json: async () => body };
  } };
window.window = window;
const ctx = vm.createContext({ window, document, localStorage, console, Promise, String });
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "..", "app", "app.js"), "utf8"), ctx);
(async () => {
  await window.lca.renderShell();
  const walk = (n, out) => { if (n.tagName === "a") out.push(n.href); n.children.forEach((c) => walk(c, out)); return out; };
  const find = (n, cls) => (n.className.includes(cls) ? n : n.children.map((c) => find(c, cls)).find(Boolean));
  const btn = find(mount, "lca-shell-menu");
  btn.listeners.click();
  const opened = btn.getAttribute("aria-expanded");
  docListeners.keydown({ key: "Escape" });
  console.log(JSON.stringify({ links: walk(mount, []), chip: find(mount, "lca-shell-chip").textContent,
    calls, interval, opened, closed: btn.getAttribute("aria-expanded") }));
})();
