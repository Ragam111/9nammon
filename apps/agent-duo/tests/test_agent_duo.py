"""agent-duo: allowlist and argv building, message parsing, grounding, and the full Scout/Critic loop with fakes."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_duo.models import AnthropicClient, ModelError
from agent_duo.orchestrator import Orchestrator, Settings
from agent_duo.protocol import ProtocolError, parse_message
from agent_duo.tools import ToolCall, ToolError, call_from_dict, run_call, urls_in


class FakeModel:
    """Returns scripted replies in order and records what it was shown."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict[str, str]]] = []

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        self.seen.append(messages)
        if not self.replies:
            raise ModelError("script ran out")
        return self.replies.pop(0)


def fake_runner(stdout: str):  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


VIDEO_URL = "https://www.youtube.com/watch?v=abc123"
VIDEO_JSON = json.dumps({"ok": True, "items": [{"title": "demo", "url": VIDEO_URL}]})


class ToolTest(unittest.TestCase):
    def test_only_allowlisted_read_actions_build_argv(self) -> None:
        argv = ToolCall("youtube", "subtitle", "https://www.youtube.com/watch?v=abc123").argv("agent-reach")
        self.assertEqual(argv, ["agent-reach", "youtube", "subtitle", "https://www.youtube.com/watch?v=abc123"])

    def test_paid_transcription_and_unknown_channels_are_refused(self) -> None:
        with self.assertRaises(ToolError):
            ToolCall("youtube", "transcribe", "x").validate()
        with self.assertRaises(ToolError):
            ToolCall("twitter", "search", "x").validate()

    def test_target_is_required_except_for_hot(self) -> None:
        with self.assertRaises(ToolError):
            ToolCall("youtube", "read", "").validate()
        ToolCall("v2ex", "hot").validate()

    def test_flag_like_target_and_bad_limit_are_refused(self) -> None:
        with self.assertRaises(ToolError):
            ToolCall("web", "read", "--output=/tmp/x").validate()
        with self.assertRaises(ToolError):
            ToolCall("web", "search", "q", limit=99).validate()

    def test_leading_space_cannot_smuggle_a_flag_past_the_guard(self) -> None:
        call = call_from_dict({"channel": "web", "action": "read", "target": " --output=C:/x.txt"})
        with self.assertRaises(ToolError):
            call.validate()

    def test_web_read_refuses_private_local_and_non_http_targets(self) -> None:
        for target in ("http://192.168.1.1/admin", "http://127.0.0.1:8080/", "file:///C:/Users/x",
                       "http://localhost/x", "http://printer.local/"):
            with self.assertRaises(ToolError, msg=target):
                ToolCall("web", "read", target).validate()
        ToolCall("web", "read", "https://en.wikipedia.org/wiki/Python").validate()

    def test_urls_keep_balanced_parentheses_and_drop_sentence_punctuation(self) -> None:
        found = urls_in({"text": "see https://en.wikipedia.org/wiki/Foo_(bar). and (https://x.test/a)"})
        self.assertIn("https://en.wikipedia.org/wiki/Foo_(bar)", found)
        self.assertIn("https://x.test/a", found)

    def test_failed_process_is_reported_as_not_ok(self) -> None:
        def failing(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 1, stdout='{"ok": false, "error": "x"}', stderr="")

        self.assertFalse(run_call(ToolCall("web", "search", "q"), runner=failing)["ok"])

    def test_limit_flag_only_for_actions_that_take_it(self) -> None:
        self.assertIn("--limit", ToolCall("web", "search", "q", 3).argv("ar"))
        self.assertNotIn("--limit", ToolCall("youtube", "subtitle", "x", 3).argv("ar"))

    def test_bad_call_shape_from_model_raises_tool_error_for_the_orchestrator_to_report(self) -> None:
        # call_from_dict is strict about types; a non-numeric limit is reported, not crashed on.
        with self.assertRaises(ToolError):
            call_from_dict({"channel": "web", "action": "search", "target": "q", "limit": "x"})
        result = run_call(ToolCall("web", "search", "q", limit=0))
        self.assertFalse(result["ok"])

    def test_runner_output_is_parsed_and_urls_are_extracted(self) -> None:
        runner = fake_runner(VIDEO_JSON)
        result = run_call(ToolCall("youtube", "search", "agent"), runner=runner)
        self.assertIn("https://www.youtube.com/watch?v=abc123", urls_in(result))
        self.assertEqual(runner.calls[0][:3], ["agent-reach", "youtube", "search"])  # type: ignore[attr-defined]

    def test_non_json_output_is_reported(self) -> None:
        result = run_call(ToolCall("web", "read", "https://example.com"), runner=fake_runner("not json"))
        self.assertFalse(result["ok"])


class ProtocolTest(unittest.TestCase):
    def test_accepts_plain_and_fenced_json(self) -> None:
        self.assertEqual(parse_message('{"type": "claim", "content": "ok", "sources": []}').type, "claim")
        self.assertEqual(parse_message('```json\n{"type": "final", "content": "x"}\n```').type, "final")

    def test_rejects_prose_unknown_type_and_bad_sources(self) -> None:
        for raw in ("hello", '{"type": "shell"}', '{"type": "claim", "sources": "x"}', '{"type": "tool"}'):
            with self.assertRaises(ProtocolError, msg=raw):
                parse_message(raw)


