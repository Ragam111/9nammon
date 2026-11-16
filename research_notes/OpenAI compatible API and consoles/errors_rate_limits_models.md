# OpenAI API errors, auth failures, rate limits, and /v1/models: a reference for OpenAI-compatible servers

Scope: how OpenAI reports errors (body shape, status codes, type/code values), how the official SDKs (openai-python, openai-node) retry, which rate-limit headers OpenAI returns, the /v1/models response format, and mid-stream error shapes. Anthropic's error model is included for comparison. Researched 2026-11-13. Note: OpenAI docs moved from platform.openai.com/docs/... to developers.openai.com/api/docs/... (301 redirects observed), and Anthropic docs moved from docs.anthropic.com to platform.claude.com.

## Q1. Exact error body shape and common type/code values per status (400, 401, 403, 404, 429, 500, 503)

### Takeaway
OpenAI errors are JSON `{"error": {"message", "type", "param", "code"}}`. `type` and `message` are always strings; `param` and `code` can be null. The SDKs read the nested `error` object (falling back to the whole body) and pick the exception class from the HTTP status alone, never from `type` or `code`. So a compatible server mostly needs the right status code plus a nested `error` object. 429 now covers several distinct cases (rate limit, slow_down, credits exhausted, spend or usage limits), and SDK retry logic cannot tell them apart.

### Cited Findings
**Body parsing in the SDK (primary source):**
- openai-python `_make_status_error` starts with `data = body.get("error", body) if is_mapping(body) else body`, so it reads the nested `error` object and falls back to the top-level body. — [openai-python _client.py](https://github.com/openai/openai-python/blob/main/src/openai/_client.py)
- `APIError` reads `code = body.get("code")`, `param` (typed `Optional[str]`) and `type` (typed `str`) from that dict. If the body is not a dict, all three become `None`. The message is passed in separately; it is not taken from the body inside `APIError`. — [openai-python _exceptions.py](https://github.com/openai/openai-python/blob/main/src/openai/_exceptions.py)
- Status-to-exception mapping in openai-python: 400 `BadRequestError`, 401 `AuthenticationError`, 403 `PermissionDeniedError`, 404 `NotFoundError`, 409 `ConflictError`, 422 `UnprocessableEntityError`, 429 `RateLimitError`, `>= 500` `InternalServerError`. Any other status becomes the base `APIStatusError`. — [openai-python _client.py](https://github.com/openai/openai-python/blob/main/src/openai/_client.py); class definitions in [_exceptions.py](https://github.com/openai/openai-python/blob/main/src/openai/_exceptions.py). There is also an `OAuthError(AuthenticationError)` subclass.
- openai-python sends the optional `OpenAI-Organization` and `OpenAI-Project` default headers, and omits each one when it is unset. — [openai-python _client.py](https://github.com/openai/openai-python/blob/main/src/openai/_client.py)

**Documented error messages and codes (official error-codes guide, 2026):**
- 400: "Invalid `service_tier` argument: The requested service tier is not allowed for this project." — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)
- 401 messages: "Invalid Authentication"; "Incorrect API key provided"; "You must be a member of an organization to use the API"; "IP not authorized". — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)
- 403: "Country, region, or territory not supported". — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)
- 429 variants:
  - "Rate limit reached for requests"
  - credit balance exhausted, code `credit_balance_exhausted` ("Retrying won't restore access"; the guide notes `error.type` can be `insufficient_quota`)
  - "Slow down", type `rate_limit_error`, code `slow_down` (the request rate rose too quickly)
  - `organization_spend_limit_exceeded`
  - `project_spend_limit_exceeded`
  - `organization_usage_limit_exceeded`
  — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)
- 500: "The server had an error while processing your request". — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)
- 503: "Model temporarily overloaded", type `service_unavailable_error`, code `server_is_overloaded`. Guidance: "Follow `Retry-After` if present". — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes); also mentioned in [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- The Python error-types table in the guide maps `RateLimitError` to 429 and `InternalServerError` to 503 (the 503 example is illustrative; the SDK maps every status >= 500 to it). — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)

