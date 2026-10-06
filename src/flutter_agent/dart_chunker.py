"""Turn parsed Dart into embedding-sized chunks that never cut a method in half.

The unit is one top-level declaration. A 600-line Cubit is too big for one
vector, so it splits at member boundaries — and every part keeps the class header
(its name, supertype and fields) so a chunk from the middle of a file still knows
what it belongs to.
"""
from __future__ import annotations

from .chunk import Chunk
from .config import KIND_CODE, SourceConfig
from .dart_parser import DartFile, Declaration, parse_dart
from .layers import Location


def chunk_dart(
    text: str,
    *,
    location: Location,
    config: SourceConfig,
    path: str = "",
) -> tuple[list[Chunk], str]:
    """Chunk one Dart file. Returns (chunks, title)."""
    parsed = parse_dart(text, path=path)
    title = _title_of(parsed, path)

    if not parsed.declarations:
        # Barrel files (`export '...';` only) carry no declarations but are the
        # best answer to "what does this package expose", so keep them whole.
        body = text.strip()
        if not body:
            return [], title
        return [
            _chunk(
                text=_clip(body, config.max_chunk_chars),
                heading=title,
                heading_path=[title],
                line_start=1,
                line_end=parsed.line_count,
                location=location,
                symbol=title,
                symbol_kind="file",
            )
        ], title

    chunks: list[Chunk] = []
    for decl in parsed.declarations:
        chunks.extend(_chunks_for_declaration(parsed, decl, location, config))
    return chunks, title


def _chunks_for_declaration(
    parsed: DartFile,
    decl: Declaration,
    location: Location,
    config: SourceConfig,
) -> list[Chunk]:
    source = parsed.slice(decl.line_start, decl.line_end)
    name = decl.name or "(anonymous)"

    if len(source) <= config.max_chunk_chars or not decl.members:
        return [
            _chunk(
                text=_clip(source, config.max_chunk_chars * 3),
                heading=name,
                heading_path=[name],
                line_start=decl.line_start,
                line_end=decl.line_end,
                location=location,
                symbol=name,
                symbol_kind=decl.kind,
            )
        ]

    # Too big for one vector: split on member boundaries, repeating the header.
    header_end = max(decl.line_start, decl.members[0].line_start - 1)
    header = parsed.slice(decl.line_start, header_end)

    groups: list[tuple[int, int, list[str]]] = []
    current_start: int | None = None
    current_end = header_end
    current_names: list[str] = []
    current_len = 0
    cursor = header_end

    for member in decl.members:
        seg_start = cursor + 1
        seg_end = max(member.line_end, seg_start)
        if seg_start > seg_end:
            continue
        seg_len = len(parsed.slice(seg_start, seg_end))

        if current_start is not None and current_len + seg_len > config.max_chunk_chars:
            groups.append((current_start, current_end, current_names))
            current_start, current_len, current_names = None, 0, []

        if current_start is None:
            current_start = seg_start
        current_end = seg_end
        current_len += seg_len
        if member.name:
            current_names.append(member.name)
        cursor = seg_end

    # Whatever trails the last member (the closing brace, usually).
    if current_start is not None:
        groups.append((current_start, max(current_end, decl.line_end), current_names))
    elif cursor < decl.line_end:
        groups.append((cursor + 1, decl.line_end, []))

    total = len(groups)
    out: list[Chunk] = []
    for index, (start, end, names) in enumerate(groups):
        body = parsed.slice(start, end)
        summary = _summarise(names)
        text = f"{header}\n{body}" if header.strip() else body
        out.append(
            _chunk(
                text=_clip(text, config.max_chunk_chars * 3),
                heading=f"{name} - {summary}" if summary else name,
                heading_path=[name] + ([summary] if summary else []),
                line_start=start,
                line_end=end,
                location=location,
                symbol=name,
                symbol_kind=decl.kind,
                part=index,
                total_parts=total,
            )
        )
    return out


def _chunk(
    *,
    text: str,
    heading: str,
    heading_path: list[str],
    line_start: int,
    line_end: int,
    location: Location,
    symbol: str,
    symbol_kind: str,
    part: int = 0,
    total_parts: int = 1,
) -> Chunk:
    return Chunk(
        text=text,
        heading=heading,
        heading_path=heading_path,
        level=0,
        line_start=line_start,
        line_end=line_end,
        part=part,
        total_parts=total_parts,
        kind=KIND_CODE,
        project=location.project,
        feature=location.feature,
        layer=location.label,
        symbol=symbol,
        symbol_kind=symbol_kind,
    )


def _summarise(names: list[str]) -> str:
    """A short member list for the chunk heading, so split parts stay tellable apart."""
    if not names:
        return ""
    if len(names) <= 3:
        return ", ".join(names)
    return f"{names[0]}, {names[1]} ... {names[-1]}"


def _title_of(parsed: DartFile, path: str) -> str:
    """The file's headline symbol — the first class, else its filename."""
    for decl in parsed.declarations:
        if decl.kind in ("class", "mixin", "enum", "extension") and decl.name:
            return decl.name
    for decl in parsed.declarations:
        if decl.name:
            return decl.name
    stem = path.rsplit("/", 1)[-1]
    return stem[:-5] if stem.endswith(".dart") else stem


def _clip(text: str, limit: int) -> str:
    """Last-resort guard against a single pathological declaration.

    The limit is generous (3x the chunk budget): splitting already happened at
    member boundaries, and truncating real code is worse than one long vector.
    """
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n// ... truncated by flutter-agent"
