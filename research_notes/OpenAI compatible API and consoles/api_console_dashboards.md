# AI API console dashboards: Observability/Activity and Usage & limits pages (OpenAI, Anthropic, OpenRouter, TokenMe)

Research date: 2026-11-13. Several primary pages blocked automated fetches (help.openai.com returned 403; tokenme.limited returned 403; api.tokenme.limited returned 404). Where a page could not be fetched, findings come from search-result summaries of that page or from the provider's API reference, which mirrors the dashboard. This is noted inline.

## 1. OpenAI platform: Usage dashboard and per-project limits / rate-limit pages

### Takeaway
OpenAI's Usage dashboard is a project-filterable, UTC-based view of spend and token/request usage that can be grouped by project, API key, model, and user. A separate Cost view gives billed amounts, and exports are available. Limits sit on two pages: an organization Limits page (per-model RPM/TPM and the usage-tier ladder with an "Upgrade tier" button) and a per-project Settings > Limits page (per-model rate limits, spend limits with a hard-limit toggle, and spend alerts).

### Cited Findings
**Usage dashboard (UI, from help-center search summaries; the article itself returned 403):**
- Dashboard data is shown in UTC. Only Organization Owners, or users explicitly given Usage Dashboard permission, can open it. The dashboard has its own project selector, and "if no projects are selected, it will default to showing all project data" — [OpenAI Help: API usage dashboard](https://help.openai.com/en/articles/10478918-api-usage-dashboard) (via search summary)
- The help article's screenshots show a "Group by" menu. A user-reported forum thread says usage per model is shown first and you can switch to see usage per API key — [OpenAI Help](https://help.openai.com/en/articles/10478918-api-usage-dashboard); [OpenAI Community: can't see usage by key](https://community.openai.com/t/i-cant-see-api-usage-by-key-only-by-project/1129907) (user-reported, not official)
- Detail pages support interval selection, and choosing a 1-minute interval shows tokens per minute (TPM). That interval applies to usage data, not billing data. A "Spend categories" tab (reached after clearing the project filter) shows organization-level costs such as the Scale Tier subscription. Billed amounts should be read from Cost data — [OpenAI Help: Reviewing API usage and costs](https://help.openai.com/en/articles/10478918-reviewing-api-usage-and-costs) (via search summary)
- Per-user review: go to the API capabilities section and use "Filter by" to pick a user — [OpenAI Help](https://help.openai.com/en/articles/10478918-reviewing-api-usage-and-costs) (via search summary)
- Monthly export can be grouped by project, user, API key, model, batch, or service tier. Export has no date-range limit, but long ranges may be split into several files — [OpenAI Help: export monthly usage details](https://help-lb.openai.com/en/articles/20001072-how-do-i-export-monthly-usage-details-from-the-api-usage-dashboard) (via search summary)
- A secondary news site says OpenAI's changelog added API-key grouping to the Usage and Costs dashboards. This is unverified against OpenAI's own changelog — [aicatchup](https://aicatchup.com/news/openai-api-key-usage-spend-hard-limits)

**Usage API (the data model behind the dashboard, from the primary API reference):**
- `GET /organization/usage/completions` takes `bucket_width` of `1m`, `1h`, or `1d` (default `1d`). Default/max bucket counts are 1d: 7/31, 1h: 24/168, and 1m: 60/1440 — [OpenAI API reference: Usage](https://developers.openai.com/api/docs/api-reference/usage)
- `group_by` values: `project_id`, `user_id`, `api_key_id`, `model`, `batch`, `service_tier`, `api_source`. Filters: `api_key_ids`, `models`, `project_ids`, `user_ids`, and `batch` — [OpenAI API reference: Usage](https://developers.openai.com/api/docs/api-reference/usage)
- Result fields per bucket: `input_tokens`, `output_tokens`, `input_cached_tokens`, `input_uncached_tokens`, `input_cache_write_tokens`, modality breakdowns (audio/text/image in and out), and `num_model_requests` — [OpenAI API reference: Usage](https://developers.openai.com/api/docs/api-reference/usage)
- `GET /organization/costs` supports only `bucket_width=1d` (limit 1–180). It groups by `project_id`, `user_id`, `line_item`, `api_key_id`, or `api_source`, and returns `amount.value` plus `amount.currency` (lowercase ISO-4217), with `line_item`, `quantity`, and `quantity_unit` — [OpenAI API reference: Usage](https://developers.openai.com/api/docs/api-reference/usage)

**Rate limits and tiers (primary doc):**
- Limit types: RPM, RPD, TPM, TPD, IPM (images per minute), and audio minutes per minute for some streaming audio models. "A limit can be hit on any of these metrics, whichever comes first" — [OpenAI Rate limits guide](https://developers.openai.com/api/docs/guides/rate-limits)
- Usage tiers as currently documented: Free (allowed geography, $100/month usage limit), Build ($5 in credit purchases, $500/month), Launch ($100, $5,000/month), and Grow ($500, $200,000/month). Tiers upgrade automatically as total credit purchases cross each threshold. "Tier describes rate limits, not model access" — [OpenAI Rate limits guide](https://developers.openai.com/api/docs/guides/rate-limits)
- Example standard limits shown per tier and model family, e.g. Build: 5,000 RPM / 1,000,000 TPM; Grow: 15,000 RPM / 40,000,000 TPM for one model family. The fetched doc names model families "Astra, Sol, Terra" and "Luna"; verify these names against the live page — [OpenAI Rate limits guide](https://developers.openai.com/api/docs/guides/rate-limits)
- The organization Limits page (`platform.openai.com/settings/organization/limits`) shows per-model Rate limits, a Usage Tiers section with an "Upgrade tier" button, and "shared limits" where several models draw from one TPM pool. Limits are set at the organization and project levels, not per user — [OpenAI Rate limits guide](https://developers.openai.com/api/docs/guides/rate-limits)
- Response headers: `x-ratelimit-limit-requests`/`-tokens`, `x-ratelimit-remaining-requests`/`-tokens`, `x-ratelimit-reset-requests`/`-tokens`, and project-scoped `x-ratelimit-*-project-tokens`, plus `Retry-After`. Failed requests still count toward the per-minute limit. A `slow_down` error can occur within RPM/TPM if traffic ramps too fast — [OpenAI Rate limits guide](https://developers.openai.com/api/docs/guides/rate-limits)

**Per-project limits and spend controls:**
- Project limits live under the project's Settings > Limits. Per-model access and rate limits are set there under "Model usage". Spend limits sit on the same page with a hard-limit toggle that makes API calls fail once the limit is reached. Spend alerts only notify. Enforcement is not instantaneous, so spend can slightly exceed the limit. The OpenAI-approved monthly usage limit (tier) is separate from user-set spend limits — [OpenAI Spend limits guide](https://developers.openai.com/api/docs/guides/spend-limits); [OpenAI Help: spend limits](https://help.openai.com/en/articles/9186755-managing-your-work-in-the-api-platform-with-spend-limits); [OpenAI Help: troubleshooting usage and spend limits](https://help.openai.com/en/articles/6614457-troubleshooting-api-usage-and-spend-limits) (via search summary)
- A community thread reports budget buttons being replaced by "Alerts" wording and advises against relying on them as hard caps. This is user commentary that conflicts with the hard-limit toggle described in official docs — [OpenAI Community thread](https://community.openai.com/t/per-project-and-per-organization-spending-limits-buttons-missing/1380321)

### Inferences
- OpenAI separates **observability of usage** (tokens and requests, groupable, with 1m/1h/1d buckets) from **billing truth** (Cost, daily only). It does not show latency or TTFT anywhere in the Usage dashboard. No source mentioned latency metrics.
- Limits are shown as a **static table per model** (RPM/TPM ceilings) and a **tier ladder**, not as live gauges. Real-time headroom is exposed only through response headers.

### Gaps
- Exact current tab names and chart types on platform.openai.com/usage could not be verified, because the help article returned 403. One search summary found no "Activity" tab named in help pages.
- Empty-state wording ("No usage yet", etc.) is not documented anywhere found.
- Data freshness/latency of the dashboard is not stated in the sources reached.

## 2. Anthropic Console (Claude Console): Usage, Cost, and Rate limits pages

### Takeaway
The Claude Console has a Usage page (token bar chart with drill-down to hour and minute, cache rate, rate-limited request count, two per-model rate-limit headroom charts, filters by workspace/model/month/day/API key, CSV export) and a Cost page (daily cost chart per month, token and tool costs, CSV export). A Rate limits page shows tier and per-model RPM/ITPM/OTPM with a "Request tier increase" button, and Spend limits live under Settings. Per-user breakdown is not available.

### Cited Findings
**Usage page (`platform.claude.com/usage`):**
- A bar chart shows input and output token counts. You can "click into the bars on the bar chart for hour and minute granularity." Headline metrics are total input/output tokens for the filters, cache rate (share of input tokens read from cache), and rate-limited requests that were blocked — [Claude Help: Cost and usage reporting in Console](https://support.claude.com/en/articles/9534590-cost-and-usage-reporting-in-console)
- Filters: workspace (or all), model (or all), month, a specific day, and API key (or all). Data can be viewed by model, date/time, and API key. CSV download is available — [Claude Help](https://support.claude.com/en/articles/9534590-cost-and-usage-reporting-in-console)
- Two rate-limit charts are shown per model. **Rate Limit - Input Tokens** shows hourly maximum uncached input tokens per minute, the current ITPM limit, and cache rate. **Rate Limit - Output Tokens** shows hourly maximum output tokens per minute and the current OTPM limit. They are intended to "see what headroom you have to grow, identify when you might be hitting peak use, understand what rate limits to request, and learn how to improve your caching rates" — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)

**Cost page (`platform.claude.com/cost`):**
- A daily cost chart covers the selected month. It shows token cost and tool-use costs (web search, code execution) plus the period total, filtered by workspace, model, and month, with CSV export. "Currently, it's not possible to break down usage or cost by individual users." Both pages are visible to the Developer, Billing, and Admin roles — [Claude Help](https://support.claude.com/en/articles/9534590-cost-and-usage-reporting-in-console)

**Rate limits page and spend limits:**
- There are two limit types. Spend limits are a monthly cost cap. Rate limits are RPM, ITPM, and OTPM per model class. Tier and current limits appear on the Rate limits page (`platform.claude.com/usage/limits`). The API uses a token bucket algorithm ("capacity is continuously replenished up to your maximum limit, rather than being reset at fixed intervals"). 60 RPM may be enforced as 1 request per second — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Tiers: Evaluation (below standard, for new orgs), Start (monthly spend cap $500), Build ($1,000), Scale ($200,000), and Custom (no cap). Example limits: Start tier Claude Opus 5.5 is 4,000 RPM / 2,000,000 ITPM / 400,000 OTPM — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Spend limits are at `platform.claude.com/settings/spend-limits`, using "Adjust limit" or "Set limit" next to "Monthly spend limit". The value can't exceed the tier cap. Hitting the tier cap returns HTTP 429 `rate_limit_error` with `error_code: enforced_spend_limit_reached` and **no** `retry-after`. Hitting a self-set limit returns HTTP 400 `invalid_request_error` — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Cache-aware ITPM: only `input_tokens` + `cache_creation_input_tokens` count, and `cache_read_input_tokens` do not. Total input = cache_read + cache_creation + input_tokens. Users are told to "Monitor your cache hit rate on the Usage page." OTPM counts actual tokens generated, and `max_tokens` does not count — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Ramp limits: a 429 can occur below ITPM/OTPM after a sharp increase (`error_code: ramp_limit_exceeded`). The ramp limit is the recent peak per-minute usage plus a step — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Workspaces can have custom spend and rate limits per limiter type, but not on the default workspace. If unset, they match the org limit, and org limits always apply — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Response headers: `anthropic-ratelimit-requests-{limit,remaining,reset}`, `-tokens-*`, `-input-tokens-*`, and `-output-tokens-*`. Reset is RFC 3339. Token remaining is rounded to the nearest thousand. The headers reflect "the most restrictive limit currently in effect" — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- The Usage & Cost Admin API mirrors the Console Usage and Cost pages. The Rate Limits API returns the limits shown on the Rate limits page — [Anthropic Docs: Usage and Cost API](https://docs.anthropic.com/en/api/usage-cost-api); [Claude Docs: Rate Limits API](https://platform.claude.com/docs/en/manage-claude/rate-limits-api)

### Inferences
- Anthropic is the only one of the three that puts **limit-vs-actual headroom charts** directly on the Usage page: peak per-minute usage per hour, plotted against the limit line. This is a strong pattern for a small provider whose capacity is the binding constraint.
- "Rate-limited requests blocked" as a headline metric tells customers when they are throttled, which is useful on CPU-only hardware where throttling will be common.
- The Console shows no latency or TTFT. Like OpenAI, Anthropic treats performance as out of scope for the console.

### Gaps
- Time zone of the Console charts and data refresh delay are not stated in the help article.
- Empty-state UI is not documented.

## 3. OpenRouter: Activity page, Logs (per-generation), generation stats API, and key limits

### Takeaway
OpenRouter splits observability into **Activity** (aggregate: spend, requests, tokens, blended $/M tokens, cache hit rate, top keys/apps/users, trends, a configurable Explore chart builder with CSV/PDF export) and **Logs** (one row per generation with latency; a detail panel with provider latency, throughput, TTFT, cost breakdown, finish reason). `GET /api/v1/generation` returns per-request `latency`, `generation_time`, token counts, and cost. Per-key credit limits reset daily, weekly, monthly, or never, at UTC boundaries.

### Cited Findings
**Activity page:**
- Tabs: **Overview** (total spend, requests, token volume, blended cost per million tokens, cache hit rate; ranked cards for top API keys, apps, users; charts for usage by model, token breakdown prompt/completion/reasoning, prompt caching, and usage type credits vs BYOK), **Trends** (time series for requests/spend/tokens plus a "Trending" card of the biggest changes vs the prior period), **Explore** (metric + up to two grouping dimensions "Group"/"Subgroup" + rollup + bar/line/dot view; overflow series go to "Other"; "Cumulative sum" for additive metrics), and **Guardrails** — [OpenRouter Docs: Activity](https://openrouter.ai/docs/guides/features/activity.md)
- All tabs share one date range and filter state stored in the URL. Filters include user, model, provider, API key, and modality, and org accounts can filter by member. Cards link to "View logs" or "Open in Explorer" with filters applied. Explore charts can be saved as named charts (private or org-wide) and exported as CSV or PDF — [OpenRouter Docs: Activity](https://openrouter.ai/docs/guides/features/activity.md)
- Analytics API: `GET /api/v1/analytics/meta`, `POST /api/v1/analytics/query` (equivalent of Explore), and `GET /api/v1/activity` (daily usage and spend by model endpoint) — [OpenRouter Docs: Activity](https://openrouter.ai/docs/guides/features/activity.md)
- Tokens/second throughput metrics were added to the Activity Explorer (changelog, 21 Apr 2026) — [OpenRouter changelog 2026-04-21](https://openrouter.ai/docs/changelog/2026/4/21) (via search summary). A search summary also said Explore offers P50/P90/P99 latency, but the fetched Activity doc did not list latency percentiles, so treat this as **unverified/conflicting** — [OpenRouter Docs: Activity](https://openrouter.ai/docs/guides/features/activity.md)

**Logs page:**
- The Generations tab (default) has one row per completed generation, with columns date, model, final provider, generation ID, status, attempts, API key, and latency (plus Org Member for orgs). Other tabs are Upstream Requests (routing attempts, retries, fallbacks), Sessions, Videos, and Batches — [OpenRouter Docs: Logs](https://openrouter.ai/docs/guides/features/logs.md)
- The detail panel shows Overview (model, provider, cost, tokens, finish reason, streaming flag, "provider latency and throughput," data region, fallbacks), Provider Responses (a per-attempt waterfall of latency, moderation time, and overhead), Usage (cost breakdown incl. cache read discounts), Prompt/Completion (only if logging is enabled), and Raw JSON. A request histogram shows volume over the date range — [OpenRouter Docs: Logs](https://openrouter.ai/docs/guides/features/logs.md)
- Per-generation performance shows provider latency, throughput, and time to first token — [OpenRouter Docs: Logs](https://openrouter.ai/docs/guides/features/logs) (via search summary)
- By default logs hold metadata only. Content storage is opt-in via Settings > Observability, and "Only generations made after you enable it will have stored content" — [OpenRouter Docs: Logs](https://openrouter.ai/docs/guides/features/logs.md)

**Generation stats API (`GET /api/v1/generation`):**
- Fields include `latency` ("Total latency, in milliseconds"), `generation_time` (ms), `moderation_latency` (ms), `tokens_prompt`, `tokens_completion`, `native_tokens_prompt`, `native_tokens_completion`, `native_tokens_cached`, `native_tokens_reasoning`, `total_cost` (USD), `cache_discount`, `upstream_inference_cost`, `finish_reason`, `native_finish_reason`, `streamed`, `cancelled`, `provider_name`, `model`, `created_at`, `provider_responses` (incl. fallbacks), `request_id`, and `session_id` — [OpenRouter API reference: Get a generation](https://openrouter.ai/docs/api-reference/get-a-generation)
- Definitions changed in May 2025: for reasoning models, latency measures time until the first reasoning token, and throughput includes both reasoning and output tokens — [OpenRouter blog: Better insights, faster metrics](https://openrouter.ai/blog/announcements/better-insights-faster-metrics-and-new-developer-power-tools/) (via search summary). Note that this "time to first token" meaning of latency differs from the API reference's "Total latency" wording, so the two sources are ambiguous on what `latency` measures.

**Key limits and rate limits:**
- A per-key credit cap uses `limit`, `limit_remaining`, and `limit_reset` (null = never resets). Daily/weekly/monthly windows reset at UTC boundaries: daily 00:00 UTC, weekly on Monday, monthly on the 1st. `GET /api/v1/key` returns `usage`, `usage_daily`, `usage_weekly`, `usage_monthly`, BYOK variants, `is_free_tier`, and `free_model_daily_requests` {`used`,`limit`,`remaining`}, along with `budgets`/`effective_budget`. `rate_limit` is deprecated — [OpenRouter Docs: Limits](https://openrouter.ai/docs/limits.md)
- Free models (`:free`) allow 20 RPM, and 50 requests/day with <10 credits purchased or 1,000/day with at least 10. Limits are global, so more keys don't raise them. An "in-flight budget" caps the estimated cost of running requests — [OpenRouter Docs: Limits](https://openrouter.ai/docs/limits.md)
- Errors: 402 with `error.metadata.limit_source` = `openrouter_in_flight_budget` | `openrouter_key_limit` | `openrouter_credits`. 403 is for guardrail/workspace budgets. 429 carries `X-RateLimit-Limit/Remaining/Reset`, and a mid-stream error arrives as an SSE event with `finish_reason: "error"` — [OpenRouter Docs: Limits](https://openrouter.ai/docs/limits.md)

### Inferences
- OpenRouter is the closest model for an "Observability" page: aggregate tiles (requests, tokens, spend, cache hit rate) plus drill-through to per-request logs with latency, TTFT, and throughput.
- The per-key `limit` + `limit_reset` (daily/weekly/monthly) + `usage_daily/weekly/monthly` pattern maps directly to a "daily/weekly/monthly allowance" display.

### Gaps
- Exact formula OpenRouter uses for "throughput" (whether it is tokens / generation_time or tokens / total latency) is not documented in the pages fetched.
- Log retention period and empty states are not documented.

## 4. TokenMe (Token Me Limited, tokenme.limited / api.tokenme.limited)

### Takeaway
**No public documentation of TokenMe's console was found.** Nothing public describes an Observability page (P50/P95 request time, TTFT, decode tok/s, cache hit rate), a Usage & limits page (daily/weekly/monthly allowance, concurrency, RPM, TPM), or a Playground with an "API quick start" curl. The website blocked automated fetching (403), `api.tokenme.limited/` returned 404 at the root, and targeted searches returned nothing. Public information is limited to news coverage and site snippets: a Thai AI inference company, OpenAI-compatible API, limited customer trial, with daily and weekly caps mentioned but no numbers.

### Cited Findings
- TokenMe's website presents an "AI Inference" service — [TokenMe — AI Inference](https://www.tokenme.limited/) (site returned HTTP 403 to fetch; content known only via search snippets). It also has a contact page — [TokenMe contact](https://www.tokenme.limited/contact)
- Company: TOKEN ME LIMITED (บริษัท โทเคนมี จำกัด), registered 25 May 2026, capital 1,000,000 baht, Mueang Nakhon Ratchasima. It is founded by Thai tech YouTuber 9arm — [TradingView/Bitcoin Addict news (Thai)](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/); [DataForThai company record](https://www.dataforthai.com/company/0305569005321/)
- The API is OpenAI-compatible: users change `base_url` and the API key to use existing code. It is reported to work with OpenCode, Cline, and Hermes Agent. The exact base_url is not stated in the coverage — [TradingView/Bitcoin Addict](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/)
- Status: "ทดลองให้บริการกับลูกค้าจำนวนจำกัด" (limited-customer trial) as of 11 Oct 2026. The API key button is labeled "Soon", and a live counter shows total tokens served (724,704,404,861 at time of the report) — [TradingView/Bitcoin Addict](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/)
- Models listed on the site per coverage: Qwen3.8 27B (limited trial), DeepSeek V4 Flash, Gemma 4 31B, GLM 5.3 — [TradingView/Bitcoin Addict](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/)
- Pricing (reported, not published on site): ~300 baht/month subscription including ~1,500 baht worth of equivalent API usage. "Daily and weekly caps apply" with no numbers given — [TradingView/Bitcoin Addict](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/)
- Privacy: prompts and responses are not stored. Only request metadata is kept (request ID, time, model, token count) — [TradingView/Bitcoin Addict](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/); [Bitcoin Addict](https://www.bitcoinaddict.com/news/9arm-token-me-ai-inference-company-thailand) (fetch returned 429; content via search summary)
- An operational incident was reported: logs filled the disk overnight and enterprise clients were down ~10:00–19:00. Alerts were then added — [TradingView/Bitcoin Addict](https://th.tradingview.com/news/bitcoin_addict:0eebf9947fa6a:0/)
- A third-party GitHub PR added a TokenMe endpoint preset. Its authors noted that a provider API key is required and that a live request was not tested — [GitHub: ManaphatDev/vibe-Board PR #14](https://github.com/ManaphatDev/vibe-Board/pull/14)

### Inferences
- The console sections named in the assignment (Observability with P50/P95/TTFT/decode tok/s/cache hit rate; Usage & limits with daily/weekly/monthly allowance, concurrency, RPM, TPM; Playground "API quick start" curl) could not be confirmed from any public source. They may exist behind login. The report should present them as the assignment's design brief, not as documented TokenMe features.
- TokenMe's metadata-only logging (request ID, time, model, token count) is the same privacy posture as OpenRouter's default (metadata only, content opt-in). It is enough to compute every metric in section 5 if per-request timings are also recorded.

### Gaps
- No public TokenMe docs, console screenshots, rate-limit numbers, concurrency limits, or base URL were found. The site returned 403 to automated fetch, and `api.tokenme.limited/` returned 404 at its root (expected for an API host). A human with a browser or account may see more.

## 5. Common definitions: TTFT, P50/P95 latency, decode speed (tokens/sec), and how they are computed

### Takeaway
Standard definitions from NVIDIA's benchmarking docs: TTFT = submission to first non-empty token (includes queueing + prefill + network); end-to-end latency = TTFT + generation time; inter-token latency = (e2e − TTFT) / (output_tokens − 1); per-request tokens/sec = output tokens / e2e (approaching 1/ITL for long outputs); system TPS = total output tokens / wall-clock window. Tools disagree on whether TTFT is included in tokens/sec, so a console must state its formula.

### Cited Findings
- **TTFT:** "Time from query submission to the first received token" (ignoring empty initial responses). It "includes request queuing, prefill, and network latency" — [NVIDIA NIM benchmarking: Metrics](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html)
- **End-to-end request latency:** time from submission to the full response, `e2e_latency = TTFT + Generation_time`, where generation time runs from first to last token (excluding the final `[done]`) — [NVIDIA NIM Metrics](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html)
- **Inter-token latency (ITL/TPOT):** `ITL = (e2e_latency − TTFT) / (Total_output_tokens − 1)`. The −1 excludes the first token so ITL "characterizes only the decoding part" — [NVIDIA NIM Metrics](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html)
- **Tokens per second:** per user = output sequence length / e2e_latency (approaches 1/ITL for long outputs). System = `Total_output_tokens / (T_y − T_x)` from the first request to the last response. RPS = `total_completed_requests / (T_y − T_x)` — [NVIDIA NIM Metrics](https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html)
- Tools differ: AIPerf excludes TTFT from ITL, while LLMPerf includes it. NVIDIA advises comparing results only when definitions match — [NVIDIA NIM Metrics](https://docs.nvidia.com/nim/benchmarking/llm/metrics) (via search summary)
- An IETF Internet-Draft (Aug 2026) notes inconsistent use of "throughput," "latency," and "tokens per second" across implementations and proposes shared terminology. It is still a draft — [IETF draft-gaikwad-llm-benchmarking-terminology-01](https://datatracker.ietf.org/doc/html/draft-gaikwad-llm-benchmarking-terminology-01)
- TTFT covers network round-trip, queue wait, and initial inference, and total latency − TTFT approximates generation time — [OneUptime blog](https://oneuptime.com/blog/post/2026-02-06-track-token-usage-prompt-costs-model-latency-opentelemetry/view)
- **Cache hit rate** as used in consoles: Anthropic defines cache rate as "the percentage of input tokens read from the cache" — [Claude Docs: Rate limits](https://platform.claude.com/docs/en/api/rate-limits). OpenAI exposes `input_cached_tokens` vs `input_tokens` — [OpenAI Usage API](https://developers.openai.com/api/docs/api-reference/usage). OpenRouter shows "cache hit rate" on Activity Overview — [OpenRouter Activity](https://openrouter.ai/docs/guides/features/activity.md)
- Amazon Bedrock added TTFT CloudWatch metrics, showing that hyperscalers now expose TTFT as a first-class operational metric — [AWS ML Blog](https://aws.amazon.com/blogs/machine-learning/improve-operational-visibility-for-inference-workloads-on-amazon-bedrock-with-new-cloudwatch-metrics-for-ttft-and-estimated-quota-consumption/) (title only seen in search)

### Inferences

#### Comparison matrix (what each console shows)

| Element | OpenAI | Anthropic Console | OpenRouter | TokenMe |
|---|---|---|---|---|
| Requests count | Yes (`num_model_requests`) | Implied via request charts; rate-limited count shown | Yes (Overview tile) | Not public |
| Tokens in/out | Yes, + cached/uncached, modality | Yes, input/output bar chart | Yes, prompt/completion/reasoning | Token counter on site only |
| Cost | Cost view, daily, by line item | Cost page, daily per month | Spend, blended $/M tokens | Not public |
| Cache hit rate | Data only (cached tokens) | Yes ("cache rate") | Yes (Overview) | Not public |
| Latency / TTFT / tok/s | Not shown | Not shown | Logs: latency, TTFT, throughput; Explore: tokens/sec | Not public |
| Percentiles (P50/P95) | No | No | Unverified (P50/P90/P99 per one summary) | Not public |
| Group by | project, API key, model, user, batch, service tier | model, date/time, API key; filter workspace | model, provider, API key, app, user (2 levels) | Not public |
| Time buckets | 1m / 1h / 1d (cost: 1d) | Month → day → hour/minute drill-down | Rollup control | Not public |
| Limits display | Per-model RPM/TPM table + tier ladder + "Upgrade tier"; project Limits page | Tier + RPM/ITPM/OTPM table; headroom charts vs limit; "Request tier increase" | Per-key credit limit + daily/weekly/monthly reset; free-tier daily request counter | Daily/weekly caps reported, no numbers |
| Reset clock | UTC | Token bucket (continuous); monthly spend at 00:00 UTC on the 1st | UTC (daily 00:00, weekly Monday, monthly 1st) | Unknown |
| Export | CSV export | CSV on both pages | CSV/PDF from Explore | Not public |
| Per-request logs | No | No | Yes (metadata by default; content opt-in) | Metadata only stored |

#### Recommended minimal set for a small self-hosted, CPU-only, Thai-facing console (inference from the above)
- **Observability page (aggregate, per API key, selectable 24h / 7d / 30d):**
  - Tiles: Requests (with error/429 count), Total tokens (in / out), P50 and P95 total request time, P50 and P95 TTFT, median decode speed (tok/s), and cache hit rate. Requests, tokens, and cache rate follow OpenRouter/Anthropic. TTFT and tok/s follow OpenRouter Logs. Percentiles are a small-provider addition, since none of the big three confirm them on the console.
  - One time-series chart (requests or tokens per hour/day) and one "by model" breakdown. That is enough: Anthropic and OpenAI both lead with a token bar chart.
  - A recent-requests table (metadata only, the TokenMe/OpenRouter-default privacy posture): time, model, key name, in/out tokens, TTFT, total time, tok/s, status.
- **Formulas to state on the page (per request, server-side timestamps):**
  - TTFT = t_first_token − t_request_received (includes queue + prefill, consistent with NVIDIA's definition).
  - Total request time = t_last_token − t_request_received.
  - Decode speed = (output_tokens − 1) / (t_last_token − t_first_token). This is 1/ITL by NVIDIA's formula and excludes prefill, which on CPU dominates for long prompts. Showing "per-request tok/s = output/e2e" instead would make CPU hardware look much slower for long prompts.
  - P50/P95 = nearest-rank percentile over the requests in the selected window. Show "—" when n < ~20 rather than a misleading percentile.
  - Cache hit rate = cached_prompt_tokens / total_prompt_tokens (Anthropic's definition).
- **Usage & limits page:**
  - Progress bars for daily / weekly / monthly token or credit allowance with "used / limit" and the reset time. This follows OpenRouter's `usage_daily/weekly/monthly` + `limit_reset` model.
  - A static limits table: concurrent requests, RPM, TPM, the same layout as the OpenAI/Anthropic per-model limit tables.
  - Headroom chart (optional): hourly peak TPM vs TPM limit, as on Anthropic's Usage page.
  - Show reset times in **Asia/Bangkok (UTC+7)**. All three big providers reset at UTC, and 00:00 UTC is 07:00 in Bangkok, so a "daily" reset at UTC midnight happens mid-morning for Thai users. Either reset at local midnight or label the reset time explicitly.
- **Error semantics to mirror:** 429 + `Retry-After` for RPM/TPM/concurrency, and a distinct error code for allowance exhausted (cf. Anthropic `enforced_spend_limit_reached` with no retry-after; OpenRouter 402 `openrouter_key_limit`). Return `x-ratelimit-limit-*`, `-remaining-*`, and `-reset-*` headers (the OpenAI naming that OpenAI-SDK users already parse).
- **Empty states:** none of the providers document theirs. Recommended: "ยังไม่มีคำขอในช่วงเวลานี้" (no requests in this period) plus the quick-start curl snippet and a link to the Playground. Percentile tiles should show "—" with a "need more requests" hint.

### Gaps
- None of the sources describe how the big consoles compute percentiles (nearest-rank vs interpolation) or their minimum sample sizes. The NVIDIA page fetched did not describe percentile computation.
- OpenRouter's exact throughput formula is undocumented in the pages reached.
- Not verified in this session, but worth checking for a CPU-only stack: llama.cpp's server is believed to return a per-request `timings` object (prompt token count/ms and predicted token count/ms/tokens-per-second, plus cached token count). If so, it could feed TTFT/decode/cache metrics directly without client-side timing. Confirm against the llama.cpp server README before relying on it.
- Empty-state designs for all providers are undocumented in public sources.
