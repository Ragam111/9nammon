# Multi-agent workflow: Harness, Planner, Executor

Three roles with one job each:

- **Agent 1, Harness:** runs the workflow. Accepts or rejects each result, retries a rejected task, and stops on a block. It is the only role that decides whether work is accepted.
- **Agent 2, Planner:** splits the goal into at most 8 tasks with acceptance lines and dependencies. The plan must be a valid graph (no unknown ids, no self-dependency, no cycles, no duplicates), or it is rejected and the Planner is asked again once.
- **Agent 3, Executor:** does one task at a time, in dependency order, and receives the outputs of the tasks it depends on.

## Run (offline demo, no key)

```powershell
# from apps/multi-agent-workflow
python -m mawf --demo --workdir work\demo --transcript runs\demo.jsonl
```

`--demo` runs the whole loop with built-in replies: the Planner makes 2 tasks, the Executor writes a note
into `work\demo\notes\t1.md` and reads it back, and the Harness accepts both. It shows the workflow
runs end to end; it does not measure any model.

## Run (real models)

```powershell
# from apps/multi-agent-workflow
$env:ANTHROPIC_API_KEY = "<your key>"   # never commit it
python -m mawf "<goal>" --transcript runs\demo.jsonl --workdir work\demo
```

Default models: Planner `claude-sonnet-5-5`, Executor `claude-haiku-5-5`, judge `claude-sonnet-5-5`.
Exit codes: 0 completed, 1 stopped before all tasks passed, 2 setup or model error.

## Tests

```powershell
python -m unittest discover -s tests -t .
```

Tests use fake models, so they need no key and no network.

## Limits

- The Executor has three file tools only when `--workdir <folder>` is given: `read_file`, `write_file` (create or overwrite) and `list_dir`. All paths must stay inside that folder. `..`, absolute paths, drive paths and symlinks that point outside are refused. There is no delete, no shell and no code execution.
- Without `--workdir` the Executor produces text only.
- The Planner cannot replan after a block. A blocked task stops the run and the report says why.
- Retries are limited by `max_retries` (default 2 extra attempts per task).