class AnthropicClientTest(unittest.TestCase):
    def test_empty_content_is_a_protocol_error(self) -> None:
        for raw in ('{"type": "request"}', '{"type": "final", "content": "  "}'):
            with self.assertRaises(ProtocolError, msg=raw):
                parse_message(raw)

    def test_empty_key_is_refused_before_any_call(self) -> None:
        with self.assertRaises(ModelError):
            AnthropicClient("", "claude-haiku-5-5")


class OrchestratorTest(unittest.TestCase):
    def _orchestrator(self, scout: list[str], critic: list[str], stdout: str = VIDEO_JSON,
                      transcript: Path | None = None) -> Orchestrator:
        return Orchestrator(FakeModel(scout), FakeModel(critic), Settings(max_rounds=4, max_tool_steps=2),
                            runner=fake_runner(stdout), transcript_path=transcript)

    def test_full_round_trip_ends_with_a_grounded_final_answer(self) -> None:
        scout = [
            json.dumps({"type": "tool",
                        "call": {"channel": "youtube", "action": "search", "target": "agent", "limit": 2}}),
            json.dumps({"type": "claim", "content": "พบคลิปเดโม", "sources": ["https://www.youtube.com/watch?v=abc123"]}),
        ]
        critic = [
            json.dumps({"type": "request", "content": "ค้นหาคลิปเดโม"}),
            json.dumps({"type": "final", "content": "มีคลิปเดโม 1 รายการ", "sources": ["https://www.youtube.com/watch?v=abc123"]}),
        ]
        result = self._orchestrator(scout, critic).run("หาคลิปเดโม")
        self.assertEqual(result.status, "final")
        self.assertEqual(result.sources, ["https://www.youtube.com/watch?v=abc123"])

    def test_final_answer_citing_an_unseen_url_is_rejected_and_critic_asks_again(self) -> None:
        scout = [json.dumps({"type": "claim", "content": "ไม่มีผลลัพธ์", "sources": []})]
        critic = [
            json.dumps({"type": "request", "content": "ลองใหม่"}),
            json.dumps({"type": "final", "content": "สรุป", "sources": ["https://invented.example/x"]}),
            json.dumps({"type": "final", "content": "ยังตรวจไม่ได้", "sources": []}),
        ]
        result = self._orchestrator(scout, critic).run("งาน")
        self.assertEqual(result.status, "final")
        self.assertEqual(result.sources, [])

    def test_final_from_the_last_allowed_critic_reply_is_not_discarded(self) -> None:
        scout = [
            json.dumps({"type": "tool", "call": {"channel": "youtube", "action": "search", "target": "x"}}),
            json.dumps({"type": "claim", "content": "พบ", "sources": [VIDEO_URL]}),
        ]
        critic = [
            json.dumps({"type": "request", "content": "ค้นหา"}),
            json.dumps({"type": "final", "content": "สรุป", "sources": [VIDEO_URL]}),
        ]
        orch = Orchestrator(FakeModel(scout), FakeModel(critic), Settings(max_rounds=2, max_tool_steps=1),
                            runner=fake_runner(VIDEO_JSON))
        self.assertEqual(orch.run("งาน").status, "final")

    def test_critic_sees_its_own_earlier_requests(self) -> None:
        scout = [json.dumps({"type": "claim", "content": "พบ", "sources": []})]
        critic_model = FakeModel([
            json.dumps({"type": "request", "content": "REQ-ONE"}),
            json.dumps({"type": "final", "content": "สรุป", "sources": []}),
        ])
        orch = Orchestrator(FakeModel(scout), critic_model, Settings(max_rounds=4, max_tool_steps=1),
                            runner=fake_runner(VIDEO_JSON))
        orch.run("งาน")
        second_call = json.dumps(critic_model.seen[1], ensure_ascii=False)
        self.assertIn("REQ-ONE", second_call)

    def test_url_only_in_final_text_is_grounding_checked(self) -> None:
        scout = [json.dumps({"type": "claim", "content": "x", "sources": []})]
        critic = [
            json.dumps({"type": "request", "content": "go"}),
            json.dumps({"type": "final", "content": "ดู https://invented.example/p", "sources": []}),
            json.dumps({"type": "final", "content": "ไม่มีแหล่ง", "sources": []}),
        ]
        result = self._orchestrator(scout, critic).run("งาน")
        self.assertEqual(result.status, "final")
        self.assertNotIn("invented", result.answer)

    def test_stops_at_max_rounds_without_a_final(self) -> None:
        scout = [json.dumps({"type": "claim", "content": "x", "sources": []})] * 10
        critic = [json.dumps({"type": "request", "content": "อีกที"})] * 10
        result = self._orchestrator(scout, critic).run("งาน")
        self.assertEqual(result.status, "max_rounds")

    def test_invalid_shape_gets_one_correction_then_errors(self) -> None:
        from agent_duo.orchestrator import OrchestratorError

        critic = ["ไม่ใช่ JSON", "ยังไม่ใช่ JSON"]
        with self.assertRaises(OrchestratorError):
            self._orchestrator([], critic).run("งาน")

    def test_transcript_is_written_as_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            scout = [json.dumps({"type": "claim", "content": "x", "sources": []})]
            critic = [
                json.dumps({"type": "request", "content": "go"}),
                json.dumps({"type": "final", "content": "done", "sources": []}),
            ]
            self._orchestrator(scout, critic, transcript=path).run("งาน")
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["agent"] for e in lines], ["critic", "scout", "critic"])


if __name__ == "__main__":
    unittest.main()
