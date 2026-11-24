# Changelog

## 2026-11-22 · First version

### Added
- `agent_duo/__init__.py`, `agent_duo/__main__.py`: CLI entry point (`python -m agent_duo`).
- `agent_duo/tools.py`: allowlisted read-only bridge to `agent-reach`. Builds argv lists (no shell), refuses paid and write actions, truncates output.
- `agent_duo/protocol.py`: JSON message format and validation.
- `agent_duo/models.py`: Anthropic Messages API client using the standard library.
- `agent_duo/roles.py`: system prompts for Scout and Critic.
- `agent_duo/orchestrator.py`: Scout/Critic loop, tool-step and round limits, grounding check on cited URLs, JSONL transcript.
- `tests/__init__.py`, `tests/test_agent_duo.py`: 24 unit tests with a fake model and a fake runner.
- `README.md`, `scenarios.md`: how to run, safety rules, and the three use cases.
- `CHANGELOG.md`: this file.

### Fixed after review
- Off-by-one: the last allowed Critic reply is now examined instead of discarded.
- Critic now sees its own earlier requests and finals in its history.
- Grounding now checks URLs in the final answer text, not only in `sources`.
- Leading-space bypass of the flag guard closed (targets are stripped before validation).
- `web read` refuses localhost, LAN, link-local and non-http(s) targets.
- URLs keep balanced parentheses (Wikipedia-style) and lose only sentence punctuation.
- Empty `content` on claim, request or final is a protocol error.
- A failed agent-reach process is reported as `ok: false`.

### Not changed
- Nothing outside `apps/agent-duo/` was modified.
