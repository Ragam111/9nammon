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
    },
    clearKey: function () { this.setKey(""); },

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
})(window);
