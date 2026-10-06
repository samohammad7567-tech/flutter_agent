"""Global paths, defaults and per-source configuration (.flutter-agent.json)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CONFIG_FILENAME = ".flutter-agent.json"

# Dart is the corpus. Markdown is picked up only under knowledge/ (handled by the
# knowledge indexer), never by walking a Flutter project.
DEFAULT_INCLUDE = ["**/*.dart"]

DEFAULT_EXCLUDE = [
    ".git/**",
    ".dart_tool/**",
    "build/**",
    "ios/**",
    "android/**",
    "web/**",
    "linux/**",
    "macos/**",
    "windows/**",
    "test/**",
    "integration_test/**",
    "node_modules/**",
    ".idea/**",
    ".vscode/**",
    ".flutter-agent/**",
    # Generated code carries no architectural signal and would swamp retrieval.
    "**/*.g.dart",
    "**/*.freezed.dart",
    "**/*.gr.dart",
    "**/*.config.dart",
    "**/*.mocks.dart",
    "**/generated_plugin_registrant.dart",
    "**/generated/**",
    "**/l10n/**",
]

# all-MiniLM-L6-v2: 384 dims, ~90 MB, fast on a 6 GB laptop GPU, good enough for
# code-with-context retrieval once the metadata header is prepended.
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Code chunks run longer than prose: a whole Cubit method is the useful unit.
DEFAULT_MAX_CHUNK_CHARS = 2400
DEFAULT_MIN_CHUNK_CHARS = 60
DEFAULT_OVERLAP_CHARS = 200
DEFAULT_SEARCH_LIMIT = 3
MAX_SEARCH_LIMIT = 30

# Hard ceiling on a single tool response, so retrieval can never blow up the
# caller's context window.
DEFAULT_MAX_RESPONSE_CHARS = 6000
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024

# Corpus kinds stored in the `kind` column.
KIND_CODE = "code"
KIND_RULE = "rule"
KIND_PATTERN = "pattern"
KIND_LESSON = "lesson"
ALL_KINDS = (KIND_CODE, KIND_RULE, KIND_PATTERN, KIND_LESSON)


def data_home() -> Path:
    """Root directory for the index and knowledge store. Override: FLUTTER_AGENT_HOME."""
    env = os.environ.get("FLUTTER_AGENT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".flutter-agent"


def index_dir() -> Path:
    """The single global index. Unlike docs-mcp there is one brain, not one per project."""
    return data_home() / "index"


def knowledge_home() -> Path:
    """Where rule cards, golden patterns and lessons live.

    Defaults to the repo's own `knowledge/` directory when running from a source
    checkout, so edits are version-controlled; override with FLUTTER_AGENT_KNOWLEDGE.
    """
    env = os.environ.get("FLUTTER_AGENT_KNOWLEDGE")
    if env:
        return Path(env).expanduser().resolve()
    repo_knowledge = Path(__file__).resolve().parents[2] / "knowledge"
    if repo_knowledge.is_dir():
        return repo_knowledge
    return data_home() / "knowledge"


def model_name() -> str:
    return os.environ.get("FLUTTER_AGENT_MODEL", DEFAULT_MODEL)


def device_override() -> str | None:
    """'cuda', 'cpu', or None for auto-detect."""
    dev = os.environ.get("FLUTTER_AGENT_DEVICE", "").strip().lower()
    return dev or None


@dataclass
class SourceConfig:
    """Resolved contents of a source root's .flutter-agent.json (or the defaults)."""

    include: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE))
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    model: str | None = None
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS
    overlap_chars: int = DEFAULT_OVERLAP_CHARS
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    source: str | None = None  # path of the config file, if one was found

    @property
    def effective_model(self) -> str:
        return self.model or model_name()

    @classmethod
    def load(cls, root: Path) -> "SourceConfig":
        path = Path(root) / CONFIG_FILENAME
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A broken config must never make the whole source root unusable.
            return cls()
        if not isinstance(raw, dict):
            return cls()

        def _strlist(key: str, default: list[str]) -> list[str]:
            val = raw.get(key)
            if isinstance(val, list) and all(isinstance(x, str) for x in val):
                return val or default
            return default

        def _int(key: str, default: int) -> int:
            val = raw.get(key)
            return val if isinstance(val, int) and val > 0 else default

        model = raw.get("model")
        extra = _strlist("exclude_extra", [])
        return cls(
            include=_strlist("include", list(DEFAULT_INCLUDE)),
            exclude=_strlist("exclude", list(DEFAULT_EXCLUDE)) + extra,
            model=model if isinstance(model, str) and model else None,
            max_chunk_chars=_int("max_chunk_chars", DEFAULT_MAX_CHUNK_CHARS),
            min_chunk_chars=_int("min_chunk_chars", DEFAULT_MIN_CHUNK_CHARS),
            overlap_chars=_int("overlap_chars", DEFAULT_OVERLAP_CHARS),
            max_file_bytes=_int("max_file_bytes", DEFAULT_MAX_FILE_BYTES),
            source=str(path),
        )

    def matches(self, rel_posix: str) -> bool:
        """True if a root-relative POSIX path should be indexed."""
        if not any(_glob_match(rel_posix, pat) for pat in self.include):
            return False
        return not any(_glob_match(rel_posix, pat) for pat in self.exclude)


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    """Translate a glob to a regex with real `**` semantics.

    fnmatch is not usable directly: it lets `*` cross `/`, and it treats `**/`
    as requiring at least one directory. Here `**/` means "zero or more
    directories", `**` matches across separators, and `*`/`?` never do.
    """
    out = ["(?s:"]
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            close = pattern.find("]", i + 1)
            if close == -1:
                out.append(re.escape(ch))
                i += 1
            else:
                inner = pattern[i + 1 : close].replace("\\", "\\\\")
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                out.append(f"[{inner}]")
                i = close + 1
        else:
            out.append(re.escape(ch))
            i += 1
    out.append(r")\Z")
    return re.compile("".join(out))


def _glob_match(path: str, pattern: str) -> bool:
    if _compile(pattern).match(path):
        return True
    # `dir/**` should also match the directory entry itself.
    if pattern.endswith("/**") and _compile(pattern[:-3]).match(path):
        return True
    # An unanchored pattern such as `build/**` is expected to apply at any depth,
    # so `packages/app/build/x.dart` is excluded too.
    if not pattern.startswith(("**", "/")):
        return bool(_compile("**/" + pattern).match(path))
    return False
