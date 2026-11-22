# Multi-agent workflow: Harness, Planner, Executor

Three roles with one job each:

- **Agent 1, Harness:** runs the workflow. Accepts or rejects each result, retries a rejected task, and stops on a block. It is the only role that decides whether work is accepted.
- **Agent 2, Planner:** splits the goal into at most 8 tasks with acceptance lines and dependencies. The plan must be a valid graph (no unknown ids, no self-dependency, no cycles, no duplicates), or it is rejected and the Planner is asked again once.
- **Agent 3, Executor:** does one task at a time, in dependency order, and receives the outputs of the tasks it depends on.

## Run

```powershell
# from apps/multi-agent-workflow
$env:ANTHROPIC_API_KEY = "<your key>"   # never commit it
python -m mawf "<goal>" --transcript runs\demo.jsonl
```

Default models: Planner `claude-sonnet-5-5`, Executor `claude-haiku-5-5`, judge `claude-sonnet-5-5`.
Exit codes: 0 completed, 1 stopped before all tasks passed, 2 setup or model error.

## Tests

```powershell
python -m unittest discover -s tests -t .
```

Tests use fake models, so they need no key and no network.

## Limits

- The Executor has no tools. It produces text deliverables only. It cannot edit files or run code. Adding tools needs a separate design with approval before any write action.
- The Planner cannot replan after a block. A blocked task stops the run and the report says why.
- Retries are limited by `max_retries` (default 2 extra attempts per task).
