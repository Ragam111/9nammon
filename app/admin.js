// admin.js — LCA-Admin hub (/admin). textContent only; POSTs carry X-LCA-CSRF (double-submit).
(function (w) {
  "use strict";
  var d = w.document;

  function $(id) { return d.getElementById(id); }

  function csrfToken() {
    var m = (d.cookie || "").match(/(?:^|;\s*)lca_csrf=([^;]+)/);
    return m ? m[1] : "";
  }

  function headers(extra) {
    var h = (w.lca && w.lca.authHeaders) ? w.lca.authHeaders() : {};
    Object.keys(extra || {}).forEach(function (k) { h[k] = extra[k]; });
    return h;
  }

  function showErr(msg) {
    var e = $("err");
    e.textContent = msg || "";
    e.hidden = !msg;
  }

  async function getJson(url) {
    var res = await w.fetch(url, { headers: headers(), cache: "no-store" });
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }

  async function postJson(url, body) {
    var res = await w.fetch(url, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json", "X-LCA-CSRF": csrfToken() }),
      body: JSON.stringify(body || {})
    });
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }

  function pretty(el, data) { el.textContent = JSON.stringify(data, null, 2); }

  function statCard(label, value) {
    var c = d.createElement("div");
    c.className = "card";
    var b = d.createElement("b");
    b.textContent = value == null ? "—" : String(value);
    var s = d.createElement("span");
    s.textContent = label;
    c.appendChild(b);
    c.appendChild(s);
    return c;
  }

  async function loadOverview() {
    var box = $("stats");
    box.textContent = "";
    try {
      var st = await getJson("/api/admin/stats");
      Object.keys(st).slice(0, 12).forEach(function (k) {
        var v = st[k];
        box.appendChild(statCard(k, typeof v === "object" ? JSON.stringify(v) : v));
      });
    } catch (e) { showErr("stats: " + e.message); }
    try { pretty($("watchdog"), await getJson("/api/admin/watchdog")); }
    catch (e) { $("watchdog").textContent = e.message; }
  }

  async function loadUsers() {
    var tb = $("users");
    tb.textContent = "";
    try {
      var data = await getJson("/api/admin/users");
      (data.users || []).forEach(function (u) {
        var tr = d.createElement("tr");
        [u.username, u.role, u.tier].forEach(function (v) {
          var td = d.createElement("td");
          td.textContent = v == null ? "" : String(v);
          tr.appendChild(td);
        });
        tb.appendChild(tr);
      });
    } catch (e) { showErr("users: " + e.message); }
  }

  async function loadFinance(target, refundsOnly) {
    try {
      var data = await getJson("/api/admin/finance");
      if (refundsOnly && Array.isArray(data.records)) {
        data = { records: data.records.filter(function (r) {
          return /refund/i.test(String(r.status || r.kind || ""));
        }) };
      }
      pretty($(target), data);
    } catch (e) { $(target).textContent = e.message; }
  }

  async function nodeAction(action) {
    var out = $("nodes");
    out.textContent = "กำลังสั่ง " + action + "…";
    try { pretty(out, await postJson("/api/admin/nodes", { action: action })); }
    catch (e) { out.textContent = e.message; }
  }

  var LOADERS = {
    overview: loadOverview,
    users: loadUsers,
    orders: function () { return loadFinance("orders", false); },
    refunds: function () { return loadFinance("refunds", true); },
    nodes: function () {}
  };

  function show(sec) {
    if (!LOADERS[sec]) sec = "overview";
    Object.keys(LOADERS).forEach(function (k) { $("sec-" + k).hidden = k !== sec; });
    d.querySelectorAll(".nav a[data-sec]").forEach(function (a) {
      if (a.getAttribute("data-sec") === sec) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    showErr("");
    LOADERS[sec]();
  }

  d.addEventListener("DOMContentLoaded", function () {
    d.querySelectorAll("[data-node]").forEach(function (b) {
      b.addEventListener("click", function () { nodeAction(b.getAttribute("data-node")); });
    });
    w.addEventListener("hashchange", function () { show(w.location.hash.slice(1)); });
    show((w.location.hash || "#overview").slice(1));
  });
})(window);
