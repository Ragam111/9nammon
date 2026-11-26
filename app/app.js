// app.js — auth ร่วมของทุกหน้าในระบบ LCA (chat / dev / support / login)
// เก็บ key ไว้ฝั่ง browser (localStorage) แล้วแนบเป็น header ให้ทุก fetch เอง
// — ระบบ auth เป็น header-based (X-API-Key / X-Auth-Token) ไม่มี cookie/session ฝั่ง server
// ครอบทุกการเข้าถึง localStorage ด้วย try/catch เพราะโหมด private/ปิด storage จะ throw ได้
(function (w) {
  "use strict";
  var KEY = "lca_key";

  // session ที่เซิร์ฟเวอร์ฝังในหน้า หรือ fragment #lca_token= — ไม่เขียนทับ key ที่ผู้ใช้บันทึก
  function launchToken() {
    if (w.__LCA_SESSION_TOKEN) return String(w.__LCA_SESSION_TOKEN);
    try {
      var h = (w.location && w.location.hash) || "";
      var m = h.match(/(?:^#|&)lca_token=([^&]+)/);
      return m ? decodeURIComponent(m[1]) : "";
    } catch (e) { return ""; }
  }

  // Google sign-in: the callback puts a one-time login code (not a session) in the
  // fragment #lca_login_code=. Read it, strip it from the URL right away, and never
  // store it as a key: the session comes only from POST /api/auth/google/finish,
  // which also requires the HttpOnly lca_google_finish cookie set for this browser.
  function takeLoginCode() {
    try {
      var h = (w.location && w.location.hash) || "";
      var m = h.match(/(?:^#|&)lca_login_code=([^&]+)/);
      if (!m) return "";
      if (w.history && w.history.replaceState) {
        w.history.replaceState(null, "", w.location.pathname + w.location.search);
      }
      return decodeURIComponent(m[1]);
    } catch (e) { return ""; }
  }

  w.lca = {
    getKey: function () {
      try {
        var stored = localStorage.getItem(KEY) || "";
        if (stored) return stored;
      } catch (e) { /* storage ปิด — ใช้ session ของการเปิดครั้งนี้ */ }
      return launchToken();
    },
    setKey: function (v) {
      try {
        if (v) localStorage.setItem(KEY, v);
        else localStorage.removeItem(KEY);
      } catch (e) { /* storage ปิดอยู่ — ใช้งานต่อได้แบบไม่จำ key */ }
      // cookie ใช้เฉพาะตอน browser เปิด "หน้า" ที่ต้องมีสิทธิ์ (/dev, /console) — navigation
      // ส่ง header เองไม่ได้; server ไม่รับ cookie กับ /api/* (header-only กัน CSRF)
      try {
        if (v) document.cookie = KEY + "=" + encodeURIComponent(v) + "; path=/; SameSite=Strict";
        else document.cookie = KEY + "=; path=/; Max-Age=0; SameSite=Strict";
      } catch (e) { /* cookie ปิดอยู่ */ }
    },
    clearKey: function () { this.setKey(""); },

    // ล็อกอินด้วย username/password → ได้ session token (อายุจำกัด) แล้วเก็บเหมือน key
    // คืน {username,role,tier} หรือ null (รหัสผิด/ล็อกถี่เกิน) — error อยู่ใน this.lastError
    login: async function (username, password) {
      this.lastError = "";
      try {
        var res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: username, password: password })
        });
        // เซิร์ฟเวอร์ตอบไม่ใช่ JSON (เช่น หน้า HTML 502 จาก proxy) — ไม่ให้ SyntaxError หลุดไปถึงผู้ใช้
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok || !data.token) { this.lastError = data.error || ("HTTP " + res.status); return null; }
        this.setKey(data.token);
        return data;
      } catch (e) {
        // ต่อ server ไม่ได้ (network/เครื่องปิด) — ใช้ข้อความไทยแทน TypeError ดิบ
        console.error("login ไม่สำเร็จ:", e);
        this.lastError = "ต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจว่า LCA เปิดอยู่";
        return null;
      }
    },

    // ออกจากระบบ: เพิกถอน session ฝั่ง server (ถ้าเป็น session) แล้วล้าง key ฝั่ง browser
    logout: async function () {
      try {
        await fetch("/api/auth/logout", { method: "POST", headers: this.authHeaders() });
      } catch (e) { /* server ไม่ตอบก็ล้างฝั่งเราอยู่ดี */ }
      this.clearKey();
    },

    // แนบทั้งสอง header — วาง master token หรือ API key ช่องเดียวกันได้ server แยกเอง
    authHeaders: function () {
      var t = this.getKey();
      return t ? { "X-API-Key": t, "X-Auth-Token": t } : {};
    },

    // ผสม auth เข้ากับ header อื่น (เช่น Content-Type) สำหรับ fetch
    headers: function (extra) {
      var h = this.authHeaders();
      if (extra) { for (var k in extra) if (extra.hasOwnProperty(k)) h[k] = extra[k]; }
      return h;
    },

    // ถาม server ว่า key ปัจจุบันคือใคร — คืน {username,role,tier} หรือ null ถ้าไม่ผ่าน
    // โหมด local ที่ไม่ได้ตั้ง token: หน้าเว็บส่ง session token ที่เซิร์ฟเวอร์ฝังให้ แล้วได้สิทธิ์ CEO
    whoami: async function () {
      try {
        var res = await fetch("/api/me", { headers: this.authHeaders() });
        if (!res.ok) return null;
        return await res.json();
      } catch (e) { return null; }
    }
  };
  // finish Google sign-in only through the cookie-bound POST (an attacker's code
  // fails here without the attacker's cookie, so it cannot replace this browser's key)
  async function finishGoogleLogin(code) {
    try {
      var res = await fetch("/api/auth/google/finish", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code })
      });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok || !data.token) {
        w.lca.lastError = data.error || ("HTTP " + res.status);
        return null;
      }
      var before = w.lca.getKey();
      w.lca.setKey(data.token);
      if (before !== data.token && w.location && w.location.reload) w.location.reload();
      return data;
    } catch (e) {
      w.lca.lastError = "ต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจว่า LCA เปิดอยู่";
      return null;
    }
  }
  var loginCode = takeLoginCode();
  w.lca.googleLoginDone = loginCode ? finishGoogleLogin(loginCode) : Promise.resolve(null);

  // ---------- Shared shell: nav + status chip (LCA_UI_SPEC task 4) ----------
  // Rendered into #lca-shell (full nav + chip) or #lca-status-chip (chip only, /chat).
  // textContent only. Quota comes from GET /api/me, which is read-only (no reserve).
  var SHELL_LINKS = [
    { href: "/chat", label: "Chat" },
    { href: "/models", label: "Models" },
    { href: "/console/keys", label: "API keys" },
    { href: "/plans", label: "Plans" },
    { href: "/spaces", label: "Spaces" },
    { href: "/support", label: "Support" }
  ];
  var ADMIN_LINK = { href: "/admin/db", label: "Admin DB" };
  var SHELL_POLL_MS = 30000;

  function el(tag, cls, text) {
    var e = w.document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }

  function chipText(health, me) {
    var parts = ["Ollama " + (health && health.ollama === "up" ? "up" : "down")];
    var t = me && me.tokens;
    if (t && t.limit != null) parts.push("tokens " + (t.used || 0) + "/" + t.limit);
    return parts.join(" · ");
  }

  async function getJson(url, headers) {
    try {
      var res = await w.fetch(url, { headers: headers || {} });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) { return null; }
  }

  async function refreshChip(chip) {
    var health = await getJson("/api/health");
    var me = w.lca.getKey() ? await getJson("/api/me", w.lca.authHeaders()) : null;
    chip.textContent = chipText(health, me);
    chip.setAttribute("data-ollama", health && health.ollama === "up" ? "up" : "down");
    return me;
  }

  function buildNav(mount, isCeo) {
    var bar = el("div", "lca-shell-bar");
    var btn = el("button", "lca-shell-menu", "☰");
    btn.type = "button";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "lca-shell-nav");
    btn.setAttribute("aria-label", "เมนู");
    var nav = el("nav", "lca-shell-nav");
    nav.id = "lca-shell-nav";
    nav.setAttribute("aria-label", "เมนูหลัก");
    var links = SHELL_LINKS.slice();
    if (isCeo) links.push(ADMIN_LINK);
    var here = (w.location && w.location.pathname) || "";
    links.forEach(function (l) {
      var a = el("a", null, l.label);
      a.href = l.href;
      if (l.href === here) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });
    function setOpen(open) {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      nav.classList.toggle("open", open);
    }
    btn.addEventListener("click", function () { setOpen(btn.getAttribute("aria-expanded") !== "true"); });
    w.document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && btn.getAttribute("aria-expanded") === "true") { setOpen(false); btn.focus(); }
    });
    var chip = el("span", "chip lca-shell-chip", "Ollama …");
    chip.setAttribute("role", "status");
    bar.appendChild(btn); bar.appendChild(nav); bar.appendChild(chip);
    while (mount.firstChild) mount.removeChild(mount.firstChild);
    mount.appendChild(bar);
    return { nav: nav, chip: chip, btn: btn };
  }

  async function renderShell() {
    var d = w.document;
    var mount = d.getElementById("lca-shell");
    var chip = d.getElementById("lca-status-chip");
    if (!mount && !chip) return null;
    var parts = null;
    if (mount) { parts = buildNav(mount, false); chip = parts.chip; }
    var me = await refreshChip(chip);
    if (parts && me && me.role === "CEO") {
      var text = chip.textContent, state = chip.getAttribute("data-ollama");
      parts = buildNav(mount, true);
      chip = parts.chip;
      chip.textContent = text;
      chip.setAttribute("data-ollama", state);
    }
    w.setInterval(function () { refreshChip(chip); }, SHELL_POLL_MS);
    return parts || { chip: chip };
  }
  w.lca.renderShell = renderShell;
  w.lca.SHELL_LINKS = SHELL_LINKS;
  w.lca.SHELL_POLL_MS = SHELL_POLL_MS;
  if (w.document && w.document.readyState !== "loading") renderShell();
  else if (w.document && w.document.addEventListener) w.document.addEventListener("DOMContentLoaded", renderShell);

  // PWA: register the service worker only on secure contexts (https / localhost / 127.0.0.1).
  // Any failure is swallowed so the page keeps working without offline support.
  function registerServiceWorker() {
    try {
      var loc = w.location || {};
      var host = loc.hostname || "";
      var secure = loc.protocol === "https:" || host === "localhost" || host === "127.0.0.1";
      if (!secure || w.isSecureContext === false) return;
      if (!w.navigator || !("serviceWorker" in w.navigator)) return;
      w.navigator.serviceWorker.register("/sw.js", { scope: "/" })
        .catch(function () { /* no offline support — page still works */ });
    } catch (e) { /* ignore */ }
  }
  if (w.document && w.document.readyState === "complete") registerServiceWorker();
  else if (w.addEventListener) w.addEventListener("load", registerServiceWorker);
})(window);
