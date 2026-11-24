# Copy OpenAI's wire format, borrow OpenRouter's dashboards

Unmodified openai-python, openai-node and curl clients work against any server that gets six things right. First, a `POST /v1/chat/completions` route behind `Authorization: Bearer` that requires only `model` and `messages` and silently ignores every field it does not understand. Second, a `chat.completion` JSON body with `id`, `object`, `created`, `model`, `choices[].message`, `finish_reason` and a three-integer `usage`, sent as `application/json`. Third, a Server-Sent Events (SSE) stream of `data: <chat.completion.chunk>\n\n` events that ends in exactly `data: [DONE]\n\n`. Fourth, errors shaped as `{"error":{"message","type","param","code"}}` with the correct HTTP status, because both SDKs choose the exception class from the status code alone. Fifth, 429 responses that carry `Retry-After` (at most 60 s) and the six `x-ratelimit-*` headers. Sixth, a `GET /v1/models` list of `{id, object:"model", created, owned_by}`. The strictest rules are in the SDK source, not OpenAI's docs. openai-node checks the stream sentinel with strict equality (`===`). openai-python drops a final SSE event that has no trailing blank line. Both SDKs retry every 429 twice unless the server sends `x-should-retry: false`. On the console side, OpenAI and Anthropic show tokens, requests, cost and per-model limit tables but no latency. OpenRouter is the only one that shows per-request latency, time to first token (TTFT) and throughput. TokenMe publishes no console documentation, so the Observability and Usage & limits pages it is said to have could not be checked.

## Only `model` and `messages` are required, and the rest should be ignored without errors

OpenAI's reference marks only `model` and a non-empty `messages` array as required ([OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)). Messages use the roles `developer`, `system`, `user`, `assistant` and `tool`, plus the legacy `function` role. User `content` is either a string or an array of parts typed `text`, `image_url`, `input_audio` or `file`. A minimal server should parse a short list of fields:

| Field | What to accept |
|---|---|
| `stream` and `stream_options.include_usage` | as sent |
| `temperature` | 0–2, default 1 |
| `top_p` | 0–1 |
| `stop` | a string or up to 4 strings |
| `n` | default 1, maximum 128 |
| `max_tokens` and `max_completion_tokens` | both |

`max_tokens` is deprecated in favor of `max_completion_tokens`, but older clients and OpenAI's own image example still send it, so accept both ([OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)). Everything else can be accepted and ignored. That includes `tools`, `response_format`, `logit_bias`, `seed`, `reasoning_effort`, `prompt_cache_key` and the fields added in 2026. **Strict schema validation is the quickest way to break a newer SDK version.** Established servers ignore unknown fields this way. vLLM ignores the `user` parameter ([vLLM](https://docs.vllm.ai/en/latest/serving/online_serving/)), and Ollama openly lists what it does not support, including `tool_choice`, `logit_bias`, `n` and image URLs ([Ollama](https://docs.ollama.com/api/openai-compatibility)). Treat `developer` as `system` and join the text parts into one string for text-only backends.

