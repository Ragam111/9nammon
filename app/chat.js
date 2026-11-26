/* LCA Chat Hub — vanilla JS. No framework, no CDN. */
/* layout:start */
// 3-column layout helpers: "⋯" menu, collapsible right panel, pinned-first list.
// No stream/send logic here. Tested in node by tests/ui_layout.test.mjs.
(function (root) {
  "use strict";
  const PANEL_KEY = "lca.chat.panelCollapsed";
  function readCollapsed(store) {
    try {
      return !!store && store.getItem(PANEL_KEY) === "1";
    } catch (_) {
      return false;
    }
  }
  function writeCollapsed(store, collapsed) {
    try {
      if (store) store.setItem(PANEL_KEY, collapsed ? "1" : "0");
    } catch (_) { /* private mode / blocked storage: keep in memory only */ }
  }
  function getStore(win) {
    try {
      return win.localStorage || null;
    } catch (_) {
      return null;
    }
  }
  function pinnedFirst(list) {
    return (list || []).map((c, i) => ({ c, i }))
      .sort((a, b) => (b.c.pinned ? 1 : 0) - (a.c.pinned ? 1 : 0) || a.i - b.i)
      .map((x) => x.c);
  }
  // Disclosure menu: button[aria-expanded] controls box[hidden].
  function menu(btn, box) {
    const items = () => [...box.querySelectorAll("button, select, input:not([type=file])")]
      .filter((el) => !el.hidden && !(el.getClientRects && el.getClientRects().length === 0));
    const isOpen = () => !box.hidden;
    function open() {
      box.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      const first = items()[0];
      if (first) first.focus();
    }
    function close(refocus) {
      if (box.hidden) return;
      box.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      if (refocus) btn.focus();
    }
    function onKey(ev) {
      if (!isOpen()) return;
      if (ev.key === "Escape") {
        ev.preventDefault();
        ev.stopPropagation(); // first Esc closes the menu, not the stream
        close(true);
      } else if ((ev.key === "ArrowDown" || ev.key === "ArrowUp")
          && items().includes(ev.target) && !(ev.target.tagName === "SELECT" && ev.altKey)) {
        // Arrows walk every item (button, checkbox, select); Alt+Arrow on a select keeps
        // the native value change / open behaviour.
        const list = items();
        if (!list.length) return;
        ev.preventDefault();
        const at = list.indexOf(ev.target);
        const step = ev.key === "ArrowDown" ? 1 : -1;
        list[(at + step + list.length) % list.length].focus();
      }
    }
    btn.addEventListener("click", () => (isOpen() ? close(false) : open()));
    btn.addEventListener("keydown", onKey);
    box.addEventListener("keydown", onKey);
    box.addEventListener("click", (ev) => {
      if (ev.target && ev.target.tagName === "BUTTON") close(false);
    });
    return {
      open, close, isOpen,
      onOutside(target) {
        if (isOpen() && !box.contains(target) && !btn.contains(target)) close(false);
      },
    };
  }
  function panel(hub, btn, store) {
    let collapsed = readCollapsed(store);
    function apply() {
      hub.classList.toggle("panel-collapsed", collapsed);
      btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
    apply();
    btn.addEventListener("click", () => {
      collapsed = !collapsed;
      apply();
      writeCollapsed(store, collapsed);
    });
    return { isCollapsed: () => collapsed };
  }
  // Mirror the composer chips (#attach-chips) and model into the right panel.
  function mirrorPanel(doc, Observer) {
    const chips = doc.getElementById("attach-chips");
    const list = doc.getElementById("attachments");
    const sel = doc.getElementById("model");
    const card = doc.getElementById("panel-model");
    const showFiles = () => {
      const names = [...chips.querySelectorAll(".attach-chip .name")].map((n) => n.textContent);
      list.replaceChildren();
      names.forEach((name) => {
        const li = doc.createElement("li");
        li.textContent = name;
        list.append(li);
      });
      if (!names.length) {
        const li = doc.createElement("li");
        li.className = "meta";
        li.textContent = "ยังไม่มีไฟล์แนบ";
        list.append(li);
      }
    };
    const showModel = () => {
      const opt = sel.options[sel.selectedIndex];
      card.textContent = opt ? opt.textContent : "—";
    };
    sel.addEventListener("change", showModel);
    if (Observer) {
      new Observer(showFiles).observe(chips, { childList: true });
      new Observer(showModel).observe(sel, { childList: true });
    }
    showFiles();
    showModel();
  }
  // Mobile overlay (drawer / bottom sheet): box gets class "open", backdrop shows,
  // body scroll locks, `background` nodes go inert, focus moves in and returns.
  const FOCUSABLE = "button, select, input:not([type=file]), textarea, a[href]";
  function overlay(opts) {
    const { box, btn, backdrop, body, background = [], closers = [], ariaOnly = false } = opts;
    let trigger = null;
    const isOpen = () => box.classList.contains("open");
    function setInert(on) {
      background.forEach((el) => {
        if (!el) return;
        if ("inert" in el || on) el.inert = on;
        if (on) el.setAttribute("aria-hidden", "true"); else if (el.removeAttribute) el.removeAttribute("aria-hidden");
      });
    }
    function open(from) {
      if (isOpen()) return;
      trigger = from || btn;
      box.classList.toggle("open", true);
      box.setAttribute("aria-modal", "true");
      if (btn) btn.setAttribute("aria-expanded", "true");
      if (backdrop) backdrop.hidden = false;
      if (body) body.classList.toggle("overlay-open", true);
      setInert(true);
      focusWhenVisible();
    }
    const items = () => [...box.querySelectorAll(FOCUSABLE)].filter((el) => !el.hidden && !el.disabled);
    // Focus the first item only once the box is visibility:visible (a hidden
    // element cannot take focus). Retry on the next frame, then on transitionend.
    function focusWhenVisible() {
      const w = typeof window !== "undefined" ? window : {};
      const visible = () => !w.getComputedStyle || w.getComputedStyle(box).visibility === "visible";
      let done = false;
      const go = () => {
        if (done || !isOpen() || !visible()) return;
        done = true;
        const first = items()[0];
        if (first) first.focus();
      };
      go();
      if (done) return;
      if (w.requestAnimationFrame) w.requestAnimationFrame(go);
      const onEnd = () => { box.removeEventListener && box.removeEventListener("transitionend", onEnd); go(); };
      box.addEventListener("transitionend", onEnd);
    }
    function close(refocus = true) {
      if (!isOpen()) return;
      box.classList.toggle("open", false);
      if (box.removeAttribute) box.removeAttribute("aria-modal");
      if (btn) btn.setAttribute("aria-expanded", "false");
      if (backdrop) backdrop.hidden = true;
      if (body) body.classList.toggle("overlay-open", false);
      setInert(false);
      if (refocus && trigger) trigger.focus();
      trigger = null;
    }
    function onKey(ev) {
      if (isOpen() && ev.key === "Tab") { // focus trap inside the open overlay
        const list = items();
        if (!list.length) return;
        const first = list[0], last = list[list.length - 1];
        if (ev.shiftKey && ev.target === first) { ev.preventDefault(); last.focus(); }
        else if (!ev.shiftKey && ev.target === last) { ev.preventDefault(); first.focus(); }
        return;
      }
      if (isOpen() && ev.key === "Escape") {
        ev.preventDefault();
        ev.stopPropagation(); // Esc closes the overlay first, not the stream
        close(true);
      }
    }
    if (btn && !ariaOnly) btn.addEventListener("click", () => (isOpen() ? close(true) : open(btn)));
    box.addEventListener("keydown", onKey);
    if (backdrop) backdrop.addEventListener("click", () => close(true));
    closers.forEach((c) => c && c.addEventListener("click", () => close(true)));
    return { open, close, isOpen, onKey };
  }
  // Keep the composer above the on-screen keyboard: --lca-vvh follows visualViewport.
  function trackViewport(win, docEl) {
    const vv = win.visualViewport;
    if (!vv || !docEl) return;
    const set = () => docEl.style.setProperty("--lca-vvh", vv.height + "px");
    vv.addEventListener("resize", set);
    set();
  }
  function initMobile(doc, win) {
    const $ = (id) => doc.getElementById(id);
    const backdrop = $("backdrop");
    const drawer = overlay({
      box: $("sidebar"), btn: $("drawer-btn"), backdrop, body: doc.body,
      background: [doc.querySelector(".main"), $("side-panel")], closers: [$("drawer-close")],
    });
    const sheet = overlay({
      box: $("side-panel"), btn: $("sheet-btn"), ariaOnly: true, backdrop, body: doc.body,
      background: [$("sidebar"), doc.querySelector(".main")], closers: [$("sheet-close")],
    });
    // Sheet is opened from the "⋯" menu, which closes itself: return focus to "⋯".
    $("sheet-btn").addEventListener("click", () => sheet.open($("more-btn")));
    doc.addEventListener("keydown", (ev) => { drawer.onKey(ev); sheet.onKey(ev); }, true);
    // Picking a chat or link inside the drawer closes it.
    $("sidebar").addEventListener("click", (ev) => {
      const t = ev.target && ev.target.closest && ev.target.closest("#conv-list button, #search-hits button, #new-chat");
      if (t && drawer.isOpen()) drawer.close(false);
    });
    const mq = win.matchMedia ? win.matchMedia("(min-width: 1024px)") : null;
    if (mq && mq.addEventListener) {
      mq.addEventListener("change", (e) => { if (e.matches) { drawer.close(false); sheet.close(false); } });
    }
    trackViewport(win, doc.documentElement);
    return { drawer, sheet };
  }
  function init(doc, win) {
    const m = menu(doc.getElementById("more-btn"), doc.getElementById("more-menu"));
    doc.addEventListener("click", (ev) => m.onOutside(ev.target));
    panel(doc.getElementById("hub"), doc.getElementById("panel-toggle"), getStore(win));
    mirrorPanel(doc, win.MutationObserver);
    if (doc.getElementById("drawer-btn")) initMobile(doc, win);
    const input = doc.getElementById("input");
    if (input) input.focus(); // send the first message without a click
  }
  root.LCALayout = { menu, panel, overlay, initMobile, readCollapsed, writeCollapsed, pinnedFirst, init, PANEL_KEY };
  if (typeof document !== "undefined" && document.getElementById("more-btn")) init(document, root);
})(typeof window !== "undefined" ? window : this);
/* layout:end */
(function () {
  "use strict";
  const PAGE = 50;
  const S = {
    providers: [],
    conversations: [],
    folders: [],
    personas: [],
    conv: null,
    messages: [],
    ephemeral: false,
    ephemeralLog: [],
    streaming: false,
    abort: null,
    editId: null,
    branchFrom: null,
    start: 0,
    online: navigator.onLine !== false,
  };
  const $ = (id) => document.getElementById(id);
  const thread = $("thread");
  const input = $("input");
  const sendBtn = $("send");
  const DEFAULT_PH = "พิมพ์ข้อความ… (Enter ส่ง, Shift+Enter ขึ้นบรรทัด)";
  let modeChip = null;     // ป้ายโหมดแก้ไข/แตกสาขา เหนือช่องพิมพ์ (สร้างตอนใช้ครั้งแรก)
  let editPrefill = null;  // ข้อความที่ ArrowUp ใส่ให้ตอนเข้าโหมดแก้ไข

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function clip(text, n) {
    text = text || "";
    if (text.length <= n) return text;
    if (typeof Intl !== "undefined" && Intl.Segmenter) {
      const seg = new Intl.Segmenter("th", { granularity: "word" });
      let out = "";
      for (const part of seg.segment(text)) {
        if ((out + part.segment).length > n) return out + "…";
        out += part.segment;
      }
      return out;
    }
    return text.slice(0, n) + "…";
  }
  // Session token from /app.js (server-injected or #lca_token=), or the saved key.
  // Every /api/* call needs it since the localhost CSRF guard (#107).
  function authed(extra) {
    const base = window.lca && typeof window.lca.headers === "function" ? window.lca.headers() : {};
    return Object.assign(base, extra || {});
  }
  async function api(path, opts) {
    opts = Object.assign({}, opts || {});
    opts.headers = authed(opts.headers);
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || ("HTTP " + res.status));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }
  function choice() {
    const sel = $("model");
    if (sel.value === "custom") {
      const custom = $("custom-model").value.trim();
      const prev = S.providers.find((p) => p.id === (S._customProvider || "ollama")) || S.providers[0];
      return { provider: (prev && prev.id) || "ollama", model: custom };
    }
    const [provider, model] = sel.value.split("\t");
    return { provider, model };
  }
  function fillModels() {
    const sel = $("model");
    const prev = sel.value;
    sel.replaceChildren();
    S.providers.forEach((p) => {
      (p.models || []).forEach((m) => {
        const opt = document.createElement("option");
        opt.value = p.id + "\t" + m;
        opt.textContent = p.label + " · " + m;
        opt.disabled = !S.online && !p.local;
        opt.title = opt.disabled ? "ต้องออนไลน์" : (p.local ? "local" : "cloud");
        sel.append(opt);
      });
    });
    const custom = document.createElement("option");
    custom.value = "custom";
    custom.textContent = "กำหนดโมเดลเอง";
    sel.append(custom);
    if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
    $("custom-model").hidden = sel.value !== "custom";
    renderComparePicks();
  }
  function renderComparePicks() {
    const box = $("compare-picks");
    box.replaceChildren();
    let locals = 0;
    S.providers.forEach((p) => {
      const m = (p.models || [])[0];
      if (!m) return;
      const id = "cmp-" + p.id;
      const label = document.createElement("label");
      label.className = "meta";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = id;
      cb.dataset.provider = p.id;
      cb.dataset.model = m;
      cb.disabled = !S.online && !p.local;
      cb.addEventListener("change", () => {
        const n = [...box.querySelectorAll("input:checked")].filter((el) => {
          const prov = S.providers.find((x) => x.id === el.dataset.provider);
          return prov && prov.local;
        }).length;
        $("queue-note").hidden = n < 2;
      });
      label.append(cb, document.createTextNode(" " + p.label + " · " + m));
      box.append(label, document.createTextNode(" "));
      if (p.local) locals += 1;
    });
    void locals;
  }
  function setNotice(text) {
    const el = $("notice");
    el.hidden = !text;
    el.textContent = text || "";
  }
  // ป้ายโหมดแก้ไข/แตกสาขา: บอกว่าส่งแล้วจะเกิดอะไร และมีปุ่มยกเลิก
  function renderMode() {
    if (!modeChip) {
      modeChip = document.createElement("div");
      modeChip.className = "mode-chip";
      modeChip.setAttribute("role", "status");
      modeChip.hidden = true;
      const label = document.createElement("span");
      label.className = "mode-label";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "mode-cancel";
      cancel.textContent = "✕ ยกเลิก";
      cancel.addEventListener("click", cancelMode);
      modeChip.append(label, cancel);
      $("composer").parentNode.insertBefore(modeChip, $("composer"));
    }
    const text = S.editId
      ? "กำลังแก้ข้อความเดิม — ส่งเพื่อสร้างเวอร์ชันใหม่"
      : S.branchFrom
        ? "กำลังแตกสาขาจากข้อความนี้ — ส่งเพื่อเริ่มสาขาใหม่"
        : "";
    modeChip.hidden = !text;
    modeChip.querySelector(".mode-label").textContent = text;
  }
  // ออกจากโหมดแก้ไข/แตกสาขา (ไม่แตะข้อความในช่องพิมพ์)
  function exitMode() {
    S.editId = null;
    S.branchFrom = null;
    editPrefill = null;
    input.placeholder = DEFAULT_PH;
    renderMode();
  }
  // ยกเลิกโดยผู้ใช้: ถ้าช่องยังเป็นข้อความที่ ArrowUp ใส่ให้ ก็ล้างทิ้ง ข้อความที่พิมพ์เองจะคงไว้
  function cancelMode() {
    if (S.editId && editPrefill !== null && input.value === editPrefill) input.value = "";
    exitMode();
    input.focus();
  }
  // Wrap an async handler so a failed api() call shows in #notice instead of only the console.
  function safe(fn) {
    return async function (...args) {
      try {
        return await fn.apply(this, args);
      } catch (err) {
        setNotice((err && err.message) || "เกิดข้อผิดพลาด ลองใหม่อีกครั้ง");
      }
    };
  }
  async function refreshLists() {
    const [convs, folders, personas] = await Promise.all([
      api("/api/chat/conversations"),
      api("/api/chat/folders"),
      api("/api/chat/personas"),
    ]);
    S.conversations = convs.conversations || [];
    S.folders = folders.folders || [];
    S.personas = personas.personas || [];
    const folder = $("folder");
    const keep = folder.value;
    folder.replaceChildren();
    const all = document.createElement("option");
    all.value = "all";
    all.textContent = "ล่าสุดทั้งหมด";
    folder.append(all);
    const root = document.createElement("option");
    root.value = "root";
    root.textContent = "ไม่มีโปรเจกต์";
    folder.append(root);
    S.folders.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = String(f.id);
      opt.textContent = "· ".repeat(f.depth || 0) + f.name + " (" + f.n + ")";
      folder.append(opt);
    });
    if ([...folder.options].some((o) => o.value === keep)) folder.value = keep;
    const persona = $("persona");
    const pk = persona.value;
    persona.replaceChildren();
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "persona";
    persona.append(none);
    S.personas.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = String(p.id);
      opt.textContent = p.name;
      persona.append(opt);
    });
    if ([...persona.options].some((o) => o.value === pk)) persona.value = pk;
    const list = $("conv-list");
    list.replaceChildren();
    window.LCALayout.pinnedFirst(S.conversations).forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = (c.pinned ? "● " : "") + (clip(c.title, 42) || "ไม่มีชื่อ");
      btn.setAttribute("aria-current", S.conv && S.conv.id === c.id ? "true" : "false");
      btn.addEventListener("click", safe(() => openConv(c.id)));
      list.append(btn);
    });
  }
  function visibleMessages() {
    const all = S.messages;
    if (all.length <= PAGE + 20) return all.map((m, i) => ({ m, i }));
    S.start = Math.max(0, Math.min(S.start, all.length - 1));
    return all.slice(S.start).map((m, i) => ({ m, i: S.start + i }));
  }
  function inlineHtml(text) {
    let html = esc(text);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" rel="noopener noreferrer">$1</a>');
    return html.replace(/\n/g, "<br>");
  }
  // highlight.js escapes every token before wrapping it in <span>, so innerHTML is safe here.
  function codeBlock(code, lang) {
    const codeEl = document.createElement("code");
    const hl = window.LCAHighlight;
    const name = hl ? hl.normalizeLang(lang) : null;
    if (name && code.length <= (hl.MAX_LENGTH || 100000)) {
      codeEl.className = "lang-" + name;
      codeEl.innerHTML = hl.highlight(code, name);
    } else {
      codeEl.textContent = code;
    }
    return codeEl;
  }
  function copyCode(btn, code) {
    const done = (label) => {
      btn.textContent = label;
      setTimeout(() => { btn.textContent = "คัดลอก"; }, 1200);
    };
    Promise.resolve()
      .then(() => navigator.clipboard.writeText(code))
      .then(() => done("คัดลอกแล้ว"), () => done("คัดลอกไม่ได้"));
  }
  function renderBody(el, text, rich) {
    el.replaceChildren();
    if (!rich) {
      el.textContent = text || "";
      return;
    }
    const chunks = String(text || "").split("```");
    chunks.forEach((chunk, index) => {
      if (index % 2 === 1) {
        const nl = chunk.indexOf("\n");
        const code = nl >= 0 ? chunk.slice(nl + 1) : chunk;
        const lang = nl >= 0 ? chunk.slice(0, nl).trim() : "";
        const pre = document.createElement("pre");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "copy";
        btn.textContent = "คัดลอก";
        btn.addEventListener("click", () => copyCode(btn, code));
        pre.append(btn, codeBlock(code, lang));
        el.append(pre);
      } else if (chunk) {
        const div = document.createElement("div");
        div.innerHTML = inlineHtml(chunk);
        el.append(div);
      }
    });
  }
  function renderThread(opts) {
    opts = opts || {};
    const stick = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
    thread.replaceChildren();
    if (!S.messages.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.innerHTML = "<h1>เริ่มแชทใหม่</h1><p>ตัวอย่าง:</p>";
      ["อธิบายโค้ดนี้", "เขียนเทสต์", "สรุปไฟล์", "แปลไทย↔อังกฤษ"].forEach((sample) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = sample;
        b.addEventListener("click", () => { input.value = sample; input.focus(); });
        empty.append(b);
      });
      thread.append(empty);
      return;
    }
    if (S.start > 0) {
      const more = document.createElement("button");
      more.type = "button";
      more.id = "older";
      more.textContent = "โหลดข้อความเก่า";
      more.addEventListener("click", () => {
        S.start = Math.max(0, S.start - PAGE);
        renderThread();
      });
      thread.append(more);
    }
    visibleMessages().forEach(({ m }) => {
      const art = document.createElement("article");
      art.className = "msg " + (m.role || "");
      art.dataset.id = m.id;
      const who = document.createElement("div");
      who.className = "who";
      const label = m.role === "user" ? "คุณ" : ((m.model || m.provider || "ผู้ช่วย") + (m.provider ? " · " + m.provider : ""));
      who.append(document.createTextNode(label));
      if (m.n_ver > 1) {
        const prev = document.createElement("button");
        prev.type = "button";
        prev.textContent = "‹";
        prev.addEventListener("click", () => stepSibling(m, -1));
        const next = document.createElement("button");
        next.type = "button";
        next.textContent = "›";
        next.addEventListener("click", () => stepSibling(m, 1));
        const ver = document.createElement("span");
        ver.className = "num";
        ver.textContent = m.ver + "/" + m.n_ver;
        who.append(prev, ver, next);
      }
      art.append(who);
      const body = document.createElement("div");
      body.className = "body";
      const rich = !(opts.streaming && m === S.messages[S.messages.length - 1]);
      renderBody(body, m.content, rich);
      art.append(body);
      if (m.status === "error" || m.status === "stopped") {
        const warn = document.createElement("p");
        warn.className = "meta";
        warn.textContent = m.status === "stopped"
          ? "หยุดแล้ว — ข้อความเท่าที่ได้ถูกเก็บไว้"
          : "ขาดตอน — ต่อโมเดลไม่สำเร็จ ข้อความเท่าที่ได้ถูกเก็บไว้";
        art.append(warn);
      }
      if (m.compare && m.compare.length > 1) {
        const grid = document.createElement("div");
        grid.className = "compare";
        m.compare.forEach((c) => {
          const col = document.createElement("article");
          const h = document.createElement("div");
          h.className = "who";
          h.textContent = (c.provider || "") + " · " + (c.model || "");
          const b = document.createElement("div");
          b.className = "body";
          b.textContent = c.content || "";
          const pick = document.createElement("button");
          pick.type = "button";
          pick.textContent = "เลือกอันนี้ต่อ";
          pick.addEventListener("click", safe(() => switchTo(c.id)));
          col.append(h, b, pick);
          grid.append(col);
        });
        art.append(grid);
      }
      const actions = document.createElement("div");
      actions.className = "actions";
      if (m.role === "assistant") {
        const regen = document.createElement("button");
        regen.type = "button";
        regen.textContent = "ตอบใหม่";
        regen.addEventListener("click", () => regenMsg(m));
        actions.append(regen);
      }
      const branch = document.createElement("button");
      branch.type = "button";
      branch.textContent = "แตกสาขา";
      branch.addEventListener("click", () => {
        S.branchFrom = m.id;
        S.editId = null;
        editPrefill = null;
        input.placeholder = "ข้อความสาขาใหม่จากข้อความนี้";
        renderMode();
        input.focus();
      });
      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "คัดลอก";
      copy.addEventListener("click", () => navigator.clipboard.writeText(m.content || ""));
      actions.append(branch, copy);
      art.append(actions);
      thread.append(art);
    });
    if (stick) thread.scrollTop = thread.scrollHeight;
    const older = $("older");
    if (older && !S._obs) {
      S._obs = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting) && S.start > 0) {
          S.start = Math.max(0, S.start - PAGE);
          renderThread();
        }
      });
    }
    if (older && S._obs) S._obs.observe(older);
  }
  async function openConv(id) {
    S.ephemeral = false;
    $("ephemeral").checked = false;
    const data = await api("/api/chat/conversations?id=" + encodeURIComponent(id));
    S.conv = data.conversation;
    S.messages = data.messages || [];
    S.start = Math.max(0, S.messages.length - PAGE);
    exitMode();
    $("title").textContent = clip(S.conv.title, 48) || "แชท";
    if (S.conv.persona_id) $("persona").value = String(S.conv.persona_id);
    renderThread();
    refreshLists().catch((err) => setNotice(err.message));
  }
  async function ensureConv() {
    if (S.ephemeral) return null;
    if (S.conv) return S.conv;
    const folder = $("folder").value;
    const body = {
      title: "",
      persona_id: $("persona").value || null,
      folder_id: folder === "all" || folder === "root" ? null : Number(folder),
    };
    const data = await api("/api/chat/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    S.conv = data.conversation;
    return S.conv;
  }
  function selectedTargets() {
    return [...$("compare-picks").querySelectorAll("input:checked")].map((el) => ({
      provider: el.dataset.provider,
      model: el.dataset.model,
    }));
  }
  async function readSSE(resp, onEvent) {
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const step = await reader.read();
      if (step.done) break;
      buf += dec.decode(step.value, { stream: true });
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n");
        if (data) onEvent(JSON.parse(data));
      }
    }
  }
  async function sendStream(text) {
    const picked = choice();
    if (!picked.model) { setNotice("ต้องเลือกโมเดล"); return; }
    if (!S.online && S.providers.some((p) => p.id === picked.provider && !p.local)) {
      setNotice("โมเดล cloud ต้องออนไลน์");
      return;
    }
    S.streaming = true;
    sendBtn.textContent = "หยุด";
    setNotice("");
    const ctrl = new AbortController();
    S.abort = ctrl;
    if (S.ephemeral) {
      S.ephemeralLog.push({ role: "user", content: text });
      S.messages.push({ role: "user", content: text, id: "local-" + S.messages.length });
      const draft = { role: "assistant", content: "", provider: picked.provider, model: picked.model, status: "streaming", id: "draft" };
      S.messages.push(draft);
      renderThread({ streaming: true });
      const node = thread.querySelector("article:last-child .body");
      let acc = "";
      try {
        const history = S.ephemeralLog.map((m) => ({ role: m.role, content: m.content }));
        const resp = await fetch("/api/chat/stream", {
          method: "POST",
          headers: authed({ "Content-Type": "application/json" }),
          body: JSON.stringify({ provider: picked.provider, model: picked.model, messages: history }),
          signal: ctrl.signal,
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.error || "ส่งไม่สำเร็จ");
        }
        await readSSE(resp, (ev) => {
          if (ev.delta) {
            acc += ev.delta;
            if (node) node.textContent = acc;
          }
          if (ev.error) {
            draft.status = "error";
            draft.content = acc;
            setNotice(ev.error + " (ขาดตอน)");
          }
          if (ev.done) draft.status = "ok";
        });
        draft.content = acc;
        draft.status = draft.status === "error" ? "error" : "ok";
        S.ephemeralLog.push({ role: "assistant", content: acc, provider: picked.provider, model: picked.model });
      } catch (err) {
        if (err.name !== "AbortError") setNotice(err.message);
        draft.status = ctrl.signal.aborted ? "stopped" : "error";
        // Keep the partial reply and keep the log alternating user/assistant.
        draft.content = acc;
        S.ephemeralLog.push({ role: "assistant", content: acc, provider: picked.provider, model: picked.model });
      }
      S.streaming = false;
      sendBtn.textContent = "ส่ง";
      renderThread();
      return;
    }
    let conv;
    try {
      conv = await ensureConv();
    } catch (err) {
      // Reset the send button so the composer is not stuck on "หยุด"; onSubmit shows the error.
      S.streaming = false;
      sendBtn.textContent = "ส่ง";
      throw err;
    }
    const user = { role: "user", content: text, id: "pending-user" };
    const draft = { role: "assistant", content: "", provider: picked.provider, model: picked.model, status: "streaming", id: "draft" };
    S.messages.push(user, draft);
    S.start = Math.max(0, S.messages.length - PAGE);
    renderThread({ streaming: true });
    const node = thread.querySelector("article:last-child .body");
    let acc = "";
    try {
      const resp = await fetch("/api/chat/stream", {
        method: "POST",
        headers: authed({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          provider: picked.provider,
          model: picked.model,
          conversation_id: conv.id,
          content: text,
        }),
        signal: ctrl.signal,
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || "ส่งไม่สำเร็จ");
      }
      await readSSE(resp, (ev) => {
        if (ev.delta) {
          acc += ev.delta;
          if (node) node.textContent = acc;
          thread.scrollTop = thread.scrollHeight;
        }
        if (ev.error) {
          draft.status = ev.status || "error";
          setNotice((ev.error || "ขาดตอน") + " — ข้อความเท่าที่ได้ถูกเก็บไว้");
        }
      });
      await openConv(conv.id);
    } catch (err) {
      if (err.name !== "AbortError") setNotice(err.message);
      draft.content = acc;
      draft.status = ctrl.signal.aborted ? "stopped" : "error";
      renderThread();
    }
    S.streaming = false;
    sendBtn.textContent = "ส่ง";
    input.placeholder = DEFAULT_PH;
  }
  async function onSubmit(ev) {
    ev.preventDefault();
    if (S.streaming) {
      if (S.abort) S.abort.abort();
      return;
    }
    const rawInput = input.value;
    const savedAttachments = attachments.slice();
    const text = withAttachments(rawInput.trim());
    if (!text) return;
    input.value = "";
    clearAttachments();
    const picked = choice();
    // Send failed -> give the user back their text and files.
    const restoreDraft = () => {
      if (!input.value) input.value = rawInput;
      if (!attachments.length && savedAttachments.length) {
        attachments = savedAttachments;
        renderAttachments();
      }
    };
    try {
      if (S.editId && S.conv) {
        const data = await api("/api/chat/edit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conversation_id: S.conv.id, message_id: S.editId, content: text,
            provider: picked.provider, model: picked.model,
          }),
        });
        exitMode();
        if (data.status && data.status !== "ok") setNotice(data.error || "แก้แล้วแต่คำตอบขาดตอน");
        await openConv(S.conv.id);
        return;
      }
      if (S.branchFrom && S.conv) {
        const data = await api("/api/chat/branch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conversation_id: S.conv.id, message_id: S.branchFrom, content: text,
            provider: picked.provider, model: picked.model,
          }),
        });
        exitMode();
        if (data.status && data.status !== "ok") setNotice(data.error || "สาขาใหม่ตอบไม่จบ");
        await openConv(S.conv.id);
        return;
      }
      await sendStream(text);
    } catch (err) {
      restoreDraft();
      setNotice(err.message);
    }
  }
  async function regenMsg(m) {
    if (!S.conv) return;
    const picked = choice();
    try {
      const data = await api("/api/chat/regen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: S.conv.id, message_id: m.id,
          provider: picked.provider, model: picked.model,
        }),
      });
      if (data.status && data.status !== "ok") setNotice(data.error || "ตอบใหม่ไม่สำเร็จ");
      await openConv(S.conv.id);
    } catch (err) {
      setNotice(err.message);
    }
  }
  async function switchTo(id) {
    if (!S.conv) return;
    await api("/api/chat/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: S.conv.id, message_id: id }),
    });
    await openConv(S.conv.id);
  }
  function stepSibling(m, dir) {
    const sibs = m.siblings || [];
    const idx = sibs.findIndex((s) => s.id === m.id);
    const next = sibs[idx + dir];
    if (next) safe(switchTo)(next.id);
  }
  async function runCompare() {
    const targets = selectedTargets();
    if (targets.length < 2) { setNotice("เลือกอย่างน้อย 2 โมเดล"); return; }
    const text = input.value.trim();
    const conv = S.ephemeral ? null : await ensureConv();
    const body = { targets, content: text };
    if (conv) body.conversation_id = conv.id;
    if (!text && S.messages.length) {
      const lastUser = [...S.messages].reverse().find((m) => m.role === "user" && typeof m.id === "number");
      if (lastUser) {
        body.message_id = lastUser.id;
        delete body.content;
      }
    }
    if (!body.content && !body.message_id) { setNotice("ต้องมีข้อความที่จะเทียบ"); return; }
    setNotice("กำลังเทียบ…");
    try {
      const data = await api("/api/chat/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      input.value = "";
      const failed = (data.replies || []).filter((r) => r.status && r.status !== "ok");
      if (failed.length) setNotice("บางคำตอบขาดตอน: " + failed.map((r) => r.provider).join(", "));
      else setNotice("");
      if (data.conversation_id) await openConv(data.conversation_id);
    } catch (err) {
      setNotice(err.message);
    }
  }
  async function doSearch() {
    const q = $("search").value.trim();
    const box = $("search-hits");
    if (!q) { box.hidden = true; box.replaceChildren(); return; }
    const data = await api("/api/chat/search?q=" + encodeURIComponent(q));
    box.hidden = false;
    box.replaceChildren();
    (data.conversations || []).forEach((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "ชื่อ: " + clip(c.title, 40);
      b.addEventListener("click", safe(() => openConv(c.id)));
      box.append(b);
    });
    (data.messages || []).forEach((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = clip(m.snippet || m.content, 48);
      b.addEventListener("click", safe(() => openConv(m.conversation_id)));
      box.append(b);
    });
    if (!box.childElementCount) box.textContent = "ไม่พบ";
  }
  /* Attach text files: read in the browser, sent inside the user message (no upload). */
  const ATTACH_EXT = ["py", "js", "ts", "json", "md", "txt", "csv", "html", "css", "sh"];
  const ATTACH_LANG = { py: "python", js: "javascript", ts: "typescript", md: "markdown", sh: "bash" };
  const ATTACH_MAX_BYTES = 200 * 1024;
  const ATTACH_MAX_FILES = 5;
  const NL = String.fromCharCode(10);
  let attachments = [];  // [{ name, size, text }]
  let attachPending = 0;  // files being read; reserved slots against the 5-file cap
  function fmtSize(n) {
    return n < 1024 ? n + " B" : (n / 1024).toFixed(1) + " KB";
  }
  function fileExt(name) {
    const i = String(name).lastIndexOf(".");
    return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
  }
  function looksBinary(text) {
    if (text.indexOf(String.fromCharCode(0)) >= 0) return true;
    const bad = (text.slice(0, 4096).match(new RegExp(String.fromCharCode(0xfffd), "g")) || []).length;
    return bad > 8;
  }
  async function readAttachment(file) {
    if (!ATTACH_EXT.includes(fileExt(file.name))) return "ไฟล์ " + file.name + " ไม่ใช่ไฟล์ข้อความ/โค้ดที่รองรับ";
    if (file.size > ATTACH_MAX_BYTES) return "ไฟล์ " + file.name + " ใหญ่เกิน 200 KB";
    let text;
    attachPending++;  // reserve a slot before await so concurrent calls see it
    try {
      text = await file.text();
    } finally {
      attachPending--;
    }
    if (looksBinary(text)) return "ไฟล์ " + file.name + " เป็นไฟล์ไบนารี แนบไม่ได้";
    if (attachments.length >= ATTACH_MAX_FILES) return "แนบได้สูงสุด " + ATTACH_MAX_FILES + " ไฟล์";
    attachments.push({ name: file.name, size: file.size, text });
    return "";
  }
  async function addAttachments(files) {
    const errors = [];
    for (const file of [...(files || [])]) {
      if (attachments.length + attachPending >= ATTACH_MAX_FILES) {
        errors.push("แนบได้สูงสุด " + ATTACH_MAX_FILES + " ไฟล์");
        break;
      }
      try {
        const err = await readAttachment(file);
        if (err) errors.push(err);
      } catch (_) {
        errors.push("อ่านไฟล์ " + file.name + " ไม่ได้");
      }
    }
    renderAttachments();
    if (errors.length) setNotice(errors.join(" · "));
  }
  function renderAttachments() {
    const box = $("attach-chips");
    box.replaceChildren();
    attachments.forEach((a, i) => {
      const chip = document.createElement("span");
      chip.className = "attach-chip";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = a.name;
      const size = document.createElement("span");
      size.className = "meta";
      size.textContent = fmtSize(a.size);
      const rm = document.createElement("button");
      rm.type = "button";
      rm.textContent = "×";
      rm.setAttribute("aria-label", "เอาไฟล์ " + a.name + " ออก");
      rm.addEventListener("click", () => { attachments.splice(i, 1); renderAttachments(); });
      chip.append(name, size, rm);
      box.append(chip);
    });
    box.hidden = attachments.length === 0;
  }
  function withAttachments(text) {
    if (!attachments.length) return text;
    const blocks = attachments.map((a) => {
      const ext = fileExt(a.name);
      // The renderer splits on ``` so a fence inside the file would end the block early.
      // A zero-width space between backticks keeps the text readable but not a fence.
      const raw = a.text.replace(/```/g, "``​`");
      const body = raw.endsWith(NL) ? raw : raw + NL;
      return "```" + (ATTACH_LANG[ext] || ext) + " " + a.name + NL + body + "```";
    });
    return [text].concat(blocks).filter(Boolean).join(NL + NL);
  }
  function clearAttachments() {
    attachments = [];
    renderAttachments();
  }
  function bindAttach() {
    const picker = $("attach-file");
    const composer = $("composer");
    $("attach-btn").addEventListener("click", () => picker.click());
    picker.addEventListener("change", () => {
      addAttachments(picker.files).finally(() => { picker.value = ""; });
    });
    composer.addEventListener("dragover", (ev) => {
      if (!ev.dataTransfer || ![...ev.dataTransfer.types].includes("Files")) return;
      ev.preventDefault();
      composer.classList.add("drop");
    });
    composer.addEventListener("dragleave", () => composer.classList.remove("drop"));
    composer.addEventListener("drop", (ev) => {
      ev.preventDefault();
      composer.classList.remove("drop");
      addAttachments(ev.dataTransfer && ev.dataTransfer.files);
    });
  }
  function bind() {
    bindAttach();
    $("composer").addEventListener("submit", onSubmit);
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        $("composer").requestSubmit();
      } else if (ev.key === "ArrowUp" && !input.value && S.conv) {
        const last = [...S.messages].reverse().find((m) => m.role === "user");
        if (last) {
          S.editId = last.id;
          S.branchFrom = null;
          editPrefill = last.content || "";
          input.value = editPrefill;
          renderMode();
        }
      }
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && S.streaming && S.abort) S.abort.abort();
      else if (ev.key === "Escape" && (S.editId || S.branchFrom)) cancelMode();
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        $("search").focus();
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "n") {
        ev.preventDefault();
        $("new-chat").click();
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.shiftKey && ev.key.toLowerCase() === "m") {
        ev.preventDefault();
        $("model").focus();
      }
    });
    $("new-chat").addEventListener("click", () => {
      S.conv = null;
      S.messages = [];
      S.ephemeralLog = [];
      exitMode();
      $("title").textContent = "แชทใหม่";
      setNotice("");
      renderThread();
    });
    $("ephemeral").addEventListener("change", safe(async () => {
      S.ephemeral = $("ephemeral").checked;
      if (!S.ephemeral && S.ephemeralLog.length) {
        let data;
        try {
          data = await api("/api/chat/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ messages: S.ephemeralLog, title: clip(S.ephemeralLog[0].content, 40) }),
          });
        } catch (err) {
          // Stay in ephemeral mode so the temporary chat is not lost.
          S.ephemeral = true;
          $("ephemeral").checked = true;
          setNotice("บันทึกแชทชั่วคราวไม่สำเร็จ — ยังอยู่ในโหมดชั่วคราว: " + err.message);
          return;
        }
        S.ephemeralLog = [];
        await openConv(data.conversation.id);
      }
    }));
    $("model").addEventListener("change", () => {
      $("custom-model").hidden = $("model").value !== "custom";
    });
    $("compare-btn").addEventListener("click", () => {
      $("compare-box").hidden = !$("compare-box").hidden;
    });
    $("compare-go").addEventListener("click", safe(runCompare));
    $("search").addEventListener("input", () => {
      clearTimeout(S._searchT);
      S._searchT = setTimeout(safe(doSearch), 200);
    });
    $("add-folder").addEventListener("click", safe(async () => {
      const name = window.prompt("ชื่อโปรเจกต์");
      if (!name) return;
      await api("/api/chat/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, kind: "project" }),
      });
      await refreshLists();
    }));
    $("persona").addEventListener("change", safe(async () => {
      if (!S.conv) return;
      await api("/api/chat/conversations/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: S.conv.id, persona_id: $("persona").value || null }),
      });
    }));
    $("export-btn").addEventListener("click", safe(async () => {
      if (!S.conv) return;
      const data = await api("/api/chat/export?id=" + S.conv.id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "lca-chat-" + S.conv.uid + ".json";
      a.click();
    }));
    $("import-btn").addEventListener("click", () => $("import-file").click());
    $("import-file").addEventListener("change", safe(async () => {
      const picker = $("import-file");
      const file = picker.files[0];
      if (!file) return;
      try {
        let doc;
        try {
          doc = JSON.parse(await file.text());
        } catch (err) {
          setNotice("ไฟล์ไม่ใช่ JSON ที่ถูกต้อง");
          return;
        }
        const data = await api("/api/chat/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document: doc }),
        });
        await openConv(data.conversation.id);
      } finally {
        // Reset so choosing the same file again still fires "change".
        picker.value = "";
      }
    }));
    $("folder").addEventListener("change", safe(async () => {
      const value = $("folder").value;
      const data = await api("/api/chat/conversations?folder_id=" + encodeURIComponent(value));
      S.conversations = data.conversations || [];
      refreshLists.convOnly = true;
      const list = $("conv-list");
      list.replaceChildren();
      window.LCALayout.pinnedFirst(S.conversations).forEach((c) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = (c.pinned ? "● " : "") + (clip(c.title, 42) || "ไม่มีชื่อ");
        btn.addEventListener("click", safe(() => openConv(c.id)));
        list.append(btn);
      });
    }));
    window.addEventListener("online", () => { S.online = true; $("offline").hidden = true; fillModels(); });
    window.addEventListener("offline", () => { S.online = false; $("offline").hidden = false; fillModels(); });
  }
  async function boot() {
    bind();
    if (!S.online) $("offline").hidden = false;
    try {
      const cat = await api("/api/chat/providers");
      S.providers = cat.providers || [];
      fillModels();
      await refreshLists();
      const health = await api("/api/health");
      $("net-dot").textContent = health.ollama === "up" ? "local ● ออนไลน์" : "local ● ไม่พบ Ollama";
      const local = S.providers.find((p) => p.local);
      if (health.ollama !== "up") {
        setNotice("ไม่พบ Ollama — เปิดแอป Ollama แล้วรีเฟรชหน้านี้ (ดูสถานะและติดตั้งโมเดลที่หน้า /models)");
      } else if (!local || !(local.models || []).length) {
        setNotice("ยังไม่มีโมเดลในเครื่อง — ติดตั้งได้ที่หน้า /models");
      }
    } catch (err) {
      setNotice(err.message);
    }
    renderThread();
  }
  boot();
})();
