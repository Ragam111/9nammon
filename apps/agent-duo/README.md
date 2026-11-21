# agent-duo: Scout and Critic

Two agents that talk to each other to research public content.

- **Scout** reads public content through `agent-reach` (YouTube, Bilibili, web, GitHub, V2EX). It only uses read actions.
- **Critic** checks Scout's claims, asks for more data when needed, and writes the final answer in Thai.

A final answer is accepted only if every cited URL appeared in a real tool result. Otherwise Critic is told to ask again.

## Run

```powershell
# from apps/agent-duo
$env:ANTHROPIC_API_KEY = "<your key>"          # never commit it
$env:AGENT_REACH_BIN = "C:\Users\Hello\.local\bin\agent-reach.exe"
python -m agent_duo "สรุปประเด็นสำคัญจาก https://www.youtube.com/watch?v=<id>" --transcript runs\demo.jsonl
```

Options: `--rounds N` (max Critic turns, default 6), `--scout-model`, `--critic-model`.
Default models: Scout `claude-haiku-5-5`, Critic `claude-sonnet-5-5`.

Exit codes: 0 final answer, 1 no final answer within the round limit, 2 model or setup error.

## Tests

```powershell
python -m unittest discover -s tests -t .
```

The tests use a fake model and a fake runner, so they need no API key and no network.

## Safety

- Only these channel actions are allowed: youtube (read, search, subtitle), bilibili (read, search, subtitle, hot), web (read, search), github (read, search), v2ex (hot, node, read, user).
- Refused: paid transcription (`youtube transcribe`), login-only channels (Instagram, Facebook, Twitter, Reddit, Xiaohongshu) and any write action.
- The model never writes a shell command. It names channel, action and target, and the code builds an argv list without a shell.
- Each agent turn has a tool-step limit, each tool call has a timeout, and each run has a round limit.

## Limits

- Scout cannot read files in this repo yet. The "match a demo to project files" scenario needs a file-reading tool, which is not added.
- Subtitles depend on the video having captions. When there are none, Scout must say so.
- A live run needs an API key. This repo does not contain one.

See [scenarios.md](scenarios.md) for the three use cases.