The docs' curl example sends `Authorization: Bearer $OPENAI_API_KEY` and `Content-Type: application/json` ([OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)). The Python SDK builds the same Bearer header from `OPENAI_API_KEY` ([_client_auth.py](https://github.com/openai/openai-python/blob/main/src/openai/lib/_client_auth.py)). It also sends `X-Stainless-*` headers that describe the client, plus `OpenAI-Organization` and `OpenAI-Project` when they are configured ([_base_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py); [_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_client.py)). A server must not reject these headers. The SDK appends `/chat/completions` to a `base_url` that normally ends in `/v1`, so mount the API routes under `/v1`. Ollama's API key is required but ignored ([Ollama](https://docs.ollama.com/api/openai-compatibility)), which reflects the fact that clients expect a non-empty key. Local servers should accept any non-empty string.

The non-streaming response must satisfy the SDK's `ChatCompletion` model. It requires `id`, `choices`, `created` (Unix seconds), `model` and the literal `object: "chat.completion"`. It treats `system_fingerprint`, `service_tier` and `usage` as optional ([chat_completion.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion.py)). `finish_reason` must be one of `stop`, `length`, `tool_calls`, `content_filter` or the deprecated `function_call`. `usage` needs integer `prompt_tokens`, `completion_tokens` and `total_tokens`, and its `*_details` breakdowns are optional ([completion_usage.py](https://github.com/openai/openai-python/blob/main/src/openai/types/completion_usage.py)). The `chatcmpl-` id prefix is only a convention that the SDK does not check. The `Content-Type` header matters more: **openai-node parses a body as JSON only if the media type contains `application/json` or ends in `+json`** ([parse.ts](https://github.com/openai/openai-node/blob/master/src/internal/parse.ts)). openai-python is more lenient unless strict response validation is turned on ([_response.py](https://github.com/openai/openai-python/blob/main/src/openai/_response.py)).

```json
{"id":"chatcmpl-abc123","object":"chat.completion","created":1741569952,"model":"my-model",
 "choices":[{"index":0,"message":{"role":"assistant","content":"Hello!","refusal":null},
             "logprobs":null,"finish_reason":"stop"}],
 "usage":{"prompt_tokens":19,"completion_tokens":10,"total_tokens":29}}
```

`GET /v1/models` returns a flat list with no pagination: `{"object":"list","data":[...]}`. No query parameters are documented ([OpenAI Models API](https://developers.openai.com/api/reference/resources/models)). Each entry needs `id`, the literal `object: "model"`, an integer `created` in Unix seconds and `owned_by`. The newer `shutdown_date` field is optional and nullable, so leaving it out does not break old or new SDKs ([model.py](https://github.com/openai/openai-python/blob/main/src/openai/types/model.py)). `GET /v1/models/{model}` returns a single object of the same shape. For an unknown id, return the 404 `model_not_found` error described below.

## Streams must end with exactly `data: [DONE]` and a blank line

With `stream: true`, every chunk has the same `id` and `object: "chat.completion.chunk"`. The first delta carries the role, middle deltas carry text, and the last choice chunk has an empty delta and a `finish_reason` ([OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)). If the client set `include_usage`, the server sends one extra chunk before `[DONE]`. That chunk has an empty `choices` array and the usage for the whole request, and every earlier chunk carries `usage: null` ([stream_options_param.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_stream_options_param.py)). The usage chunk below is built from that docstring, because no verbatim OpenAI example of it was found. In the chunk model, `delta` and `index` are the only required fields in a choice. Tool-call fragments are matched up by a required `index` ([chat_completion_chunk.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_chunk.py)).

```text
data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1694268190,"model":"my-model","choices":[{"index":0,"delta":{"role":"assistant","content":""},"logprobs":null,"finish_reason":null}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1694268190,"model":"my-model","choices":[{"index":0,"delta":{"content":"Hello"},"logprobs":null,"finish_reason":null}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1694268190,"model":"my-model","choices":[{"index":0,"delta":{},"logprobs":null,"finish_reason":"stop"}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1694268190,"model":"my-model","choices":[],"usage":{"prompt_tokens":19,"completion_tokens":10,"total_tokens":29}}

data: [DONE]

```

The SDKs' SSE parsers explain the formatting rules. openai-python follows the WHATWG SSE spec. It dispatches an event only when it sees an empty line, joins multiple `data:` lines and skips `:` comment lines. As a result, **a final event without a trailing blank line is never delivered** ([_streaming.py](https://github.com/openai/openai-python/blob/main/src/openai/_streaming.py)). Python stops when the data starts with `[DONE]`. Node requires `sse.data === '[DONE]'` exactly and throws a `SyntaxError` on malformed chunk JSON ([streaming.ts](https://github.com/openai/openai-node/blob/master/src/core/streaming.ts)). Neither SDK raises an error if `[DONE]` never arrives; iteration simply ends. Still, curl scripts and other parsers wait for the sentinel, so always send it. Both SDKs decide to parse SSE from the request's `stream` flag, not from the response header ([parse.ts](https://github.com/openai/openai-node/blob/master/src/internal/parse.ts); [_response.py](https://github.com/openai/openai-python/blob/main/src/openai/_response.py)). `Content-Type: text/event-stream` is therefore for `curl -N`, browsers and generic SSE clients. Send it with `Cache-Control: no-cache` and flush after every event.

Once a 200 response has started streaming, its status code can no longer change. In both SDKs, any event whose JSON has a non-empty `error` key raises `APIError`. Node also raises on an `event: error` line ([_streaming.py](https://github.com/openai/openai-python/blob/main/src/openai/_streaming.py); [streaming.ts](https://github.com/openai/openai-node/blob/master/src/core/streaming.ts)). So a mid-stream failure should be sent as `data: {"error":{"message":"...","type":"server_error","param":null,"code":null}}\n\n`, followed by closing the connection without `[DONE]`. No OpenAI page documents this format for Chat Completions; it comes from the SDK source. These errors have no HTTP status, so the SDKs do not retry them, and the client has to send the request again.

## Status codes pick the exception class, and `type` and `code` tell the client what happened

openai-python reads the error object from the nested `error` key, or from the whole body if that key is missing ([_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_client.py)). `APIError` then takes `type` (a string) and `param` and `code` (both nullable) from that object ([_exceptions.py](https://github.com/openai/openai-python/blob/main/src/openai/_exceptions.py)). The exception class depends only on the HTTP status:

| Status | Exception class |
|---|---|
| 400 | `BadRequestError` |
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitError` |
| 500 and above | `InternalServerError` |

([_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_client.py)) The status must therefore be exact. `type` and `code` matter to application code that branches on them, for example to tell a quota error from a temporary rate limit. The values below combine OpenAI's error-code guide with error bodies users have posted on the OpenAI forum. The guide lists messages and codes but no full JSON examples, so the forum bodies are weaker evidence.

| Status | `type` | `code` | Source |
|---|---|---|---|
| 401 bad key | `invalid_request_error` | `invalid_api_key` | [guide](https://developers.openai.com/api/docs/guides/error-codes), [forum](https://community.openai.com/t/getting-incorrect-api-key-error-in-node-js/579115) |
| 404 unknown model | `invalid_request_error` | `model_not_found` | [forum](https://community.openai.com/t/the-model-gpt-4o-audio-does-not-exist-or-you-do-not-have-access-to-it/1388356) |
| 429 RPM/TPM | `requests` or `tokens` | `rate_limit_exceeded` | [forum](https://community.openai.com/t/rate-limit-exceeded-error-when-we-only-do-one-transaction-at-a-time/974781) |
| 429 quota/credits | `insufficient_quota` | `insufficient_quota` / `credit_balance_exhausted` | [guide](https://developers.openai.com/api/docs/guides/error-codes), [forum](https://community.openai.com/t/429-error-insufficient-quota/492350) |
| 429 sudden traffic spike | `rate_limit_error` | `slow_down` | [guide](https://developers.openai.com/api/docs/guides/error-codes) |
| 503 overload | `service_unavailable_error` | `server_is_overloaded` | [guide](https://developers.openai.com/api/docs/guides/error-codes) |

**A 401 is never retried.** Both SDKs retry only 408, 409, 429 and statuses of 500 or above, so a bad key fails fast as `AuthenticationError`. Documented 401 messages include "Invalid Authentication", "Incorrect API key provided" and "IP not authorized" ([OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)). **429s are retried twice by default**, with backoff that starts at 0.5 s, doubles up to an 8 s cap and subtracts up to 25% random jitter. A `x-should-retry: true|false` header overrides the status rule ([_base_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py); [_constants.py](https://github.com/openai/openai-python/blob/main/src/openai/_constants.py); [client.ts](https://github.com/openai/openai-node/blob/master/src/client.ts)). Both SDKs read `retry-after-ms` first, then `retry-after` as seconds or an HTTP date. They part ways on long delays. **Python waits the server's delay up to 120 s and refuses to retry beyond that. Node uses the server's delay only up to 60 s and otherwise falls back to its own backoff**, which tops out at 8 s. Keep `Retry-After` at or below 60 s. Send `x-should-retry: false` on quota, spend-limit and request-too-large 429s, since OpenAI says that for exhausted credits, "Retrying won't restore access" ([OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes)). Avoid 409 for business conflicts that should not be retried.

OpenAI's rate-limit headers are documented with sample values ([OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)):

| Header | Sample |
|---|---|
| `Retry-After` | `56` |
| `x-ratelimit-limit-requests` / `-tokens` | `60` / `150000` |
| `x-ratelimit-remaining-requests` / `-tokens` | `59` / `149984` |
| `x-ratelimit-reset-requests` / `-tokens` | `1s` / `6m0s` |

Projects with their own token limit get extra `x-ratelimit-*-project-tokens` headers. Failed requests still count toward per-minute limits ([OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)). Reset values look like Go-style duration strings. No formal grammar is published, and fractional seconds appear inside error messages, so emit values such as `20ms`, `1s` or `6m0s`, and send the headers on every response, not only on 429s. Do not mix in Anthropic's conventions. Anthropic uses `anthropic-ratelimit-*` headers with RFC 3339 reset times, a top-level `type: "error"` envelope with `request_id`, and status 529 for overload ([Claude rate limits](https://platform.claude.com/docs/en/api/rate-limits); [Claude API errors](https://platform.claude.com/docs/en/api/errors)). OpenAI SDK users will not parse any of these.

## Consoles show usage everywhere, but latency only at OpenRouter

**OpenAI** separates usage from billed cost. The Usage dashboard is shown in UTC, and its project selector shows all projects when none is chosen. It groups usage by model, API key, project or user, and a 1-minute interval shows TPM. Billed figures come from a separate Cost view, and monthly exports can be grouped by project, user, key, model, batch or service tier. These details come from search summaries of OpenAI's help center, because the article returned 403 to fetching ([OpenAI Help](https://help.openai.com/en/articles/10478918-api-usage-dashboard)). The Usage API shows the same underlying data. It offers `1m`, `1h` and `1d` buckets and returns `input_tokens`, `output_tokens`, `input_cached_tokens` and `num_model_requests`. Cost data comes only in daily buckets ([OpenAI Usage API](https://developers.openai.com/api/docs/api-reference/usage)). Limits are split across two pages. The organization Limits page has a per-model RPM/TPM table, a usage-tier ladder with an "Upgrade tier" button, and shared limits where several models draw from one TPM pool. Tiers run from Free ($100/month) to Grow ($200,000/month) ([OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits)). Each project's Settings > Limits page holds per-model access, a spend limit with a hard-stop toggle, and alerts that only notify. Enforcement is not instant ([OpenAI spend limits](https://developers.openai.com/api/docs/guides/spend-limits)).

**Anthropic** puts limit headroom directly on its Usage page. The page has an input/output token bar chart that drills down to hour and minute, a cache rate, a count of blocked rate-limited requests, filters by workspace, model, month, day and API key, and CSV export ([Claude Help](https://support.claude.com/en/articles/9534590-cost-and-usage-reporting-in-console)). For each model, two charts plot the hourly peak of uncached input tokens per minute (ITPM) against the ITPM limit, and peak output tokens per minute (OTPM) against the OTPM limit ([Claude rate limits](https://platform.claude.com/docs/en/api/rate-limits)). The Cost page shows daily cost per month, including tool costs. Neither page can break down usage by user ([Claude Help](https://support.claude.com/en/articles/9534590-cost-and-usage-reporting-in-console)). The Rate limits page lists the organization's tier and per-model RPM, ITPM and OTPM, enforced with a continuously refilling token bucket. Reaching the tier's spend cap returns a 429 `enforced_spend_limit_reached` with no `retry-after` ([Claude rate limits](https://platform.claude.com/docs/en/api/rate-limits)).

**OpenRouter** is the only one with real observability. Its Activity page has four tabs. Overview shows spend, requests, tokens, blended cost per million tokens, cache hit rate and top keys, apps and users. Trends shows time series, Explore is a chart builder with CSV/PDF export, and Guardrails is the fourth tab ([OpenRouter Activity](https://openrouter.ai/docs/guides/features/activity.md)). The Logs page lists one row per generation with its latency. A detail panel shows provider latency, throughput, TTFT, a cost breakdown and the finish reason. Only metadata is stored by default; storing prompt and response content is opt-in ([OpenRouter Logs](https://openrouter.ai/docs/guides/features/logs.md)). `GET /api/v1/generation` returns `latency` and `generation_time` in milliseconds for each request ([OpenRouter generation API](https://openrouter.ai/docs/api-reference/get-a-generation)). Per-key credit limits reset daily, weekly or monthly at UTC boundaries, and `:free` models allow 20 RPM and either 50 or 1,000 requests per day ([OpenRouter limits](https://openrouter.ai/docs/limits.md)). One search summary claimed P50/P90/P99 latency in Explore, but the fetched docs do not list it, so treat it as unconfirmed.

**TokenMe** has no public console documentation. Its site returned 403 to fetching. Thai press coverage describes an OpenAI-compatible API that works by swapping `base_url` and the key, a limited-customer trial as of 11 October 2026, daily and weekly caps with no numbers given, and logging of metadata only: request ID, time, model and token count ([TradingView/Bitcoin Addict](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/)). No public source confirms the specific Observability elements (P50/P95 request time, TTFT, decode tok/s, cache hit rate). The same goes for the Usage & limits elements (daily/weekly/monthly allowance, concurrency, RPM, TPM). Treat them as a design brief, not as documented features.

| | OpenAI | Anthropic | OpenRouter | TokenMe |
|---|---|---|---|---|
| Usage | requests, tokens (cached/uncached), cost | in/out tokens, cache rate, throttled count, cost | spend, requests, tokens, $/M, cache hit rate | not public |
| Latency / TTFT / tok/s | none | none | per request in Logs; tok/s in Explore | not public |
| Granularity | 1m / 1h / 1d (cost daily) | month → day → hour → minute | configurable rollup | — |
| Limits view | per-model RPM/TPM, tier ladder, project spend cap | tier + RPM/ITPM/OTPM, headroom charts | per-key credit limit, daily/weekly/monthly reset | daily/weekly caps reported |
| Per-request log | no | no | yes, metadata by default | metadata only |

## Conclusion

Whether a server counts as OpenAI-compatible is decided by SDK source code, not by the API reference. The behavior that breaks clients is mechanical: strict request validation, a loosely written stream terminator, and wrong status codes. The most expensive mistake causes no visible error. Every non-retryable 429 turns into three requests unless the server sends `x-should-retry: false`, and a `Retry-After` above 60 s makes Node and Python behave differently. The safest error and rate-limit format is to copy OpenAI's header names and error envelope exactly and leave out Anthropic's.

The big consoles leave a gap that a small provider can fill. None of them confirms latency percentiles. For a CPU-bound server, where prefill dominates on long prompts, showing TTFT and decode speed separately is what tells users the most. Decode speed should follow NVIDIA's inter-token definition, (output_tokens − 1) / (t_last − t_first), and TTFT should include queueing and prefill ([NVIDIA NIM metrics](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html)). Benchmarking tools disagree on these formulas, so the page should state the formula it uses. Pairing those metrics with Anthropic-style headroom charts and OpenRouter-style daily/weekly/monthly allowance bars covers the rest of the page. One localization detail matters: all three large providers reset limits at UTC, and 00:00 UTC is 07:00 in Bangkok. A Thai-facing console should either reset at local midnight or label the reset time explicitly.
