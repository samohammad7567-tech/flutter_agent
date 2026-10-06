"""Incremental indexing across every registered source plus the knowledge base.

Only files whose SHA-256 changed are re-embedded, so a reindex after editing one
Cubit costs one embedding call rather than nine hundred.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from . import lessons as lessons_mod
from . import sources as sources_mod
from .chunk import Chunk
from .config import (
    KIND_PATTERN,
    KIND_RULE,
    SourceConfig,
    index_dir,
    knowledge_home,
    model_name,
)
from .dart_chunker import chunk_dart
from .embedder import Embedder, get_embedder
from .layers import classify
from .markdown_parser import parse_markdown
from .md_chunker import chunk_document
from .sources import Source
from .store import ChunkRecord, FileMeta, Store

ProgressFn = Callable[[str], None]

# The pseudo-source that owns rule cards, golden patterns and lessons.
KNOWLEDGE_SOURCE = "__knowledge__"
LESSONS_REL = "lessons/lessons.jsonl"


@dataclass
class SourceResult:
    name: str
    root: str
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    chunks_embedded: int = 0

    @property
    def changed(self) -> int:
        return len(self.added) + len(self.updated) + len(self.deleted)

    def summary(self) -> str:
        return (
            f"{self.name}: +{len(self.added)} ~{len(self.updated)} -{len(self.deleted)} "
            f"={len(self.unchanged)}"
            + (f" skipped={len(self.skipped)}" if self.skipped else "")
        )


@dataclass
class IndexResult:
    sources: list[SourceResult] = field(default_factory=list)
    total_files: int = 0
    total_chunks: int = 0
    chunks_embedded: int = 0
    device: str = ""
    model: str = ""
    seconds: float = 0.0
    full_rebuild: bool = False

    @property
    def changed(self) -> int:
        return sum(s.changed for s in self.sources)

    def summary(self) -> str:
        head = (
            f"files={self.total_files}  chunks={self.total_chunks}  "
            f"embedded={self.chunks_embedded}  device={self.device}  {self.seconds:.2f}s"
        )
        if self.full_rebuild:
            head = "full rebuild  " + head
        return "\n".join([head] + [f"  {s.summary()}" for s in self.sources])


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_text(path: Path) -> str:
    """Read tolerantly - source in the wild is not always clean UTF-8."""
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def discover(root: Path, config: SourceConfig) -> Iterator[Path]:
    """Walk a source root, yielding files that pass include/exclude."""
    root = Path(root)
    dir_excludes = [p[:-3] for p in config.exclude if p.endswith("/**")]

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel_dir = current.relative_to(root).as_posix()
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not _is_pruned((f"{rel_dir}/{d}" if rel_dir != "." else d), dir_excludes, config)
        )
        for name in sorted(filenames):
            rel = (current / name).relative_to(root).as_posix()
            if config.matches(rel):
                yield root / rel


def _is_pruned(rel_dir: str, dir_excludes: list[str], config: SourceConfig) -> bool:
    from .config import _glob_match

    for pattern in dir_excludes:
        if _glob_match(rel_dir, pattern) or rel_dir.split("/")[-1] == pattern:
            return True
    return any(_glob_match(rel_dir + "/", p) for p in config.exclude if p.endswith("/"))


class Indexer:
    """Builds and refreshes the one global index."""

    def __init__(self, *, embedder: Embedder | None = None, store: Store | None = None):
        self.model = model_name()
        self.embedder = embedder or get_embedder(self.model)
        self._store = store

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = Store(index_dir(), model=self.model)
        return self._store

    # ------------------------------------------------------------------ index

    def index(self, *, force: bool = False, progress: ProgressFn | None = None) -> IndexResult:
        started = time.time()
        say = progress or (lambda _msg: None)
        store = self.store
        result = IndexResult(model=self.model)

        # A model change invalidates every existing vector.
        stored_model = store.model
        if stored_model and stored_model != self.model:
            say(f"model changed ({stored_model} -> {self.model}); rebuilding")
            force = True
        if store.get_meta("needs_rebuild") == "1":
            force = True

        if force:
            store.clear()
            store.set_meta("model", self.model)
            result.full_rebuild = True

        registered = sources_mod.all_sources()
        if not registered:
            say("no source roots registered - run `flutter-agent sources add <path>`")

        for source in registered:
            result.sources.append(self._index_source(source, force=force, say=say))

        result.sources.append(self._index_knowledge(force=force, say=say))

        # Drop every source that was unregistered since the last run.
        live = {s.slug for s in registered} | {KNOWLEDGE_SOURCE}
        stale = [slug for slug in store.distinct("source") if slug not in live]
        if stale:
            with store.writer():
                for slug in stale:
                    store.remove_source(slug)
            say(f"dropped unregistered source(s): {', '.join(stale)}")

        result.chunks_embedded = sum(s.chunks_embedded for s in result.sources)
        result.total_files = store.count_files()
        result.total_chunks = store.count_chunks()
        result.device = self.embedder.info.device if result.total_chunks else "n/a"
        result.seconds = time.time() - started
        return result

    def _index_source(self, source: Source, *, force: bool, say: ProgressFn) -> SourceResult:
        config = source.config()
        result = SourceResult(name=source.name, root=str(source.root))
        store = self.store
        known = store.known_hashes(source.slug)
        seen: set[str] = set()
        pending: list[tuple[str, Path, str, float, int]] = []

        for path in discover(source.root, config):
            rel = path.relative_to(source.root).as_posix()
            seen.add(rel)
            try:
                stat = path.stat()
                if stat.st_size > config.max_file_bytes:
                    result.skipped.append((rel, f"larger than {config.max_file_bytes} bytes"))
                    continue
                digest = file_hash(path)
            except OSError as exc:
                result.skipped.append((rel, str(exc)))
                continue

            if not force and known.get(rel) == digest:
                result.unchanged.append(rel)
                continue
            pending.append((rel, path, digest, stat.st_mtime, stat.st_size))
            (result.updated if rel in known else result.added).append(rel)

        result.deleted = sorted(set(known) - seen)
        if not pending and not result.deleted:
            return result

        # Parse everything before touching the model, so a parse error costs nothing.
        parsed: list[tuple[str, str, float, int, list[Chunk], FileMeta]] = []
        for rel, path, digest, mtime, size in pending:
            try:
                text = read_text(path)
            except OSError as exc:
                result.skipped.append((rel, str(exc)))
                for bucket in (result.added, result.updated):
                    if rel in bucket:
                        bucket.remove(rel)
                continue
            location = classify(rel, project=source.name)
            chunks, title = chunk_dart(text, location=location, config=config, path=rel)
            meta = FileMeta(
                project=source.name,
                kind="code",
                feature=location.feature,
                layer=location.layer,
                n_lines=text.count("\n") + 1,
                title=title,
            )
            parsed.append((rel, digest, mtime, size, chunks, meta))

        self._embed_and_store(source.slug, parsed, result, say, label=source.name)
        sources_mod.update_stats(
            source,
            last_indexed=time.time(),
            files=store.count_files(source.slug),
            chunks=store.count_chunks(source.slug),
        )
        return result

    def _index_knowledge(self, *, force: bool, say: ProgressFn) -> SourceResult:
        """Index rule cards, golden patterns (Markdown) and the lesson log (JSONL)."""
        home = knowledge_home()
        result = SourceResult(name="knowledge", root=str(home))
        store = self.store
        known = store.known_hashes(KNOWLEDGE_SOURCE)
        seen: set[str] = set()
        parsed: list[tuple[str, str, float, int, list[Chunk], FileMeta]] = []

        for path in sorted(home.rglob("*.md")) if home.is_dir() else []:
            rel = path.relative_to(home).as_posix()
            seen.add(rel)
            try:
                stat = path.stat()
                digest = file_hash(path)
            except OSError as exc:
                result.skipped.append((rel, str(exc)))
                continue
            if not force and known.get(rel) == digest:
                result.unchanged.append(rel)
                continue
            (result.updated if rel in known else result.added).append(rel)

            text = read_text(path)
            kind = KIND_RULE if rel.startswith("rules/") else KIND_PATTERN
            chunks = chunk_document(parse_markdown(text))
            title = _markdown_title(text, path.stem)
            for chunk in chunks:
                chunk.kind = kind
                chunk.symbol = title
                chunk.symbol_kind = kind
            parsed.append(
                (
                    rel,
                    digest,
                    stat.st_mtime,
                    stat.st_size,
                    chunks,
                    FileMeta(project="knowledge", kind=kind, n_lines=text.count("\n") + 1, title=title),
                )
            )

        # Lessons live in one append-only file; re-chunk it whenever it moves.
        lessons_file = lessons_mod.lessons_path()
        if lessons_file.is_file():
            seen.add(LESSONS_REL)
            stat = lessons_file.stat()
            digest = file_hash(lessons_file)
            if not force and known.get(LESSONS_REL) == digest:
                result.unchanged.append(LESSONS_REL)
            else:
                (result.updated if LESSONS_REL in known else result.added).append(LESSONS_REL)
                records = lessons_mod.load_all()
                parsed.append(
                    (
                        LESSONS_REL,
                        digest,
                        stat.st_mtime,
                        stat.st_size,
                        lessons_mod.to_chunks(records),
                        FileMeta(
                            project="knowledge",
                            kind="lesson",
                            n_lines=len(records),
                            title="lessons",
                        ),
                    )
                )

        result.deleted = sorted(set(known) - seen)
        if not parsed and not result.deleted:
            return result
        self._embed_and_store(KNOWLEDGE_SOURCE, parsed, result, say, label="knowledge")
        return result

    def _embed_and_store(
        self,
        source_slug: str,
        parsed: list[tuple[str, str, float, int, list[Chunk], FileMeta]],
        result: SourceResult,
        say: ProgressFn,
        *,
        label: str,
    ) -> None:
        store = self.store
        flat: list[str] = []
        for rel, _d, _m, _s, chunks, _meta in parsed:
            file_label = rel.rsplit("/", 1)[-1]
            flat.extend(c.embed_text(file_label) for c in chunks)

        vectors = None
        if flat:
            say(
                f"{label}: embedding {len(flat)} chunks from {len(parsed)} file(s) "
                f"on {self.embedder.info.describe()}"
            )
            vectors = self.embedder.encode(flat, show_progress=False)
            result.chunks_embedded = len(flat)

        with store.writer():
            for rel in result.deleted:
                store.remove_file(source_slug, rel)
            cursor = 0
            for rel, digest, mtime, size, chunks, meta in parsed:
                store.remove_file(source_slug, rel)
                slice_ = (
                    vectors[cursor : cursor + len(chunks)]
                    if vectors is not None and chunks
                    else _no_vectors()
                )
                cursor += len(chunks)
                store.add_file(
                    source_slug,
                    rel,
                    sha256=digest,
                    mtime=mtime,
                    size=size,
                    meta=meta,
                    chunks=chunks,
                    vectors=slice_,
                )

    # ----------------------------------------------------------------- query

    def search(
        self, query: str, limit: int = 5, *, filters: dict[str, str] | None = None
    ) -> list[ChunkRecord]:
        if not query.strip() or self.store.count_chunks() == 0:
            return []
        vector = self.embedder.encode([query], is_query=True)[0]
        return self.store.search(vector, limit, filters=filters)

    def lexical(
        self, needle: str, limit: int = 5, *, filters: dict[str, str] | None = None
    ) -> list[ChunkRecord]:
        if not needle.strip():
            return []
        return self.store.lexical_search(needle, limit, filters=filters)


def _markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped and not stripped.startswith(("---", "+++")):
            break
    return fallback


def _no_vectors() -> np.ndarray:
    """An empty vector block for a file that produced no chunks.

    Its width is irrelevant - add_file never reaches FAISS with an empty chunk
    list - and asking the embedder for its dimension here would load the model
    just to index a directory of empty files.
    """
    return np.zeros((0, 1), dtype="float32")
