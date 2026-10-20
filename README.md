# flutter-agent — a local Flutter clean-architecture agent

Semantic search over *your* Dart corpus, static enforcement of *your* layer rules,
feature scaffolding in *your* house style, and a lesson store that accumulates
corrections from Claude sessions. Everything runs on this machine; nothing is
sent anywhere.

```
your Dart projects ─┐
knowledge/ (rules,  ├─► parser ─► chunker ─► local GPU embeddings ─► FAISS ─┬─► MCP ─► Claude Code
  patterns, lessons)┘                                                       └─► CLI
```

The point is precedent. Instead of Claude re-deriving your conventions from prose
every session, it retrieves the real implementations you already wrote.

---

## What it gives you

| Tool / command | What it answers |
|---|---|
| `flutter_pattern` / `pattern` | "How does this codebase do pagination?" — rule + golden example + past corrections |
| `flutter_search` / `search` | Semantic search over the Dart corpus, filterable by layer, feature, project |
| `flutter_component` / `component` | What the shared package exports, and real call sites for one component |
| `flutter_check` / `check` | Architecture-rule violations (R1–R12) for a file, feature or project |
| `flutter_refactor_plan` / `refactor` | What to extract from an oversized file, largest method first, with a precedent |
| `flutter_scaffold` / `scaffold` | A complete feature folder plus localization keys, dry-run by default |
| `flutter_lesson_add` / `lesson` | Record a correction so it is recalled in later sessions |
| `flutter_lessons` / `lessons` | Recall corrections by topic |

---

## Manuals

PDFs in [`docs/`](docs/):

| File | Pages | What it covers |
|---|---|---|
| `flutter-agent-guide-en.pdf` | 22 | Full user manual — install, both surfaces, every command, all 12 rules |
| `flutter-agent-guide-ar.pdf` | 21 | The same manual in Arabic |
| `flutter-agent-training-ar.pdf` | 19 | How to grow the knowledge base from daily work with Claude, and the token economy of doing so (Arabic) |

Each is generated from the matching `.html` beside it. Edit the HTML and rebuild
with:

```powershell
.\docs\build-pdf.ps1
```

Rendering goes through headless Edge/Chrome deliberately — it is the only engine
on a stock Windows box that shapes Arabic correctly while leaving LTR code blocks
intact.

[`docs/clients.md`](docs/clients.md) is Markdown rather than a PDF: the config
block for every other MCP client — Cursor, Codex CLI, VS Code, Gemini CLI,
Windsurf/Devin, Cline — plus the CLI fallback for tools that speak no MCP at all.

---

## Install

The dependency set is identical to `docs-mcp`, and the CUDA PyTorch wheel is a
~2.8 GB download that unpacks to ~4.9 GB. By default the installer **reuses an
existing compatible virtualenv** rather than building a second one.

```powershell
.\install.ps1                 # reuse a found venv, install, index, register
.\install.ps1 -OwnVenv        # build a private .venv instead (large download)
.\install.ps1 -SkipRegister   # install only
```

Then register your projects — the shared package first, then each app:

```powershell
flutter-agent sources add C:\path\to\corereusablepackage
flutter-agent sources add C:\path\to\your_app
flutter-agent index
flutter-agent status
```

Register the MCP server with Claude Code manually if the installer could not:

```powershell
claude mcp add --scope user flutter-agent -- <venv>\Scripts\flutter-agent-server.exe
```

Any other MCP client is the same executable behind a different config file —
[`docs/clients.md`](docs/clients.md).

### Requirements

* Python 3.10+
* An NVIDIA GPU is optional — `sentence-transformers` falls back to CPU, and
  `flutter-agent doctor` tells you which is in use
* Flutter on PATH only if you want `flutter analyze` to verify generated code

### A second machine

The knowledge travels in git; the index does not, and does not need to.

| What | Where it lives | How it gets there |
|---|---|---|
| Lessons, rule cards, pattern cards | `knowledge/` in this repo | `git clone` |
| Embeddings (`index.faiss`, `meta.sqlite3`) | `~/.flutter-agent/index/` | rebuilt by `flutter-agent index` |
| Registered roots (`sources.json`) | `~/.flutter-agent/` | re-registered by `setup.ps1`; the paths differ per machine |

```powershell
git clone https://github.com/samohammad7567-tech/flutter_agent.git
cd flutter_agent
.\setup.ps1 -Projects D:\work\corereusablepackage,D:\work\your_app
```

`setup.ps1` is that whole sequence: it refuses to run outside a checkout, hands
the environment to `install.ps1`, finds the CLI the install produced, registers
each project with shared packages first, rebuilds the index, prints `status`, and
says so if `~\.claude\CLAUDE.md` is missing. Re-running it is safe — registration
is idempotent and indexing is incremental.

| Flag | Effect |
|---|---|
| `-Scan D:\work [-Depth 3]` | discover projects by their `pubspec.yaml` instead of naming them; prompts before registering, `-Yes` skips the prompt |
| `-DryRun` | print what would be registered, change nothing |
| `-SkipInstall` | the environment already exists — register and index only |
| `-SkipIndex` | register now, index later |
| `-Cpu`, `-OwnVenv`, `-ReuseVenv`, `-SkipRegister` | forwarded to `install.ps1` |

A scan is deliberately shallow — depth 2, and it warns past ten projects. Old
copies and backup folders register exactly as readily as live work, and each one
dilutes retrieval until `pattern` starts answering with a precedent you
abandoned. Naming the projects is the better default.

Four things that bite:

