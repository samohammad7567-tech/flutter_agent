# Knowledge base

Everything in this folder is indexed and retrievable through `flutter_pattern`,
`flutter_search` and `flutter_lessons`. It is the part of the agent that learns.

| Folder | Kind | What belongs here |
|---|---|---|
| `rules/` | `rule` | Why a constraint exists, with a real before/after. One file per topic. |
| `patterns/` | `pattern` | Golden examples lifted from the corpus, with commentary on the decisions. |
| `lessons/lessons.jsonl` | `lesson` | Append-only corrections captured from sessions. Never edited by hand in bulk. |

Rules and patterns are plain Markdown: edit them, commit them, and run
`flutter-agent index` to pick the changes up.

## When to record a lesson

Call `flutter_lesson_add` (or `flutter-agent lesson`) at these moments, and only
these — a lesson is a durable correction, not a note:

1. **The user corrects generated Flutter code.** Record what was written, what it
   should have been, and the reason.
2. **`flutter analyze` rejects generated code.** Record the error and the fix.
3. **`flutter_check` finds a violation that then gets fixed.** Pass the `rule_id`
   so the lesson surfaces next to that rule.
4. **A convention is discovered that no rule encodes yet.** If it recurs, promote
   it into a `rules/` card.

Keep `right` concrete — a real snippet beats advice. A lesson whose `right` field
reads "remember to use the repo" is worthless; one containing the five lines that
were actually correct is not.

Lessons are also the training set: `flutter-agent export-dataset out.jsonl`
converts them to instruction/response pairs for a later QLoRA run. That is why
the `wrong`/`right` split matters even when only `right` seems necessary.
