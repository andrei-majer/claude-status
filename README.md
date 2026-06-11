# claude-status

Custom Claude Code status line — model, git context, token usage, session time, token speed, and a [CodeNavi](https://www.codenavi.com) index badge, in one bar.

```
Fable 5 | claude@main | 392.6k/1.0M ~ 39% | 51m:55s | 🟢 ✦ codenavi | 666.9 t/s
```

## Features

- **Model** — current model name
- **Git context** — `repo@branch` for a normal checkout, `repo@worktree` for worktrees
- **Context** — tokens used / max; light grey, turns **red at 50%**
- **Session time** — elapsed since the first message (orange)
- **CodeNavi badge** — index coverage of the current repo against a local [CodeNavi](https://www.codenavi.com) server:
  - `✦ <codebase>` — repo is indexed (grey) · `✦ uncovered` (yellow) · `✦ ✗` (red, server unreachable)
  - `🟢` prefix — a CodeNavi tool was used in the response to the current prompt
  - `CODENAVI_PORT` / `CODENAVI_HOST` point at a non-default server; `CODENAVI_CODEBASE` pins coverage. With no CodeNavi server running, the badge simply shows `✦ ✗`.
- **Token speed** — generation speed of the last response when measurable

## Setup

**1. Copy `statusline.py` to `~/.claude/`**

**2. Add to `~/.claude/settings.json`:**

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/statusline.py",
    "padding": 0,
    "refreshInterval": 2
  }
}
```

> Windows: use `python C:/Users/<you>/.claude/statusline.py`

## Requirements

Python 3.10+ · Claude Code