* **Keep it a checkout, not a wheel.** `knowledge_home()` prefers the repo's own
  `knowledge/` directory and only falls back to `~/.flutter-agent/knowledge` when
  there is no checkout above the package. Install from a wheel and every new
  lesson lands outside version control — which is why `setup.ps1` stops unless it
  finds `knowledge/lessons/` beside it.
* **The first index downloads the embedding model** — ~90 MB for
  all-MiniLM-L6-v2, on top of whatever PyTorch wheel the installer pulls.
* **Both scripts are Windows-only.** The package itself is portable — on macOS
  or Linux the same steps are `pip install -e ".[dev]"`,
  `claude mcp add --scope user flutter-agent -- <venv>/bin/flutter-agent-server`,
  then `flutter-agent sources add <project>` per project and `flutter-agent index`.
* **Two machines both recording lessons will collide in `lessons.jsonl`.** It is
  append-only with content-hash ids, so a conflict resolves to the union of both
  sides' lines — but pull before a session and push after it.

One thing git does not carry: `~/.claude/CLAUDE.md`. This agent supplies
precedent; that file supplies the house rules. Copy it across as well.

---

## Daily use

```bash
flutter-agent pattern "image upload"              # before writing a feature
flutter-agent component                           # before writing a widget
flutter-agent component AppButton                 # how is it used
flutter-agent search "firestore query" --layer data_source
flutter-agent check "C:\app\lib\features\profile" # after writing one
flutter-agent refactor "C:\app\lib\...\home_screen.dart"
flutter-agent scaffold lesson_detail --root C:\app          # dry run
flutter-agent scaffold lesson_detail --root C:\app --write
flutter-agent index                               # after a lot of editing
```

Indexing is incremental: only files whose SHA-256 changed are re-embedded, so a
reindex after editing one Cubit costs one embedding call rather than nine hundred.

---

## The rules

| | Rule |
|---|---|
| R1 | Folder layout — no `domain/`, `use_cases/`, `repo_interface/`; canonical folder names |
| R2 | No `package:<own_project>/` self-imports inside `lib/` |
| R3 | Files stay within their layer's line budget (screen 70/150, widget 120/150, …) |
| R4 | Screens hold no `_build...` methods |
| R5 | Presentation never calls Firestore / Supabase / SharedPreferences / Dio / http |
| R6 | Cubits never touch `BuildContext`, `Navigator`, `ScaffoldMessenger`, dialogs |
| R7 | UI text goes through `LangKeys`, never `'raw_key'.tr()` or a hardcoded string |
| R8 | `LangKeys`, `ar.json` and `en.json` describe the same key set |
| R9 | Repos delegate without control flow |
| R10 | No `Expanded`/`Flexible` inside an unconstrained scrollable (heuristic) |
| R11 | Models define at least one of `fromJson` / `toJson` |
| R12 | Features carry the canonical subfolders (grouping folders are skipped) |

No model is involved in any of them: every rule is a property of the source that
can be decided by reading it. Pattern matching runs against a *masked* copy of
the file in which comments and string literals are blanked, so a rule can never
fire on a word inside a comment.

`flutter analyze` remains the only authority on whether code compiles — the agent
shells out to it rather than approximating it.

---

## The knowledge base

`knowledge/` is version-controlled Markdown plus one append-only JSONL file:

* `rules/*.md` — why a constraint exists, with real before/after
* `patterns/*.md` — golden examples lifted from the corpus, with commentary
* `lessons/lessons.jsonl` — corrections captured from sessions

Edit the Markdown freely and run `flutter-agent index`. See
[`knowledge/README.md`](knowledge/README.md) for when to record a lesson.

Lessons double as a training set:

```bash
flutter-agent export-dataset lessons.jsonl   # instruction/response pairs
```

That is the deferred path to a QLoRA fine-tune — worth revisiting once there are
a few hundred real samples, not before.

---

## Layout

```
src/flutter_agent/
  config.py        paths, defaults, glob matching
  sources.py       registry of indexed Flutter projects
  embedder.py      sentence-transformers on CUDA, CPU fallback
  store.py         FAISS + SQLite, architecture metadata columns, filtered search
  dart_parser.py   masking lexer + brace scanner (declarations, members, imports)
  dart_chunker.py  one chunk per declaration, splitting at member boundaries
  layers.py        path -> (project, feature, layer)
  rules.py         R1-R12
  scaffold.py      feature generator + localization wiring
  lessons.py       the learning loop + dataset export
  indexer.py       incremental, multi-source
  service.py       formatted, budgeted tool output
  server.py        MCP stdio server
  cli.py           flutter-agent
```

### Why a hand-written Dart scanner

`dart_parser.py` is not a Dart front end and does not try to be. It finds
declaration boundaries, member boundaries, imports and string literals — enough
to chunk well and to check rules — and tolerates imprecision because nothing here
decides whether code compiles.

What it *does* take seriously is lexing. Brace counting over raw text breaks the
moment a brace appears in a comment, a string, or a `${...}` interpolation, so
everything happens over a masked copy of the source. It handles nested block
comments, raw and triple-quoted strings, and the legal-but-awkward
`'${map['key']}'`. Braces are only counted outside parentheses, because Dart
spells named parameters `({required this.repo})` and counting those as a body
brace cuts every such constructor in half.

Validated on 885 real files: 1332 declarations, 8137 members, zero crashes.

## Tests

```bash
pytest tests -q
```

Covers lexing edge cases, layer classification, every rule with a positive and a
negative case, chunk splitting, scaffolding, and the lesson store. The scaffolder
is additionally asserted to pass the agent's own rule engine.
