"""Runs the Scout/Critic conversation: request -> Scout uses tools -> claim -> Critic -> request or final.

A final answer is accepted only if every URL it cites (sources and text) appeared in a real tool result.
Each event is also written to a JSONL transcript so a run can be read back afterwards.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ModelClient, ModelError
from .protocol import CRITIC_TYPES, SCOUT_TYPES, Message, ProtocolError, check_type, parse_message
from .roles import CRITIC_SYSTEM, SCOUT_SYSTEM
from .tools import Runner, ToolError, call_from_dict, default_runner, run_call, urls_in

MAX_PROTOCOL_RETRIES = 1


class OrchestratorError(RuntimeError):
    """A model reply stayed invalid after the retry, or a model call failed."""


@dataclass(frozen=True)
class Settings:
    max_rounds: int = 6  # counts Critic replies
    max_tool_steps: int = 4  # tool calls Scout may make in one turn
    binary: str = "agent-reach"


@dataclass
class Result:
    status: str  # "final" | "max_rounds"
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)


class Conversation:
    """One agent's view of the dialogue. Anthropic needs strictly alternating roles, so same-role turns are merged."""

    def __init__(self) -> None:
        self._items: list[tuple[str, str]] = []

    def add_user(self, text: str) -> None:
        self._append("user", text)

    def add_assistant(self, text: str) -> None:
        self._append("assistant", text)

    def _append(self, role: str, text: str) -> None:
        if self._items and self._items[-1][0] == role:
            self._items[-1] = (role, f"{self._items[-1][1]}\n\n{text}")
        else:
            self._items.append((role, text))

    def messages(self) -> list[dict[str, str]]:
        return [{"role": role, "content": text} for role, text in self._items]


class Orchestrator:
    def __init__(
        self,
        scout: ModelClient,
        critic: ModelClient,
        settings: Settings | None = None,
        runner: Runner = default_runner,
        transcript_path: Path | None = None,
    ) -> None:
        self.scout = scout
        self.critic = critic
        self.settings = settings or Settings()
        self.runner = runner
        self.transcript_path = transcript_path
        self.events: list[dict[str, Any]] = []

    def run(self, task: str) -> Result:
        """Every Critic reply is examined. Once the budget of Critic replies is spent, the run stops."""
        seen_urls: set[str] = set()
        critic_ctx = Conversation()
        critic_ctx.add_user(f"งานที่ต้องทำ:\n{task}\n\nเริ่มด้วยการสั่ง Scout ว่าควรดึงข้อมูลอะไร")
        critic_turns = 1
        request = self._critic_turn(critic_ctx)
        while True:
            if request.type == "final":
                problem = self._grounding_problem(request, seen_urls)
                if problem is None:
                    return Result("final", request.content, list(request.sources), list(self.events))
                critic_ctx.add_user(problem)
            else:
                if critic_turns >= self.settings.max_rounds:
                    break
                claim = self._scout_turn(request.content, seen_urls)
                critic_ctx.add_user(self._claim_text(claim, seen_urls))
            if critic_turns >= self.settings.max_rounds:
                break
            request = self._critic_turn(critic_ctx)
            critic_turns += 1
        return Result("max_rounds", "", [], list(self.events))

    def _critic_turn(self, ctx: Conversation) -> Message:
        msg, raw = self._ask(self.critic, ctx, "critic", CRITIC_TYPES)
        ctx.add_assistant(raw)
        self._log("critic", msg)
        return msg

    @staticmethod
    def _grounding_problem(msg: Message, seen_urls: set[str]) -> str | None:
        """None when every URL in the final answer (sources and text) came from a tool result."""
        cited = set(msg.sources) | urls_in({"content": msg.content})
        missing = sorted(cited - seen_urls)
        if not missing:
            return None
        return f"URL เหล่านี้ไม่มีในผลที่ Scout ดึงมา ห้ามใช้: {missing}. ขอข้อมูลใหม่หรือลบ URL นั้นออก"

    @staticmethod
    def _claim_text(claim: Message, seen_urls: set[str]) -> str:
        unseen = sorted(urls_in({"content": claim.content, "sources": list(claim.sources)}) - seen_urls)
        note = f"\nคำเตือน: URL ที่ไม่มีในผลเครื่องมือ อย่าใช้: {unseen}" if unseen else ""
        return f"Scout รายงาน:\n{claim.content}\nแหล่งที่อ้าง: {list(claim.sources)}{note}"

    def _scout_turn(self, request: str, seen_urls: set[str]) -> Message:
        """Let Scout call tools until it reports a claim or runs out of tool steps."""
        scout_ctx = Conversation()
        scout_ctx.add_user(request)
        for step in range(self.settings.max_tool_steps + 1):
            msg, raw = self._ask(self.scout, scout_ctx, "scout", SCOUT_TYPES)
            scout_ctx.add_assistant(raw)
            if msg.type == "claim":
                self._log("scout", msg)
                return msg
            if step == self.settings.max_tool_steps:
                break
            self._log("scout", msg)
            result = self._execute(msg.call or {})
            seen_urls |= urls_in(result)
            scout_ctx.add_user(f"ผลจากเครื่องมือ:\n{json.dumps(result, ensure_ascii=False)}")
        forced = Message("claim", "ดึงข้อมูลครบจำนวนครั้งที่กำหนดแล้วแต่ยังไม่ได้ข้อสรุป", ())
        self._log("scout", forced)
        return forced

    def _execute(self, raw_call: dict[str, Any]) -> dict[str, Any]:
        try:
            call = call_from_dict(raw_call)
        except ToolError as exc:
            return {"ok": False, "error": str(exc)}
        return run_call(call, self.settings.binary, self.runner)

    def _ask(self, client: ModelClient, ctx: Conversation, name: str, allowed: frozenset[str]) -> tuple[Message, str]:
        """Ask a model for one valid message. A bad shape gets one correction turn, then an error."""
        system = SCOUT_SYSTEM if name == "scout" else CRITIC_SYSTEM
        for _attempt in range(MAX_PROTOCOL_RETRIES + 1):
            try:
                raw = client.complete(system, ctx.messages())
            except ModelError as exc:
                raise OrchestratorError(str(exc)) from exc
            try:
                return check_type(parse_message(raw), allowed), raw
            except ProtocolError as exc:
                ctx.add_assistant(raw)
                ctx.add_user(f"รูปแบบไม่ถูกต้อง: {exc}. ตอบใหม่เป็น JSON object เดียวตามที่กำหนด")
        raise OrchestratorError(f"{name} ตอบรูปแบบไม่ถูกต้องซ้ำ")

    def _log(self, agent: str, msg: Message) -> None:
        event = {"ts": round(time.time(), 3), "agent": agent, "type": msg.type, "content": msg.content,
                 "sources": list(msg.sources), "call": msg.call}
        self.events.append(event)
        if self.transcript_path is not None:
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            with self.transcript_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
