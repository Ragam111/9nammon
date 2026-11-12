// app.js — auth ร่วมของทุกหน้าในระบบ LCA (chat / dev / support / login)
// เก็บ key ไว้ฝั่ง browser (localStorage) แล้วแนบเป็น header ให้ทุก fetch เอง
// — ระบบ auth เป็น header-based (X-API-Key / X-Auth-Token) ไม่มี cookie/session ฝั่ง server
// ครอบทุกการเข้าถึง localStorage ด้วย try/catch เพราะโหมด private/ปิด storage จะ throw ได้
(function (w) {
  "use strict";
  var KEY = "lca_key";
  var LANG_KEY = "lca_ui_lang";

  function storedLang() {
    try {
      var v = localStorage.getItem(LANG_KEY);
      if (v === "en" || v === "th") return v;
    } catch (e) { /* storage ปิด */ }
    return "th";
  }

  try { document.documentElement.lang = storedLang(); } catch (e) { /* ไม่มี document */ }

  // session ที่เซิร์ฟเวอร์ฝังในหน้า หรือ fragment #lca_token= — ไม่เขียนทับ key ที่ผู้ใช้บันทึก
  function launchToken() {
    if (w.__LCA_SESSION_TOKEN) return String(w.__LCA_SESSION_TOKEN);
    try {
      var h = (w.location && w.location.hash) || "";
      var m = h.match(/(?:^#|&)lca_token=([^&]+)/);
      return m ? decodeURIComponent(m[1]) : "";
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
        var data = await res.json();
        if (!res.ok || !data.token) { this.lastError = data.error || ("HTTP " + res.status); return null; }
        this.setKey(data.token);
        return data;
      } catch (e) { this.lastError = String(e); return null; }
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
    },

    // ภาษา UI: ไทยเป็นค่าเริ่มต้น เลือกอังกฤษได้ จำในเครื่องนี้
    uiLang: function () { return storedLang(); },
    setUiLang: function (lang) {
      lang = lang === "en" ? "en" : "th";
      try { localStorage.setItem(LANG_KEY, lang); } catch (e) { /* ใช้ต่อแบบไม่จำ */ }
      try { document.documentElement.lang = lang; } catch (e2) { /* ignore */ }
      try { document.dispatchEvent(new CustomEvent("lca-lang", { detail: lang })); } catch (e3) { /* ignore */ }
      this.refreshBadge();
    },

    // เติมข้อความจาก dict[lang] ลง [data-i18n] / placeholder / aria-label / title
    applyI18n: function (dict) {
      var lang = this.uiLang();
      var pack = (dict && (dict[lang] || dict.th)) || {};
      var nodes = document.querySelectorAll("[data-i18n]");
      var i, key;
      for (i = 0; i < nodes.length; i++) {
        key = nodes[i].getAttribute("data-i18n");
        if (pack[key] != null) nodes[i].textContent = pack[key];
      }
      var attrs = ["placeholder", "aria-label", "title"];
      var a, name, list, j;
      for (a = 0; a < attrs.length; a++) {
        name = attrs[a];
        list = document.querySelectorAll("[data-i18n-" + name + "]");
        for (j = 0; j < list.length; j++) {
          key = list[j].getAttribute("data-i18n-" + name);
          if (pack[key] != null) list[j].setAttribute(name, pack[key]);
        }
      }
    },

    // อ่าน GET /api/version แล้วโชว์รุ่น + เซิร์ฟเวอร์พร้อม หรือออฟไลน์
    refreshBadge: async function () {
      var el = document.getElementById("lca-status");
      var textEl = document.getElementById("lca-status-text");
      if (!el || !textEl) return;
      var en = this.uiLang() === "en";
      try {
        var res = await fetch("/api/version", { cache: "no-store" });
        if (!res.ok) throw new Error("status");
        var data = await res.json();
        var ver = data && data.version ? String(data.version) : "?";
        textEl.textContent = "v" + ver + " · " + (en ? "server OK" : "เซิร์ฟเวอร์พร้อม");
        el.classList.add("ok");
        el.classList.remove("bad");
      } catch (e) {
        textEl.textContent = en ? "offline" : "ออฟไลน์";
        el.classList.add("bad");
        el.classList.remove("ok");
      }
    }
  };

  function bootChrome() {
    var sel = document.getElementById("ui-lang");
    if (sel) {
      sel.value = w.lca.uiLang();
      sel.addEventListener("change", function () { w.lca.setUiLang(sel.value); });
    }
    w.lca.refreshBadge();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootChrome);
  else bootChrome();
})(window);
