"""FAISS vector index + SQLite metadata sidecar for the whole corpus.

Adapted from docs-mcp's per-project store, with two changes that matter:

* One index spans many source roots, so `(source, path)` is the file key rather
  than `path` alone.
* Chunks carry architecture metadata (kind/project/feature/layer/symbol), which
  makes `search(..., filters=...)` possible. FAISS cannot filter, so a filtered
  query over-fetches and narrows in SQL.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .chunk import Chunk

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    source     TEXT NOT NULL,
    path       TEXT NOT NULL,
    project    TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'code',
    feature    TEXT NOT NULL DEFAULT '',
    layer      TEXT NOT NULL DEFAULT '',
    sha256     TEXT NOT NULL,
    mtime      REAL NOT NULL,
    size       INTEGER NOT NULL,
    n_lines    INTEGER NOT NULL DEFAULT 0,
    n_chunks   INTEGER NOT NULL DEFAULT 0,
    title      TEXT,
    indexed_at REAL NOT NULL,
    PRIMARY KEY (source, path)
);
CREATE TABLE IF NOT EXISTS chunks (
    id           INTEGER PRIMARY KEY,
    source       TEXT NOT NULL,
    path         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'code',
    project      TEXT NOT NULL DEFAULT '',
    feature      TEXT NOT NULL DEFAULT '',
    layer        TEXT NOT NULL DEFAULT '',
    symbol       TEXT NOT NULL DEFAULT '',
    symbol_kind  TEXT NOT NULL DEFAULT '',
    heading      TEXT NOT NULL DEFAULT '',
    heading_path TEXT NOT NULL DEFAULT '[]',
    level        INTEGER NOT NULL DEFAULT 0,
    line_start   INTEGER NOT NULL,
    line_end     INTEGER NOT NULL,
    part         INTEGER NOT NULL DEFAULT 0,
    total_parts  INTEGER NOT NULL DEFAULT 1,
    n_chars      INTEGER NOT NULL DEFAULT 0,
    text         TEXT NOT NULL,
    FOREIGN KEY (source, path) REFERENCES files(source, path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_file    ON chunks(source, path);
CREATE INDEX IF NOT EXISTS idx_chunks_kind    ON chunks(kind);
CREATE INDEX IF NOT EXISTS idx_chunks_layer   ON chunks(layer);
CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);
CREATE INDEX IF NOT EXISTS idx_chunks_feature ON chunks(feature);
CREATE INDEX IF NOT EXISTS idx_chunks_symbol  ON chunks(symbol);
"""

# Columns a caller may filter a search on.
FILTERABLE = ("kind", "project", "feature", "layer", "symbol", "symbol_kind", "source")


