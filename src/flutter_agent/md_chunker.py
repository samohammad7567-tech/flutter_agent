"""Turn parsed Markdown sections into embedding-sized chunks (adapted from docs-mcp).

Used for the rule / pattern / lesson corpora, which are prose. Dart goes through
dart_chunker instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .chunk import Chunk
from .markdown_parser import Section, iter_code_spans

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?:;])\s+")
FENCE_MARKERS = ("`" * 3, "~" * 3)


@dataclass
class _Block:
    text: str
    line_start: int
    line_end: int
    is_code: bool


def _lstrip_blank(buf: list[str]) -> list[str]:
    k = 0
    while k < len(buf) and not buf[k].strip():
        k += 1
    return buf[k:]


def _blocks_for(section: Section) -> list[_Block]:
    """Break a section body into atomic blocks: whole code fences, or paragraphs."""
    lines = section.content.split("\n")
    base = section.body_start
    code_start = {s: e for s, e in iter_code_spans(lines)}

    blocks: list[_Block] = []
    buf: list[str] = []
    buf_start = 0

    def flush(end_idx: int) -> None:
        nonlocal buf
        if buf and "\n".join(buf).strip():
            lead = len(buf) - len(_lstrip_blank(buf))
            blocks.append(
                _Block(
                    text="\n".join(buf).strip("\n"),
                    line_start=base + buf_start + lead,
                    line_end=base + end_idx,
                    is_code=False,
                )
            )
        buf = []

    i = 0
    while i < len(lines):
        if i in code_start:
            flush(i - 1)
            end = code_start[i]
            blocks.append(
                _Block(
                    text="\n".join(lines[i : end + 1]),
                    line_start=base + i,
                    line_end=base + end,
                    is_code=True,
                )
            )
            i = end + 1
            buf_start = i
            continue
        if not lines[i].strip() and buf and "\n".join(buf).strip():
            flush(i - 1)
            buf_start = i + 1
            i += 1
            continue
        if not buf:
            buf_start = i
        buf.append(lines[i])
        i += 1
    flush(len(lines) - 1)
    return [b for b in blocks if b.text.strip()]


def _split_oversized(block: _Block, max_chars: int) -> list[_Block]:
    """Split a single block that exceeds the budget.

    Code is split on line boundaries only (never mid-line), prose on sentence
    boundaries, so a chunk is always syntactically coherent.
    """
    if len(block.text) <= max_chars:
        return [block]

    out: list[_Block] = []
    if block.is_code:
        lines = block.text.split("\n")
        cur: list[str] = []
        cur_start = block.line_start
        for offset, line in enumerate(lines):
            if cur and len("\n".join(cur + [line])) > max_chars:
                out.append(
                    _Block("\n".join(cur), cur_start, block.line_start + offset - 1, True)
                )
                cur = [line]
                cur_start = block.line_start + offset
            else:
                cur.append(line)
        if cur:
            out.append(_Block("\n".join(cur), cur_start, block.line_end, True))
        return out

    # Prose: sentences first, then hard-wrap anything still too long.
    cur_text = ""
    for piece in SENTENCE_SPLIT_RE.split(block.text):
        while len(piece) > max_chars:
            if cur_text:
                out.append(_Block(cur_text.strip(), block.line_start, block.line_end, False))
                cur_text = ""
            out.append(_Block(piece[:max_chars], block.line_start, block.line_end, False))
            piece = piece[max_chars:]
        if cur_text and len(cur_text) + 1 + len(piece) > max_chars:
            out.append(_Block(cur_text.strip(), block.line_start, block.line_end, False))
            cur_text = piece
        else:
            cur_text = f"{cur_text} {piece}".strip() if cur_text else piece
    if cur_text.strip():
        out.append(_Block(cur_text.strip(), block.line_start, block.line_end, False))
    return out or [block]


def chunk_section(
    section: Section,
    *,
    max_chars: int = 1800,
    min_chars: int = 80,
    overlap_chars: int = 200,
) -> list[Chunk]:
    """Pack a section's blocks into chunks of at most `max_chars` characters."""
    blocks: list[_Block] = []
    for block in _blocks_for(section):
        blocks.extend(_split_oversized(block, max_chars))

    if not blocks:
        # A heading with no body still deserves an entry so it stays discoverable.
        if section.heading:
            return [
                Chunk(
                    text=f"{'#' * max(section.level, 1)} {section.heading}".strip(),
                    heading=section.heading,
                    heading_path=list(section.heading_path),
                    level=section.level,
                    line_start=section.line_start,
                    line_end=section.line_end,
                )
            ]
        return []

    groups: list[list[_Block]] = []
    cur: list[_Block] = []
    cur_len = 0
    for block in blocks:
        blen = len(block.text)
        if cur and cur_len + blen + 2 > max_chars:
            groups.append(cur)
            cur, cur_len = [], 0
        cur.append(block)
        cur_len += blen + 2
    if cur:
        groups.append(cur)

    # Merge a trailing scrap into its predecessor rather than emitting a stub.
    if len(groups) > 1:
        tail_len = sum(len(b.text) for b in groups[-1])
        head_len = sum(len(b.text) for b in groups[-2])
        if tail_len < min_chars and head_len + tail_len <= max_chars * 1.25:
            groups[-2].extend(groups.pop())

    chunks: list[Chunk] = []
    for i, group in enumerate(groups):
        body = "\n\n".join(b.text for b in group)
        prefix = ""
        if i > 0 and overlap_chars > 0:
            # Carry a tail of the previous chunk so context is not lost at the
            # seam, but never duplicate part of a code fence into the overlap.
            tail = chunks[-1].text[-overlap_chars:]
            if not any(marker in tail for marker in FENCE_MARKERS):
                cut = tail.find("\n")
                tail = tail[cut + 1 :] if cut != -1 else tail
                if tail.strip():
                    prefix = tail.strip() + "\n\n"
        heading_line = ""
        if i == 0 and section.heading:
            heading_line = f"{'#' * max(section.level, 1)} {section.heading}\n\n"
        chunks.append(
            Chunk(
                text=(heading_line + prefix + body).strip(),
                heading=section.heading,
                heading_path=list(section.heading_path),
                level=section.level,
                line_start=group[0].line_start,
                line_end=group[-1].line_end,
                part=i,
                total_parts=len(groups),
            )
        )
    return chunks


def chunk_document(
    sections: list[Section],
    *,
    max_chars: int = 1800,
    min_chars: int = 80,
    overlap_chars: int = 200,
) -> list[Chunk]:
    out: list[Chunk] = []
    for section in sections:
        out.extend(
            chunk_section(
                section,
                max_chars=max_chars,
                min_chars=min_chars,
                overlap_chars=overlap_chars,
            )
        )
    return out