**Observed wire bodies (community reports; lower confidence than the docs):**
- 404 model not found: `{'error': {'message': 'The model gpt-4o-audio does not exist or you do not have access to it.', 'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}}` (shown as a Python repr, where `None` is JSON `null`). — [OpenAI Community thread](https://community.openai.com/t/the-model-gpt-4o-audio-does-not-exist-or-you-do-not-have-access-to-it/1388356)
- 401 wrong key: message "Incorrect API key provided: <masked key>..." pointing to the API keys page, with `type: 'invalid_request_error'`, `param: null`, `code: 'invalid_api_key'`. This comes from a search-result summary of the thread, not a full fetch. — [OpenAI Community thread](https://community.openai.com/t/getting-incorrect-api-key-error-in-node-js/579115)
- 429 TPM limit: message like "Rate limit reached for gpt-4o-mini in organization org-... on tokens per min (TPM): Limit 100000, Used 99918, Requested 2094. Please try again in 5.72s." with `'type': 'tokens'`, `'param': None`, `'code': 'rate_limit_exceeded'`. The `type` is `tokens` or `requests` here, not `rate_limit_error`. From search summaries of community threads. — [OpenAI Community thread](https://community.openai.com/t/rate-limit-exceeded-error-when-we-only-do-one-transaction-at-a-time/974781)
- 429 "Request too large for organization org-... on tokens per min (TPM): Limit 250000, Requested 258762". It fails every time until the request changes, so retrying does not help. From a search summary. — [OpenAI Community thread](https://community.openai.com/t/rate-limit-exceeded-error-when-we-only-do-one-transaction-at-a-time/974781)
- 429 quota: message "You exceeded your current quota, please check your plan and billing details..." with `type` and `code` both `insufficient_quota`. From a search summary. — [OpenAI Community thread](https://community.openai.com/t/429-error-insufficient-quota/492350)

**Anthropic, for comparison (official docs):**
- Body shape: `{"type": "error", "error": {"type": "not_found_error", "message": "..."}, "request_id": "req_..."}`. There is no `param` or `code`; every response carries a `request-id` header. — [Claude API errors](https://platform.claude.com/docs/en/api/errors)
- Status-to-type mapping:

  | Status | Type |
  |---|---|
  | 400 | `invalid_request_error` (also returned when a user-set spend limit is reached) |
  | 401 | `authentication_error` |
  | 402 | `billing_error` |
  | 403 | `permission_error` |
  | 404 | `not_found_error` |
  | 409 | `conflict_error` |
  | 413 | `request_too_large` |
  | 429 | `rate_limit_error` (also the tier spend cap, which has no `retry-after` and keeps failing) |
  | 500 | `api_error` |
  | 504 | `timeout_error` |
  | 529 | `overloaded_error` |

  — [Claude API errors](https://platform.claude.com/docs/en/api/errors)
- So Anthropic uses 529 for overload where OpenAI uses 503 (`server_is_overloaded`). — [Claude API errors](https://platform.claude.com/docs/en/api/errors); [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)

### Inferences
- Recommended bodies for a compatible server, built from the shapes above. Always include all four keys, with `null` where there is nothing to report:

  | Status | `type` | `code` | Notes |
  |---|---|---|---|
  | 400 | `invalid_request_error` | null or a specific code | `param` names the offending field, such as `"messages"` |
  | 401 | `invalid_request_error` | `invalid_api_key` | message `"Incorrect API key provided: sk-...abcd."` |
  | 403 | a permission-style type | null or a specific code | exact OpenAI type and code not verified (see Gaps) |
  | 404 | `invalid_request_error` | `model_not_found` | message ``"The model `X` does not exist or you do not have access to it."`` |
  | 429 (rate) | `requests` or `tokens` | `rate_limit_exceeded` | add `Retry-After` and the `x-ratelimit-*` headers |
  | 429 (quota) | `insufficient_quota` | `insufficient_quota` | |
  | 500 | likely `server_error` | | message "The server had an error while processing your request" |
  | 503 | `service_unavailable_error` | `server_is_overloaded` | |

- The SDKs choose exception classes by status only. Clients that branch on `e.code` or `e.type` (for example `insufficient_quota` versus `rate_limit_exceeded`) need the values above to be exact.
- Wrapping errors in `error` is the safest choice: a flat body like `{"message": ...}` still parses because of the `body.get("error", body)` fallback, but `e.type` and `e.code` would then come from the top level.

### Gaps
- The exact 403 `type` and `code` (for example, whether the country error uses `unsupported_country_region_territory`) and the exact 500 `type` (`server_error`?) were not confirmed in a primary source.
- OpenAI's OpenAPI `ErrorResponse` schema was not fetched. The required and nullable status of each field above comes from the SDK types (`param: Optional[str]`, `type: str`).
- The verbatim 401 and 429 bodies come from community or search summaries. The current official guide gives messages and codes but no full JSON examples.
- Whether GET `/v1/models/{model}` for an unknown id returns `param: "model"` or `null` was not verified.
- OpenAI's request-id response header (`x-request-id`) and other response headers were not verified in this pass.

## Q2. Which status codes the SDKs retry, defaults, and Retry-After / retry-after-ms handling

### Takeaway
Both SDKs retry 408, 409, 429 and all statuses >= 500. They retry 2 times by default, with exponential backoff from 0.5s, capped at 8s, minus up to 25% random jitter. A server header `x-should-retry: true|false` overrides the status rule. Both read `retry-after-ms` first and then `retry-after` (seconds or HTTP-date). They handle a long Retry-After differently. openai-python follows it up to 120s and does not retry at all above that. openai-node follows it only up to 60s and falls back to its own backoff above that.

### Cited Findings
**openai-python (main branch):**
- `_should_retry` checks in this order:
  1. If `retry_after > MAX_RETRY_AFTER_DELAY`, return `False` (no retry).
  2. `x-should-retry` header: `"true"` returns `True`, `"false"` returns `False`.
  3. Status `408`, `409`, `429`, or `>= 500` returns `True`.
  4. Anything else is not retried.

  — [openai-python _base_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py)
- `_parse_retry_after_header` loops `for header, divisor in (("retry-after-ms", 1000), ("retry-after", 1))`, then falls back to parsing an HTTP-date with `email.utils.parsedate_tz` (delay = date minus now). A non-numeric overflow to infinity is treated as excessive (`MAX_RETRY_AFTER_DELAY + 1`). — [openai-python _base_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py)
- `_calculate_retry_timeout`:
  - If `0 < retry_after <= MAX_RETRY_AFTER_DELAY`, it returns `retry_after` exactly. The code comment reads "Honor server-directed delays up to two minutes."
  - Otherwise `sleep = min(INITIAL_RETRY_DELAY * 2**nb_retries, MAX_RETRY_DELAY)` and `jitter = 1 - 0.25 * random()`.

  — [openai-python _base_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py)
- Constants: `DEFAULT_MAX_RETRIES = 2`; `INITIAL_RETRY_DELAY = 0.5`; `MAX_RETRY_DELAY = 8.0`; `MAX_RETRY_AFTER_DELAY = 120` (seconds); `DEFAULT_TIMEOUT` = 600s overall with a 5s connect timeout. — [openai-python _constants.py](https://github.com/openai/openai-python/blob/main/src/openai/_constants.py)

**openai-node (master branch):**
- `shouldRetry`: `x-should-retry` `'true'` or `'false'` is honored first, then status `408`, `409`, `429`, or `>= 500` returns `true`. — [openai-node client.ts](https://github.com/openai/openai-node/blob/master/src/client.ts)
- Retry-after handling:
  - It reads `retry-after-ms` first (`parseFloat`), then `retry-after`: a number in seconds (times 1000) or `Date.parse(...) - Date.now()`.
  - It uses the server's delay only if that delay is finite, non-negative and at most `60 * 1000` ms. Otherwise it uses its own backoff.

  — [openai-node client.ts](https://github.com/openai/openai-node/blob/master/src/client.ts)
- Backoff: `initialRetryDelay = 0.5`, `maxRetryDelay = 8.0`, `sleepSeconds = Math.min(initialRetryDelay * Math.pow(2, numRetries), maxRetryDelay)`, `jitter = 1 - Math.random() * 0.25`. — [openai-node client.ts](https://github.com/openai/openai-node/blob/master/src/client.ts)
- Defaults: maxRetries `2`; `DEFAULT_TIMEOUT = 600000` (10 minutes). — [openai-node client.ts](https://github.com/openai/openai-node/blob/master/src/client.ts)
- The client sends `X-Stainless-Retry-Count` (`maxRetries - retriesRemaining`, so 0 on the first attempt). — [openai-node client.ts](https://github.com/openai/openai-node/blob/master/src/client.ts)

**OpenAI guidance:**
- Wait at least `Retry-After` seconds plus a little jitter. Use exponential backoff with jitter when the header is missing. Cap attempts and total time. Don't retry quota or billing errors. Disable SDK retries if you add your own retry loop. — [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- Credit-exhausted 429: "Retrying won't restore access." — [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)

**Anthropic, for comparison:**
- The Anthropic SDK retries connection errors, rate limits and 5xx "twice by default, honoring the `retry-after` header when present", and accepts `max_retries` / `maxRetries` to change or disable this. — [Claude API errors](https://platform.claude.com/docs/en/api/errors)

### Inferences
- Both SDKs retry every 429, including `insufficient_quota` and spend-limit 429s that will never succeed. A compatible server should send `x-should-retry: false` on non-retryable 429s (quota, billing, request too large). That avoids up to 2 wasted retries per call in both SDKs. It should send `x-should-retry: true` (or rely on the status) for transient 429 and 503 responses.
- Send `Retry-After` as integer seconds, optionally with `retry-after-ms` for sub-second precision. Keep it at or below 60s so both SDKs follow it exactly. Values between 60s and 120s are followed by Python, but Node ignores them and uses at most 8s of backoff. Values above 120s make Python give up immediately.
- Avoid 409 for business-logic conflicts that should not be retried: both SDKs retry 409 automatically.
- Python likely sends `X-Stainless-Retry-Count` as well (same Stainless generator), but this was verified only in Node.

### Gaps
- Retries on connection errors and timeouts (no HTTP status) were not confirmed from the source fetched. The guide's advice to retry `APITimeoutError` suggests the SDKs do.
- Whether Python's 120s "do not retry" rule was a recent change (older releases used a 60s cap with fallback) was not checked against the changelog.

## Q3. Rate-limit headers and value formats

### Takeaway
OpenAI returns six `x-ratelimit-*` headers (limit, remaining and reset, for requests and for tokens), plus `Retry-After` on temporary rate-limit errors. It may also add project-scoped token variants. Reset values are duration strings such as `1s` and `6m0s`.

### Cited Findings
- Header table, with the sample values from the docs:

  | Header | Sample value | Meaning |
  |---|---|---|
  | `Retry-After` | `56` | "The minimum number of seconds to wait before retrying a temporary rate-limit error, when present." |
  | `x-ratelimit-limit-requests` | `60` | maximum requests allowed |
  | `x-ratelimit-limit-tokens` | `150000` | maximum tokens allowed |
  | `x-ratelimit-remaining-requests` | `59` | requests left |
  | `x-ratelimit-remaining-tokens` | `149984` | tokens left |
  | `x-ratelimit-reset-requests` | `1s` | "The time until the rate limit (based on requests) resets to its initial state." |
  | `x-ratelimit-reset-tokens` | `6m0s` | same, for tokens |

  — [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- Project-scoped headers may appear when a project-level token limit applies: `x-ratelimit-limit-project-tokens`, `x-ratelimit-remaining-project-tokens`, `x-ratelimit-reset-project-tokens`. — [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- Limit types: RPM, RPD, TPM, TPD, IPM. A request is limited by whichever is hit first. — [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- Token accounting uses the larger of `max_tokens` and an estimate from the request's character count. — [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- "Unsuccessful requests contribute to your per-minute limit." — [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)

### Inferences
- The reset values (`1s`, `6m0s`) look like Go-style duration strings (h/m/s, possibly with ms). A compatible server should emit the same style, such as `20ms`, `1s`, `6m0s` or `1h2m3s`, and not ISO-8601 or epoch timestamps.
- The headers are documented as appearing on normal responses, not only on 429s, so dashboards and clients can track remaining budget. Emit them on every response where possible.

### Gaps
- The docs do not formally specify whether reset values can be fractional (for example `"5.72s"`, which appears inside 429 messages) or how multi-day values are written.
- No official headers for daily limits (RPD/TPD) or images (IPM) were found.

## Q4. GET /v1/models and GET /v1/models/{model} format

### Takeaway
The list endpoint returns `{"object": "list", "data": [Model, ...]}`, takes no query parameters, and has no pagination. Each Model is `{"id", "object": "model", "created" (Unix seconds), "owned_by"}`. A newer optional, nullable `shutdown_date` field (a date string) now appears in the docs and the Python SDK type. Retrieve returns one Model; DELETE (fine-tuned models only) returns `{"id", "object": "model", "deleted": true}`.

### Cited Findings
- Endpoints:
  - `GET /v1/models` lists models; the response has `object: "list"` and a `data` array.
  - `GET /v1/models/{model}` retrieves one model.
  - `DELETE /v1/models/{model}` deletes a fine-tuned model and requires the organization Owner role.
  - No query parameters or pagination are documented for the list.

  — [OpenAI Models API reference](https://developers.openai.com/api/reference/resources/models)
- Example responses:
  - Retrieve: `"object": "model"`, `"created": 1686935002`, `"owned_by": "openai"`, `"shutdown_date": "2026-10-23"`.
  - Delete: `{"id": "ft:gpt-4o-mini:acemeco:suffix:abc123", "object": "model", "deleted": true}`.

  — [OpenAI Models API reference](https://developers.openai.com/api/reference/resources/models)
- SDK `Model` type: `id: str`; `created: int` ("The Unix timestamp (in seconds) when the model was created."); `object: Literal["model"]`; `owned_by: str`; `shutdown_date: Optional[str] = None` ("The date when the model will shut down, or null if not announced."). — [openai-python types/model.py](https://github.com/openai/openai-python/blob/main/src/openai/types/model.py)

### Inferences
- A minimal compatible response:

  ```json
  {"object":"list","data":[{"id":"my-model","object":"model","created":1731456000,"owned_by":"organization-owner"}]}
  ```

  `shutdown_date` can be left out: the Python type defaults it to `None`, so older and newer SDKs both parse without it.
- `created` must be an integer in Unix seconds, and `object` must be the literal `"model"`.
- The Python SDK's `models.list()` returns a page object, but since the API documents no cursor, a single `data` array with every model is correct.
- For an unknown id in retrieve, return 404 with the `model_not_found` body from Q1.

### Gaps
- The list example in the docs showed ids such as `model-id-2`, and the retrieve example used a placeholder-looking id (`gpt-6-astra`). Example ids are illustrative and should not be treated as real model names.
- The exact `owned_by` values OpenAI returns today (`openai`, `system`, `openai-internal`, organization ids for fine-tunes) were not verified in this pass.

## Q5. Error shape when a streaming request fails after the stream has started

### Takeaway
After a 200 SSE response has started, the HTTP status can no longer change. Errors are sent in-band as an SSE `data:` payload. For Chat Completions and other legacy streams, both SDKs raise when an event's JSON has a truthy `error` key, so send `data: {"error": {"message", "type", "param", "code"}}` and then close the stream. The Responses API instead has a typed `error` event (`{"type": "error", "code", "message", "param", "sequence_number"}`). The `[DONE]` sentinel only marks a normal end.

### Cited Findings
**openai-python `Stream.__stream__`:**
- It stops at `if sse.data.startswith("[DONE]")`.
- For events whose name does not start with `thread.`, it checks `if is_mapping(data) and data.get("error"):` and raises `APIError(message=..., request=..., body=data["error"])`. The message comes from `error.message`, with the fallback "An error occurred during streaming".
- The event *name* `error` is not checked outside the `thread.` branch. Detection depends on the `error` key in the data.

— [openai-python _streaming.py](https://github.com/openai/openai-python/blob/main/src/openai/_streaming.py)

**openai-node `Stream.fromSSEResponse` (legacy mode):**
- `sse.data === '[DONE]'` ends the stream.
- `thread.*` events are passed through.
- `if (sse.event === 'error') throw new APIError(undefined, data?.error ?? data, undefined, response.headers)`.
- `if (data && data.error) throw new APIError(undefined, data.error, undefined, response.headers)`.

— [openai-node core/streaming.ts](https://github.com/openai/openai-node/blob/master/src/core/streaming.ts)

**Responses API error event:**
- `ResponseErrorEvent` fields: `code: Optional[str]`, `message: str`, `param: Optional[str]`, `sequence_number: int`, `type: Literal["error"]`. — [openai-python types/responses/response_error_event.py](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_error_event.py)
- The Response object's `error` field is "An error object returned when the model fails to generate a Response." — [OpenAI Responses streaming events reference](https://developers.openai.com/api/reference/resources/responses/streaming-events)

**Anthropic, for comparison:**
- "an error can occur after the API returns a 200 response. In that case, error handling doesn't follow these standard mechanisms". Anthropic points to separate SSE "error events". — [Claude API errors](https://platform.claude.com/docs/en/api/errors)

### Inferences
- A Chat Completions-compatible mid-stream failure that both SDKs raise on:

  ```
  data: {"error":{"message":"...","type":"server_error","param":null,"code":null}}

  ```

  Then close the connection without sending `data: [DONE]`. Optionally also send an `event: error` line: Node handles it, and Python still raises because of the `error` key.
- SDK retries do not apply mid-stream. The base `APIError` has no HTTP status, so the stream is not retried automatically, and clients must resend.
- In Python, a Responses-style flat event (`{"type":"error","message":...}`, with no nested `error` key) probably does not raise inside `__stream__`. It would be yielded to the caller as a typed `error` event. Servers that emulate `/v1/responses` should therefore emit the typed `error` event and/or a `response.failed` event, following the Responses spec, rather than the Chat Completions shape.
- If an error happens before the first byte is sent, return a normal non-200 JSON error. That is the only case where SDK retries and status-based exception classes work.

### Gaps
- No official OpenAI page found in this pass documents the Chat Completions mid-stream error format. The `data: {"error": ...}` shape comes from SDK source behavior.
- The exact `response.failed` payload (`response.status: "failed"`, `response.error.code` and `message`) was not retrieved; the streaming-events reference page is about 2.3M characters and was truncated.
- Node's newer non-legacy streaming path was not inspected.
