"""A line-and-brace scanner for Dart — enough structure to chunk and to check rules.

This is deliberately not a Dart front end. Its job is to find declaration
boundaries, member boundaries, imports and string literals; it tolerates
imprecision because nothing here decides whether code compiles. `flutter analyze`
is the only authority on that, and the agent shells out to it for generated code.

The one thing it does take seriously is lexing. Brace counting over raw text is
wrong the moment a brace appears inside a comment, a string, or a `${...}`
interpolation, so everything is done over a *masked* copy of the source in which
comments and string literals are replaced by spaces, position for position.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"

_DECL_RE = re.compile(
    r"""
    (?P<mods>(?:\b(?:abstract|base|final|sealed|interface|external|augment)\b\s+)*)
    \b(?P<kw>mixin\s+class|class|mixin|extension\s+type|extension|enum|typedef)\b
    (?:\s+(?P<name>""" + IDENT + r"""))?
    """,
    re.VERBOSE,
)
_DIRECTIVE_RE = re.compile(r"^\s*(?P<kw>import|export|part\s+of|part|library)\b")
_URI_RE = re.compile(r"""['"]([^'"]*)['"]""")
_EXTENDS_RE = re.compile(r"\bextends\s+(?P<v>[^{]+?)(?=\s+\b(?:with|implements|on)\b|\s*\{|\s*$)")
_WITH_RE = re.compile(r"\bwith\s+(?P<v>[^{]+?)(?=\s+\b(?:implements|on)\b|\s*\{|\s*$)")
_IMPLEMENTS_RE = re.compile(r"\bimplements\s+(?P<v>[^{]+?)(?=\s+\bon\b|\s*\{|\s*$)")
_ON_RE = re.compile(r"\bon\s+(?P<v>[^{]+?)(?=\s*\{|\s*$)")
_NAME_BEFORE_PAREN_RE = re.compile(r"(" + IDENT + r")\s*(?:<[^<>]*>)?\s*$")
_GETTER_RE = re.compile(r"\bget\s+(" + IDENT + r")")
_SETTER_RE = re.compile(r"\bset\s+(" + IDENT + r")")
_ANNOTATION_RE = re.compile(r"@" + IDENT + r"(?:\.\w+)*\s*(?:\([^()]*\))?")
_FIELD_NAME_RE = re.compile(r"(" + IDENT + r")\s*(?:=|;|$)")


# --------------------------------------------------------------------------- lexing


@dataclass(frozen=True)
class StringLiteral:
    """A string literal with its quotes and interpolations stripped off."""

    value: str
    line: int
    raw: bool
    triple: bool


def _is_ident_char(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch in "_$")


def _skip_block_comment(text: str, i: int) -> int:
    """Index just past a `/* ... */`. Dart nests block comments, so depth matters."""
    n = len(text)
    depth = 0
    while i < n:
        if text.startswith("/*", i):
            depth += 1
            i += 2
            continue
        if text.startswith("*/", i):
            depth -= 1
            i += 2
            if depth <= 0:
                return i
            continue
        i += 1
    return n


def _skip_string(text: str, i: int) -> tuple[int, int, int, bool, bool]:
    """Walk one string literal.

    Returns (index past the closing delimiter, content start, content end, raw, triple).
    """
    n = len(text)
    raw = text[i] == "r"
    if raw:
        i += 1
    quote = text[i]
    triple = text.startswith(quote * 3, i)
    delim = quote * 3 if triple else quote
    i += len(delim)
    content_start = i

    while i < n:
        ch = text[i]
        if not raw and ch == "\\":
            i += 2
            continue
        if text.startswith(delim, i):
            return i + len(delim), content_start, i, raw, triple
        # `'${map['k']}'` is legal Dart: interpolation re-enters expression
        # context, so the same quote may appear nested. Skip the whole `${...}`.
        if not raw and ch == "$" and i + 1 < n and text[i + 1] == "{":
            i = _skip_braces(text, i + 1)
            continue
        if not triple and ch == "\n":
            # Unterminated single-line string. Stop at the newline so one bad
            # line cannot swallow the remainder of the file.
            return i, content_start, i, raw, triple
        i += 1
    return n, content_start, n, raw, triple


def _skip_braces(text: str, i: int) -> int:
    """Index just past the `}` matching the `{` at `i`, skipping strings and comments."""
    n = len(text)
    depth = 0
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i = _skip_block_comment(text, i)
            continue
        if ch in "'\"" or (
            ch == "r"
            and i + 1 < n
            and text[i + 1] in "'\""
            and not _is_ident_char(text[i - 1] if i else "")
        ):
            i = _skip_string(text, i)[0]
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth <= 0:
                return i + 1
        i += 1
    return n


def mask_source(text: str) -> tuple[str, list[StringLiteral]]:
    """Blank out comments and string literals, preserving length and line breaks.

    Everything downstream counts braces over the result, so `if (x) { /* } */ }`
    and `'a}b'` can no longer corrupt the structure.
    """
    n = len(text)
    out = list(text)
    starts = _line_starts(text)
    literals: list[StringLiteral] = []

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    i = 0
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = i
            while j < n and text[j] != "\n":
                j += 1
            blank(i, j)
            i = j
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = _skip_block_comment(text, i)
            blank(i, j)
            i = j
            continue
        if ch in "'\"" or (
            ch == "r"
            and i + 1 < n
            and text[i + 1] in "'\""
            and not _is_ident_char(text[i - 1] if i else "")
        ):
            j, cs, ce, raw, triple = _skip_string(text, i)
            literals.append(
                StringLiteral(
                    value=text[cs:ce],
                    line=_line_of(starts, i),
                    raw=raw,
                    triple=triple,
                )
            )
            blank(i, j)
            i = j
            continue
        i += 1

    return "".join(out), literals


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            starts.append(idx + 1)
    return starts


def _line_of(starts: list[int], index: int) -> int:
    """1-based line number for a character offset."""
    return bisect.bisect_right(starts, index)


# ----------------------------------------------------------------------- structure


@dataclass(frozen=True)
class Directive:
    kind: str  # import | export | part | part_of | library
    uri: str
    line: int
    raw: str


@dataclass
class Member:
    name: str
    kind: str  # constructor | method | getter | setter | field | unknown
    line_start: int
    line_end: int
    is_static: bool = False
    is_override: bool = False

    @property
    def line_count(self) -> int:
        return self.line_end - self.line_start + 1


@dataclass
class Declaration:
    name: str
    kind: str  # class | mixin | enum | extension | typedef | function | variable
    line_start: int
    line_end: int
    extends: str = ""
    mixins: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    on_types: list[str] = field(default_factory=list)
    is_abstract: bool = False
    members: list[Member] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.line_end - self.line_start + 1

    @property
    def supertypes(self) -> list[str]:
        out = [self.extends] if self.extends else []
        return out + self.mixins + self.interfaces + self.on_types


@dataclass
class DartFile:
    path: str
    text: str
    masked: str
    lines: list[str]
    directives: list[Directive] = field(default_factory=list)
    declarations: list[Declaration] = field(default_factory=list)
    literals: list[StringLiteral] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def code_line_count(self) -> int:
        """Lines with something other than comments and whitespace on them."""
        return sum(1 for line in self.masked.split("\n") if line.strip())

    @property
    def imports(self) -> list[Directive]:
        return [d for d in self.directives if d.kind == "import"]

    def masked_line(self, line_no: int) -> str:
        """The masked text of a 1-based line — safe to regex without string noise."""
        rows = self.masked.split("\n")
        return rows[line_no - 1] if 1 <= line_no <= len(rows) else ""

    def iter_masked_lines(self):
        """Yield (1-based line number, masked text) for every line."""
        for idx, row in enumerate(self.masked.split("\n"), start=1):
            yield idx, row

    def slice(self, line_start: int, line_end: int) -> str:
        return "\n".join(self.lines[line_start - 1 : line_end])


def _units(masked: str, offset: int = 0) -> list[tuple[int, int]]:
    """Split a masked region into top-level statements/declarations.

    A unit runs from its first non-space character to either the `}` that returns
    brace depth to zero, or a `;` seen at depth zero outside parentheses. That
    covers `class X { ... }`, `void f() => y;`, `final a = 1;` and `import '...';`
    with one rule.

    Braces are only counted outside parentheses. Dart spells named and optional
    parameters `({required this.repo})`, and treating those as a body brace would
    cut every such constructor in half; a closure passed as an argument is in the
    same position and is likewise part of the enclosing unit either way.
    """
    units: list[tuple[int, int]] = []
    n = len(masked)
    depth = 0
    paren = 0
    start: int | None = None
    i = 0

    while i < n:
        ch = masked[i]
        if start is None and not ch.isspace():
            start = i

        if ch in "([":
            paren += 1
        elif ch in ")]":
            paren = max(0, paren - 1)
        elif paren == 0 and ch == "{":
            depth += 1
        elif paren == 0 and ch == "}":
            depth = max(0, depth - 1)
            if depth == 0 and start is not None:
                end = i + 1
                # `Map<String, int> get m => {'a': 1};` ends its body on `}` but
                # still owns the trailing `;`. Swallow it so it cannot start a
                # phantom unit of its own.
                probe = end
                while probe < n and masked[probe] in " \t\r\n":
                    probe += 1
                if probe < n and masked[probe] == ";":
                    end = probe + 1
                    i = probe
                units.append((start + offset, end + offset))
                start = None
        elif ch == ";" and depth == 0 and paren == 0 and start is not None:
            units.append((start + offset, i + 1 + offset))
            start = None
        i += 1

    if start is not None:
        units.append((start + offset, n + offset))
    return units


def _body_open(masked: str, start: int, end: int) -> int:
    """Index of the `{` that opens a unit's body, or -1 if it has none.

    Only braces at paren depth zero qualify, so `({required this.repo})` is not
    mistaken for the body of a constructor.
    """
    paren = 0
    i = start
    while i < end:
        ch = masked[i]
        if ch in "([":
            paren += 1
        elif ch in ")]":
            paren = max(0, paren - 1)
        elif paren == 0 and ch == "{":
            return i
        i += 1
    return -1


def _header(masked: str, start: int, end: int) -> str:
    """The signature part of a unit: everything before its body or terminator.

    The `{` and `=>` that end a signature only count at paren depth zero, so a
    parameter list like `({required this.repo})` stays inside the header.
    """
    paren = 0
    i = start
    while i < end:
        ch = masked[i]
        if ch in "([":
            paren += 1
        elif ch in ")]":
            paren = max(0, paren - 1)
        elif paren == 0 and (ch == "{" or masked.startswith("=>", i)):
            return masked[start:i]
        i += 1
    return masked[start:end]


def _strip_annotations(header: str) -> str:
    return _ANNOTATION_RE.sub(" ", header)


def _split_types(raw: str) -> list[str]:
    """Split `A, B<C, D>, E` on top-level commas only."""
    out: list[str] = []
    depth = 0
    current = ""
    for ch in raw:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        out.append(current.strip())
    return [t for t in out if t]


def _classify_top_level(
    text: str, masked: str, start: int, end: int, starts: list[int]
) -> Directive | Declaration | None:
    header = _header(masked, start, end)
    line_start = _line_of(starts, start)
    line_end = _line_of(starts, max(start, end - 1))

    directive = _DIRECTIVE_RE.match(header)
    if directive:
        kw = directive.group("kw").replace("part of", "part_of").split()[0]
        kw = "part_of" if directive.group("kw").startswith("part of") else kw
        # The URI lives in a string, which masking blanked — read it from the original.
        raw_span = text[start:end]
        uri_match = _URI_RE.search(raw_span)
        return Directive(
            kind=kw,
            uri=uri_match.group(1) if uri_match else "",
            line=line_start,
            raw=raw_span.strip(),
        )

    clean = _strip_annotations(header)
    decl = _DECL_RE.search(clean)
    if decl:
        kw = decl.group("kw")
        kind = {
            "mixin class": "class",
            "extension type": "extension",
        }.get(kw, kw)
        node = Declaration(
            name=decl.group("name") or "",
            kind=kind,
            line_start=line_start,
            line_end=line_end,
            is_abstract="abstract" in (decl.group("mods") or ""),
        )
        tail = clean[decl.end() :]
        if m := _EXTENDS_RE.search(tail):
            node.extends = m.group("v").strip()
        if m := _WITH_RE.search(tail):
            node.mixins = _split_types(m.group("v"))
        if m := _IMPLEMENTS_RE.search(tail):
            node.interfaces = _split_types(m.group("v"))
        if m := _ON_RE.search(tail):
            node.on_types = _split_types(m.group("v"))
        if kind in ("class", "mixin", "extension", "enum"):
            node.members = _parse_members(masked, start, end, starts, node.name)
        return node

    # Not a keyword declaration: a top-level function or variable.
    stripped = clean.strip()
    if not stripped:
        return None
    paren = clean.find("(")
    if paren != -1:
        name_match = _NAME_BEFORE_PAREN_RE.search(clean[:paren])
        return Declaration(
            name=name_match.group(1) if name_match else "",
            kind="function",
            line_start=line_start,
            line_end=line_end,
        )
    name_match = _FIELD_NAME_RE.search(stripped) or re.search(IDENT + r"\s*$", stripped)
    return Declaration(
        name=name_match.group(1) if name_match and name_match.groups() else "",
        kind="variable",
        line_start=line_start,
        line_end=line_end,
    )


def _parse_members(
    masked: str, start: int, end: int, starts: list[int], class_name: str
) -> list[Member]:
    body_open = _body_open(masked, start, end)
    if body_open == -1:
        return []
    body_close = end - 1
    while body_close > body_open and masked[body_close] != "}":
        body_close -= 1
    if body_close <= body_open + 1:
        return []

    inner = masked[body_open + 1 : body_close]
    members: list[Member] = []
    for m_start, m_end in _units(inner, offset=body_open + 1):
        member = _classify_member(masked, m_start, m_end, starts, class_name)
        if member is not None:
            members.append(member)
    return members


def _classify_member(
    masked: str, start: int, end: int, starts: list[int], class_name: str
) -> Member | None:
    raw_header = _header(masked, start, end)
    header = _strip_annotations(raw_header)
    stripped = header.strip()
    if not stripped:
        return None

    line_start = _line_of(starts, start)
    line_end = _line_of(starts, max(start, end - 1))
    is_static = bool(re.search(r"\bstatic\b", header))
    is_override = "@override" in raw_header

    def build(name: str, kind: str) -> Member:
        return Member(
            name=name,
            kind=kind,
            line_start=line_start,
            line_end=line_end,
            is_static=is_static,
            is_override=is_override,
        )

    if g := _GETTER_RE.search(header):
        return build(g.group(1), "getter")
    if s := _SETTER_RE.search(header):
        return build(s.group(1), "setter")

    paren = header.find("(")
    if paren != -1:
        before = header[:paren]
        ctor = re.search(
            r"\b" + re.escape(class_name) + r"(?:\.(" + IDENT + r"))?\s*$", before
        ) if class_name else None
        if ctor:
            suffix = ctor.group(1)
            return build(f"{class_name}.{suffix}" if suffix else class_name, "constructor")
        name_match = _NAME_BEFORE_PAREN_RE.search(before)
        return build(name_match.group(1) if name_match else "", "method")

    name_match = _FIELD_NAME_RE.search(stripped)
    if name_match:
        return build(name_match.group(1), "field")
    return build("", "unknown")


def parse_dart(text: str, *, path: str = "") -> DartFile:
    """Parse one Dart source file into directives, declarations and members."""
    masked, literals = mask_source(text)
    starts = _line_starts(text)

    directives: list[Directive] = []
    declarations: list[Declaration] = []
    for start, end in _units(masked):
        node = _classify_top_level(text, masked, start, end, starts)
        if isinstance(node, Directive):
            directives.append(node)
        elif isinstance(node, Declaration):
            declarations.append(node)

    return DartFile(
        path=path,
        text=text,
        masked=masked,
        lines=text.split("\n"),
        directives=directives,
        declarations=declarations,
        literals=literals,
    )
