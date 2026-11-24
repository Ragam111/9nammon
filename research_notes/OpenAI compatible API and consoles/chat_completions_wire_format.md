# OpenAI Chat Completions wire format (POST /v1/chat/completions) for OpenAI-compatible servers

Sources were fetched on 2026-11-13: the OpenAI API reference (developers.openai.com, Markdown version via `.md` suffix; platform.openai.com returned HTTP 403), plus `main`/`master` source of openai-python and openai-node. Note: the 2026 docs list newer models (`gpt-6-astra`, `gpt-5.x`) and newer fields (`prompt_cache_options`, `moderation`, `service_tier: "fast"`) that older compatible servers will not know about.

## Request body fields a minimal compatible server must accept, and which can be ignored

### Takeaway
Only `model` and `messages` are required. A minimal server should parse `messages` (string or content-part array content), `stream`, `stream_options.include_usage`, `temperature`, `top_p`, both `max_tokens` and `max_completion_tokens`, `stop` (string or array), and `n`. It should silently accept and ignore any unknown or unsupported field, because the official SDKs send whatever the caller passes. `max_tokens`, `functions`/`function_call` and `user` are deprecated but still sent by many clients.

### Cited Findings
- Required: `messages: array of ChatCompletionMessageParam` (`minItems: 1`) and `model: string` (or a listed enum such as `"gpt-6-astra"`). — [OpenAI API ref: Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- Message roles and shapes:
  - `developer {content, role:"developer", name?}`
  - `system {content, role:"system", name?}`. For both of these, `content` is a string or an array of text parts.
  - `user {content, role:"user", name?}`, where `content` is a string or an array of `ChatCompletionContentPart`.
  - `assistant {role:"assistant", content? (string | text/refusal parts | null), refusal?, tool_calls?, function_call? (deprecated), audio?, name?}`
  - `tool {content, role:"tool", tool_call_id}`
  - `function {content, name, role:"function"}` (legacy)
  — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- User content parts:
  - text: `{type:"text", text}`
  - image: `{type:"image_url", image_url:{url, detail? "auto"|"low"|"high"|"original", default "auto"}}`
  - audio: `{type:"input_audio", input_audio:{data, format:"wav"|"mp3"}}`
  - file: `{type:"file", file:{file_data?|file_id?, filename?}}`
  - New in 2026: each part may carry an optional `prompt_cache_breakpoint` object. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md); [openai-python chat_completion_content_part_param.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_content_part_param.py)
- Docs example of a content-part array:
  ```json
  {"role":"user","content":[{"type":"text","text":"What is in this image?"},{"type":"image_url","image_url":{"url":"https://..."}}]}
  ```
  The same example also sets `"max_tokens": 300`. — [OpenAI API ref, "Image input" example](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- `max_completion_tokens: optional integer or null` is "an upper bound … including visible output tokens and reasoning tokens". `max_tokens` "is now deprecated in favor of `max_completion_tokens`, and is not compatible with o-series models". — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- `n: optional integer or null (default: 1)`, `minimum: 1`, `maximum: 128`. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- `stop: optional string or array of string or null`, "Up to 4 sequences". The returned text does not contain the stop sequence. Not supported with `o3`/`o4-mini`. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- `temperature: optional number or null (default: 1)`, range 0–2. `top_p: optional number or null (default: 1)`, range 0–1. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- `stream: optional boolean or null (default: false)` streams via server-sent events. `stream_options` should be set "only … when you set `stream: true`". It contains `include_usage: bool` and `include_obfuscation: bool`. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md); [openai-python chat_completion_stream_options_param.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_stream_options_param.py)
