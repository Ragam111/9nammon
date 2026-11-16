"""Editable USD price table for a cost *estimate*.

Every number below is a configurable default copied from a public price page
on 2026-11-03. It is not an invoice, not a cache/batch/long-context rate, and
not a regional premium. If a model is missing, or the published rate depends
on a threshold this table does not apply, ``lookup_price`` returns ``None``
and the cost estimate is ``None``.

Operators can replace a row at runtime with ``register_price`` or by passing
``price_table=`` into ``chat`` / ``stream``. Do not invent a number to fill a
gap — leave the row out.

Ollama's row is 0 USD per token because the Ollama HTTP API has no meter.
That is not a claim that electricity or hardware is free.

Sources (checked 2026-11-03):

* Anthropic standard base rates — https://platform.claude.com/docs/en/about-claude/pricing
* OpenAI standard short-context text rates — https://developers.openai.com/api/docs/pricing
* Gemini paid standard text rates — https://ai.google.dev/gemini-api/docs/pricing
* xAI global-endpoint short-context text rates — https://docs.x.ai/developers/pricing

Rates are USD per 1,000,000 tokens (input, output).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

CHECKED_ON = "2026-11-03"

PRICE_NOTE = (
    "Configurable default from the provider's public price page, not an invoice. "
    "Standard text rates only: prompt cache, batch, long context, audio, images, "
    "and regional premiums are not applied. Edit PRICES or pass price_table=."
)

ANTHROPIC_SOURCE = (
    "https://platform.claude.com/docs/en/about-claude/pricing "
    f"(checked {CHECKED_ON}, standard base input/output, USD per 1M tokens)"
)
OPENAI_SOURCE = (
    "https://developers.openai.com/api/docs/pricing "
    f"(checked {CHECKED_ON}, standard short-context input/output, USD per 1M tokens)"
)
GEMINI_SOURCE = (
    "https://ai.google.dev/gemini-api/docs/pricing "
    f"(checked {CHECKED_ON}, paid standard text input/output, USD per 1M tokens)"
)
XAI_SOURCE = (
    "https://docs.x.ai/developers/pricing "
    f"(checked {CHECKED_ON}, global endpoint, short-context input/output, USD per 1M tokens)"
)
OLLAMA_SOURCE = (
    "Ollama HTTP API has no token meter (local runtime). "
    "0 is the API price only. Electricity and hardware are not estimated."
)


@dataclass(frozen=True)
class Price:
    """USD per 1,000,000 tokens. ``source`` says where the number came from."""

    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    source: str


@dataclass(frozen=True)
class CostEstimate:
    usd: Decimal | None
    input_usd_per_mtok: Decimal | None
    output_usd_per_mtok: Decimal | None
    currency: str
    estimated: bool
    authoritative: bool
    source: str | None
    note: str


def _price(inp: str, out: str, source: str, extra: str = "") -> Price:
    text = source if not extra else f"{source} {extra}"
    return Price(Decimal(inp), Decimal(out), text)


# Keys are (provider, model id). A request for "<id>-<snapshot>" uses the
# longest matching id. There is no catch-all cloud price.
PRICES: dict[tuple[str, str], Price] = {
    # Anthropic. Haiku 5.5's page lists a second rate above 100k prompt tokens
    # ($0.50 / $2.50). This row is the up-to-100k rate only.
    ("anthropic", "claude-fable-5-1"): _price("10", "50", ANTHROPIC_SOURCE),
    ("anthropic", "claude-opus-5-5"): _price("4", "20", ANTHROPIC_SOURCE),
    ("anthropic", "claude-sonnet-5-5"): _price("2", "10", ANTHROPIC_SOURCE),
    ("anthropic", "claude-haiku-5-5"): _price(
        "0.10", "0.50", ANTHROPIC_SOURCE,
        "Up-to-100k prompt rate. Over 100k the page lists $0.50/$2.50; that tier is not selected automatically.",
    ),
    ("anthropic", "claude-sonnet-4-5"): _price("3", "15", ANTHROPIC_SOURCE),
    ("anthropic", "claude-haiku-4-5"): _price("1", "5", ANTHROPIC_SOURCE),
    # OpenAI short-context standard. gpt-5.4's long-context rate is higher and is not used here.
    ("openai", "gpt-5.4"): _price(
        "2.50", "15", OPENAI_SOURCE,
        "Short-context rate (page threshold 272k). The long-context rate is not selected automatically.",
    ),
    ("openai", "gpt-5.4-mini"): _price("0.75", "4.50", OPENAI_SOURCE),
    ("openai", "gpt-5-mini"): _price("0.25", "2", OPENAI_SOURCE),
    ("openai", "gpt-4.1"): _price("2", "8", OPENAI_SOURCE),
    ("openai", "gpt-4.1-mini"): _price("0.40", "1.60", OPENAI_SOURCE),
    ("openai", "gpt-4o"): _price("2.50", "10", OPENAI_SOURCE),
    ("openai", "gpt-4o-mini"): _price("0.15", "0.60", OPENAI_SOURCE),
    # Gemini paid standard, text, prompts at or under the page's 200k tier where one exists.
    ("gemini", "gemini-4-argon"): _price(
        "2", "10", GEMINI_SOURCE,
        "Paid standard rate the page lists through 2026-11-30 ($4/$20 starting 2026-12-01). Edit this row when that date passes.",
    ),
    ("gemini", "gemini-3.1-pro-preview"): _price(
        "2", "12", GEMINI_SOURCE,
        "Prompts <= 200k. Above 200k the page lists $4/$18; that tier is not selected automatically.",
    ),
    ("gemini", "gemini-3-flash-preview"): _price(
        "0.50", "3", GEMINI_SOURCE,
        "Text/image/video input. Audio is a different rate and is not used here.",
    ),
    ("gemini", "gemini-2.5-pro"): _price(
        "1.25", "10", GEMINI_SOURCE,
        "Prompts <= 200k. The page says this model routes to gemini-3.8-flash on 2026-12-01; that model's price is not in this table.",
    ),
    ("gemini", "gemini-2.5-flash"): _price(
        "0.30", "2.50", GEMINI_SOURCE,
        "Text/image/video input. Audio is $1 / 1M on the page and is not used here.",
    ),
    # xAI global endpoint, under the 200k long-context threshold.
    ("xai", "grok-4.7"): _price(
        "2", "6", XAI_SOURCE,
        "Short context. At >= 200k prompt tokens the page lists $4/$12; that tier is not selected automatically.",
    ),
    ("xai", "grok-4.3"): _price(
        "1.25", "2.50", XAI_SOURCE,
        "Short context. At >= 200k the page lists $2.50/$5; that tier is not selected automatically.",
    ),
    ("xai", "grok-4.20-0309-reasoning"): _price("1.25", "2.50", XAI_SOURCE),
    # Local. Any Ollama model id matches via lookup_price, not this wildcard key,
    # so a custom table can override a single model without inheriting 0.
    ("ollama", "*"): _price("0", "0", OLLAMA_SOURCE),
}


def register_price(
    provider: str,
    model: str,
    input_usd_per_mtok,
    output_usd_per_mtok,
    source: str,
) -> Price:
    """Insert or replace one default row. ``source`` should say where the number came from."""
    if not source or not str(source).strip():
        raise ValueError("price source is required")
    price = Price(Decimal(str(input_usd_per_mtok)), Decimal(str(output_usd_per_mtok)), str(source).strip())
    PRICES[(provider, model)] = price
    return price


def unregister_price(provider: str, model: str) -> None:
    PRICES.pop((provider, model), None)


def _model_key(model: str) -> str:
    model = (model or "").strip()
    if model.startswith("models/"):
        model = model[len("models/"):]
    return model


def lookup_price(
    provider: str,
    model: str,
    table: Mapping[tuple[str, str], Price] | None = None,
) -> Price | None:
    """Return the row for ``provider``/``model``, or ``None`` when we have no source."""
    rows = PRICES if table is None else table
    provider = (provider or "").strip().lower()
    model = _model_key(model)
    exact = rows.get((provider, model))
    if exact is not None:
        return exact
    best: Price | None = None
    best_len = -1
    wildcard: Price | None = None
    for (prov, mid), price in rows.items():
        if prov != provider:
            continue
        if mid == "*":
            wildcard = price
            continue
        if model.startswith(mid + "-") or model.startswith(mid + "."):
            if len(mid) > best_len:
                best = price
                best_len = len(mid)
    if best is not None:
        return best
    if provider == "ollama" and table is None:
        return rows.get(("ollama", "*"))
    return wildcard


def estimate_tokens(text: str) -> int:
    """Fallback size when a provider omits a count.

    Uses the common English rule of thumb of about 4 characters per token.
    Thai and other scripts often tokenize differently. The result is an
    estimate (``Usage.estimated`` is set), not a provider count.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_message_tokens(messages) -> int:
    total = 0
    for message in messages:
        content = message.content if hasattr(message, "content") else ""
        total += estimate_tokens(content or "")
    return total


