"""Static architecture rules — the review-and-enforce pillar.

No model is involved here and none should be: every rule below is a property of
the source that can be decided by reading it. That makes the checker fast, free,
deterministic, and safe to run on every file in the corpus.

All pattern matching runs against the *masked* source from `dart_parser`, so a
rule can never fire on a word inside a comment or a string literal.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .dart_parser import DartFile, parse_dart
from .layers import (
    FEATURE_REQUIRED_DIRS,
    LAYER_CUBIT,
    LAYER_MODEL,
    LAYER_REPO,
    LAYER_SCREEN,
    PRESENTATION_LAYERS,
    Location,
    classify,
)

ERROR = "error"
WARNING = "warning"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1}


@dataclass
class Finding:
    rule_id: str
    severity: str
    path: str
    line: int
    message: str
    hint: str = ""

    def format(self) -> str:
        head = f"{self.path}:{self.line}  [{self.rule_id} {self.severity}] {self.message}"
        return f"{head}\n    fix: {self.hint}" if self.hint else head

    @property
    def sort_key(self) -> tuple:
        return (_SEVERITY_ORDER.get(self.severity, 9), self.path, self.line, self.rule_id)


RULES = {
    "R1": "Folder layout follows features/<name>/{data,presentation}/...",
    "R2": "No package: self-imports inside lib/",
    "R3": "Files stay within their layer's line budget",
    "R4": "Screens hold no _build methods or layout logic",
    "R5": "Presentation never touches a backend or persistence API",
    "R6": "Cubits never touch BuildContext or navigation",
    "R7": "UI text goes through LangKeys, never a raw string",
    "R8": "LangKeys, ar.json and en.json agree",
    "R9": "Repos delegate without logic",
    "R10": "No Expanded/Flexible inside an unconstrained scrollable",
    "R11": "Models define fromJson and toJson",
    "R12": "Features have the required folders",
}

# --- R5: things only a data source may call -------------------------------
_BACKEND_PATTERNS = [
    (r"\bFirebaseFirestore\b", "FirebaseFirestore"),
    (r"\bFirebaseAuth\b", "FirebaseAuth"),
    (r"\bFirebaseStorage\b", "FirebaseStorage"),
    (r"\bFirebaseMessaging\b", "FirebaseMessaging"),
    (r"\bSupabase\b", "Supabase"),
    (r"\bSharedPreferences\b", "SharedPreferences"),
    (r"\bHive\b", "Hive"),
    (r"\bDio\b", "Dio"),
    (r"\bhttp\.(?:get|post|put|patch|delete)\b", "http client call"),
    (r"\bFlutterSecureStorage\b", "FlutterSecureStorage"),
]

# --- R6: things a cubit may not touch -------------------------------------
_CONTEXT_PATTERNS = [
    (r"\bBuildContext\b", "BuildContext"),
    (r"\bNavigator\s*\.", "Navigator"),
    (r"\bGoRouter\b", "GoRouter"),
    (r"\bScaffoldMessenger\b", "ScaffoldMessenger"),
    (r"\bshowDialog\b", "showDialog"),
    (r"\bshowModalBottomSheet\b", "showModalBottomSheet"),
]

_RAW_TR_RE = re.compile(r"""(['"])(?P<key>(?:(?!\1)[^\\])*)\1\s*\.tr\s*\(""")
_RAW_TRANSLATE_RE = re.compile(r"""\.translate\s*\(\s*(['"])(?P<key>(?:(?!\1)[^\\])*)\1""")
_HARDCODED_TEXT_RE = re.compile(r"""\bText\s*\(\s*(['"])(?P<body>(?:(?!\1)[^\\])*)\1""")
_LANGKEY_CONST_RE = re.compile(
    r"""static\s+const\s+(?:String\s+)?(?P<name>[A-Za-z_]\w*)\s*=\s*(['"])(?P<value>(?:(?!\2).)*)\2"""
)
_CONTROL_FLOW_RE = re.compile(r"\b(?:if|for|while|switch|try)\s*[({]")
_FROM_JSON_RE = re.compile(r"\bfromJson\b")
_TO_JSON_RE = re.compile(r"\btoJson\b")


@dataclass
class ProjectContext:
    """Project-wide facts a per-file rule needs (package name, localization keys)."""

    root: Path
    package: str = ""
    lang_keys: dict[str, str] = field(default_factory=dict)  # constant name -> key string
    lang_keys_path: str = ""
    translations: dict[str, dict] = field(default_factory=dict)  # locale -> {key: value}
    translation_paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path | str) -> "ProjectContext":
        root = Path(root)
        ctx = cls(root=root, package=_package_name(root))
        ctx._load_lang_keys()
        ctx._load_translations()
        return ctx

    def _load_lang_keys(self) -> None:
        for candidate in sorted(self.root.glob("lib/**/lang_keys.dart")):
            text = _read(candidate)
            masked, _ = _mask(text)
            # Values live in strings, which masking blanks, so read the original.
            self.lang_keys = {
                m.group("name"): m.group("value") for m in _LANGKEY_CONST_RE.finditer(text)
            }
            self.lang_keys_path = candidate.relative_to(self.root).as_posix()
            return

    def _load_translations(self) -> None:
        for candidate in sorted(self.root.glob("assets/translations/*.json")):
            locale = candidate.stem
            try:
                raw = json.loads(_read(candidate))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(raw, dict):
                self.translations[locale] = _flatten(raw)
                self.translation_paths[locale] = candidate.relative_to(self.root).as_posix()


# --------------------------------------------------------------------------- file


def check_file(
    rel_path: str,
    text: str,
    *,
    context: ProjectContext,
    project: str = "",
) -> list[Finding]:
    """Run every per-file rule against one Dart file."""
    location = classify(rel_path, project=project or context.package)
    parsed = parse_dart(text, path=rel_path)
    findings: list[Finding] = []

    findings += _r1_layout(rel_path, location)
    findings += _r2_self_import(rel_path, parsed, context)
    findings += _r3_size(rel_path, parsed, location)
    findings += _r4_screen_build_methods(rel_path, parsed, location)
    findings += _r5_backend_in_presentation(rel_path, parsed, location)
    findings += _r6_context_in_cubit(rel_path, parsed, location)
    findings += _r7_raw_strings(rel_path, text, parsed, context)
    findings += _r9_repo_logic(rel_path, parsed, location)
    findings += _r10_scrollable_expanded(rel_path, parsed)
    findings += _r11_model_json(rel_path, parsed, location)
    return findings


def _r1_layout(rel_path: str, location: Location) -> list[Finding]:
    out = []
    if location.forbidden_dir:
        out.append(
            Finding(
                "R1",
                ERROR,
                rel_path,
                1,
                f"forbidden folder `{location.forbidden_dir}/` - this project has no domain layer",
                "move the code into data/{data_source,models,repos} or presentation/",
            )
        )
    if location.nonstandard_dir:
        out.append(
            Finding(
                "R1",
                WARNING,
                rel_path,
                1,
                f"non-standard folder `{location.nonstandard_dir}/` under features/{location.feature}",
                f"rename it to the canonical folder for a {location.label}",
            )
        )
    return out


def _r2_self_import(rel_path: str, parsed: DartFile, context: ProjectContext) -> list[Finding]:
    if not context.package or "lib/" not in f"{rel_path}":
        return []
    prefix = f"package:{context.package}/"
    return [
        Finding(
            "R2",
            ERROR,
            rel_path,
            directive.line,
            f"self-import `{directive.uri}` inside lib/",
            "use a relative import instead",
        )
        for directive in parsed.directives
        if directive.uri.startswith(prefix)
    ]


def _r3_size(rel_path: str, parsed: DartFile, location: Location) -> list[Finding]:
    soft, hard = location.line_budget
    lines = parsed.line_count
    if lines > hard:
        return [
            Finding(
                "R3",
                ERROR,
                rel_path,
                lines,
                f"{location.label} is {lines} lines, over the {hard}-line ceiling",
                "split the body into presentation/refactor/ or presentation/widgets/",
            )
        ]
    if lines > soft:
        return [
            Finding(
                "R3",
                WARNING,
                rel_path,
                lines,
                f"{location.label} is {lines} lines, over the {soft}-line target",
                "consider extracting a section into refactor/ or widgets/",
            )
        ]
    return []


def _r4_screen_build_methods(
    rel_path: str, parsed: DartFile, location: Location
) -> list[Finding]:
    if location.layer != LAYER_SCREEN:
        return []
    out = []
    for decl in parsed.declarations:
        for member in decl.members:
            if member.kind != "method" or member.is_override:
                continue
            if member.name.startswith("_build") or member.name.startswith("build_"):
                out.append(
                    Finding(
                        "R4",
                        ERROR,
                        rel_path,
                        member.line_start,
                        f"screen defines layout method `{member.name}`",
                        "move it to presentation/refactor/ as a body section, "
                        "or presentation/widgets/ as a dumb widget",
                    )
                )
    return out


def _r5_backend_in_presentation(
    rel_path: str, parsed: DartFile, location: Location
) -> list[Finding]:
    if location.layer not in PRESENTATION_LAYERS:
        return []
    out = []
    seen: set[str] = set()
    for line_no, masked_line in parsed.iter_masked_lines():
        for pattern, label in _BACKEND_PATTERNS:
            if label in seen:
                continue
            if re.search(pattern, masked_line):
                seen.add(label)
                out.append(
                    Finding(
                        "R5",
                        ERROR,
                        rel_path,
                        line_no,
                        f"{location.label} calls {label} directly",
                        "move the call into data/data_source/ and reach it through the repo",
                    )
                )
    return out


def _r6_context_in_cubit(rel_path: str, parsed: DartFile, location: Location) -> list[Finding]:
    if location.layer != LAYER_CUBIT:
        return []
    out = []
    seen: set[str] = set()
    for line_no, masked_line in parsed.iter_masked_lines():
        for pattern, label in _CONTEXT_PATTERNS:
            if label in seen:
                continue
            if re.search(pattern, masked_line):
                seen.add(label)
                out.append(
                    Finding(
                        "R6",
                        ERROR,
                        rel_path,
                        line_no,
                        f"cubit references {label}",
                        "emit a state instead and let the widget react via BlocListener",
                    )
                )
    return out


def _r7_raw_strings(
    rel_path: str, text: str, parsed: DartFile, context: ProjectContext
) -> list[Finding]:
    """Translation keys must come from LangKeys, and UI text must be translated."""
    out: list[Finding] = []
    starts = _line_starts(text)

    for match in _RAW_TR_RE.finditer(text):
        out.append(
            Finding(
                "R7",
                ERROR,
                rel_path,
                _line_at(starts, match.start()),
                f"raw translation key '{match.group('key')}'.tr()",
                "add the key to LangKeys and both JSON files, then use LangKeys.<name>.tr()",
            )
        )
    for match in _RAW_TRANSLATE_RE.finditer(text):
        out.append(
            Finding(
                "R7",
                ERROR,
                rel_path,
                _line_at(starts, match.start()),
                f"raw translation key context.translate('{match.group('key')}')",
                "use context.translate(LangKeys.<name>)",
            )
        )

    known_values = set(context.lang_keys.values())
    for match in _HARDCODED_TEXT_RE.finditer(text):
        body = match.group("body")
        # Interpolated or decorative strings are not translatable UI copy.
        if "$" in body or len(body.strip()) < 2 or not any(c.isalpha() for c in body):
            continue
        if body in known_values:
            continue
        out.append(
            Finding(
                "R7",
                WARNING,
                rel_path,
                _line_at(starts, match.start()),
                f"hardcoded UI text Text('{body[:40]}')",
                "add a LangKeys constant plus ar/en entries and translate it",
            )
        )
    return out


def _r9_repo_logic(rel_path: str, parsed: DartFile, location: Location) -> list[Finding]:
    if location.layer != LAYER_REPO:
        return []
    out = []
    for line_no, masked_line in parsed.iter_masked_lines():
        if _CONTROL_FLOW_RE.search(masked_line):
            out.append(
                Finding(
                    "R9",
                    WARNING,
                    rel_path,
                    line_no,
                    "repo contains control flow - repos should only delegate",
                    "move the branching into the data source",
                )
            )
    return out[:3]  # one repo rarely needs more than a few pointers


def _r10_scrollable_expanded(rel_path: str, parsed: DartFile) -> list[Finding]:
    """Heuristic: a scroll view and a flex child inside the same method.

    This cannot be decided without a widget tree, so it is reported as a warning
    and says so - `SingleChildScrollView > Row > Expanded` is perfectly legal.
    """
    out = []
    for decl in parsed.declarations:
        for member in decl.members:
            body = "\n".join(
                parsed.masked.split("\n")[member.line_start - 1 : member.line_end]
            )
            if "SingleChildScrollView(" not in body:
                continue
            flex = re.search(r"\b(Expanded|Flexible)\s*\(", body)
            if flex:
                out.append(
                    Finding(
                        "R10",
                        WARNING,
                        rel_path,
                        member.line_start,
                        f"{flex.group(1)} inside a method that builds a SingleChildScrollView",
                        "if it is a direct child of the scrolling Column, give it a bounded "
                        "height instead (heuristic - verify the widget tree)",
                    )
                )
    return out


def _r11_model_json(rel_path: str, parsed: DartFile, location: Location) -> list[Finding]:
    if location.layer != LAYER_MODEL:
        return []
    out = []
    for decl in parsed.declarations:
        if decl.kind != "class" or decl.is_abstract or not decl.name:
            continue
        body = parsed.masked[: len(parsed.masked)]
        region = "\n".join(body.split("\n")[decl.line_start - 1 : decl.line_end])
        has_from = bool(_FROM_JSON_RE.search(region))
        has_to = bool(_TO_JSON_RE.search(region))
        # Only one of the two is normal and intentional: a request model
        # serialises out, a response model reads in. Having neither is the smell.
        if has_from or has_to:
            continue
        out.append(
            Finding(
                "R11",
                WARNING,
                rel_path,
                decl.line_start,
                f"model `{decl.name}` defines neither fromJson nor toJson",
                "models own their serialisation; strip id/created_at before writes",
            )
        )
    return out


# ------------------------------------------------------------------- project-wide


def check_localization(context: ProjectContext) -> list[Finding]:
    """R8: LangKeys, ar.json and en.json must describe the same key set."""
    if not context.lang_keys and not context.translations:
        return []
    out: list[Finding] = []
    declared = set(context.lang_keys.values())
    locales = {loc: set(keys) for loc, keys in context.translations.items()}
    path = context.lang_keys_path or "lib/core/localization/lang_keys.dart"

    for locale, keys in sorted(locales.items()):
        for missing in sorted(declared - keys):
            out.append(
                Finding(
                    "R8",
                    ERROR,
                    context.translation_paths.get(locale, f"assets/translations/{locale}.json"),
                    1,
                    f"key '{missing}' is declared in LangKeys but missing from {locale}.json",
                    f"add \"{missing}\" to {locale}.json",
                )
            )

    if locales:
        union = set().union(*locales.values())
        for locale, keys in sorted(locales.items()):
            for missing in sorted(union - keys):
                if missing in declared:
                    continue  # already reported above
                out.append(
                    Finding(
                        "R8",
                        ERROR,
                        context.translation_paths.get(locale, f"assets/translations/{locale}.json"),
                        1,
                        f"key '{missing}' exists in another locale but not in {locale}.json",
                        "keep ar.json and en.json in step",
                    )
                )
        for undeclared in sorted(union - declared):
            out.append(
                Finding(
                    "R8",
                    WARNING,
                    path,
                    1,
                    f"translation key '{undeclared}' has no LangKeys constant",
                    "add it to LangKeys so the UI never uses a raw string",
                )
            )
    return out


def check_feature_structure(root: Path, feature: str) -> list[Finding]:
    """R12: a feature folder should carry the canonical subfolders.

    `features/auth/` holding `login/`, `forgot_password/` and friends is a
    grouping folder, not a feature. Those are checked individually instead, so
    the parent is not reported for lacking layers it was never meant to have.
    """
    base = Path(root) / "lib" / "features" / feature
    if not base.is_dir():
        return []

    if not _is_leaf_feature(base):
        out: list[Finding] = []
        for child in sorted(d for d in base.iterdir() if d.is_dir()):
            out += check_feature_structure(root, f"{feature}/{child.name}")
        return out

    rel = f"lib/features/{feature}"
    return [
        Finding(
            "R12",
            WARNING,
            f"{rel}/{required}",
            1,
            f"feature `{feature}` has no {required}/ folder",
            "scaffold it, or confirm this feature genuinely needs no such layer",
        )
        for required in FEATURE_REQUIRED_DIRS
        if not (base / required).is_dir()
    ]


def _is_leaf_feature(base: Path) -> bool:
    """A real feature owns a data/ or presentation/ folder of its own."""
    return (base / "data").is_dir() or (base / "presentation").is_dir()


# ------------------------------------------------------------------------ drivers


def check_path(
    target: Path | str,
    *,
    root: Path | str | None = None,
    include_localization: bool = True,
    include_structure: bool = True,
) -> tuple[list[Finding], ProjectContext]:
    """Check a file, a feature folder, or a whole project."""
    target = Path(target).expanduser().resolve()
    project_root = Path(root).resolve() if root else _find_project_root(target)
    context = ProjectContext.load(project_root)

    findings: list[Finding] = []
    files = [target] if target.is_file() else sorted(target.rglob("*.dart"))
    for path in files:
        if _is_generated(path.name):
            continue
        try:
            rel = path.resolve().relative_to(project_root).as_posix()
        except ValueError:
            rel = path.name
        findings += check_file(rel, _read(path), context=context, project=context.package)

    # Localization drift is a project-wide fact. Reporting it while someone is
    # checking one feature buries that feature's findings under hundreds of
    # warnings about keys it has nothing to do with.
    checking_whole_project = target in (project_root, project_root / "lib")
    if include_localization and checking_whole_project:
        findings += check_localization(context)

    if include_structure:
        features_dir = project_root / "lib" / "features"
        if target.is_dir() and features_dir.is_dir():
            scanned = (
                [target.name]
                if target.parent == features_dir
                else [d.name for d in sorted(features_dir.iterdir()) if d.is_dir()]
            )
            for feature in scanned:
                findings += check_feature_structure(project_root, feature)

    findings.sort(key=lambda f: f.sort_key)
    return findings, context


def summarise(findings: list[Finding]) -> str:
    errors = sum(1 for f in findings if f.severity == ERROR)
    warnings = len(findings) - errors
    return f"{errors} error(s), {warnings} warning(s)"


# ------------------------------------------------------------------------ helpers


def _find_project_root(start: Path) -> Path:
    cur = start if start.is_dir() else start.parent
    for parent in [cur, *cur.parents]:
        if (parent / "pubspec.yaml").is_file():
            return parent
    return cur


def _package_name(root: Path) -> str:
    pubspec = Path(root) / "pubspec.yaml"
    if not pubspec.is_file():
        return ""
    match = re.search(
        r"^name:\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$", _read(pubspec), re.MULTILINE
    )
    return match.group(1) if match else ""


def _is_generated(name: str) -> bool:
    return any(
        name.endswith(suffix)
        for suffix in (".g.dart", ".freezed.dart", ".gr.dart", ".config.dart", ".mocks.dart")
    )


def _read(path: Path) -> str:
    data = Path(path).read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _mask(text: str):
    from .dart_parser import mask_source

    return mask_source(text)


def _flatten(raw: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested translation JSON into dotted keys."""
    out: dict[str, str] = {}
    for key, value in raw.items():
        full = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, full))
        else:
            out[full] = str(value)
    return out


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, ch in enumerate(text):
        if ch == "\n":
            starts.append(index + 1)
    return starts


def _line_at(starts: list[int], index: int) -> int:
    import bisect

    return bisect.bisect_right(starts, index)
