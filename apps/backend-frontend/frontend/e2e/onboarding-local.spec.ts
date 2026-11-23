// Unit tests for the pure onboarding rules in src/onboardingLocal.ts. No browser page is used, so these run
// in the Playwright runner without any extra dependency (same approach as model-groups.spec.ts).
import { expect, test } from "@playwright/test";
import type { LocalHealth } from "../src/chatApi";
import {
  decideLocalOutcome, OUTCOME_MESSAGE_KEY, readModelPreference, writeModelPreference, PREFERENCE_KEY,
} from "../src/onboardingLocal";
import { tr } from "../src/i18n/th";

const QWEN = { id: "qwen2.5-coder:1.5b", installed: false, required_ram_gb: 2 };
const QWEN_INSTALLED = { ...QWEN, installed: true };
const BIG_INSTALLED = { id: "big:7b", installed: true, required_ram_gb: 8 };

test("unreachable Ollama is not_found", () => {
  const health: LocalHealth = { reachable: false, models: [], available_ram_gb: 16, models_detail: [QWEN_INSTALLED] };
  expect(decideLocalOutcome(health)).toBe("not_found");
});

test("a missing or null payload is not_found", () => {
  expect(decideLocalOutcome(null)).toBe("not_found");
  expect(decideLocalOutcome(undefined)).toBe("not_found");
});

test("reachable with no installed catalog model is not_installed", () => {
  const health: LocalHealth = { reachable: true, models: [], available_ram_gb: 16, models_detail: [QWEN] };
  expect(decideLocalOutcome(health)).toBe("not_installed");
});

test("a payload without models_detail (older server) is not_installed", () => {
  expect(decideLocalOutcome({ reachable: true, models: ["llama3"] })).toBe("not_installed");
});

test("installed model with too little RAM is not_enough_memory", () => {
  const health: LocalHealth = { reachable: true, models: ["qwen2.5-coder:1.5b"], available_ram_gb: 1.0, models_detail: [{ ...QWEN_INSTALLED, required_ram_gb: 2.0 }] };
  expect(decideLocalOutcome(health)).toBe("not_enough_memory");
});

test("installed model with enough RAM is ready", () => {
  const health: LocalHealth = { reachable: true, models: ["qwen2.5-coder:1.5b"], available_ram_gb: 16, models_detail: [QWEN_INSTALLED] };
  expect(decideLocalOutcome(health)).toBe("ready");
});

test("a null available_ram_gb does not block and gives ready", () => {
  const health: LocalHealth = { reachable: true, models: ["qwen2.5-coder:1.5b"], available_ram_gb: null, models_detail: [QWEN_INSTALLED] };
  expect(decideLocalOutcome(health)).toBe("ready");
});

test("an absent available_ram_gb key does not block and gives ready", () => {
  const health: LocalHealth = { reachable: true, models: [], models_detail: [QWEN_INSTALLED] };
  expect(decideLocalOutcome(health)).toBe("ready");
});

test("two installed models where one fits is ready", () => {
  const health: LocalHealth = {
    reachable: true, models: ["big:7b", "qwen2.5-coder:1.5b"], available_ram_gb: 4,
    models_detail: [BIG_INSTALLED, QWEN_INSTALLED],
  };
  expect(decideLocalOutcome(health)).toBe("ready");
});

test("an installed model that fits is not undone by an uninstalled catalog entry", () => {
  const health: LocalHealth = {
    reachable: true, models: ["qwen2.5-coder:1.5b"], available_ram_gb: 4,
    models_detail: [BIG_INSTALLED, QWEN_INSTALLED],
  };
  expect(decideLocalOutcome(health)).toBe("ready");
});

test("every outcome has a Thai dictionary key that resolves to non-empty text", () => {
  for (const key of Object.values(OUTCOME_MESSAGE_KEY)) {
    const text = tr(key, { id: "x", need: 2, have: 1, available: 1, required: 2 });
    expect(text.length).toBeGreaterThan(0);
    expect(/[฀-๿]/.test(text)).toBe(true);
  }
});

test("reading a preference returns null when storage is missing or throws", () => {
  expect(readModelPreference(null)).toBeNull();
  const throwing = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
  } as unknown as Storage;
  expect(readModelPreference(throwing)).toBeNull();
});

test("an invalid stored preference is ignored", () => {
  const store = new Map<string, string>([[PREFERENCE_KEY, "cloud-please"]]);
  const fake = { getItem: (k: string) => store.get(k) ?? null } as unknown as Storage;
  expect(readModelPreference(fake)).toBeNull();
});

test("a valid stored preference is read back", () => {
  const store = new Map<string, string>([[PREFERENCE_KEY, "local"]]);
  const fake = { getItem: (k: string) => store.get(k) ?? null } as unknown as Storage;
  expect(readModelPreference(fake)).toBe("local");
});

test("writing a preference never throws when storage throws", () => {
  const throwing = {
    setItem: () => { throw new Error("quota"); },
  } as unknown as Storage;
  expect(() => writeModelPreference(throwing, "server")).not.toThrow();
  expect(() => writeModelPreference(null, "server")).not.toThrow();
});

test("writing a preference stores the value under the one key", () => {
  const store = new Map<string, string>();
  const fake = { setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  writeModelPreference(fake, "server");
  expect(store.get(PREFERENCE_KEY)).toBe("server");
});
