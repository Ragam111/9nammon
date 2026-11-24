// Pure model-list rules for the chat picker: grouping, selectability, badge mapping and reason text.
// No DOM and no React here, so the rules can be tested directly (see e2e/model-groups.spec.ts).
import type { ChatModel, ModelProviderKind, ModelStatus } from "./chatApi";
import { tr, type ThKey } from "./i18n/th";

export type ModelGroups = { local: ChatModel[]; server: ChatModel[] };
/** Same values as the Badge status in components/ui.tsx; kept local so this file has no JSX dependency. */
export type BadgeStatus = "ok" | "warn" | "bad" | "neutral";

const STATUS_LABEL: Record<ModelStatus, ThKey> = {
  ready: "chat.status.ready",
  not_installed: "chat.status.not_installed",
  not_enough_memory: "chat.status.not_enough_memory",
  unreachable: "chat.status.unreachable",
  not_configured: "chat.status.not_configured",
};

const BADGE: Record<ModelStatus, BadgeStatus> = {
  ready: "ok",
  not_installed: "warn",
  not_enough_memory: "warn",
  unreachable: "bad",
  not_configured: "neutral",
};

/** Cloud rows have no provider_kind from older responses, so they default to cloud. */
export function kindOf(m: ChatModel): ModelProviderKind {
  return m.provider_kind ?? "cloud";
}

/** Uses the server status when present; otherwise a cloud row is ready when it is configured. */
export function statusOf(m: ChatModel): ModelStatus {
  return m.status ?? (m.configured ? "ready" : "not_configured");
}

/** Only ready rows can be picked or sent to. */
export function isSelectable(m: ChatModel): boolean {
  return statusOf(m) === "ready";
}

export function statusLabel(m: ChatModel): string {
  return tr(STATUS_LABEL[statusOf(m)]);
}

export function statusBadge(m: ChatModel): BadgeStatus {
  return BADGE[statusOf(m)];
}

/** Option text: the model label followed by its status, e.g. "qwen2.5-coder:1.5b (ยังไม่ได้ติดตั้ง)". */
export function optionLabel(m: ChatModel): string {
  return `${m.label} (${statusLabel(m)})`;
}

/** Reason shown under the picker for a non-ready row; null when the row is ready. */
export function reasonFor(m: ChatModel): string | null {
  switch (statusOf(m)) {
    case "ready":
      return null;
    case "not_installed":
      return tr("chat.status.reason.notInstalled", { label: m.id });
    case "not_enough_memory":
      return m.required_ram_gb != null && m.available_ram_gb != null
        ? tr("chat.status.reason.memory", { need: m.required_ram_gb, have: m.available_ram_gb })
        : tr("chat.status.reason.memoryUnknown");
    case "unreachable":
      return tr("chat.status.reason.unreachable");
    case "not_configured":
      return kindOf(m) === "local"
        ? tr("chat.status.reason.localNotConfigured")
        : tr("chat.status.reason.notConfigured");
  }
}

/** Splits rows by provider_kind, keeping the server's order inside each group. */
export function groupModels(models: ChatModel[]): ModelGroups {
  const groups: ModelGroups = { local: [], server: [] };
  for (const m of models) {
    if (kindOf(m) === "local") groups.local.push(m);
    else groups.server.push(m);
  }
  return groups;
}

/** The first ready row, local or cloud, in list order; falls back to the first row. */
export function pickDefaultModel(models: ChatModel[]): string {
  return (models.find(isSelectable) ?? models[0])?.id ?? "";
}
