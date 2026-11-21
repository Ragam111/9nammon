"""The JSON message format both agents must reply with. Anything else is rejected and the model is asked again."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MESSAGE_TYPES = frozenset({"tool", "claim", "request", "final"})
SCOUT_TYPES = frozenset({"tool", "claim"})
CRITIC_TYPES = frozenset({"request", "final"})
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class ProtocolError(ValueError):
    """The reply was not one JSON object of an allowed shape."""


@dataclass(frozen=True)
class Message:
    type: str
    content: str = ""
    sources: tuple[str, ...] = ()
    call: dict[str, Any] | None = field(default=None)


def parse_message(raw: str) -> Message:
    text = _FENCE.sub("", raw.strip()).strip()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProtocolError("ตอบเป็น JSON object เดียว ไม่มีข้อความอื่นนอก JSON") from exc
    if not isinstance(data, dict):
        raise ProtocolError("ต้องเป็น JSON object")
    mtype = data.get("type")
    if mtype not in MESSAGE_TYPES:
        raise ProtocolError(f"type ต้องเป็นหนึ่งใน {sorted(MESSAGE_TYPES)}")
    sources = data.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise ProtocolError("sources ต้องเป็นรายการ string")
    content = str(data.get("content", ""))
    if mtype != "tool" and not content.strip():
        raise ProtocolError("content ต้องไม่ว่าง")
    call = data.get("call")
    if mtype == "tool" and not isinstance(call, dict):
        raise ProtocolError("type tool ต้องมี call เป็น object")
    return Message(
        type=str(mtype),
        content=content,
        sources=tuple(s.strip() for s in sources),
        call=call if mtype == "tool" else None,
    )


def check_type(msg: Message, allowed: frozenset[str]) -> Message:
    if msg.type not in allowed:
        raise ProtocolError(f"type {msg.type!r} ใช้ในบทบาทนี้ไม่ได้ ใช้ได้เฉพาะ {sorted(allowed)}")
    return msg
