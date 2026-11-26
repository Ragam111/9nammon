// Node test for the /chat layout block in app/chat.js (more menu + right panel).
// Run: node --test tests/ui_layout.test.mjs  (no jsdom: tiny fake elements below)
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(here, "..", "app", "chat.js"), "utf8");
const block = src.split("/* layout:start */")[1].split("/* layout:end */")[0];
const sandbox = { window: {} };
vm.runInNewContext(block, sandbox);
const L = sandbox.window.LCALayout;

let focused = null;
class El {
  constructor(tag, attrs = {}) {
    this.tagName = tag.toUpperCase();
    this.hidden = false;
    this.attrs = {};
    this.type = attrs.type || "";
    this.listeners = {};
    this.children = [];
    this.parent = null;
    const cls = new Set();
    this.classList = {
      toggle: (n, force) => {
        const on = force === undefined ? !cls.has(n) : !!force;
        if (on) cls.add(n); else cls.delete(n);
        return on;
      },
      contains: (n) => cls.has(n),
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t, ev = {}) {
    if (!ev.target) ev.target = this;
    ev.preventDefault = ev.preventDefault || (() => { ev.defaultPrevented = true; });
    ev.stopPropagation = ev.stopPropagation || (() => { ev.stopped = true; });
    (this.listeners[t] || []).forEach((f) => f(ev));
    if (this.parent && !ev.stopped) this.parent.dispatch(t, ev);
    return ev;
  }
  focus() { focused = this; }
  append(...kids) { kids.forEach((c) => { c.parent = this; this.children.push(c); }); return this; }
  contains(n) { for (let x = n; x; x = x.parent) if (x === this) return true; return false; }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
  querySelectorAll() {
    return this.all().filter((e) => ["BUTTON", "SELECT", "INPUT"].includes(e.tagName) && e.type !== "file");
  }
}

function makeMenu() {
  const doc = new El("body");
  const btn = new El("button");
  btn.setAttribute("aria-expanded", "false");
  const box = new El("div");
  box.hidden = true;
  const compare = new El("button");
  const persona = new El("select");
  const file = new El("input", { type: "file" });
  const exp = new El("button");
  box.append(compare, persona, file, exp);
  doc.append(btn, box);
  return { doc, btn, box, compare, persona, exp, m: L.menu(btn, box) };
}

function memStore(init = {}) {
  const data = { ...init };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); } };
}
const brokenStore = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };

test("exposes the layout API", () => {
  for (const fn of ["menu", "panel", "readCollapsed", "writeCollapsed", "pinnedFirst", "init"]) {
    assert.equal(typeof L[fn], "function", fn);
  }
});

test("menu button toggles hidden and aria-expanded, focuses first item", () => {
  const { btn, box, compare } = makeMenu();
  btn.dispatch("click");
  assert.equal(box.hidden, false);
  assert.equal(btn.getAttribute("aria-expanded"), "true");
  assert.equal(focused, compare);
  btn.dispatch("click");
  assert.equal(box.hidden, true);
  assert.equal(btn.getAttribute("aria-expanded"), "false");
});

test("Esc closes the open menu, returns focus, and does not reach document", () => {
  const { doc, btn, box, persona } = makeMenu();
  let reached = 0;
  doc.addEventListener("keydown", () => { reached += 1; });
  btn.dispatch("click");
  const ev = persona.dispatch("keydown", { key: "Escape" });
  assert.equal(box.hidden, true);
  assert.equal(btn.getAttribute("aria-expanded"), "false");
  assert.equal(focused, btn);
  assert.equal(ev.stopped, true);
  assert.equal(reached, 0);
  // Closed menu: Esc passes through to the document (stream stop keeps working).
  btn.dispatch("keydown", { key: "Escape" });
  assert.equal(reached, 1);
});

test("arrow keys move between menu buttons; file input is skipped", () => {
  const { btn, compare, persona, exp } = makeMenu();
  btn.dispatch("click");
  compare.dispatch("keydown", { key: "ArrowDown" });
  assert.equal(focused, persona);
  exp.dispatch("keydown", { key: "ArrowDown" });
  assert.equal(focused, compare);
  compare.dispatch("keydown", { key: "ArrowUp" });
  assert.equal(focused, exp);
});

