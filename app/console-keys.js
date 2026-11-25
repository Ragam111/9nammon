/* LCA Console — API keys page (/console/keys).
 * Builds every node with createElement + textContent: user data never reaches an HTML parser.
 * Pure helpers are exported for node tests (tests/js/console_keys_xss.js). */
(function (root) {
  "use strict";

  var STATUS_TEXT = { active: "ใช้งาน", revoked: "ยกเลิกแล้ว" };

  function el(doc, tag, cls, text) {
    var node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function fmtDate(iso) {
    if (!iso) return "-";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 10);
    try {
      return d.toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
    } catch (e) {
      return d.toISOString().slice(0, 10);
    }
  }

  function filterKeys(keys, status, tier) {
    return (keys || []).filter(function (k) {
      if (status === "active" && !k.active) return false;
      if (status === "revoked" && k.active) return false;
      if (tier && tier !== "all" && k.tier !== tier) return false;
      return true;
    });
  }

  function cell(doc, label) {
    var td = doc.createElement("td");
    td.setAttribute("data-label", label);
    return td;
  }

  // One table row for key k. onRevoke(k) is called by the "ยกเลิก" button.
  function buildRow(doc, k, onRevoke) {
    var tr = doc.createElement("tr");
    var td = cell(doc, "ชื่อ");
    td.appendChild(el(doc, "span", k.name ? "" : "muted", k.name || "(ไม่มีชื่อ)"));
    tr.appendChild(td);

    td = cell(doc, "คีย์");
    td.appendChild(el(doc, "span", "mono", (k.prefix || "") + "..."));
    tr.appendChild(td);

    td = cell(doc, "ระดับ");
    td.appendChild(el(doc, "span", "pill" + (k.tier === "paid" ? " paid" : ""), k.tier));
    tr.appendChild(td);

    td = cell(doc, "เจ้าของ");
    var who = el(doc, "div", "", "");
    who.appendChild(el(doc, "div", "", k.owner || "-"));
    if (k.created_by) who.appendChild(el(doc, "div", "muted small", "สร้างโดย " + k.created_by));
    td.appendChild(who);
    tr.appendChild(td);

    tr.appendChild(textCell(doc, "วันที่สร้าง", fmtDate(k.created_at), "num"));

    td = cell(doc, "ใช้วันนี้");
    var used = Number(k.used_today) || 0;
    var limit = Number(k.daily_limit) || 0;
    var box = el(doc, "div", "", "");
    box.appendChild(el(doc, "span", "num", used + " / " + limit));
    var bar = el(doc, "div", "bar" + (limit && used >= limit ? " full" : ""), null);
    var fill = doc.createElement("i");
    fill.setAttribute("style", "width:" + (limit ? Math.min(100, Math.round(used * 100 / limit)) : 0) + "%");
    bar.appendChild(fill);
    box.appendChild(bar);
    td.appendChild(box);
    tr.appendChild(td);

    td = cell(doc, "สถานะ");
    td.appendChild(el(doc, "span", "pill " + (k.active ? "ok" : "off"),
      k.active ? STATUS_TEXT.active : STATUS_TEXT.revoked));
    tr.appendChild(td);

    td = cell(doc, "");
    if (k.active) {
      var btn = el(doc, "button", "btn danger", "ยกเลิก");
      btn.setAttribute("type", "button");
      btn.addEventListener("click", function () { onRevoke(k); });
      td.appendChild(btn);
    }
    tr.appendChild(td);
    return tr;
  }

  function textCell(doc, label, text, cls) {
    var td = cell(doc, label);
    td.appendChild(el(doc, "span", cls || "", text));
    return td;
  }

  var api = { buildRow: buildRow, filterKeys: filterKeys, fmtDate: fmtDate };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.lcaConsoleKeys = api;

  if (typeof document === "undefined" || !document.getElementById("keys-body")) return;
  init(document);

  function init(doc) {
    var $ = function (id) { return doc.getElementById(id); };
    var state = { keys: [], pending: null };

    function headers() {
      var base = { "Content-Type": "application/json" };
      var lca = root.lca;
      return lca && typeof lca.headers === "function" ? Object.assign(base, lca.headers()) : base;
    }

    async function call(method, url, body) {
      var res = await fetch(url, { method: method, headers: headers(),
        body: body ? JSON.stringify(body) : undefined });
      var data = {};
      try { data = await res.json(); } catch (e) { data = {}; }
      if (!res.ok) {
        var msg = (data && (typeof data.error === "string" ? data.error : data.error && data.error.message))
          || ("HTTP " + res.status);
        throw new Error(msg);
      }
      return data;
    }

    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

    function render() {
      var body = $("keys-body");
      clear(body);
      $("key-count").textContent = String(state.keys.length);
      var rows = filterKeys(state.keys, $("f-status").value, $("f-tier").value);
      rows.slice().reverse().forEach(function (k) { body.appendChild(buildRow(doc, k, askRevoke)); });
      var empty = rows.length === 0;
      $("empty").hidden = !empty;
      if (empty) {
        var none = state.keys.length === 0;
        $("empty-title").textContent = none ? "ยังไม่มี API key" : "ไม่พบคีย์ตามตัวกรอง";
        $("empty-text").textContent = none ? "กด \"สร้างคีย์\" เพื่อออกคีย์แรก" : "ลองเปลี่ยนสถานะหรือระดับ";
      }
    }

    async function load() {
      $("msg").textContent = "";
      try {
        var data = await call("GET", "/api/admin/apikeys");
        state.keys = Array.isArray(data.api_keys) ? data.api_keys : [];
      } catch (e) {
        state.keys = [];
        $("msg").textContent = "โหลดรายการคีย์ไม่ได้: " + e.message;
      }
      render();
    }

    async function loadOwners() {
      try {
        var data = await call("GET", "/api/admin/users");
        var list = $("owners");
        clear(list);
        (data.users || []).forEach(function (u) {
          var opt = doc.createElement("option");
          opt.value = String(u.username || "");
          list.appendChild(opt);
        });
      } catch (e) { /* datalist is only a hint */ }
    }

    // ---- create dialog ----
    function openCreate() {
      $("c-name").value = "";
      $("c-owner").value = "";
      $("c-tier").value = "free";
      $("c-err").textContent = "";
      $("c-key").value = "";
      $("create-fields").hidden = false;
      $("create-done").hidden = true;
      $("c-submit").disabled = false;
      loadOwners();
      $("dlg-create").showModal();
      $("c-name").focus();
    }

    function closeCreate() {
      $("c-key").value = "";            // drop the full key from the DOM
      $("dlg-create").close();
    }

    $("form-create").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      var owner = $("c-owner").value.trim();
      if (!owner) { $("c-err").textContent = "ต้องระบุเจ้าของคีย์"; return; }
      $("c-submit").disabled = true;
      $("c-err").textContent = "";
      try {
        var data = await call("POST", "/api/admin/apikeys",
          { name: $("c-name").value.trim(), owner: owner, tier: $("c-tier").value });
        $("c-key").value = data.api_key && data.api_key.key ? data.api_key.key : "";
        $("create-fields").hidden = true;
        $("create-done").hidden = false;
        $("c-key").select();
        load();
      } catch (e) {
        $("c-err").textContent = "สร้างคีย์ไม่ได้: " + e.message;
      } finally {
        $("c-submit").disabled = false;
      }
    });

    $("c-copy").addEventListener("click", async function () {
      var input = $("c-key");
      try {
        await navigator.clipboard.writeText(input.value);
      } catch (e) {
        input.select();
        try { doc.execCommand("copy"); } catch (e2) { /* user can copy by hand */ }
      }
      $("c-copy").textContent = "คัดลอกแล้ว";
      setTimeout(function () { $("c-copy").textContent = "คัดลอก"; }, 1500);
    });

    $("btn-create").addEventListener("click", openCreate);
    $("c-cancel").addEventListener("click", closeCreate);
    $("c-done").addEventListener("click", closeCreate);
    $("dlg-create").addEventListener("close", function () { $("c-key").value = ""; });

    // ---- revoke dialog ----
    function askRevoke(k) {
      state.pending = k;
      $("r-name").textContent = k.name || "(ไม่มีชื่อ)";
      $("r-prefix").textContent = (k.prefix || "") + "...";
      $("r-err").textContent = "";
      $("r-confirm").disabled = false;
      $("dlg-revoke").showModal();
    }

    $("r-cancel").addEventListener("click", function () { $("dlg-revoke").close(); });
    $("r-confirm").addEventListener("click", async function () {
      if (!state.pending) return;
      $("r-confirm").disabled = true;
      try {
        await call("POST", "/api/admin/apikeys/revoke", { key_id: state.pending.key_id });
        $("dlg-revoke").close();
        state.pending = null;
        load();
      } catch (e) {
        $("r-err").textContent = "ยกเลิกไม่ได้: " + e.message;
        $("r-confirm").disabled = false;
      }
    });

    $("f-status").addEventListener("change", render);
    $("f-tier").addEventListener("change", render);
    load();
  }
})(typeof window !== "undefined" ? window : globalThis);