@dataclass
class ChunkRecord:
    """A chunk as it comes back out of the store."""

    id: int
    source: str
    path: str
    kind: str
    project: str
    feature: str
    layer: str
    symbol: str
    symbol_kind: str
    heading: str
    heading_path: list[str]
    level: int
    line_start: int
    line_end: int
    part: int
    total_parts: int
    text: str
    score: float = 0.0

    @property
    def breadcrumb(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else "(file root)"

    @property
    def location_label(self) -> str:
        bits = [b for b in (self.project, self.feature, self.layer) if b]
        return " | ".join(bits)

    @property
    def line_span(self) -> str:
        return f"L{self.line_start}-{self.line_end}"


@dataclass
class FileRecord:
    source: str
    path: str
    project: str
    kind: str
    feature: str
    layer: str
    sha256: str
    mtime: float
    size: int
    n_lines: int
    n_chunks: int
    title: str
    indexed_at: float


@dataclass
class FileMeta:
    """Per-file metadata supplied at index time."""

    project: str = ""
    kind: str = "code"
    feature: str = ""
    layer: str = ""
    n_lines: int = 0
    title: str = ""


class Store:
    """Owns `index.faiss` + `meta.sqlite3` for the whole corpus.

    Vectors are unit-normalised, so the flat inner-product index yields cosine
    similarity directly. IDs are dense int64 from a monotone counter and double as
    the SQLite primary key, which keeps the two halves in sync.
    """

    def __init__(self, directory: Path, *, model: str = "", dimension: int = 0):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "meta.sqlite3"
        self.index_path = self.dir / "index.faiss"
        self._model = model
        self._dimension = dimension
        self._index = None
        self._stamp_loaded: tuple[int, int] | None = None
        self._in_writer = False
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._init_meta()

    # ---------------------------------------------------------------- meta

    def _init_meta(self) -> None:
        if self.get_meta("model") is None and self._model:
            self.set_meta("model", self._model)
        if self.get_meta("dimension") is None and self._dimension:
            self.set_meta("dimension", str(self._dimension))
        if self.get_meta("schema_version") is None:
            self.set_meta("schema_version", str(SCHEMA_VERSION))
        if self.get_meta("next_id") is None:
            self.set_meta("next_id", "1")

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            # Inside writer() an explicit transaction is open; committing here
            # would end it early and break the all-or-nothing guarantee.
            # `in_transaction` is no use: sqlite opens an implicit transaction on
            # any DML, so only the explicit flag distinguishes the two.
            if not self._in_writer:
                self._conn.commit()

    @property
    def model(self) -> str:
        return self.get_meta("model", "") or ""

    @property
    def dimension(self) -> int:
        return int(self.get_meta("dimension", "0") or 0)

    # --------------------------------------------------------------- index

    def _new_index(self, dim: int):
        import faiss

        return faiss.IndexIDMap2(faiss.IndexFlatIP(dim))

    def _stamp(self) -> tuple[int, int] | None:
        try:
            st = self.index_path.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    @property
    def index(self):
        with self._lock:
            if self._index is None:
                import faiss

                if self.index_path.is_file():
                    self._index = faiss.read_index(str(self.index_path))
                    self._stamp_loaded = self._stamp()
                else:
                    dim = self.dimension or self._dimension
                    if not dim:
                        raise RuntimeError("Index dimension unknown; index something first.")
                    self._index = self._new_index(dim)
            return self._index

    def refresh(self) -> None:
        """Drop the cached index if another process rewrote it on disk.

        The store stays alive across MCP calls so search is fast; this keeps that
        cache honest when the CLI reindexes alongside a running server.
        """
        with self._lock:
            if self._index is not None and self._stamp() != self._stamp_loaded:
                self._index = None

    def save(self) -> None:
        with self._lock:
            if self._index is None:
                return
            import faiss

            tmp = self.index_path.with_suffix(".faiss.tmp")
            faiss.write_index(self._index, str(tmp))
            os.replace(tmp, self.index_path)
            self._stamp_loaded = self._stamp()

    @contextmanager
    def writer(self):
        """Serialise index mutations across threads and processes.

        BEGIN IMMEDIATE takes SQLite's write lock, which doubles as the mutex
        protecting the FAISS file beside it.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            self._in_writer = True
            try:
                yield self
            except Exception:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()
                self.save()
            finally:
                self._in_writer = False

    # ------------------------------------------------------------ mutation

    def _alloc_ids(self, count: int) -> list[int]:
        start = int(self.get_meta("next_id", "1") or 1)
        self._conn.execute(
            "INSERT INTO meta(key,value) VALUES('next_id',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(start + count),),
        )
        return list(range(start, start + count))

    def remove_file(self, source: str, rel_path: str) -> int:
        """Drop a file's chunks from both SQLite and FAISS. Returns chunks removed."""
        rows = self._conn.execute(
            "SELECT id FROM chunks WHERE source=? AND path=?", (source, rel_path)
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            import faiss

            selector = faiss.IDSelectorBatch(np.asarray(ids, dtype="int64"))
            try:
                self.index.remove_ids(selector)
            except RuntimeError:
                # Should not happen with IDMap2, but never let a stale vector
                # survive silently: ask for a full rebuild instead.
                self.set_meta("needs_rebuild", "1")
        self._conn.execute("DELETE FROM chunks WHERE source=? AND path=?", (source, rel_path))
        self._conn.execute("DELETE FROM files WHERE source=? AND path=?", (source, rel_path))
        return len(ids)

    def remove_source(self, source: str) -> int:
        """Drop everything belonging to one source root."""
        paths = [
            r["path"]
            for r in self._conn.execute("SELECT path FROM files WHERE source=?", (source,))
        ]
        return sum(self.remove_file(source, p) for p in paths)

    def add_file(
        self,
        source: str,
        rel_path: str,
        *,
        sha256: str,
        mtime: float,
        size: int,
        meta: FileMeta,
        chunks: list[Chunk],
        vectors: np.ndarray,
    ) -> list[int]:
        """Insert a freshly-embedded file. Caller must have removed any old copy."""
        if len(chunks) != len(vectors):
            raise ValueError(f"chunk/vector mismatch: {len(chunks)} vs {len(vectors)}")

        self._conn.execute(
            "INSERT INTO files(source,path,project,kind,feature,layer,sha256,mtime,size,"
            "n_lines,n_chunks,title,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source,path) DO UPDATE SET "
            "project=excluded.project, kind=excluded.kind, feature=excluded.feature, "
            "layer=excluded.layer, sha256=excluded.sha256, mtime=excluded.mtime, "
            "size=excluded.size, n_lines=excluded.n_lines, n_chunks=excluded.n_chunks, "
            "title=excluded.title, indexed_at=excluded.indexed_at",
            (
                source,
                rel_path,
                meta.project,
                meta.kind,
                meta.feature,
                meta.layer,
                sha256,
                mtime,
                size,
                meta.n_lines,
                len(chunks),
                meta.title,
                time.time(),
            ),
        )
        if not chunks:
            return []

        ids = self._alloc_ids(len(chunks))
        self._conn.executemany(
            "INSERT INTO chunks(id,source,path,kind,project,feature,layer,symbol,symbol_kind,"
            "heading,heading_path,level,line_start,line_end,part,total_parts,n_chars,text) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    cid,
                    source,
                    rel_path,
                    c.kind,
                    c.project,
                    c.feature,
                    c.layer,
                    c.symbol,
                    c.symbol_kind,
                    c.heading,
                    json.dumps(c.heading_path, ensure_ascii=False),
                    c.level,
                    c.line_start,
                    c.line_end,
                    c.part,
                    c.total_parts,
                    len(c.text),
                    c.text,
                )
                for cid, c in zip(ids, chunks)
            ],
        )
        arr = np.ascontiguousarray(vectors, dtype="float32")
        if not self.dimension:
            self.set_meta("dimension", str(arr.shape[1]))
            self._dimension = arr.shape[1]
        self.index.add_with_ids(arr, np.asarray(ids, dtype="int64"))
        return ids

    def clear(self) -> None:
        """Wipe the whole index (full reindex, or a model change)."""
        with self._lock:
            self._conn.execute("DELETE FROM chunks")
            self._conn.execute("DELETE FROM files")
            self._conn.execute("DELETE FROM meta WHERE key IN ('next_id','needs_rebuild')")
            self._conn.commit()
            self._index = None
            if self.index_path.is_file():
                self.index_path.unlink()
            self.set_meta("next_id", "1")

    # -------------------------------------------------------------- queries

    def search(
        self,
        vector: np.ndarray,
        k: int,
        *,
        filters: dict[str, str] | None = None,
    ) -> list[ChunkRecord]:
        """Nearest chunks, optionally restricted to a slice of the corpus.

        FAISS has no notion of a WHERE clause, so a filtered query over-fetches
        and narrows in SQL. The index is flat and the corpus is small (thousands
        of chunks), so over-fetching is cheap.
        """
        filters = {k_: v for k_, v in (filters or {}).items() if v and k_ in FILTERABLE}
        with self._lock:
            self.refresh()
            total = self.count_chunks()
            if total == 0:
                return []
            fetch = min(total, max(k * 25, 300)) if filters else min(k, total)
            query = np.ascontiguousarray(vector.reshape(1, -1), dtype="float32")
            scores, ids = self.index.search(query, fetch)

            out: list[ChunkRecord] = []
            for score, cid in zip(scores[0], ids[0]):
                if cid < 0:
                    continue
                rec = self.get_chunk(int(cid))
                if rec is None:
                    continue
                if any(getattr(rec, column) != value for column, value in filters.items()):
                    continue
                rec.score = float(score)
                out.append(rec)
                if len(out) >= k:
                    break
            return out

    def lexical_search(self, needle: str, k: int, *, filters: dict[str, str] | None = None):
        """Exact substring match — for symbol lookups, where embeddings are vague.

        `AppButton` must return `AppButton`, not whichever widget happens to be
        closest in vector space.
        """
        filters = {k_: v for k_, v in (filters or {}).items() if v and k_ in FILTERABLE}
        where = ["text LIKE ? ESCAPE '\\'"]
        params: list[object] = [f"%{_escape_like(needle)}%"]
        for column, value in filters.items():
            where.append(f"{column}=?")
            params.append(value)
        # An exact symbol match outranks an incidental mention, and among equals
        # the smallest chunk is the most likely definition rather than a caller.
        params += [needle, k]
        rows = self._conn.execute(
            f"SELECT * FROM chunks WHERE {' AND '.join(where)} "
            "ORDER BY (symbol=?) DESC, n_chars ASC LIMIT ?",
            params,
        ).fetchall()
        return [_to_chunk_record(r) for r in rows]

    def get_chunk(self, chunk_id: int) -> ChunkRecord | None:
        row = self._conn.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()
        return _to_chunk_record(row) if row else None

    def chunks_for_file(self, source: str, rel_path: str) -> list[ChunkRecord]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE source=? AND path=? ORDER BY line_start, part",
            (source, rel_path),
        ).fetchall()
        return [_to_chunk_record(r) for r in rows]

    def get_file(self, source: str, rel_path: str) -> FileRecord | None:
        row = self._conn.execute(
            "SELECT * FROM files WHERE source=? AND path=?", (source, rel_path)
        ).fetchone()
        return _to_file_record(row) if row else None

    def all_files(self, source: str | None = None) -> list[FileRecord]:
        if source:
            rows = self._conn.execute(
                "SELECT * FROM files WHERE source=? ORDER BY path", (source,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM files ORDER BY source, path").fetchall()
        return [_to_file_record(r) for r in rows]

    def known_hashes(self, source: str) -> dict[str, str]:
        return {
            r["path"]: r["sha256"]
            for r in self._conn.execute(
                "SELECT path, sha256 FROM files WHERE source=?", (source,)
            )
        }

    def distinct(self, column: str, **filters) -> list[str]:
        """Distinct values of a filterable column — powers `list features` style queries."""
        if column not in FILTERABLE:
            raise ValueError(f"not a filterable column: {column}")
        where = [f"{c}=?" for c in filters if c in FILTERABLE]
        params = [v for c, v in filters.items() if c in FILTERABLE]
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn.execute(
            f"SELECT DISTINCT {column} v FROM chunks{clause} ORDER BY v", params
        ).fetchall()
        return [r["v"] for r in rows if r["v"]]

    def counts_by(self, column: str) -> dict[str, int]:
        if column not in FILTERABLE:
            raise ValueError(f"not a filterable column: {column}")
        rows = self._conn.execute(
            f"SELECT {column} v, COUNT(*) c FROM chunks GROUP BY {column} ORDER BY c DESC"
        ).fetchall()
        return {r["v"]: r["c"] for r in rows}

    def count_files(self, source: str | None = None) -> int:
        if source:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM files WHERE source=?", (source,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) c FROM files").fetchone()
        return int(row["c"])

    def count_chunks(self, source: str | None = None) -> int:
        if source:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM chunks WHERE source=?", (source,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()
        return int(row["c"])

    def total_chars(self) -> int:
        row = self._conn.execute("SELECT COALESCE(SUM(n_chars),0) s FROM chunks").fetchone()
        return int(row["s"])

    def index_size_bytes(self) -> int:
        return sum(p.stat().st_size for p in (self.index_path, self.db_path) if p.is_file())

    def verify(self) -> tuple[bool, str]:
        """Check that FAISS and SQLite agree on how many vectors exist."""
        db = self.count_chunks()
        try:
            vec = int(self.index.ntotal) if (self.index_path.is_file() or self._index) else 0
        except RuntimeError:
            vec = 0
        if db != vec:
            return False, f"metadata has {db} chunks but the vector index has {vec}"
        return True, "ok"

    def close(self) -> None:
        with self._lock:
            self._conn.close()
            self._index = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_chunk_record(row: sqlite3.Row) -> ChunkRecord:
    try:
        path_list = json.loads(row["heading_path"])
    except (json.JSONDecodeError, TypeError):
        path_list = []
    return ChunkRecord(
        id=row["id"],
        source=row["source"],
        path=row["path"],
        kind=row["kind"],
        project=row["project"],
        feature=row["feature"],
        layer=row["layer"],
        symbol=row["symbol"],
        symbol_kind=row["symbol_kind"],
        heading=row["heading"],
        heading_path=path_list if isinstance(path_list, list) else [],
        level=row["level"],
        line_start=row["line_start"],
        line_end=row["line_end"],
        part=row["part"],
        total_parts=row["total_parts"],
        text=row["text"],
    )


def _to_file_record(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        source=row["source"],
        path=row["path"],
        project=row["project"],
        kind=row["kind"],
        feature=row["feature"],
        layer=row["layer"],
        sha256=row["sha256"],
        mtime=row["mtime"],
        size=row["size"],
        n_lines=row["n_lines"],
        n_chunks=row["n_chunks"],
        title=row["title"] or "",
        indexed_at=row["indexed_at"],
    )
