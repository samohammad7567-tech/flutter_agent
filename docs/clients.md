# Using flutter-agent with other AI tools

`flutter-agent-server` is a plain [MCP](https://modelcontextprotocol.io) stdio
server built on the official SDK (`src/flutter_agent/server.py:296`). Nothing in
it is Claude-specific: the eight tools are declared the standard way, so any
client that speaks MCP can call them, and anything that can run a shell command
can use the CLI instead.

This file is the per-client wiring. For what the tools *do*, read the manuals in
this directory; for standing the agent up on a new machine, read **A second
machine** in the root `README.md`.

---

## Before any client: the index has to exist

Every tool below reaches the same local index. A client configured on a machine
that has never run `setup.ps1` will connect fine and answer every query with
nothing.

```powershell
flutter-agent status     # must report chunks > 0
flutter-agent doctor     # which device the embedder is on
```

`~/.flutter-agent/` holds the index and the registered roots and is per-machine —
it does not travel in git.

---

## The one value every config needs

All of them want an absolute path to the server executable. The installer reuses
whatever compatible venv it finds, so that path is not predictable and is usually
not on `PATH` — read it back out of the registration `install.ps1` already wrote:

```powershell
(Get-Content $HOME\.claude.json -Raw | ConvertFrom-Json).mcpServers.'flutter-agent'.command
```

On this machine that returns:

```
C:/Users/IRD-83/Desktop/local-mcp/.venv/Scripts/flutter-agent-server.exe
```

If Claude Code was never registered here, it is `<venv>\Scripts\flutter-agent-server.exe`
for the venv `install.ps1` reported — `(Get-Command flutter-agent-server).Source`
finds it only when that venv is active.

Two things that save an hour of debugging:

* **Do not activate the venv first, and do not wrap it in `cmd /c`.** A venv
  console script embeds its own interpreter path, so the absolute path works from
  any parent process with any environment.
* **In JSON, write `\\` or `/`.** A single backslash in a JSON string is an
  escape character, and a config holding `C:\Users\...` is the most common reason
  a client reports the server as failed with no further detail.

On macOS or Linux the path is `<venv>/bin/flutter-agent-server`; everything else
below is identical.

---

## The universal block

Claude Code, Claude Desktop, Cursor, Windsurf/Devin, Cline and Roo all read the
same shape — only the file path differs:

```json
{
  "mcpServers": {
    "flutter-agent": {
      "type": "stdio",
      "command": "C:/Users/IRD-83/Desktop/local-mcp/.venv/Scripts/flutter-agent-server.exe",
      "args": [],
      "env": {}
    }
  }
}
```

| Client | File |
|---|---|
| Claude Code | `claude mcp add --scope user flutter-agent -- <path>` (writes `~/.claude.json`) |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `.cursor/mcp.json` in the project, or `~/.cursor/mcp.json` for all projects |
| Windsurf (legacy) | `~/.codeium/windsurf/mcp_config.json` |
| Devin Desktop | `~/.config/devin/mcp_config.json` — Windsurf was renamed in June 2026 and moved its config |
| Cline / Roo Code | `cline_mcp_settings.json`, via the extension's MCP Servers pane |
| Gemini CLI | `~/.gemini/settings.json`, or `.gemini/settings.json` per project |

Restart the client after editing. None of them re-read the file live.

---

## Codex CLI — TOML, not JSON

OpenAI's Codex CLI keeps MCP servers in `~/.codex/config.toml`:

```toml
[mcp_servers.flutter-agent]
command = "C:/Users/IRD-83/Desktop/local-mcp/.venv/Scripts/flutter-agent-server.exe"
args = []
```

The first query loads the embedding model, which on a cold cache can take longer
than the default startup window. If Codex times out, raise it:

```toml
[mcp_servers.flutter-agent]
command = "C:/Users/IRD-83/Desktop/local-mcp/.venv/Scripts/flutter-agent-server.exe"
args = []
startup_timeout_sec = 60
```

Or let the CLI write it:

```powershell
codex mcp add flutter-agent --command C:/Users/.../flutter-agent-server.exe
```

---

## VS Code / Copilot agent mode — `servers`, not `mcpServers`

VS Code is the one outlier on the key name. `.vscode/mcp.json` in the workspace:

```json
{
  "servers": {
    "flutter-agent": {
      "type": "stdio",
      "command": "C:/Users/IRD-83/Desktop/local-mcp/.venv/Scripts/flutter-agent-server.exe",
      "args": []
    }
  }
}
```

Tools only appear in **agent mode** — ask mode cannot call them.

---

## Anything else that speaks MCP

Zed, JetBrains AI Assistant, LibreChat, Continue and the rest all accept a local
stdio server; the key name and file location are theirs to document, but the
three values are always the same — `command` is the absolute path, `args` and
`env` are empty. If a client asks for a single command line rather than a JSON
object, give it the path alone.

From the Python side no config file is involved:

```python
from agents.mcp import MCPServerStdio   # openai-agents

flutter = MCPServerStdio(params={
    "command": r"C:\Users\IRD-83\Desktop\local-mcp\.venv\Scripts\flutter-agent-server.exe",
    "args": [],
})
```

`flutter-agent serve` is the same server under the CLI, if a client would rather
invoke a subcommand than a second executable.

---

## Tools with no MCP support at all

Aider, a browser chat window, a CI step, a Makefile — use the CLI and paste the
output. Every MCP tool has a command behind it:

```bash
flutter-agent pattern "image upload"                           # flutter_pattern
flutter-agent search "firestore query" --layer data_source     # flutter_search
flutter-agent component AppButton                              # flutter_component
flutter-agent check C:\app\lib\features\profile                # flutter_check
flutter-agent refactor C:\app\lib\...\home_screen.dart         # flutter_refactor_plan
flutter-agent scaffold lesson_detail --root C:\app             # flutter_scaffold
flutter-agent lessons "localization"                           # flutter_lessons
flutter-agent lesson ...                                       # flutter_lesson_add
```

This is also the honest answer for browser-only tools — claude.ai, ChatGPT on the
web. A stdio server has to be launched by the client on the machine where the
index lives, and no amount of config changes that.

---

## The part that is easy to forget

The agent supplies **precedent**. It does not supply the **rules** — those live in
`~/.claude/CLAUDE.md`, and only Claude reads that file. Point every other tool at
the same content under the name it expects, or it will retrieve your real code
and then ignore the architecture while writing new code:

| Client | Instructions file |
|---|---|
| Claude Code / Desktop | `~/.claude/CLAUDE.md`, or `CLAUDE.md` in the project |
| Codex CLI | `AGENTS.md` in the repo root, or `~/.codex/AGENTS.md` |
| Cursor | `.cursor/rules/*.mdc` in the project (`AGENTS.md` is also read) |
| Gemini CLI | `GEMINI.md` |
| Windsurf / Devin | `.windsurfrules`, or the workspace rules pane |
| Cline / Roo | `.clinerules` |

A symlink or a copy both work. A copy drifts, so prefer the symlink where the
tool follows one.

---

## When it does not work

| Symptom | Cause |
|---|---|
| Client lists the server as failed, no detail | A single `\` in a JSON path, or a stale venv path after a reinstall |
| Connects, but every answer is empty | No index on this machine — run `setup.ps1`, then `flutter-agent status` |
| First call times out, later ones are fine | Cold embedding-model load; raise the client's startup timeout |
| `check` passes on code that is obviously wrong | The file is outside every registered root — `flutter-agent sources list` |
| Tools are listed but never called | The host model is choosing not to; name the tool in the prompt |
| Arabic keys come back mangled | A console codepage problem in that client, not the agent — the store is UTF-8 |

Run `flutter-agent-server.exe` directly to see what a client is hiding. It will
sit silently waiting for JSON-RPC on stdin, which is a successful start; a
traceback instead is the real error.

---

## What does not port

The retrieval half of this repo is client-agnostic by design. The fine-tune on
the `with_model` branch is not: a LoRA adapter only runs on the base model it was
trained against, under a runtime you host yourself. That branch's `MODEL.md`
keeps the two halves separable on purpose — the index works with every tool
above, with or without a trained adapter.
