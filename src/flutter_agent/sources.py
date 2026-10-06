"""The registry of Flutter projects that feed the index.

Unlike docs-mcp, which keeps one index per project, this agent keeps *one* index
over *many* source roots — the whole point is cross-project retrieval ("how do we
do pagination" should find the answer wherever it lives). A source root is a
Flutter app or package; its `name` becomes the `project` column on every chunk.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import CONFIG_FILENAME, SourceConfig, data_home

ROOT_MARKERS = (CONFIG_FILENAME, "pubspec.yaml", ".git")

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_PUBSPEC_NAME_RE = re.compile(r"^name:\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Source:
    root: Path
    name: str
    slug: str

    def config(self) -> SourceConfig:
        return SourceConfig.load(self.root)

    @property
    def lib(self) -> Path:
        return self.root / "lib"

    @property
    def is_package(self) -> bool:
        """A shared package exposes lib/src plus a barrel, and has no lib/features."""
        return (self.root / "lib" / "src").is_dir() and not (self.root / "lib" / "features").is_dir()


def slug_for(root: Path) -> str:
    """Stable, collision-free key for a source root.

    The basename keeps it readable; the path hash keeps two projects that share a
    folder name strictly separate.
    """
    resolved = Path(root).resolve()
    key = str(resolved).replace("\\", "/")
    if os.name == "nt":
        # Case-insensitive filesystem: C:\Apps and c:\apps are one source.
        key = key.lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    base = _SLUG_RE.sub("-", resolved.name).strip("-.") or "root"
    return f"{base[:40]}-{digest}"


def detect_name(root: Path) -> str:
    """The Dart package name from pubspec.yaml, falling back to the folder name.

    This matters beyond cosmetics: the rule that bans `package:<own_project>/`
    imports inside lib/ needs to know what the project calls itself.
    """
    pubspec = Path(root) / "pubspec.yaml"
    if pubspec.is_file():
        try:
            match = _PUBSPEC_NAME_RE.search(pubspec.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            match = None
        if match:
            return match.group(1)
    return Path(root).name


def find_root(start: Path | str | None = None) -> Path:
    """Walk upward from `start` for a pubspec.yaml or an explicit config."""
    cur = Path(start or Path.cwd()).expanduser()
    cur = cur.resolve() if cur.exists() else cur.absolute()
    if cur.is_file():
        cur = cur.parent

    first_marker: Path | None = None
    for parent in [cur, *cur.parents]:
        if (parent / CONFIG_FILENAME).exists():
            return parent
        if first_marker is None and any((parent / m).exists() for m in ROOT_MARKERS):
            first_marker = parent
    return first_marker or cur


def make(root: Path | str) -> Source:
    resolved = find_root(root)
    return Source(root=resolved, name=detect_name(resolved), slug=slug_for(resolved))


# --------------------------------------------------------------------------- registry


def registry_path() -> Path:
    return data_home() / "sources.json"


def read_registry() -> dict[str, dict]:
    path = registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_registry(entries: dict[str, dict]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def add(root: Path | str) -> Source:
    """Register a source root. Idempotent — re-adding refreshes its name."""
    source = make(root)
    if not source.root.is_dir():
        raise ValueError(f"Not a directory: {source.root}")
    if not (source.root / "lib").is_dir():
        raise ValueError(f"No lib/ directory under {source.root} - is this a Flutter project?")

    entries = read_registry()
    entry = entries.get(source.slug, {})
    entry.update(
        {
            "root": str(source.root),
            "name": source.name,
            "kind": "package" if source.is_package else "app",
            "added_at": entry.get("added_at", time.time()),
        }
    )
    entries[source.slug] = entry
    write_registry(entries)
    return source


def update_stats(source: Source, **stats) -> None:
    entries = read_registry()
    entry = entries.get(source.slug)
    if entry is None:
        return
    entry.update(stats)
    entries[source.slug] = entry
    write_registry(entries)


def remove(token: str) -> Source | None:
    found = lookup(token)
    if found is None:
        return None
    entries = read_registry()
    if entries.pop(found.slug, None) is not None:
        write_registry(entries)
    return found


def lookup(token: str) -> Source | None:
    """Find a registered source by slug, name, or path."""
    entries = read_registry()
    if token in entries:
        entry = entries[token]
        return Source(root=Path(entry["root"]), name=entry.get("name", token), slug=token)

    lowered = token.lower()
    for slug, entry in entries.items():
        if str(entry.get("name", "")).lower() == lowered:
            return Source(root=Path(entry["root"]), name=entry["name"], slug=slug)

    candidate = Path(token).expanduser()
    if candidate.exists():
        slug = slug_for(find_root(candidate))
        if slug in entries:
            entry = entries[slug]
            return Source(root=Path(entry["root"]), name=entry["name"], slug=slug)
    return None


def all_sources() -> list[Source]:
    return [
        Source(root=Path(entry["root"]), name=entry.get("name", slug), slug=slug)
        for slug, entry in sorted(read_registry().items(), key=lambda kv: kv[1].get("name", kv[0]))
        if entry.get("root")
    ]


def source_for_path(path: Path | str) -> Source | None:
    """Which registered source contains `path`, if any (longest root wins)."""
    target = Path(path).expanduser()
    target = target.resolve() if target.exists() else target.absolute()
    best: Source | None = None
    for source in all_sources():
        try:
            target.relative_to(source.root)
        except ValueError:
            continue
        if best is None or len(str(source.root)) > len(str(best.root)):
            best = source
    return best
