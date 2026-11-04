"""One transcript shape for every provider.

A conversation is a list of messages::

    {"role": "system" | "user" | "assistant", "content": "<text>"}

``content`` may also be a list of text parts (``{"type": "text", "text": "..."}``).
Image and audio parts raise ``ProviderError`` so they are not dropped silently.
The role ``model`` (Gemini) is accepted and stored as ``assistant``.

Anthropic and Gemini require alternating user/assistant turns and a user turn
first. Converters merge consecutive same-role turns with a newline and, when a
transcript starts with an assistant turn, insert a user turn whose text is
``(continued)``. OpenAI, xAI, Ollama, and OpenAI-compatible endpoints keep the
original turns, including ``system``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.errors import ProviderError

ROLES = ("system", "user", "assistant")
_ROLE_ALIASES = {"model": "assistant"}
CONTINUED = "(continued)"


@dataclass(frozen=True)
class Message:
    role: str
    content: str


def _text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
                continue
            if isinstance(part, dict):
                kind = part.get("type")
                if kind in (None, "text", "output_text", "input_text") and "text" in part:
                    chunks.append(str(part.get("text") or ""))
                    continue
            raise ProviderError("only text message parts are supported")
        return "".join(chunks)
    raise ProviderError("message content must be a string or a list of text parts")


def normalize_messages(messages) -> list[Message]:
    """Copy ``messages`` into ``Message`` objects. The input list is not changed."""
    if isinstance(messages, Message):
        messages = [messages]
    if not isinstance(messages, (list, tuple)):
        raise ProviderError("messages must be a list")
    if not messages:
        raise ProviderError("messages is empty")
    out: list[Message] = []
    for index, item in enumerate(messages):
        if isinstance(item, Message):
            role, content = item.role, item.content
        elif isinstance(item, dict):
            role, content = item.get("role"), item.get("content")
        else:
            raise ProviderError(f"message {index} must be a dict with role and content")
        if not isinstance(role, str):
            raise ProviderError(f"message {index} is missing a role")
        role = _ROLE_ALIASES.get(role.strip().lower(), role.strip().lower())
        if role not in ROLES:
            raise ProviderError(f"message {index} has unsupported role {role!r}")
        text = _text_content("" if content is None else content)
        out.append(Message(role, text))
    return out


def prepare_messages(messages, system: str | None = None) -> list[Message]:
    """Normalize, then prepend ``system`` when the caller passed one."""
    msgs = normalize_messages(messages)
    if system is not None:
        if not isinstance(system, str):
            raise ProviderError("system must be a string")
        msgs = [Message("system", system)] + msgs
    if not any(m.role in ("user", "assistant") for m in msgs):
        raise ProviderError("conversation needs a user or assistant message")
    return msgs


def _merge_turns(turns: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for turn in turns:
        if merged and merged[-1]["role"] == turn["role"]:
            merged[-1]["content"] = merged[-1]["content"] + "\n" + turn["content"]
        else:
            merged.append({"role": turn["role"], "content": turn["content"]})
    return merged


def to_openai_messages(messages: list[Message]) -> list[dict]:
    """OpenAI Chat Completions, Responses ``input``, xAI, Ollama, and compat."""
    return [{"role": m.role, "content": m.content} for m in messages]


def to_anthropic(messages: list[Message]) -> tuple[str, list[dict]]:
    """Return ``(system, messages)``. System is a top-level string, not a turn."""
    systems = [m.content for m in messages if m.role == "system" and m.content]
    turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
    turns = _merge_turns(turns)
    if turns and turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": CONTINUED})
    return "\n\n".join(systems), turns


def to_gemini(messages: list[Message]) -> tuple[str, list[dict]]:
    """Return ``(system_text, contents)`` with Gemini roles ``user`` and ``model``."""
    systems = [m.content for m in messages if m.role == "system" and m.content]
    turns = []
    for m in messages:
        if m.role == "system":
            continue
        role = "model" if m.role == "assistant" else "user"
        turns.append({"role": role, "content": m.content})
    turns = _merge_turns(turns)
    if turns and turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": CONTINUED})
    contents = [
        {"role": t["role"], "parts": [{"text": t["content"]}]}
        for t in turns
    ]
    return "\n\n".join(systems), contents
