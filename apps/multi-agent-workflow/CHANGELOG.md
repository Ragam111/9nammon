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
