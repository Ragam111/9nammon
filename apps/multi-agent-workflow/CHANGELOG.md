# Changelog

## 2026-11-22 · MCP read-only server

### Added
- `mawf/mcp_server.py`: read-only MCP server over stdio (JSON-RPC 2.0, newline-delimited) for one folder passed with `--root`. Version negotiation, `ping`, `tools/list`, `tools/call`. Exactly two tools: `list_dir` and `read_file`.
- Allowlist for `read_file` (`.md .txt .csv .log .json .jsonl`), size cap via `max_bytes` with `truncated`, binary refusal, and a denylist for secret-like and database files, applied to every path segment.
- `tests/test_mcp_server.py`: protocol, path-refusal, denylist, truncation, binary and subprocess tests.
- README section "MCP server (read-only)".

### Not changed
- `mawf/files.py` is reused as is. No new path checker was added.
- `mawf/__main__.py` and `mawf/workflow.py` were not modified.

## 2026-11-22 · First version

### Added
- `mawf/protocol.py`: JSON shapes for each role and plan-graph validation (unknown ids, self-dependency, cycles, duplicates, max 8 tasks).
- `mawf/models.py`: Messages API client using the standard library.
- `mawf/roles.py`: prompts for the Planner, Executor and Harness judge.
- `mawf/workflow.py`: the Harness loop, retries, block handling, transcript.
- `mawf/__main__.py`, `mawf/__init__.py`: command line and package exports.
- `tests/test_workflow.py`, `tests/__init__.py`: 11 unit tests with fake models.
- `README.md`, `CHANGELOG.md`.

### Added in this change
- `mawf/files.py`: `FileSandbox` with read, write and list only, confined to one folder. Rejects `..`, absolute and drive paths, symlinks out, and files over 200 KB.
- Executor tool loop (`max_tool_steps`, default 6) and `--workdir` flag to enable the tools.
- `tests/test_files.py`: sandbox and tool-loop tests. The symlink test is skipped when Windows does not allow symlinks.

### Not changed
- Nothing outside `apps/multi-agent-workflow/` was modified.
