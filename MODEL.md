# MODEL.md — fine-tuning a local Flutter model on this corpus

Working plan for the `with_model` branch. The goal is a small local model that
writes Dart in this house style without being told the style every time.

This file is the brief, not the result. Nothing here is built yet.

---

## What the model is actually for

The index already answers *what this codebase does*. `flutter_pattern` retrieves
the rule, a golden example and past corrections; `flutter_component` lists what
the shared package exports. Retrieval is good at facts and is correctable in
seconds.

A fine-tune is bad at facts and expensive to correct. What it is good at is
**defaults** — emitting a Cubit that already looks like ours, without a thousand
tokens of prompt explaining that screens hold no `_build` methods and UI text
goes through `LangKeys`.

So the target is narrow:

> Match what Claude produces *with* the full CLAUDE.md prompt plus retrieved
> precedent, on a fraction of the input tokens, for routine feature work.

Not: replace the index. Not: beat Claude on reasoning. If the fine-tune ends up
needing the same prompt to behave, it has failed and this branch should be
abandoned in favour of better retrieval.

---

## Hardware, and why that splits the work in two

| | |
|---|---|
| GPU | RTX 4050 Laptop, **6140 MB VRAM** |
| Torch | 2.11.0+cu128 / CUDA 12.8 |
| Corpus | 1706 files, 3325 chunks — code=3253, pattern=27, lesson=26, rule=19 |
| Sources | 7 registered roots (6 apps + `corereusablepackage`) |

6 GB is the binding constraint on everything below.

A Claude session on GitHub has no GPU, no access to `~/.flutter-agent/`, and no
access to the seven project roots. It can write this pipeline; it cannot run a
single step of it.

| Cloud session (`with_model`) | Local session |
|---|---|
| Dataset builders | Run them against the real corpus |
| QLoRA script and config | Train on the 4050 |
| Eval harness | Run eval, read the failures |
| Docs, tests | Index integration |

---

## The real problem is data, not training

The training script is a weekend. The dataset is the project.

`flutter-agent export-dataset <out>` already writes lessons as `messages`
triples. It currently yields **26 rows**. That is not a dataset — it is a unit
test. A QLoRA that meaningfully shifts behaviour wants three figures at minimum,
and prefers four.

Three candidate sources, in descending order of value per row:

### 1. Lessons — 26 rows, gold

Every row is a real correction with `wrong`, `right` and `why`, tagged with a
layer and often a rule id. This is the highest-signal data in the repo and the
only data that teaches the model what *not* to emit.

It grows roughly one row per corrected session. Worth protecting: never dilute
it with synthetic entries, or the `flutter_lessons` recall path degrades too.

### 2. Mined git history — unknown volume, probably the unlock

The seven registered roots have years of commits. A commit that touches a Dart
file and whose diff moves code *toward* the rules is a free `wrong → right`
pair, authored by the user, about real code.

Mechanically: for each commit, run the R1–R12 checker over the before and after
blobs. Keep the pairs where the violation count drops. That filter is cheap,
objective, and throws away refactors that were merely stylistic churn.

This is the first thing to build, because it is the only source that might
produce thousands of rows without inventing anything.

### 3. Synthesised instruction pairs — large, lowest signal

3,253 code chunks are *completions*, not instructions: there is no prompt
attached to a `ProfileCubit` that already exists. Turning them into instruction
data means generating a plausible request for each accepted file.

Doable, and the volume is there, but every row is a guess about what was asked,
and the model learns the guesser's habits along with the code. Treat as filler
after (1) and (2), and hold it out of eval entirely.

---

## Eval — the part this repo is unusually well set up for

Most fine-tuning projects cannot tell whether the model got better. This one
can, because `rules.py` is already a programmatic judge:

1. Generate code for a held-out prompt.
2. Run the R1–R12 checker over the output. Count violations by rule.
3. Run `dart analyze` over it. Count errors.
4. Compare against the base model on the same prompts.

That gives a number per checkpoint with no human in the loop, and the per-rule
breakdown says *which* conventions stuck. R7 (LangKeys) and R5 (no backend in
presentation) are the two most likely to move early — they are frequent and
syntactically obvious.

Hold out at least 8 of the 26 lessons from training. Yes, that hurts at this
sample size. Training on your whole eval set hurts more, and silently.

A compile-and-check loop this cheap also leaves the door open to rejection
sampling later — generate *n*, keep the ones that pass, train on those. Worth
noting, not worth building yet.

---

## Base model

Qwen2.5-Coder-**3B**-Instruct, 4-bit QLoRA.

7B at 4-bit technically loads in 6 GB but leaves almost nothing for activations,
which forces a sequence length too short for real Dart files — and whole-file
context is the entire point. 3B trains at a usable 2048–4096 tokens with
gradient accumulation and stays in VRAM alongside the optimiser state.

Start LoRA at r=16, alpha=32, attention and MLP projections, bf16. Resist tuning
these before the dataset is real; hyperparameters are not what is wrong at 26
rows.

---

## Proposed layout

```
model/
  dataset/
    from_lessons.py     # lessons.jsonl   -> pairs   (exists in part, as export-dataset)
    from_history.py     # git log x7 roots -> pairs  (the unlock; build first)
    from_corpus.py      # 3253 chunks     -> pairs   (filler; last)
    build.py            # merge, dedupe, split train/held-out
  train/
    qlora.py
    config.yaml         # 3B, r=16, seqlen 2048, 6GB profile
  eval/
    harness.py          # generate -> rules.py + dart analyze -> per-rule table
    prompts.jsonl       # held-out, hand-checked
```

Nothing here should import from `src/flutter_agent/` beyond `rules.py` and
`lessons.py`. The agent must keep working whether or not this branch ever lands.

---

## Order of work

1. `eval/harness.py` first, against the **base** model. Without a baseline
   number, every later claim of improvement is a vibe.
2. `dataset/from_history.py`. Measure what it actually yields before writing
   anything that consumes it. If it produces 80 rows, this whole branch is a
   different and much smaller project.
3. `dataset/build.py`, merge and split.
4. `train/qlora.py`, one run, compare to baseline.
5. Only then: synthesis, hyperparameters, more data.

---

## When to abandon this

Stated up front, while it is still cheap to walk away:

- `from_history.py` yields under ~300 usable pairs and synthesis is the only way
  to reach volume.
- The tuned 3B needs the full CLAUDE.md prompt to match baseline — meaning the
  weights learned nothing the prompt was not already doing.
- Per-rule violation counts move on R7 and R8 only. Those are the two rules a
  linter already catches, so the win would be real but not worth a training
  pipeline.

The fallback is not failure. It is the current setup — Claude plus retrieval
plus a lessons store that grows every time the user pushes back — which is
already working.

---

## Open questions

- Does `from_history.py` run over all seven roots, or only the two or three with
  the cleanest commit hygiene?
- Arabic: `ar.json` keys and RTL handling are part of the house style. Does the
  3B base handle Arabic string literals without mangling them? Check before
  training, not after.
- Is `corereusablepackage` usage learnable at all from weights, given its API
  changes? Probably a retrieval job permanently.
