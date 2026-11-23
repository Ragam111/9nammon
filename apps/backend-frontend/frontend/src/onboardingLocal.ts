// Pure onboarding rules for the local (Ollama) model choice. No DOM and no React here, so the rules can be
// tested directly (see e2e/onboarding-local.spec.ts). RAM numbers come from the health payload, never hard-coded.
import type { LocalHealth } from "./chatApi";
import type { ThKey } from "./i18n/th";

export type LocalOutcome = "ready" | "not_installed" | "not_enough_memory" | "not_found";
export type ModelChoice = "local" | "server";

/** One localStorage key for the preference. It is a per-browser convenience, never an access check. */
export const PREFERENCE_KEY = "lca.modelPreference";

export const OUTCOME_MESSAGE_KEY: Record<LocalOutcome, ThKey> = {
  ready: "onboarding.outcome.ready",
  not_installed: "onboarding.outcome.not_installed",
  not_enough_memory: "onboarding.outcome.not_enough_memory",
  not_found: "onboarding.outcome.not_found",
};

/**
 * Order of rules: missing or unreachable -> not_found; no installed catalog entry -> not_installed;
 * an installed entry fits the RAM -> ready; installed but none fits -> not_enough_memory.
 * A null available_ram_gb does not block (same as the backend status rule).
 */
export function decideLocalOutcome(health: LocalHealth | null | undefined): LocalOutcome {
  if (!health?.reachable) return "not_found";
  const installed = (health.models_detail ?? []).filter((m) => m.installed);
  if (installed.length === 0) return "not_installed";
  const available = health.available_ram_gb ?? null;
  if (available === null) return "ready";
  return installed.some((m) => m.required_ram_gb <= available) ? "ready" : "not_enough_memory";
}

export type RamNumbers = { available: number | null; required: number | null };

/** Available RAM from the payload, and the smallest requirement among installed entries (the best fit). */
export function ramNumbers(health: LocalHealth | null | undefined): RamNumbers {
  const required = (health?.models_detail ?? []).filter((m) => m.installed).map((m) => m.required_ram_gb);
  return {
    available: health?.available_ram_gb ?? null,
    required: required.length > 0 ? Math.min(...required) : null,
  };
}

/** The first catalog entry that is not installed yet, used in the `ollama pull` hint. */
export function missingModelId(health: LocalHealth | null | undefined): string | null {
  return health?.models_detail?.find((m) => !m.installed)?.id ?? null;
}

/** Reads the saved choice. Any error, missing storage or unknown value gives null. */
export function readModelPreference(storage: Pick<Storage, "getItem"> | null): ModelChoice | null {
  try {
    const value = storage?.getItem(PREFERENCE_KEY);
    return value === "local" || value === "server" ? value : null;
  } catch {
    return null;
  }
}

/** Saves the choice. Returns false when storage is missing or throws; the page keeps working either way. */
export function writeModelPreference(storage: Pick<Storage, "setItem"> | null, choice: ModelChoice): boolean {
  try {
    storage?.setItem(PREFERENCE_KEY, choice);
    return storage !== null;
  } catch {
    return false;
  }
}
