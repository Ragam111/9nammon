## 2026-11-23 · Runnable demo

### Added
- `mawf/demo.py`: `DemoModel`, offline replies for all three roles, so the workflow runs without an API key.
- `--demo` flag in `mawf/__main__.py`; the goal is optional with `--demo` and defaults to a sample goal.
- `tests/test_demo.py`: end-to-end demo with file tools, text-only demo, and CLI exit codes.
- UTF-8 stdout for Thai output on Windows consoles.

### Not changed
- Real runs still use `AnthropicClient` and need `ANTHROPIC_API_KEY`. The demo does not measure any model.

# Changelog

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
