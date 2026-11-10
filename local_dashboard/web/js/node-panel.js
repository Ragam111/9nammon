import { CLUSTER_PATH, POLL_MS } from "./config.js";
import { clear, el } from "./dom.js";
import {
  emptyCluster,
  latencyText,
  nodeStateLabel,
  normalizeCluster,
  roleLabel,
  rowsForTransport,
} from "./nodes.js";
import { startVisibilityPoll } from "./poll.js";
import { planLogTransport } from "./log-buffer.js";

export function mountNodePanel(root, deps) {
  const fetchImpl = (deps && deps.fetchImpl) || fetch;
  const list = el("div", { id: "node-list" });
  const status = el("p", { id: "node-status", role: "status" }, "กำลังตรวจ…");
  let rows = emptyCluster();
  let disposed = false;

  function paint() {
    clear(list);
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i];
      const card = el("article", { class: "node", "data-port": String(row.port) });
      card.append(
        el("h3", null, "พอร์ต " + row.port + " · " + roleLabel(row.role)),
        el("span", { class: "chip " + (row.state === "up" ? "ok" : row.state === "checking" ? "warn" : "bad") }, nodeStateLabel(row.state)),
        el("span", { class: "latency" }, latencyText(row)),
      );
      list.append(card);
    }
  }

  root.append(
    el("h2", null, "สถานะโหนด"),
    el("p", { class: "muted" }, "8420 คือโหนดงาน 8421 คือแดชบอร์ดนี้ ถาม /api/cluster/status ทุก 8 วินาที และหยุดเมื่อแท็บถูกซ่อน"),
    status,
    list,
  );
  paint();

  async function refresh() {
    try {
      const res = await fetchImpl(CLUSTER_PATH, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(2000),
      });
      const plan = planLogTransport(res.status);
      if (plan === "ok") {
        rows = normalizeCluster(await res.json());
        status.textContent = "ตรวจแล้ว";
      } else if (plan === "missing") {
        rows = rowsForTransport("missing");
        status.textContent = "not implemented";
      } else {
        rows = rowsForTransport("offline");
        status.textContent = "offline";
      }
    } catch (err) {
      rows = rowsForTransport("offline");
      if (!disposed) status.textContent = "offline";
    }
    if (!disposed) paint();
  }

  const stop = startVisibilityPoll({
    intervalMs: POLL_MS,
    isHidden: function () { return document.hidden; },
    run: refresh,
  });

  return function dispose() {
    disposed = true;
    stop();
  };
}
