import type { ApiError, ErrorType } from "../api";
import { tr, type ThKey } from "../i18n/th";

const TITLE_KEYS: Record<ErrorType, ThKey> = {
  auth: "error.title.auth",
  quota: "error.title.quota",
  rate_limit: "error.title.rate_limit",
  timeout: "error.title.timeout",
  validation: "error.title.validation",
  upstream: "error.title.upstream",
  unknown: "error.title.unknown",
  network: "error.title.network",
  cancelled: "error.title.cancelled",
};

export const errorTitle = (err: ApiError): string => tr(TITLE_KEYS[err.type] ?? TITLE_KEYS.unknown);

/** The model key on the server is wrong or missing: the fix is on the Settings page, not a retry. */
export const isKeyProblem = (err: ApiError): boolean => err.type === "upstream" && err.message.includes("API key");

export function errorDetail(err: ApiError): string {
  const wait = err.retryAfterS ? ` ${tr("error.detail.wait", { s: err.retryAfterS })}` : "";
  const ref = err.requestId ? ` ${tr("error.detail.ref", { id: err.requestId })}` : "";
  return `${err.message}${wait}${ref}`;
}
