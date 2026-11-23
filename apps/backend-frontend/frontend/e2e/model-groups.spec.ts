// Unit tests for the pure model-list rules in src/modelGroups.ts. No browser page is used, so these run
// in the Playwright runner without any dependency beyond the one already installed.
import { expect, test } from "@playwright/test";
import type { ChatModel } from "../src/chatApi";
import {
  groupModels, isSelectable, optionLabel, pickDefaultModel, reasonFor, statusBadge, statusOf,
} from "../src/modelGroups";

const cloudOk: ChatModel = { id: "claude-a", provider: "claude", label: "Claude A", configured: true, provider_kind: "cloud", status: "ready" };
const cloudNoKey: ChatModel = { id: "gpt-a", provider: "gpt", label: "GPT A", configured: false, provider_kind: "cloud", status: "not_configured" };
const localMissing: ChatModel = {
  id: "qwen2.5-coder:1.5b", provider: "ollama", label: "Qwen 1.5B", configured: false, provider_kind: "local",
  status: "not_installed", required_ram_gb: 2, available_ram_gb: 6,
};
const localReady: ChatModel = {
  id: "llama3.2:1b", provider: "ollama", label: "Llama 1B", configured: true, provider_kind: "local", status: "ready",
  required_ram_gb: 1, available_ram_gb: 6,
};
const localLowRam: ChatModel = {
  id: "big:7b", provider: "ollama", label: "Big 7B", configured: false, provider_kind: "local",
  status: "not_enough_memory", required_ram_gb: 8, available_ram_gb: 3,
};
const localLowRamUnknown: ChatModel = { ...localLowRam, id: "big2:7b", required_ram_gb: null, available_ram_gb: null };
const localDown: ChatModel = { ...localLowRam, id: "down:1b", status: "unreachable", configured: false };
const legacyCloudOk: ChatModel = { id: "legacy", provider: "claude", label: "Legacy", configured: true };
const legacyCloudNoKey: ChatModel = { id: "legacy2", provider: "gemini", label: "Legacy 2", configured: false };

test("groupModels splits rows by provider_kind and keeps the order inside each group", () => {
  const groups = groupModels([cloudOk, localMissing, cloudNoKey, localReady]);
  expect(groups.local.map((m) => m.id)).toEqual(["qwen2.5-coder:1.5b", "llama3.2:1b"]);
  expect(groups.server.map((m) => m.id)).toEqual(["claude-a", "gpt-a"]);
});

test("groupModels treats rows without provider_kind as server rows", () => {
  const groups = groupModels([legacyCloudOk, legacyCloudNoKey]);
  expect(groups.local).toEqual([]);
  expect(groups.server.map((m) => m.id)).toEqual(["legacy", "legacy2"]);
});

test("statusBadge maps each status to the Badge status", () => {
  expect(statusBadge(cloudOk)).toBe("ok");
  expect(statusBadge(localMissing)).toBe("warn");
  expect(statusBadge(localLowRam)).toBe("warn");
  expect(statusBadge(localDown)).toBe("bad");
  expect(statusBadge(cloudNoKey)).toBe("neutral");
});

test("only ready rows are selectable", () => {
  expect(isSelectable(cloudOk)).toBe(true);
  expect(isSelectable(localReady)).toBe(true);
  expect(isSelectable(localMissing)).toBe(false);
  expect(isSelectable(cloudNoKey)).toBe(false);
});

test("reasonFor gives null for ready rows and a reason for every other status", () => {
  expect(reasonFor(cloudOk)).toBeNull();
  expect(reasonFor(localMissing)).toBe("ติดตั้งโมเดลด้วยคำสั่ง ollama pull qwen2.5-coder:1.5b");
  expect(reasonFor(localLowRam)).toBe("ต้องการ RAM อย่างน้อย 8 GB, เครื่องมีว่าง 3 GB");
  expect(reasonFor(localLowRamUnknown)).toBe("RAM ของเครื่องไม่พอสำหรับโมเดลนี้");
  expect(reasonFor(localDown)).toContain("ติดต่อ Ollama ไม่ได้");
  expect(reasonFor(cloudNoKey)).toBe("ยังไม่ได้ตั้งค่า API key บน server");
});

test("optionLabel appends the status text to the model label", () => {
  expect(optionLabel(localMissing)).toBe("Qwen 1.5B (ยังไม่ได้ติดตั้ง)");
  expect(optionLabel(cloudOk)).toBe("Claude A (พร้อมใช้งาน)");
});

test("statusOf derives status from configured when the server sends none", () => {
  expect(statusOf(legacyCloudOk)).toBe("ready");
  expect(statusOf(legacyCloudNoKey)).toBe("not_configured");
});

test("pickDefaultModel prefers the first ready row, local or cloud, in list order", () => {
  expect(pickDefaultModel([cloudNoKey, localMissing, localReady, cloudOk])).toBe("llama3.2:1b");
  expect(pickDefaultModel([cloudNoKey, cloudOk, localReady])).toBe("claude-a");
});

test("pickDefaultModel falls back to the first row when nothing is ready", () => {
  expect(pickDefaultModel([localMissing, cloudNoKey])).toBe("qwen2.5-coder:1.5b");
  expect(pickDefaultModel([])).toBe("");
});