test("arrow keys also leave checkbox and select; Alt+Arrow on select is left alone", () => {
  const { btn, box, compare, persona, exp } = makeMenu();
  const check = new El("input", { type: "checkbox" });
  box.append(check);
  btn.dispatch("click");
  persona.dispatch("keydown", { key: "ArrowDown" });
  assert.equal(focused, exp);
  persona.dispatch("keydown", { key: "ArrowUp" });
  assert.equal(focused, compare);
  exp.dispatch("keydown", { key: "ArrowDown" });
  assert.equal(focused, check);
  check.dispatch("keydown", { key: "ArrowDown" });
  assert.equal(focused, compare);
  focused = persona;
  const ev = persona.dispatch("keydown", { key: "ArrowDown", altKey: true });
  assert.equal(focused, persona);
  assert.notEqual(ev.defaultPrevented, true);
});

test("clicking an action button closes the menu; select does not", () => {
  const { btn, box, compare, persona } = makeMenu();
  btn.dispatch("click");
  persona.dispatch("click");
  assert.equal(box.hidden, false);
  compare.dispatch("click");
  assert.equal(box.hidden, true);
  assert.equal(btn.getAttribute("aria-expanded"), "false");
});

test("outside click closes, inside click keeps open", () => {
  const { btn, box, persona, m } = makeMenu();
  btn.dispatch("click");
  m.onOutside(persona);
  assert.equal(box.hidden, false);
  m.onOutside(new El("main"));
  assert.equal(box.hidden, true);
});

test("panel collapse is remembered in storage", () => {
  const hub = new El("div");
  const btn = new El("button");
  const store = memStore();
  const p = L.panel(hub, btn, store);
  assert.equal(p.isCollapsed(), false);
  assert.equal(btn.getAttribute("aria-expanded"), "true");
  btn.dispatch("click");
  assert.equal(hub.classList.contains("panel-collapsed"), true);
  assert.equal(btn.getAttribute("aria-expanded"), "false");
  assert.equal(L.readCollapsed(store), true);
  // A fresh page with the same storage starts collapsed.
  const hub2 = new El("div");
  const btn2 = new El("button");
  L.panel(hub2, btn2, store);
  assert.equal(hub2.classList.contains("panel-collapsed"), true);
  assert.equal(btn2.getAttribute("aria-expanded"), "false");
});

test("blocked or missing storage never throws; panel still toggles", () => {
  assert.equal(L.readCollapsed(brokenStore), false);
  assert.equal(L.readCollapsed(null), false);
  L.writeCollapsed(brokenStore, true);
  L.writeCollapsed(null, true);
  const hub = new El("div");
  const btn = new El("button");
  L.panel(hub, btn, brokenStore);
  btn.dispatch("click");
  assert.equal(hub.classList.contains("panel-collapsed"), true);
});

test("pinnedFirst keeps order otherwise", () => {
  const out = L.pinnedFirst([{ id: 1 }, { id: 2, pinned: 1 }, { id: 3 }, { id: 4, pinned: true }]);
  assert.deepEqual(Array.from(out, (c) => c.id), [2, 4, 1, 3]);
  assert.equal(L.pinnedFirst(null).length, 0);
});

// ---- Task 3: mobile drawer / bottom sheet ----
function makeOverlay(extra = {}) {
  const body = new El("body");
  const btn = new El("button");
  btn.setAttribute("aria-expanded", "false");
  const box = new El("aside");
  const first = new El("button");
  const closeBtn = new El("button");
  box.append(first, closeBtn);
  const backdrop = new El("div");
  backdrop.hidden = true;
  const main = new El("section");
  body.append(btn, box, backdrop, main);
  const o = L.overlay({ box, btn, backdrop, body, background: [main], closers: [closeBtn], ...extra });
  return { body, btn, box, first, closeBtn, backdrop, main, o };
}

test("overlay API exported", () => {
  assert.equal(typeof L.overlay, "function");
  assert.equal(typeof L.initMobile, "function");
});

