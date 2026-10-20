# eval — does the model write Dart this codebase would accept?

Generate a file, drop it into a known-clean project, and run the same R1–R12
checker the agent already enforces. No human in the loop, no judge model, no
rubric to argue with.

Built first, before any training, so that every later claim of improvement has
a number from before it.

---

## Run it

Score files somebody else produced — Claude, a colleague, an earlier run:

```powershell
python -m model.eval.harness score --from-dir model\runs\claude\raw --name claude
```

One `<prompt id>.dart` (or `.txt`) per prompt in that directory. Prose around a
fenced block is fine; the extractor pulls the Dart out.

Generate with a local model, then score:

```powershell
python -m model.eval.harness run --model Qwen/Qwen2.5-Coder-3B-Instruct --condition full
python -m model.eval.harness run --model Qwen/Qwen2.5-Coder-3B-Instruct --adapter model\out\lora --condition bare
```

Diff two runs:

```powershell
python -m model.eval.harness compare model\runs\base-full\report.json model\runs\tuned-bare\report.json
```

Add `--analyze` to also run `flutter pub get` and `dart analyze` over the
workspace. Slow, and needs the Flutter SDK on PATH, but it is the only check
that catches a `LangKeys.inventedKey` that does not exist.

---

## The two conditions are the experiment

`--condition full` sends `system_full.txt`, a condensed CLAUDE.md. `--condition
bare` sends four lines.

The question this harness exists to answer:

> Does the tuned model on **bare** match the base model on **full**?

If yes, the weights absorbed the house style and every future prompt gets a
thousand tokens shorter. If the tuned model still needs **full** to behave, the
fine-tune taught nothing the prompt was not already teaching, and MODEL.md says
to stop.

Compare runs across the diagonal — `base-full` against `tuned-bare` — not
`base-bare` against `tuned-bare`, which flatters the tune.

---

## How scoring works

`tests/fixtures/quick_tasks` is a scaffolded project asserted clean by
`test_fixture_project.py`. Each run copies it to a scratch directory, writes the
generated file at its declared target path, and runs `check_path` on that file.
Because the ground is clean, every finding came from the generated code.

Three outcomes per prompt, kept distinct:

| | |
|---|---|
| **clean** | code was produced and the checker found nothing |
| **errors / warnings** | code was produced and broke specific rules |
| **no code emitted** | nothing extractable in the response |

Collapsing the third into "failed" would let a model that answers in prose score
the same as one that writes bad Dart. They are different problems.

Read the **per-rule table**, not the total. A model that stops emitting raw
`.tr()` keys but still puts Firestore in a widget has learned a lint, not an
architecture.

---

## Prompts

12 tasks in `prompts.jsonl`, each anchored in `quick_tasks` and each carrying a
`rules` field naming what it is built to stress.

Several are traps, and they are the interesting ones:

- `widget-no-persistence` asks a widget to remember something across launches.
  The house answer pushes that to a data source; the tempting answer reaches for
  `SharedPreferences` and trips R5.
- `cubit-notes-filter` asks a Cubit to persist a choice *and* close a bottom
  sheet. The second half is an R6 violation waiting to happen.
- `datasource-notes` asks for Firestore calls in a data source, where they are
  correct. It carries an empty `rules` list on purpose: a model that has
  over-learned "never touch Firebase" fails here, and that failure is worth
  seeing.

---

## Known gaps

- **Single-file checks skip R8 and R12.** Both are project-wide facts — whether
  `LangKeys`, `ar.json` and `en.json` agree, and whether a feature has its
  required folders. One generated file cannot be blamed for either.
  `Workspace.check_project()` covers them when a whole feature is generated.
- **R7 does not verify that a `LangKeys` constant exists.** It catches raw keys
  and hardcoded `Text('…')`, but `LangKeys.madeUpName` passes. `--analyze`
  catches it.
- **12 prompts is a small sample.** A two-file swing moves the clean rate by
  17%. Treat small deltas as noise until the set grows.
- **Greedy decoding only** by default. Deliberate: two runs of one checkpoint
  must agree, or `compare` means nothing.

---

## Checking the judge itself

The harness is only trustworthy if it discriminates. Feed it one file written in
house style and one with planted violations; the first must come back clean and
the second must name the exact rules you planted. That control was run when this
was built — a widget using `LangKeys` scored clean, and a widget importing
`package:quick_tasks/…`, calling `SharedPreferences`, and writing
`'clear_completed'.tr()` came back with R2, R5 and R7 and nothing else.

Re-run that control after any change to `extract.py` or `workspace.py`.