- `user: optional string or null` "is being replaced by `safety_identifier` and `prompt_cache_key`". — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- Deprecated fields still in the spec:
  - `function_call` ("Deprecated in favor of `tool_choice`")
  - `functions` ("Deprecated in favor of `tools`")
  - `prompt_cache_retention` (deprecated in favor of `prompt_cache_options.ttl`)
  — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- Other optional fields a server may ignore: `audio`, `frequency_penalty`, `logit_bias`, `logprobs`, `top_logprobs`, `metadata`, `modalities`, `moderation`, `parallel_tool_calls`, `prediction`, `presence_penalty`, `prompt_cache_key`, `prompt_cache_options`, `reasoning_effort` (`none`…`max`), `response_format`, `safety_identifier`, `seed`, `service_tier`, `store`, `tool_choice`, `tools`, `verbosity`, `web_search_options`. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- How established compatible servers handle fields:
  - Ollama `/v1/chat/completions` supports `model`, `messages`, `frequency_penalty`, `presence_penalty`, `response_format`, `seed`, `stop`, `stream`, `stream_options` (`include_usage`), `temperature`, `top_p`, `max_tokens`, `tools`, `reasoning_effort` and `reasoning`.
  - Ollama does not support `tool_choice`, `logit_bias`, `user`, `n`, image URLs (only base64 images) or logprobs.
  - vLLM: "`user` parameter is ignored", and the model needs a chat template or "all chat requests will error".
  — [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility); [vLLM online serving](https://docs.vllm.ai/en/latest/serving/online_serving/)

### Inferences
- Accept both `max_tokens` and `max_completion_tokens`, and treat whichever is present as the generation limit; newer SDK users and agent frameworks send `max_completion_tokens`. Ollama's documented support for only `max_tokens` shows that partial support is common in practice.
- Flatten content-part arrays to text for text-only backends (concatenate the `text` parts). Reject unsupported part types with a 400 rather than crashing, or ignore them.
- Treat `developer` the same as `system` for backends that do not know the role. Current SDK examples use `developer`.
- Ignore unknown fields (no strict schema validation). Otherwise newer SDK versions that send new fields would break. Ollama and vLLM show that silently ignoring `user` and similar fields is accepted practice.

### Gaps
- The full vLLM list of supported and unsupported chat parameters, `extra_body` usage and `--api-key` behaviour were not retrieved. The detailed vLLM subpage (https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/#chat-api) was not fetched.

## Non-streaming response object

### Takeaway
Return `{id, object:"chat.completion", created, model, choices:[{index, message:{role:"assistant", content, refusal?}, logprobs, finish_reason}], usage:{prompt_tokens, completion_tokens, total_tokens}}` with `Content-Type: application/json`. `system_fingerprint`, `service_tier`, the `*_details` usage breakdowns and `annotations` are optional.

### Cited Findings
- Docs response example (verbatim):
  ```json
  {
    "id": "chatcmpl-B9MBs8CjcvOU2jLn4n570S5qMJKcT",
    "object": "chat.completion",
    "created": 1741569952,
    "model": "gpt-6-astra",
    "choices": [
      {
        "index": 0,
        "message": {
          "role": "assistant",
          "content": "Hello! How can I assist you today?",
          "refusal": null,
          "annotations": []
        },
        "logprobs": null,
        "finish_reason": "stop"
      }
    ],
    "usage": {
      "prompt_tokens": 19,
      "completion_tokens": 10,
      "total_tokens": 29,
      "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 0},
      "completion_tokens_details": {"reasoning_tokens": 0, "audio_tokens": 0, "accepted_prediction_tokens": 0, "rejected_prediction_tokens": 0}
    },
    "service_tier": "default"
  }
  ```
  — [OpenAI API ref, Example](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- SDK model `ChatCompletion`:
  - Required: `id: str`, `choices: List[Choice]`, `created: int` ("Unix timestamp (in seconds)"), `model: str`, `object: Literal["chat.completion"]`.
  - Optional: `metadata`, `moderation`, `service_tier` (`auto|default|flex|scale|priority|fast`), `system_fingerprint: str`, `usage: CompletionUsage`.
  — [openai-python chat_completion.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion.py)
- `Choice` has `finish_reason: Literal["stop","length","tool_calls","content_filter","function_call"]` (required; `function_call` is deprecated), `index: int`, `logprobs: Optional`, and `message: ChatCompletionMessage`. — [openai-python chat_completion.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion.py)
- `ChatCompletionMessage` has `role: Literal["assistant"]` (required), plus optional `content: str|None`, `refusal`, `annotations` (`url_citation`), `audio`, `tool_calls`, and `function_call` ("Deprecated and replaced by `tool_calls`"). — [openai-python chat_completion_message.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_message.py)
- `CompletionUsage` has `completion_tokens: int`, `prompt_tokens: int` and `total_tokens: int` (required). It also has optional `completion_tokens_details` (`reasoning_tokens`, `audio_tokens`, `accepted_prediction_tokens`, `rejected_prediction_tokens`, `text_tokens`) and `prompt_tokens_details` (`cached_tokens`, `audio_tokens`, `image_tokens`, `text_tokens`, `cache_write_tokens`). — [openai-python completion_usage.py](https://github.com/openai/openai-python/blob/main/src/openai/types/completion_usage.py)
- The `id` prefix in all official examples is `chatcmpl-`. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- Content-type handling in the Python SDK: if the response content-type does not end with `json`, it still tries `response.json()` for model types. It raises only when `_strict_response_validation` is on, with the message "Expected Content-Type response header to be `application/json`…". — [openai-python _response.py](https://github.com/openai/openai-python/blob/main/src/openai/_response.py)
- The Node SDK parses a body as JSON when the media type includes `application/json` or ends with `+json`. — [openai-node parse.ts](https://github.com/openai/openai-node/blob/master/src/internal/parse.ts)

### Inferences
- `chatcmpl-` is a convention, not validated by the SDKs (`id: str`). Using it maximises compatibility with tools that pattern-match on it.
- Always send `Content-Type: application/json` on non-streaming responses. Node parses the body as JSON only when the media type includes `application/json` or ends with `+json` ([parse.ts](https://github.com/openai/openai-node/blob/master/src/internal/parse.ts)), so a different type would likely break it.
- `system_fingerprint` can be omitted or set to `null`, because it is `Optional` in the SDK model.

### Gaps
- The HTTP error body schema was not fully traced. The Python SDK reads `code`, `param` and `type` from the error body, and the streaming code reads `error.message` ([_exceptions.py](https://github.com/openai/openai-python/blob/main/src/openai/_exceptions.py), [_streaming.py](https://github.com/openai/openai-python/blob/main/src/openai/_streaming.py)). That is consistent with `{"error":{"message","type","param","code"}}`, but no docs page stating that envelope was fetched.

## Streaming (SSE)

### Takeaway
With `stream:true`, send one event per chunk in the form `data: <json>\n\n`, where each chunk has `object:"chat.completion.chunk"` and the same `id`. The first chunk carries `delta:{"role":"assistant","content":""}`, middle chunks carry `delta:{"content":"..."}`, and the last choice chunk has `delta:{}` plus `finish_reason`. If `include_usage` is set, add a usage chunk with `choices:[]`. End with `data: [DONE]\n\n`. Both SDKs stop cleanly at `[DONE]`. If it is missing, they end iteration silently with no error, but the final event is lost if it is not terminated by a blank line.

### Cited Findings
- Docs streaming response example (verbatim, including the SSE comment line):
  ```
  data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1694268190,"model":"gpt-6-astra", "system_fingerprint": "fp_44709d6fcb", "choices":[{"index":0,"delta":{"role":"assistant","content":""},"logprobs":null,"finish_reason":null}]}

  data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1694268190,"model":"gpt-6-astra", "system_fingerprint": "fp_44709d6fcb", "choices":[{"index":0,"delta":{"content":"Hello"},"logprobs":null,"finish_reason":null}]}

  : Intermediate chat completion chunks omitted.

  data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1694268190,"model":"gpt-6-astra", "system_fingerprint": "fp_44709d6fcb", "choices":[{"index":0,"delta":{},"logprobs":null,"finish_reason":"stop"}]}

  data: [DONE]
  ```
  — [OpenAI API ref, Streaming example](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- `ChatCompletionChunk`:
  - Required: `id` ("Each chunk has the same ID"), `choices`, `created`, `model`, `object: Literal["chat.completion.chunk"]`.
  - Optional: `system_fingerprint`, `service_tier`, `usage`, `obfuscation`, `moderation`.
  - `Choice` requires `delta` and `index`; `finish_reason` and `logprobs` are optional.
  - In `ChoiceDelta`, every field is optional (`role`, `content`, `refusal`, `tool_calls`, `function_call`, `audio`).
  - In `ChoiceDeltaToolCall`, `index` is required; `id`, `type` and `function` are optional.
  — [openai-python chat_completion_chunk.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_chunk.py)
- `include_usage`: "an additional chunk will be streamed before the `data: [DONE]` message. The `usage` field on this chunk shows the token usage statistics for the entire request, and the `choices` field will always be an empty array. All other chunks will also include a `usage` field, but with a null value." If the stream is interrupted, the usage chunk may be missing. — [openai-python chat_completion_stream_options_param.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_stream_options_param.py)
- `include_obfuscation`: random padding is added in an `obfuscation` field "by default". The field is `Optional[str]` in the SDK chunk model. — [stream_options_param.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_stream_options_param.py); [chat_completion_chunk.py](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_chunk.py)
- Python `Stream.__stream__`:
  - It does `if sse.data.startswith("[DONE]"): break`.
  - Any event whose JSON has a non-empty `error` raises `APIError` (message = `error.message`, or "An error occurred during streaming").
  - There is no check after the loop, so a stream that ends without `[DONE]` just stops iterating.
  - The `finally:` block closes the response.
  — [openai-python _streaming.py](https://github.com/openai/openai-python/blob/main/src/openai/_streaming.py)
- Python `SSEDecoder.decode` follows the WHATWG SSE spec:
  - It dispatches an event only on an empty line and joins multiple `data:` lines with `\n`.
  - It ignores `:` comment lines and strips one leading space after `data:`.
  - `iter_bytes` feeds a final `finish()`, but with no trailing blank line the last buffered event is never dispatched.
  — [openai-python _streaming.py](https://github.com/openai/openai-python/blob/main/src/openai/_streaming.py)
- Node `Stream.fromSSEResponse`:
  - It does `if (sse.data === '[DONE]') { receivedCompletionSentinel = true; break; }` (exact equality, unlike Python's `startswith`).
  - Bad JSON throws `SyntaxError('Error reading response: malformed server-sent event JSON.')`.
  - `sse.event === 'error'` or `data.error` throws `APIError`.
  - If the body ends without `[DONE]`, the loop ends normally (`done = true`) and no error is thrown.
  — [openai-node streaming.ts](https://github.com/openai/openai-node/blob/master/src/core/streaming.ts)
- The Node `LineDecoder` "Supports `\n`, `\r`, and `\r\n` line endings". — [openai-node line.ts](https://github.com/openai/openai-node/blob/master/src/internal/decoders/line.ts)
- Both SDKs choose the SSE parser from the request option, not the response header:
  - Node: `if (props.options.stream)` calls `fromSSEResponse`.
  - Python: `self._is_sse_stream = stream`.
  — [openai-node parse.ts](https://github.com/openai/openai-node/blob/master/src/internal/parse.ts); [openai-python _response.py](https://github.com/openai/openai-python/blob/main/src/openai/_response.py)
- The docs say `stream: true` uses "server-sent events" and link to the MDN Event stream format. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)

### Inferences
- Send the header `Content-Type: text/event-stream`. This is the SSE standard that the docs link to; the SDKs don't check it, but browsers' EventSource and generic SSE clients do. Also send `Cache-Control: no-cache`, and flush after every event.
- Emit exactly `data: [DONE]` (no trailing text). Node compares with `===`, so `[DONE]` must be the entire data value. Always end every event, including `[DONE]`, with a blank line (`\n\n`).
- Not sending `[DONE]` does not raise an error in either SDK. However, curl/bash consumers and other libraries (e.g. LangChain-style parsers) may hang or wait for it, so always send it.
- Mid-stream errors: send `data: {"error":{"message":"...","type":"...","code":...}}\n\n`. Both SDKs raise `APIError` on this. HTTP status errors must be returned before streaming begins.
- Usage-chunk shape, derived from the docstring rather than a verbatim docs example:
  ```
  {"id":"chatcmpl-…","object":"chat.completion.chunk","created":…,"model":"…","choices":[],"usage":{"prompt_tokens":…,"completion_tokens":…,"total_tokens":…}}
  ```
  Clients iterating `chunk.choices[0]` must guard against the empty array.
- For `n>1`, each choice streams with its own `index`. For tool calls, `delta.tool_calls[]` items are keyed by `index`, with `id`/`function.name` in the first fragment and `function.arguments` streamed as string pieces.

### Gaps
- No verbatim OpenAI docs example of the `include_usage` final chunk was retrieved; the shape above is assembled from SDK docstrings.
- The `Content-Type` header that api.openai.com actually returns for streams was not observed on the wire in this session.
- The streaming-events reference page (`/api/reference/resources/chat/subresources/completions/streaming-events`) was not fetched separately.

## Required headers and auth

### Takeaway
Clients send `Authorization: Bearer <key>` and `Content-Type: application/json`. The SDKs also add optional `OpenAI-Organization`, `OpenAI-Project`, `X-Stainless-*`, `Accept` and `User-Agent` headers, which a server should ignore. Local servers often accept any key, but the SDK requires a non-empty one.

### Cited Findings
- The docs curl example uses `-H "Content-Type: application/json"`, `-H "Authorization: Bearer $OPENAI_API_KEY"` and `curl https://api.openai.com/v1/chat/completions`. — [OpenAI API ref](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create.md)
- The Python SDK sets `{"Authorization": f"Bearer {api_key}"}` (key from `OPENAI_API_KEY`). — [openai-python lib/_client_auth.py](https://github.com/openai/openai-python/blob/main/src/openai/lib/_client_auth.py)
- The Python SDK adds `OpenAI-Organization`/`OpenAI-Project` only when they are configured. — [openai-python _client.py](https://github.com/openai/openai-python/blob/main/src/openai/_client.py)
- Default Python SDK headers:
  - `Accept: application/json` and `User-Agent`
  - `X-Stainless-Lang`, `-Package-Version`, `-OS`, `-Arch`, `-Runtime`, `-Runtime-Version`
  - `x-stainless-retry-count` and `x-stainless-read-timeout`
  — [openai-python _base_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py)
- Retry headers the Python SDK honours: `retry-after-ms`, `retry-after` (seconds or an HTTP date) and `x-should-retry` (`true`/`false`). — [openai-python _base_client.py](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py)
- Ollama: base URL `http://localhost:11434/v1/`; the api_key is "required but ignored" for local use. — [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)

### Inferences
- The path is `/v1/chat/completions` because the SDK `base_url` normally ends in `/v1` and the SDK appends `/chat/completions`. Mount the route under `/v1`, and optionally also at `/chat/completions` for clients configured without `/v1`.
- Return 401 with a JSON `error` envelope for bad keys. Sending `x-should-retry: false` on non-retryable errors stops SDK retries.
- Do not reject requests that carry unknown `X-Stainless-*` or `OpenAI-*` headers. Allow `Authorization` in CORS if browsers will call the server.

### Gaps
- vLLM `--api-key` / `VLLM_API_KEY` behaviour was not verified from primary docs in this session.
