/* LCA Chat Hub — vanilla JS. No framework, no CDN. */
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
    ollama: "",
  };
  const COPY = {
    th: {
      newChat: "+ แชทใหม่", searchPh: "ค้นหา… (Ctrl+K)", project: "โปรเจกต์", addProject: "สร้างโปรเจกต์",
      ephemeral: "ชั่วคราว (ไม่บันทึก)", home: "หน้าแรก", classic: "เครื่องมือเดิม", keys: "คีย์",
      newChatTitle: "แชทใหม่", model: "โมเดล", customModel: "ชื่อโมเดล", compare: "เทียบ", persona: "บุคลิก",
      exportBtn: "ส่งออก", importBtn: "นำเข้า", offlineBanner: "ไม่มีอินเทอร์เน็ต — ใช้ได้เฉพาะโมเดล local",
      composerPh: "พิมพ์ข้อความ… (Enter ส่ง, Shift+Enter ขึ้นบรรทัด)", send: "ส่ง",
      compareHelp: "เลือกอย่างน้อย 2 โมเดล แล้วกดเทียบกับข้อความในช่องพิมพ์",
      queueNote: "รอคิว — เครื่องรันได้ทีละโมเดล local", compareGo: "เทียบตอนนี้", uiLang: "ภาษา",
      customOpt: "กำหนดโมเดลเอง", needOnline: "ต้องออนไลน์", allRecent: "ล่าสุดทั้งหมด", noProject: "ไม่มีโปรเจกต์",
      untitled: "ไม่มีชื่อ", copy: "คัดลอก", emptyTitle: "เริ่มแชทใหม่", samplesLead: "ตัวอย่าง:",
      sample1: "อธิบายโค้ดนี้", sample2: "เขียนเทสต์", sample3: "สรุปไฟล์", sample4: "แปลไทย↔อังกฤษ",
      loadOlder: "โหลดข้อความเก่า", you: "คุณ", assistant: "ผู้ช่วย",
      stopped: "หยุดแล้ว — ข้อความเท่าที่ได้ถูกเก็บไว้",
      dropped: "ขาดตอน — ต่อโมเดลไม่สำเร็จ ข้อความเท่าที่ได้ถูกเก็บไว้",
      pickThis: "เลือกอันนี้ต่อ", regen: "ตอบใหม่", branch: "แตกสาขา",
      branchPh: "ข้อความสาขาใหม่จากข้อความนี้", chat: "แชท", needModel: "ต้องเลือกโมเดล",
      cloudNeedsNet: "โมเดล cloud ต้องออนไลน์", stop: "หยุด", sendFail: "ส่งไม่สำเร็จ",
      editPartial: "แก้แล้วแต่คำตอบขาดตอน", branchPartial: "สาขาใหม่ตอบไม่จบ",
      keptPartial: " — ข้อความเท่าที่ได้ถูกเก็บไว้", regenFail: "ตอบใหม่ไม่สำเร็จ",
      needTwo: "เลือกอย่างน้อย 2 โมเดล", needText: "ต้องมีข้อความที่จะเทียบ", comparing: "กำลังเทียบ…",
      somePartial: "บางคำตอบขาดตอน: ", namePrefix: "ชื่อ: ", noHits: "ไม่พบ", projectName: "ชื่อโปรเจกต์",
      ollamaUp: "local ● ออนไลน์", ollamaDown: "local ● ไม่พบ Ollama",
    },
    en: {
      newChat: "+ New chat", searchPh: "Search… (Ctrl+K)", project: "Project", addProject: "New project",
      ephemeral: "Temporary (not saved)", home: "Home", classic: "Older tools", keys: "Keys",
      newChatTitle: "New chat", model: "Model", customModel: "Model name", compare: "Compare", persona: "Persona",
      exportBtn: "Export", importBtn: "Import", offlineBanner: "No internet — local models only",
      composerPh: "Message… (Enter to send, Shift+Enter for a new line)", send: "Send",
      compareHelp: "Pick at least 2 models, then compare the message in the box",
      queueNote: "Queued — this machine runs one local model at a time", compareGo: "Compare now", uiLang: "Language",
      customOpt: "Custom model", needOnline: "Needs internet", allRecent: "All recent", noProject: "No project",
      untitled: "Untitled", copy: "Copy", emptyTitle: "Start a new chat", samplesLead: "Examples:",
      sample1: "Explain this code", sample2: "Write a test", sample3: "Summarize a file", sample4: "Translate Thai↔English",
      loadOlder: "Load older messages", you: "You", assistant: "Assistant",
      stopped: "Stopped — the partial reply was kept",
      dropped: "Interrupted — the model did not finish. The partial reply was kept",
      pickThis: "Continue with this", regen: "Regenerate", branch: "Branch",
      branchPh: "New branch from this message", chat: "Chat", needModel: "Choose a model",
      cloudNeedsNet: "Cloud models need internet", stop: "Stop", sendFail: "Could not send",
      editPartial: "Edited, but the reply was interrupted", branchPartial: "The new branch did not finish",
      keptPartial: " — the partial reply was kept", regenFail: "Could not regenerate",
      needTwo: "Pick at least 2 models", needText: "Need a message to compare", comparing: "Comparing…",
      somePartial: "Some replies were interrupted: ", namePrefix: "Title: ", noHits: "No matches", projectName: "Project name",
      ollamaUp: "local ● online", ollamaDown: "local ● Ollama not found",
    },
  };
  function tx(key) {
    const lang = document.documentElement.lang === "en" ? "en" : "th";
    const pack = COPY[lang] || COPY.th;
    return pack[key] != null ? pack[key] : (COPY.th[key] != null ? COPY.th[key] : key);
  }
  function paintTitle() {
    if (S.conv) $("title").textContent = clip(S.conv.title, 48) || tx("chat");
    else $("title").textContent = tx("newChatTitle");
  }
  function paintSend() {
    sendBtn.textContent = S.streaming ? tx("stop") : tx("send");
  }
  function paintComposer() {
    input.placeholder = S.branchFrom ? tx("branchPh") : tx("composerPh");
  }
  function paintNet() {
    const el = $("net-dot");
    if (!el || !S.ollama) return;
    el.textContent = S.ollama === "up" ? tx("ollamaUp") : tx("ollamaDown");
  }
  function applyChrome() {
    if (window.lca && window.lca.applyI18n) window.lca.applyI18n(COPY);
    paintTitle();
    paintSend();
    paintComposer();
    paintNet();
  }
  const $ = (id) => document.getElementById(id);
  const thread = $("thread");
  const input = $("input");
  const sendBtn = $("send");

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
        opt.title = opt.disabled ? tx("needOnline") : (p.local ? "local" : "cloud");
        sel.append(opt);
      });
    });
    const custom = document.createElement("option");
    custom.value = "custom";
    custom.textContent = tx("customOpt");
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
    all.textContent = tx("allRecent");
    folder.append(all);
    const root = document.createElement("option");
    root.value = "root";
    root.textContent = tx("noProject");
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
    none.textContent = tx("persona");
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
    S.conversations.forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = (c.pinned ? "● " : "") + (clip(c.title, 42) || tx("untitled"));
      btn.setAttribute("aria-current", S.conv && S.conv.id === c.id ? "true" : "false");
      btn.addEventListener("click", () => openConv(c.id));
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
        const pre = document.createElement("pre");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "copy";
        btn.textContent = tx("copy");
        btn.addEventListener("click", () => navigator.clipboard.writeText(code));
        const codeEl = document.createElement("code");
        codeEl.textContent = code;
        pre.append(btn, codeEl);
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
      const heading = document.createElement("h1");
      heading.textContent = tx("emptyTitle");
      const lead = document.createElement("p");
      lead.textContent = tx("samplesLead");
      empty.append(heading, lead);
      ["sample1", "sample2", "sample3", "sample4"].forEach((sampleKey) => {
        const sample = tx(sampleKey);
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
      more.textContent = tx("loadOlder");
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
      const label = m.role === "user" ? tx("you") : ((m.model || m.provider || tx("assistant")) + (m.provider ? " · " + m.provider : ""));
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
        warn.textContent = m.status === "stopped" ? tx("stopped") : tx("dropped");
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
          pick.textContent = tx("pickThis");
          pick.addEventListener("click", () => switchTo(c.id));
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
        regen.textContent = tx("regen");
        regen.addEventListener("click", () => regenMsg(m));
        actions.append(regen);
      }
      const branch = document.createElement("button");
      branch.type = "button";
      branch.textContent = tx("branch");
      branch.addEventListener("click", () => {
        S.branchFrom = m.id;
        S.editId = null;
        input.placeholder = tx("branchPh");
        input.focus();
      });
      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = tx("copy");
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
    S.editId = null;
    S.branchFrom = null;
    paintTitle();
    if (S.conv.persona_id) $("persona").value = String(S.conv.persona_id);
    renderThread();
    refreshLists();
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
    if (!picked.model) { setNotice(tx("needModel")); return; }
    if (!S.online && S.providers.some((p) => p.id === picked.provider && !p.local)) {
      setNotice(tx("cloudNeedsNet"));
      return;
    }
    S.streaming = true;
    sendBtn.textContent = tx("stop");
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
          throw new Error(err.error || tx("sendFail"));
        }
        let acc = "";
        await readSSE(resp, (ev) => {
          if (ev.delta) {
            acc += ev.delta;
            if (node) node.textContent = acc;
          }
          if (ev.error) {
            draft.status = "error";
            draft.content = acc;
            setNotice(ev.error + tx("keptPartial"));
          }
          if (ev.done) draft.status = "ok";
        });
        draft.content = acc;
        draft.status = draft.status === "error" ? "error" : "ok";
        S.ephemeralLog.push({ role: "assistant", content: acc, provider: picked.provider, model: picked.model });
      } catch (err) {
        if (err.name !== "AbortError") setNotice(err.message);
        draft.status = ctrl.signal.aborted ? "stopped" : "error";
      }
      S.streaming = false;
      sendBtn.textContent = tx("send");
      renderThread();
      return;
    }
    const conv = await ensureConv();
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
        throw new Error(err.error || tx("sendFail"));
      }
      await readSSE(resp, (ev) => {
        if (ev.delta) {
          acc += ev.delta;
          if (node) node.textContent = acc;
          thread.scrollTop = thread.scrollHeight;
        }
        if (ev.error) {
          draft.status = ev.status || "error";
          setNotice(ev.error ? ev.error + tx("keptPartial") : tx("dropped"));
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
    sendBtn.textContent = tx("send");
    input.placeholder = tx("composerPh");
  }
  async function onSubmit(ev) {
    ev.preventDefault();
    if (S.streaming) {
      if (S.abort) S.abort.abort();
      return;
    }
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    const picked = choice();
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
        S.editId = null;
        if (data.status && data.status !== "ok") setNotice(data.error || tx("editPartial"));
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
        S.branchFrom = null;
        if (data.status && data.status !== "ok") setNotice(data.error || tx("branchPartial"));
        await openConv(S.conv.id);
        return;
      }
      await sendStream(text);
    } catch (err) {
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
      if (data.status && data.status !== "ok") setNotice(data.error || tx("regenFail"));
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
    if (next) switchTo(next.id);
  }
  async function runCompare() {
    const targets = selectedTargets();
    if (targets.length < 2) { setNotice(tx("needTwo")); return; }
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
    if (!body.content && !body.message_id) { setNotice(tx("needText")); return; }
    setNotice(tx("comparing"));
    try {
      const data = await api("/api/chat/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      input.value = "";
      const failed = (data.replies || []).filter((r) => r.status && r.status !== "ok");
      if (failed.length) setNotice(tx("somePartial") + failed.map((r) => r.provider).join(", "));
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
      b.textContent = tx("namePrefix") + clip(c.title, 40);
      b.addEventListener("click", () => openConv(c.id));
      box.append(b);
    });
    (data.messages || []).forEach((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = clip(m.snippet || m.content, 48);
      b.addEventListener("click", () => openConv(m.conversation_id));
      box.append(b);
    });
    if (!box.childElementCount) box.textContent = tx("noHits");
  }
  function bind() {
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
          input.value = last.content || "";
        }
      }
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && S.streaming && S.abort) S.abort.abort();
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
      S.editId = null;
      S.branchFrom = null;
      paintTitle();
      paintComposer();
      setNotice("");
      renderThread();
    });
    $("ephemeral").addEventListener("change", async () => {
      S.ephemeral = $("ephemeral").checked;
      if (!S.ephemeral && S.ephemeralLog.length) {
        const data = await api("/api/chat/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: S.ephemeralLog, title: clip(S.ephemeralLog[0].content, 40) }),
        });
        S.ephemeralLog = [];
        await openConv(data.conversation.id);
      }
    });
    $("model").addEventListener("change", () => {
      $("custom-model").hidden = $("model").value !== "custom";
    });
    $("compare-btn").addEventListener("click", () => {
      $("compare-box").hidden = !$("compare-box").hidden;
    });
    $("compare-go").addEventListener("click", runCompare);
    $("search").addEventListener("input", () => {
      clearTimeout(S._searchT);
      S._searchT = setTimeout(doSearch, 200);
    });
    $("add-folder").addEventListener("click", async () => {
      const name = window.prompt(tx("projectName"));
      if (!name) return;
      await api("/api/chat/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, kind: "project" }),
      });
      refreshLists();
    });
    $("persona").addEventListener("change", async () => {
      if (!S.conv) return;
      await api("/api/chat/conversations/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: S.conv.id, persona_id: $("persona").value || null }),
      });
    });
    $("export-btn").addEventListener("click", async () => {
      if (!S.conv) return;
      const data = await api("/api/chat/export?id=" + S.conv.id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "lca-chat-" + S.conv.uid + ".json";
      a.click();
    });
    $("import-btn").addEventListener("click", () => $("import-file").click());
    $("import-file").addEventListener("change", async () => {
      const file = $("import-file").files[0];
      if (!file) return;
      const doc = JSON.parse(await file.text());
      const data = await api("/api/chat/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc }),
      });
      await openConv(data.conversation.id);
    });
    $("folder").addEventListener("change", async () => {
      const value = $("folder").value;
      const data = await api("/api/chat/conversations?folder_id=" + encodeURIComponent(value));
      S.conversations = data.conversations || [];
      refreshLists.convOnly = true;
      const list = $("conv-list");
      list.replaceChildren();
      S.conversations.forEach((c) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = clip(c.title, 42) || tx("untitled");
        btn.addEventListener("click", () => openConv(c.id));
        list.append(btn);
      });
    });
    window.addEventListener("online", () => { S.online = true; $("offline").hidden = true; fillModels(); });
    window.addEventListener("offline", () => { S.online = false; $("offline").hidden = false; fillModels(); });
    document.addEventListener("lca-lang", () => {
      applyChrome();
      fillModels();
      renderThread();
      refreshLists().catch((err) => setNotice(err.message));
    });
  }
  async function boot() {
    bind();
    applyChrome();
    if (!S.online) $("offline").hidden = false;
    try {
      const cat = await api("/api/chat/providers");
      S.providers = cat.providers || [];
      fillModels();
      await refreshLists();
      const health = await api("/api/health");
      S.ollama = health.ollama === "up" ? "up" : "down";
      paintNet();
    } catch (err) {
      setNotice(err.message);
    }
    renderThread();
  }
  boot();
})();
