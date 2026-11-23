import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type Health, type KeyStatus, type User } from "../api";
import { getLocalHealth, type LocalHealth } from "../chatApi";
import { Badge, Button, Card, ErrorState, Skeleton, type Status } from "../components/ui";
import { tr, type ThKey } from "../i18n/th";
import {
  decideLocalOutcome, missingModelId, OUTCOME_MESSAGE_KEY, ramNumbers, readModelPreference,
  writeModelPreference, type LocalOutcome, type ModelChoice,
} from "../onboardingLocal";
import { navigate } from "../router";
import { KeySetup } from "./KeySetup";

type LocalState = { status: "loading" } | { status: "error" } | { status: "ok"; health: LocalHealth };

const BADGE: Record<LocalOutcome, { status: Status; label: ThKey }> = {
  ready: { status: "ok", label: "chat.status.ready" },
  disabled: { status: "neutral", label: "onboarding.outcome.badge.disabled" },
  not_installed: { status: "warn", label: "chat.status.not_installed" },
  not_enough_memory: { status: "warn", label: "chat.status.not_enough_memory" },
  not_found: { status: "bad", label: "onboarding.outcome.badge.not_found" },
} as const;

/** Storage can be blocked (private window, disabled site data). Reading it must not break the page. */
function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function LocalOutcomeView({ health }: { health: LocalHealth }) {
  const outcome = decideLocalOutcome(health);
  const ram = ramNumbers(health);
  const badge = BADGE[outcome];
  const message = tr(OUTCOME_MESSAGE_KEY[outcome], {
    id: missingModelId(health) ?? "",
    required: ram.required ?? "-",
  });
  return (
    <div className="flex flex-col gap-2">
      <Badge status={badge.status}>{tr(badge.label)}</Badge>
      <p className="text-sm text-fg">{message}</p>
      {outcome === "ready" && ram.available === null && <p className="text-sm text-muted">{tr("onboarding.ram.unknown")}</p>}
      {ram.available !== null && ram.required !== null && (
        <p className="text-sm text-muted">
          {tr("onboarding.ram.line", { required: ram.required, available: ram.available })}
        </p>
      )}
    </div>
  );
}

export function Onboarding({ user }: { user: User }) {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [local, setLocal] = useState<LocalState>({ status: "loading" });
  const [choice, setChoice] = useState<ModelChoice | null>(() => readModelPreference(browserStorage()));
  const [saveFailed, setSaveFailed] = useState(false);

  const load = useCallback(() => {
    setError(null);
    Promise.all([api<KeyStatus>("/api/settings/key"), api<Health>("/api/health")])
      .then(([k, h]) => { setStatus(k); setHealth(h); })
      .catch((err: unknown) => setError(err instanceof ApiError ? err : new ApiError("unknown", tr("onboarding.loadFail.fallback"), true)));
  }, []);

  const loadLocal = useCallback(() => {
    setLocal({ status: "loading" });
    getLocalHealth()
      .then((h) => setLocal({ status: "ok", health: h }))
      .catch(() => setLocal({ status: "error" }));
  }, []);

  useEffect(() => {
    load();
    loadLocal();
  }, [load, loadLocal]);

  const pick = (next: ModelChoice) => {
    setChoice(next);
    setSaveFailed(!writeModelPreference(browserStorage(), next));
  };

  return (
    <div className="mx-auto flex w-full max-w-xl min-w-0 flex-col gap-4">
      <h1 className="text-2xl font-semibold">{tr("onboarding.title")}</h1>
      <p className="text-sm text-muted">{tr("onboarding.intro")}</p>
      {error && <ErrorState title={tr("onboarding.loadFail.title")} detail={error.message} action={{ label: tr("onboarding.retry"), onClick: load }} />}
      {!status && !error && <Card><Skeleton className="h-6 w-1/2" /></Card>}
      {status && (
        <Card title={tr("onboarding.keyCard.title", { model: health?.model ?? tr("onboarding.keyCard.fallbackModel") })}>
          <KeySetup status={status} isAdmin={user.role === "admin"} onChange={setStatus} />
        </Card>
      )}
      <Card title={tr("onboarding.local.heading")}>
        {local.status === "loading" && <Skeleton className="h-6 w-1/2" />}
        {local.status === "error" && (
          <ErrorState
            title={tr("onboarding.local.healthFail.title")}
            detail={tr("onboarding.local.healthFail.detail")}
            action={{ label: tr("onboarding.retry"), onClick: loadLocal }}
          />
        )}
        {local.status === "ok" && <LocalOutcomeView health={local.health} />}
        <fieldset className="mt-4 flex min-w-0 flex-wrap gap-2 border-0 p-0">
          <legend className="sr-only">{tr("onboarding.choice.heading")}</legend>
          <Button variant={choice === "local" ? "primary" : "secondary"} aria-pressed={choice === "local"} onClick={() => pick("local")}>
            {tr("onboarding.choice.local")}
          </Button>
          <Button variant={choice === "server" ? "primary" : "secondary"} aria-pressed={choice === "server"} onClick={() => pick("server")}>
            {tr("onboarding.choice.server")}
          </Button>
        </fieldset>
        {choice && <p className="mt-2 text-sm text-muted">{tr(choice === "local" ? "onboarding.choice.savedLocal" : "onboarding.choice.savedServer")}</p>}
        {saveFailed && <p className="mt-2 text-sm text-muted">{tr("onboarding.choice.notSaved")}</p>}
      </Card>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={!status?.configured} onClick={() => navigate("workbench")}>{tr("onboarding.goWork")}</Button>
        <Button variant="ghost" onClick={() => navigate("workbench")}>{tr("onboarding.skip")}</Button>
      </div>
    </div>
  );
}
