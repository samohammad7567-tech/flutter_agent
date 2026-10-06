"""Generate a complete feature folder in the house architecture.

Templates are rendered from `templates/*.tmpl`, which were derived from
`bilhikma/lib/features/archive` - the cleanest instance of the layout in the
corpus. Nothing here is a placeholder: the output compiles as written, and the
only thing left to do is replace the data source's stub call with the real one.

Planning and writing are separate. `plan()` is pure and returns every file and
edit it would make; `apply()` is the only function that touches the disk.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"

# template stem -> path inside lib/features/<feature>/
_LAYOUT = {
    "data_source": "data/data_source/{feature}_data_source.dart",
    "model": "data/models/{feature}_model.dart",
    "repo": "data/repos/{feature}_repo.dart",
    "cubit": "presentation/cubit/{feature}_cubit.dart",
    "state": "presentation/cubit/{feature}_state.dart",
    "body": "presentation/refactor/{feature}_body.dart",
    "screen": "presentation/screens/{feature}_screen.dart",
    "widget": "presentation/widgets/{feature}_tile.dart",
}

_DEFAULT_LANG_KEYS = "lib/core/localization/lang_keys.dart"
_TRANSLATIONS_DIR = "assets/translations"
_DEFAULT_LOCALES = ("ar", "en")

_LANG_KEYS_STUB = """class LangKeys {
  LangKeys._();
}
"""


@dataclass
class PlannedFile:
    path: str  # project-relative, POSIX
    content: str
    exists: bool = False

    @property
    def status(self) -> str:
        return "CONFLICT (exists)" if self.exists else "new"


@dataclass
class PlannedEdit:
    path: str
    description: str
    content: str
    exists: bool = True


@dataclass
class ScaffoldPlan:
    feature: str
    root: Path
    files: list[PlannedFile] = field(default_factory=list)
    edits: list[PlannedEdit] = field(default_factory=list)
    keys: dict[str, str] = field(default_factory=dict)  # LangKeys constant -> key
    notes: list[str] = field(default_factory=list)

    @property
    def conflicts(self) -> list[PlannedFile]:
        return [f for f in self.files if f.exists]

    def render(self, *, with_content: bool = False) -> str:
        lines = [f"feature `{self.feature}` in {self.root}", ""]
        lines.append("files:")
        for item in self.files:
            lines.append(f"  [{item.status:17}] {item.path}")
        lines.append("")
        lines.append("edits:")
        for edit in self.edits:
            lines.append(f"  [{'update' if edit.exists else 'create':17}] {edit.path} - {edit.description}")
        if self.keys:
            lines.append("")
            lines.append("localization keys:")
            for const, key in self.keys.items():
                lines.append(f"  LangKeys.{const} = '{key}'")
        if self.notes:
            lines.append("")
            lines.extend(f"note: {n}" for n in self.notes)
        if self.conflicts:
            lines.append("")
            lines.append(
                f"{len(self.conflicts)} file(s) already exist - nothing was written. "
                "Re-run with force to overwrite."
            )
        if with_content:
            for item in self.files:
                lines += ["", f"----- {item.path}", item.content]
        return "\n".join(lines)


# --------------------------------------------------------------------------- naming


def to_snake(value: str) -> str:
    """`LessonDetail`, `lesson-detail`, `lesson detail` -> `lesson_detail`."""
    value = re.sub(r"[\s\-]+", "_", value.strip())
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    value = re.sub(r"[^A-Za-z0-9_]", "", value)
    return re.sub(r"_+", "_", value).strip("_").lower()


def to_pascal(snake: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in snake.split("_") if part)


def to_camel(snake: str) -> str:
    pascal = to_pascal(snake)
    return pascal[:1].lower() + pascal[1:]


def names_for(feature: str) -> dict[str, str]:
    snake = to_snake(feature)
    if not snake:
        raise ValueError("feature name is empty after normalisation")
    if snake[0].isdigit():
        raise ValueError(f"feature name cannot start with a digit: {feature!r}")
    return {
        "feature": snake,
        "Feature": to_pascal(snake),
        "featureCamel": to_camel(snake),
        "feature_words": snake.replace("_", " "),
        "error_key": f"{snake}_load_failed",
    }


def keys_for(feature: str) -> dict[str, str]:
    """LangKeys constant name -> translation key, for one scaffolded feature."""
    snake = to_snake(feature)
    camel = to_camel(snake)
    return {
        f"{camel}Title": f"{snake}_title",
        f"{camel}Empty": f"{snake}_empty",
        f"{camel}Error": f"{snake}_error",
        f"{camel}LoadFailed": f"{snake}_load_failed",
    }


# ----------------------------------------------------------------------------- plan


def plan(root: Path | str, feature: str, *, locales: tuple[str, ...] = _DEFAULT_LOCALES) -> ScaffoldPlan:
    """Work out every file and edit, without touching the disk."""
    root = Path(root).expanduser().resolve()
    tokens = names_for(feature)
    snake = tokens["feature"]
    result = ScaffoldPlan(feature=snake, root=root, keys=keys_for(snake))

    lang_keys_rel = _find_lang_keys(root)
    base = f"lib/features/{snake}"

    for stem, pattern in _LAYOUT.items():
        rel = f"{base}/{pattern.format(feature=snake)}"
        content = _render(
            stem,
            tokens
            | {"lang_keys_import": _relative_import(rel, lang_keys_rel)},
        )
        result.files.append(
            PlannedFile(path=rel, content=content, exists=(root / rel).is_file())
        )

    result.edits.append(_plan_lang_keys(root, lang_keys_rel, result.keys))
    for locale in locales:
        result.edits.append(_plan_translations(root, locale, result.keys, snake))

    if not (root / "pubspec.yaml").is_file():
        result.notes.append(f"{root} has no pubspec.yaml - is this the project root?")
    return result


def _plan_lang_keys(root: Path, rel: str, keys: dict[str, str]) -> PlannedEdit:
    path = root / rel
    exists = path.is_file()
    text = path.read_text(encoding="utf-8") if exists else _LANG_KEYS_STUB

    missing = {c: k for c, k in keys.items() if not re.search(rf"\b{re.escape(c)}\b", text)}
    if not missing:
        return PlannedEdit(rel, "already has every key", text, exists)

    block = "".join(f"  static const {const} = '{key}';\n" for const, key in missing.items())
    close = text.rfind("}")
    if close == -1:
        updated = text.rstrip() + "\n" + block
    else:
        updated = text[:close].rstrip("\n") + "\n" + block + text[close:]
    return PlannedEdit(rel, f"add {len(missing)} constant(s)", updated, exists)


def _plan_translations(
    root: Path, locale: str, keys: dict[str, str], feature: str
) -> PlannedEdit:
    rel = f"{_TRANSLATIONS_DIR}/{locale}.json"
    path = root / rel
    exists = path.is_file()
    data: dict = {}
    if exists:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            return PlannedEdit(rel, "INVALID JSON - left untouched", "", exists)

    words = feature.replace("_", " ")
    defaults = {
        f"{feature}_title": words.title(),
        f"{feature}_empty": f"No {words} yet",
        f"{feature}_error": f"Could not load {words}",
        f"{feature}_load_failed": f"Could not load {words}",
    }
    added = 0
    for key in keys.values():
        if key not in data:
            # Arabic copy is the translator's job; an English seed is honest and
            # visible, where a silently-empty string would ship as blank UI.
            data[key] = defaults.get(key, key)
            added += 1

    if not added:
        return PlannedEdit(rel, "already has every key", json.dumps(data, ensure_ascii=False, indent=2) + "\n", exists)
    note = f"add {added} key(s)" + ("" if locale != "ar" else " (English seed - translate them)")
    return PlannedEdit(rel, note, json.dumps(data, ensure_ascii=False, indent=2) + "\n", exists)


# ---------------------------------------------------------------------------- apply


def apply(plan_: ScaffoldPlan, *, force: bool = False) -> list[str]:
    """Write the plan. Returns the paths actually written."""
    if plan_.conflicts and not force:
        raise FileExistsError(
            "refusing to overwrite: " + ", ".join(f.path for f in plan_.conflicts)
        )

    written: list[str] = []
    for item in plan_.files:
        target = plan_.root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8", newline="\n")
        written.append(item.path)

    for edit in plan_.edits:
        if not edit.content:
            continue
        target = plan_.root / edit.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit.content, encoding="utf-8", newline="\n")
        written.append(edit.path)
    return written


# -------------------------------------------------------------------------- helpers


def _render(stem: str, tokens: dict[str, str]) -> str:
    text = (TEMPLATE_DIR / f"{stem}.dart.tmpl").read_text(encoding="utf-8")
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", value)
    leftover = re.search(r"\{\{(\w+)\}\}", text)
    if leftover:
        raise KeyError(f"template {stem} has an unfilled token: {leftover.group(1)}")
    return text


def _find_lang_keys(root: Path) -> str:
    found = sorted(root.glob("lib/**/lang_keys.dart"))
    return found[0].relative_to(root).as_posix() if found else _DEFAULT_LANG_KEYS


def _relative_import(from_rel: str, to_rel: str) -> str:
    """A relative Dart import from one project-relative path to another."""
    from_parts = from_rel.split("/")[:-1]
    to_parts = to_rel.split("/")
    common = 0
    while (
        common < len(from_parts)
        and common < len(to_parts) - 1
        and from_parts[common] == to_parts[common]
    ):
        common += 1
    ups = [".."] * (len(from_parts) - common)
    return "/".join(ups + to_parts[common:]) or to_parts[-1]