def estimate_cost(provider: str, model: str, usage, table=None) -> CostEstimate:
    """USD estimate from ``usage`` and the price table. ``authoritative`` is always false."""
    price = lookup_price(provider, model, table)
    note = PRICE_NOTE
    if price is None or usage is None:
        return CostEstimate(
            usd=None,
            input_usd_per_mtok=None,
            output_usd_per_mtok=None,
            currency="USD",
            estimated=True,
            authoritative=False,
            source=None,
            note=note + " No price row for this provider and model.",
        )
    in_tokens = usage.input_tokens
    out_tokens = usage.output_tokens
    if in_tokens is None or out_tokens is None:
        return CostEstimate(
            usd=None,
            input_usd_per_mtok=price.input_usd_per_mtok,
            output_usd_per_mtok=price.output_usd_per_mtok,
            currency="USD",
            estimated=True,
            authoritative=False,
            source=price.source,
            note=note + " Token counts were incomplete, so no USD figure was produced.",
        )
    usd = (
        Decimal(in_tokens) * price.input_usd_per_mtok
        + Decimal(out_tokens) * price.output_usd_per_mtok
    ) / Decimal(1_000_000)
    return CostEstimate(
        usd=usd,
        input_usd_per_mtok=price.input_usd_per_mtok,
        output_usd_per_mtok=price.output_usd_per_mtok,
        currency="USD",
        estimated=bool(usage.estimated),
        authoritative=False,
        source=price.source,
        note=note,
    )
