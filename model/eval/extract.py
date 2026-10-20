"""Pull the Dart out of whatever the model wrapped it in.

A base instruct model answers with prose, then a fenced block, then more prose.
A tuned model may answer with bare code. Both have to score the same way, or the
comparison measures politeness rather than Dart.

Returning "" rather than guessing is deliberate: a prompt the generator did not
actually answer must show up as an empty result in the report, not as a file
full of English that the checker then calls clean.
"""
from __future__ import annotations

import re

_FENCED = re.compile(r"```(?:dart|Dart|DART)?[ \t]*\r?\n(?P<body>.*?)```", re.DOTALL)

# Something is Dart if it declares or imports like Dart. Prose does not.
_LOOKS_DART = re.compile(
    r"^\s*(import\s+['\"]|part\s+(of\s+)?['\"]|(abstract\s+|final\s+|sealed\s+)?class\s+\w|"
    r"enum\s+\w|mixin\s+\w|extension\s+\w|typedef\s+\w|void\s+main\s*\()",
    re.MULTILINE,
)


def dart_from(text: str) -> str:
    """Best Dart block in a model response, or "" if there is none."""
    if not text or not text.strip():
        return ""

    blocks = [m.group("body") for m in _FENCED.finditer(text)]
    dart_blocks = [b for b in blocks if _LOOKS_DART.search(b)]
    if dart_blocks:
        # Several fences usually means the model showed a wrong/right pair or
        # split the file; the longest Dart block is the answer, the rest commentary.
        return max(dart_blocks, key=len).strip() + "\n"

    # An unterminated fence -- the model hit the token limit mid-file. Keep what
    # there is; a truncated file is a real failure the checker should see.
    opened = re.search(r"```(?:dart|Dart|DART)?[ \t]*\r?\n", text)
    if opened and "```" not in text[opened.end():]:
        tail = text[opened.end():]
        if _LOOKS_DART.search(tail):
            return tail.strip() + "\n"

    if _LOOKS_DART.search(text):
        return text.strip() + "\n"

    return ""
