"""Split a Markdown document into heading-scoped sections.

Line numbers are 1-based and inclusive, matching what an editor shows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ATX_RE = re.compile(r"^(?P<hashes>#{1,6})(?:\s+(?P<title>.*?))?\s*$")
SETEXT_RE = re.compile(r"^(?P<marker>=+|-+)\s*$")
FENCE_RE = re.compile(r"^(?P<indent>\s{0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
FRONT_MATTER_RE = re.compile(r"^(---|\+\+\+)\s*$")
TRAILING_HASHES_RE = re.compile(r"\s+#+\s*$")


@dataclass
class Section:
    """One heading and the body that belongs to it (excluding subsections)."""

    heading: str
    level: int
    heading_path: list[str] = field(default_factory=list)
    line_start: int = 1  # line of the heading itself (or 1 for the preamble)
    line_end: int = 1
    body_start: int = 1  # first line of body content after the heading
    content: str = ""

    @property
    def breadcrumb(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else "(document root)"


def strip_front_matter(lines: list[str]) -> tuple[list[str], int]:
    """Drop a leading YAML/TOML front-matter block.

    Returns the remaining lines and the number of lines removed, so callers can
    keep reporting real line numbers.
    """
    if not lines:
        return lines, 0
    m = FRONT_MATTER_RE.match(lines[0])
    if not m:
        return lines, 0
    delim = m.group(1)
    for i in range(1, len(lines)):
        if lines[i].rstrip() == delim:
            return lines[i + 1 :], i + 1
    return lines, 0


def _is_fence_open(line: str) -> tuple[str, int] | None:
    m = FENCE_RE.match(line)
    if not m:
        return None
    info = m.group("info")
    fence = m.group("fence")
    # An opening backtick fence may not carry backticks in its info string.
    if fence[0] == "`" and "`" in info:
        return None
    return fence[0], len(fence)


def _closes_fence(line: str, char: str, length: int) -> bool:
    m = FENCE_RE.match(line)
    if not m:
        return False
    fence = m.group("fence")
    if fence[0] != char or len(fence) < length:
        return False
    return not m.group("info").strip()


def iter_code_spans(lines: list[str]):
    """Yield (start_idx, end_idx) inclusive 0-based ranges of fenced code blocks."""
    i = 0
    n = len(lines)
    while i < n:
        opened = _is_fence_open(lines[i])
        if opened:
            char, length = opened
            start = i
            j = i + 1
            while j < n and not _closes_fence(lines[j], char, length):
                j += 1
            yield (start, min(j, n - 1))
            i = j + 1
        else:
            i += 1


def parse_markdown(text: str, *, keep_front_matter: bool = False) -> list[Section]:
    """Parse Markdown into a flat list of sections in document order."""
    raw_lines = text.splitlines()
    offset = 0
    if not keep_front_matter:
        raw_lines, offset = strip_front_matter(raw_lines)

    n = len(raw_lines)
    in_code = [False] * n
    for start, end in iter_code_spans(raw_lines):
        for k in range(start, min(end + 1, n)):
            in_code[k] = True

    # Locate headings (ATX anywhere outside code; setext where a text line is
    # underlined by = or -).
    headings: list[tuple[int, int, str, int]] = []  # (idx, level, title, consumed_lines)
    for idx, line in enumerate(raw_lines):
        if in_code[idx]:
            continue
        m = ATX_RE.match(line)
        if m:
            title = (m.group("title") or "").strip()
            title = TRAILING_HASHES_RE.sub("", title).strip()
            headings.append((idx, len(m.group("hashes")), title, 1))
            continue
        if idx + 1 < n and not in_code[idx + 1] and line.strip() and not line.startswith(" " * 4):
            sm = SETEXT_RE.match(raw_lines[idx + 1])
            if sm and not ATX_RE.match(line):
                level = 1 if sm.group("marker").startswith("=") else 2
                headings.append((idx, level, line.strip(), 2))

    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (level, title)

    def body_range(start_idx: int, end_idx: int) -> tuple[str, int]:
        """Return the body text plus how many blank lines were trimmed off the front.

        The caller needs that count to keep `body_start` pointing at the real
        first line of content, so every downstream line number stays true.
        """
        chunk = raw_lines[start_idx:end_idx]
        lead = 0
        while lead < len(chunk) and not chunk[lead].strip():
            lead += 1
        return "\n".join(chunk).strip("\n"), lead

    # Preamble before the first heading.
    first_heading_idx = headings[0][0] if headings else n
    preamble, pre_lead = body_range(0, first_heading_idx)
    if preamble.strip():
        sections.append(
            Section(
                heading="",
                level=0,
                heading_path=[],
                line_start=1 + offset,
                line_end=first_heading_idx + offset,
                body_start=1 + pre_lead + offset,
                content=preamble,
            )
        )

    for pos, (idx, level, title, consumed) in enumerate(headings):
        next_idx = headings[pos + 1][0] if pos + 1 < len(headings) else n
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        body, lead = body_range(idx + consumed, next_idx)
        sections.append(
            Section(
                heading=title,
                level=level,
                heading_path=[t for _, t in stack],
                line_start=idx + 1 + offset,
                line_end=next_idx + offset,
                body_start=idx + consumed + lead + 1 + offset,
                content=body,
            )
        )

    return sections
