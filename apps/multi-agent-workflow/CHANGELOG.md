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

### Not changed
- Nothing outside `apps/multi-agent-workflow/` was modified.