test("drawer opens: aria-expanded, backdrop, scroll lock, inert, focus inside", () => {
  const { body, btn, box, first, backdrop, main } = makeOverlay();
  btn.dispatch("click");
  assert.equal(box.classList.contains("open"), true);
  assert.equal(btn.getAttribute("aria-expanded"), "true");
  assert.equal(box.getAttribute("aria-modal"), "true");
  assert.equal(backdrop.hidden, false);
  assert.equal(body.classList.contains("overlay-open"), true);
  assert.equal(main.inert, true);
  assert.equal(main.getAttribute("aria-hidden"), "true");
  assert.equal(focused, first);
});

test("Esc closes drawer, stops propagation, returns focus to trigger", () => {
  const { body, btn, box, first, backdrop, main } = makeOverlay();
  let reached = 0;
  body.addEventListener("keydown", () => { reached += 1; });
  btn.dispatch("click");
  const ev = first.dispatch("keydown", { key: "Escape" });
  assert.equal(ev.stopped, true);
  assert.equal(reached, 0);
  assert.equal(box.classList.contains("open"), false);
  assert.equal(btn.getAttribute("aria-expanded"), "false");
  assert.equal(box.getAttribute("aria-modal"), null);
  assert.equal(backdrop.hidden, true);
  assert.equal(body.classList.contains("overlay-open"), false);
  assert.equal(main.inert, false);
  assert.equal(main.getAttribute("aria-hidden"), null);
  assert.equal(focused, btn);
  // Closed: Esc passes through (stream stop still works).
  first.dispatch("keydown", { key: "Escape" });
  assert.equal(reached, 1);
});

test("backdrop tap and close button close the overlay", () => {
  const { btn, box, backdrop, closeBtn } = makeOverlay();
  btn.dispatch("click");
  backdrop.dispatch("click");
  assert.equal(box.classList.contains("open"), false);
  assert.equal(focused, btn);
  btn.dispatch("click");
  closeBtn.dispatch("click");
  assert.equal(box.classList.contains("open"), false);
  assert.equal(btn.getAttribute("aria-expanded"), "false");
});

test("sheet opened from the more menu returns focus to the given trigger", () => {
  const more = new El("button");
  const { btn, box, backdrop, o } = makeOverlay({ ariaOnly: true });
  btn.dispatch("click"); // ariaOnly: the button click alone does not toggle
  assert.equal(o.isOpen(), false);
  o.open(more);
  assert.equal(btn.getAttribute("aria-expanded"), "true");
  assert.equal(backdrop.hidden, false);
  o.onKey({ key: "Escape", preventDefault() {}, stopPropagation() {} });
  assert.equal(box.classList.contains("open"), false);
  assert.equal(focused, more);
});

test("Tab / Shift+Tab are trapped inside the open overlay", () => {
  const { btn, first, closeBtn } = makeOverlay();
  btn.dispatch("click");
  let ev = closeBtn.dispatch("keydown", { key: "Tab" });
  assert.equal(ev.defaultPrevented, true);
  assert.equal(focused, first);
  ev = first.dispatch("keydown", { key: "Tab", shiftKey: true });
  assert.equal(ev.defaultPrevented, true);
  assert.equal(focused, closeBtn);
  ev = first.dispatch("keydown", { key: "Tab" }); // middle move: browser default
  assert.notEqual(ev.defaultPrevented, true);
});

test("open() waits until the box is visibility:visible before focusing", () => {
  let vis = "hidden";
  const frames = [];
  sandbox.window.getComputedStyle = () => ({ visibility: vis });
  sandbox.window.requestAnimationFrame = (f) => frames.push(f);
  try {
    const { btn, box, first } = makeOverlay();
    focused = null;
    btn.dispatch("click");
    assert.equal(focused, null); // still hidden: no focus yet
    vis = "visible";
    frames.shift()();
    assert.equal(focused, first);
    // transitionend fallback when the frame fires too early
    const o2 = makeOverlay();
    vis = "hidden"; focused = null;
    o2.btn.dispatch("click");
    frames.shift()();
    assert.equal(focused, null);
    vis = "visible";
    o2.box.dispatch("transitionend");
    assert.equal(focused, o2.first);
  } finally {
    delete sandbox.window.getComputedStyle;
    delete sandbox.window.requestAnimationFrame;
  }
});
