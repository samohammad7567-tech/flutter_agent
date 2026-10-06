"""Tool implementations shared by the CLI and the MCP server.

Everything here returns plain text under a character budget: these results land
in a model's context window, so a tool that dumps a whole file is a tool that
makes the agent dumber.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import lessons as lessons_mod
from . import scaffold as scaffold_mod
from . import sources as sources_mod
from .config import (
    ALL_KINDS,
    DEFAULT_MAX_RESPONSE_CHARS,
    DEFAULT_SEARCH_LIMIT,
    KIND_CODE,
    MAX_SEARCH_LIMIT,
    index_dir,
    knowledge_home,
)
from .embedder import detect_device
from .indexer import Indexer
from .layers import LAYER_LABELS
from .rules import ERROR, check_path, summarise
from .store import ChunkRecord

_INDEXER: Indexer | None = None
_LOCK = threading.Lock()

# Accept either the canonical layer id (`data_source`) or its label ("data source").
_LAYER_ALIASES = {label: key for key, label in LAYER_LABELS.items()}


def indexer() -> Indexer:
    """One process-wide indexer, so the embedding model loads at most once."""
    global _INDEXER
    with _LOCK:
        if _INDEXER is None:
            _INDEXER = Indexer()
        return _INDEXER


def reset() -> None:
    """Drop the cached indexer (used by tests)."""
    global _INDEXER
    with _LOCK:
        _INDEXER = None


# ---------------------------------------------------------------------- searching


def search(
    query: str,
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    kind: str | None = None,
    project: str | None = None,
    feature: str | None = None,
    layer: str | None = None,
    symbol: str | None = None,
    show_text: bool = True,
    budget: int = DEFAULT_MAX_RESPONSE_CHARS,
) -> str:
    """Semantic search over the corpus, optionally narrowed to one slice of it."""
    if not query.strip():
        return "Give me something to search for."
    limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    if kind and kind not in ALL_KINDS:
        return f"Unknown kind {kind!r}. Use one of: {', '.join(ALL_KINDS)}."

    filters = _filters(kind=kind, project=project, feature=feature, layer=layer, symbol=symbol)
    hits = indexer().search(query, limit, filters=filters)
    if not hits:
        extra = f" with filters {filters}" if filters else ""
        return f"No matches for {query!r}{extra}. Try `flutter-agent status` to check the index."
    return _render_hits(hits, query=query, show_text=show_text, budget=budget)


def component(name: str = "", *, limit: int = 8, budget: int = DEFAULT_MAX_RESPONSE_CHARS) -> str:
    """The reusable-component catalog, and where each one is actually used.

    With no name it lists what the shared package exports; with one it shows the
    definition plus real call sites, which is the part that answers "how do I use
    this".
    """
    packages = [s for s in sources_mod.all_sources() if s.is_package]
    if not packages:
        return (
            "No shared package is registered. Add one with "
            "`flutter-agent sources add <path-to-corereusablepackage>`."
        )

    if not name.strip():
        lines = []
        for pkg in packages:
            exports = _package_exports(pkg.root)
            lines.append(f"{pkg.name} exports {len(exports)} symbol(s):")
            lines += [f"  {e}" for e in exports]
        return "\n".join(lines) if lines else "The shared package exports nothing yet."

    needle = name.strip()
    ix = indexer()
    definition = ix.lexical(f"class {needle}", 2) or ix.lexical(needle, 2, filters={"symbol": needle})
    usages = [
        hit
        for hit in ix.lexical(needle, limit + 4, filters={"kind": KIND_CODE})
        if hit.symbol != needle
    ][:limit]

    if not definition and not usages:
        return f"Nothing in the corpus mentions {needle!r}."

    out = []
    if definition:
        out.append(f"=== {needle} - definition")
        out.append(_render_hits(definition[:1], show_text=True, budget=budget // 2, scored=False))
    if usages:
        out.append(f"\n=== used in {len(usages)} place(s)")
        for hit in usages:
            out.append(f"  {hit.path}:{hit.line_start}  ({hit.location_label}) {hit.symbol}")
    return "\n".join(out)


def pattern(topic: str, *, limit: int = 1, budget: int = DEFAULT_MAX_RESPONSE_CHARS) -> str:
    """How this codebase does `topic`: the rule, the golden example, the lessons.

    This is the tool to reach for before writing a feature, because it answers
    with the project's own precedent rather than generic Flutter advice.
    """
    if not topic.strip():
        return "Name a topic, e.g. `pagination` or `error mapping`."

    ix = indexer()
    sections: list[str] = []
    for label, kind in (("rules", "rule"), ("patterns", "pattern"), ("lessons", "lesson")):
        hits = ix.search(topic, limit, filters={"kind": kind})
        if hits:
            sections.append(f"=== {label}")
            sections.append(_render_hits(hits, show_text=True, budget=budget // 3, scored=False))

    code = ix.search(topic, limit, filters={"kind": KIND_CODE})
    if code:
        sections.append("=== how it is written in this codebase")
        sections.append(_render_hits(code, show_text=True, budget=budget // 2, scored=False))

    if not sections:
        return (
            f"Nothing indexed for {topic!r}. The knowledge base may be empty - "
            f"add rule cards and golden examples under {knowledge_home()}."
        )
    return "\n".join(sections)


# ----------------------------------------------------------------------- checking


def check(target: str, *, root: str | None = None, budget: int = DEFAULT_MAX_RESPONSE_CHARS) -> str:
    """Report architecture-rule violations for a file, feature or project."""
    path = Path(target).expanduser()
    if not path.exists():
        return f"No such path: {path}"
    try:
        findings, context = check_path(path, root=root)
    except OSError as exc:
        return f"Could not check {path}: {exc}"

    if not findings:
        return f"{path} - clean, no rule violations."

    head = f"{path}\npackage={context.package or '?'}  {summarise(findings)}"
    body: list[str] = []
    used = len(head)
    shown = 0
    for finding in findings:
        block = finding.format()
        if used + len(block) > budget:
            break
        body.append(block)
        used += len(block) + 1
        shown += 1
    if shown < len(findings):
        body.append(f"... and {len(findings) - shown} more (narrow the path to see them)")
    return head + "\n\n" + "\n".join(body)


def refactor_plan(target: str, *, root: str | None = None) -> str:
    """What to split out of an oversized file, and the precedent to copy.

    Deliberately a plan rather than an edit: the rule engine knows what is wrong
    and retrieval knows what good looks like, but the actual restructuring is a
    judgement call that belongs to whoever is reading this.
    """
    path = Path(target).expanduser()
    if not path.is_file():
        return f"Point me at a Dart file. {path} is not one."

    from .dart_parser import parse_dart
    from .layers import classify
    from .rules import _read

    text = _read(path)
    parsed = parse_dart(text, path=path.name)
    findings, context = check_path(path, root=root)
    try:
        rel = path.resolve().relative_to(Path(context.root)).as_posix()
    except ValueError:
        rel = path.name
    location = classify(rel, project=context.package)
    soft, hard = location.line_budget

    out = [f"{rel}", f"  layer: {location.label}   lines: {parsed.line_count} (target {soft}, ceiling {hard})"]
    if findings:
        out.append(f"  rules: {summarise(findings)}")
        out += [f"    {f.rule_id} L{f.line}: {f.message}" for f in findings[:8]]

    biggest = sorted(
        (
            (decl, member)
            for decl in parsed.declarations
            for member in decl.members
            if member.kind in ("method", "getter")
        ),
        key=lambda pair: pair[1].line_count,
        reverse=True,
    )[:6]
    if biggest and parsed.line_count > soft:
        out.append("\n  split candidates, largest first:")
        for decl, member in biggest:
            # A private class in a body file is already an extracted widget; it
            # just has not been given a file yet.
            destination = (
                "presentation/widgets/"
                if decl.name.startswith("_") or member.name.startswith("_")
                else "presentation/refactor/"
            )
            label = f"{decl.name}.{member.name}"
            out.append(
                f"    {label:34} L{member.line_start}-{member.line_end} "
                f"({member.line_count} lines) -> {destination}"
            )

    example = indexer().search(
        f"{location.label} for {location.feature or 'a feature'}", 1, filters={"layer": location.layer}
    )
    if example:
        out.append("\n  closest clean precedent in the corpus:")
        out.append(f"    {example[0].path}:{example[0].line_start} ({example[0].location_label})")
    return "\n".join(out)


# --------------------------------------------------------------------- scaffolding


def scaffold(feature: str, *, root: str, write: bool = False, force: bool = False) -> str:
    """Plan (and optionally write) a complete feature folder."""
    project_root = Path(root).expanduser()
    if not project_root.is_dir():
        return f"No such directory: {project_root}"
    try:
        plan_ = scaffold_mod.plan(project_root, feature)
    except ValueError as exc:
        return f"Cannot scaffold: {exc}"

    if not write:
        return plan_.render(with_content=True) + "\n\n(dry run - nothing written)"

    try:
        written = scaffold_mod.apply(plan_, force=force)
    except FileExistsError as exc:
        return f"{exc}\nRe-run with force=true to overwrite."
    return (
        plan_.render()
        + "\n\nwrote "
        + str(len(written))
        + " file(s). Run `flutter analyze` to confirm."
    )


# ------------------------------------------------------------------------ lessons


def lesson_add(
    topic: str,
    right: str,
    *,
    wrong: str = "",
    why: str = "",
    tags: list[str] | None = None,
    layer: str = "",
    feature: str = "",
    project: str = "",
    source_path: str = "",
    rule_id: str = "",
    reindex_now: bool = True,
) -> str:
    """Record one correction so the same mistake is not repeated next session."""
    try:
        lesson = lessons_mod.add(
            topic,
            right,
            wrong=wrong,
            why=why,
            tags=tags,
            layer=layer,
            feature=feature,
            project=project,
            source_path=source_path,
            rule_id=rule_id,
        )
    except ValueError as exc:
        return f"Not recorded: {exc}"

    note = ""
    if reindex_now:
        indexer().index()
        note = " and indexed"
    return f"Recorded lesson {lesson.id}{note}: {lesson.title}"


def lessons_list(query: str = "", *, limit: int = 10) -> str:
    """Recall lessons, by relevance when given a query, else most recent first."""
    if query.strip():
        hits = indexer().search(query, limit, filters={"kind": "lesson"})
        if not hits:
            return f"No lessons match {query!r}."
        return _render_hits(hits, show_text=True, scored=False)

    records = sorted(lessons_mod.load_all(), key=lambda l: l.created_at, reverse=True)[:limit]
    if not records:
        return f"No lessons recorded yet ({lessons_mod.lessons_path()})."
    return "\n\n".join(f"[{r.id}] {r.as_markdown()}" for r in records)


def export_dataset(out_path: str) -> str:
    count = lessons_mod.export_dataset(out_path)
    return f"Wrote {count} training example(s) to {out_path}."


# ------------------------------------------------------------------------- admin


def reindex(*, force: bool = False, progress=None) -> str:
    return indexer().index(force=force, progress=progress).summary()


def sources_add(path: str) -> str:
    try:
        source = sources_mod.add(path)
    except ValueError as exc:
        return f"Not added: {exc}"
    kind = "package" if source.is_package else "app"
    return f"Registered {source.name} ({kind}) at {source.root}. Run `flutter-agent index` next."


def sources_remove(token: str) -> str:
    removed = sources_mod.remove(token)
    if removed is None:
        return f"No registered source matches {token!r}."
    return f"Removed {removed.name}. Run `flutter-agent index` to drop it from the index."


def sources_list() -> str:
    registry = sources_mod.read_registry()
    if not registry:
        return "No source roots registered. Add one with `flutter-agent sources add <path>`."
    lines = []
    for slug, entry in sorted(registry.items(), key=lambda kv: kv[1].get("name", kv[0])):
        files = entry.get("files", "?")
        chunks = entry.get("chunks", "?")
        lines.append(
            f"{entry.get('name', slug):24} {entry.get('kind', 'app'):8} "
            f"files={files:<5} chunks={chunks:<5} {entry.get('root', '')}"
        )
    return "\n".join(lines)


def status() -> str:
    store = indexer().store
    ok, message = store.verify()
    lines = [
        f"index:   {index_dir()}",
        f"model:   {store.model or '(unset)'}  dim={store.dimension}",
        f"device:  {detect_device().describe()}",
        f"files:   {store.count_files()}",
        f"chunks:  {store.count_chunks()}  ({store.total_chars()} chars)",
        f"size:    {store.index_size_bytes() / 1_048_576:.1f} MB",
        f"health:  {'ok' if ok else 'BROKEN - ' + message}",
    ]
    by_kind = store.counts_by("kind")
    if by_kind:
        lines.append("kinds:   " + ", ".join(f"{k}={v}" for k, v in by_kind.items()))
    by_layer = store.counts_by("layer")
    if by_layer:
        lines.append("layers:  " + ", ".join(f"{k}={v}" for k, v in by_layer.items() if k))
    lines.append(f"knowledge: {knowledge_home()}")
    return "\n".join(lines)


def gpu_report() -> str:
    info = detect_device()
    lines = [f"device: {info.describe()}", f"cuda available: {info.cuda_available}"]
    if info.reason:
        lines.append(f"reason: {info.reason}")
    if info.device != "cuda":
        lines.append(
            "Install the CUDA PyTorch wheel to use the GPU, or set FLUTTER_AGENT_DEVICE=cpu "
            "to silence this."
        )
    return "\n".join(lines)


# ------------------------------------------------------------------------ helpers


def _filters(**kwargs) -> dict[str, str]:
    out = {}
    for key, value in kwargs.items():
        if not value:
            continue
        value = str(value).strip()
        if key == "layer":
            value = _LAYER_ALIASES.get(value, value)
            # The store holds the human label, which is what the chunker wrote.
            value = LAYER_LABELS.get(value, value)
        out[key] = value
    return out


def _render_hits(
    hits: list[ChunkRecord],
    *,
    query: str = "",
    show_text: bool = True,
    budget: int = DEFAULT_MAX_RESPONSE_CHARS,
    scored: bool = True,
) -> str:
    out: list[str] = []
    used = 0
    for rank, hit in enumerate(hits, start=1):
        head = f"{rank}. {hit.path}:{hit.line_start}-{hit.line_end}"
        if scored:
            head += f"  (score {hit.score:.3f})"
        meta = hit.location_label
        if hit.symbol:
            meta = f"{meta} | {hit.symbol}" if meta else hit.symbol
        if hit.total_parts > 1:
            meta += f" [part {hit.part + 1}/{hit.total_parts}]"
        block = f"{head}\n   {meta}"
        if show_text:
            body = hit.text.rstrip()
            remaining = budget - used - len(block)
            if remaining < 200:
                out.append(block + "\n   (text omitted - response budget reached)")
                break
            if len(body) > remaining:
                body = body[:remaining].rstrip() + "\n// ... truncated"
            block += "\n" + _indent(body)
        out.append(block)
        used += len(block)
        if used >= budget:
            break
    if query and len(out) < len(hits):
        out.append(f"({len(hits) - len(out)} further match(es) omitted)")
    return "\n\n".join(out)


def _indent(text: str, prefix: str = "   ") -> str:
    return "\n".join(prefix + line for line in text.split("\n"))


def _package_exports(root: Path) -> list[str]:
    """Symbols a shared package re-exports, read from its barrel file."""
    barrels = sorted(Path(root).glob("lib/*.dart"))
    out: list[str] = []
    for barrel in barrels:
        try:
            text = barrel.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("export "):
                start = stripped.find("'")
                end = stripped.find("'", start + 1)
                if start != -1 and end != -1:
                    out.append(stripped[start + 1 : end])
    return out
