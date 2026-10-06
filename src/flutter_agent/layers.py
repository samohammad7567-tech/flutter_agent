"""Where a file sits in the architecture, derived from its path.

Every other module leans on this: search filters by layer, the rule engine asks
what a file is allowed to do, and the scaffolder asks where a file belongs. The
layout it encodes is the one in CLAUDE.md:

    lib/features/<feature>/data/{data_source,models,repos}
    lib/features/<feature>/presentation/{cubit,refactor,screens,widgets}
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

# --- feature layers ---
LAYER_DATA_SOURCE = "data_source"
LAYER_MODEL = "model"
LAYER_REPO = "repo"
LAYER_CUBIT = "cubit"
LAYER_REFACTOR = "refactor"
LAYER_SCREEN = "screen"
LAYER_WIDGET = "widget"

# --- everything else ---
LAYER_CORE = "core"
LAYER_APP = "app"
LAYER_PACKAGE = "package"
LAYER_PACKAGE_EXPORT = "package_export"
LAYER_UNKNOWN = "unknown"

DATA_LAYERS = (LAYER_DATA_SOURCE, LAYER_MODEL, LAYER_REPO)
PRESENTATION_LAYERS = (LAYER_CUBIT, LAYER_REFACTOR, LAYER_SCREEN, LAYER_WIDGET)
# Layers that must never reach a backend or a persistence API directly.
UI_LAYERS = (LAYER_REFACTOR, LAYER_SCREEN, LAYER_WIDGET)

# Directory name under data/ or presentation/ -> layer.
_FEATURE_DIRS = {
    "data_source": LAYER_DATA_SOURCE,
    "data_sources": LAYER_DATA_SOURCE,
    "models": LAYER_MODEL,
    "model": LAYER_MODEL,
    "repos": LAYER_REPO,
    "repo": LAYER_REPO,
    "cubit": LAYER_CUBIT,
    "cubits": LAYER_CUBIT,
    "bloc": LAYER_CUBIT,
    "refactor": LAYER_REFACTOR,
    "screens": LAYER_SCREEN,
    "screen": LAYER_SCREEN,
    "pages": LAYER_SCREEN,
    "widgets": LAYER_WIDGET,
    "widget": LAYER_WIDGET,
}

# Directory names that mean the right thing but are spelled the wrong way. They
# are classified so retrieval still works on older code, and simultaneously
# reported by the rule engine so the deviation stays visible.
_ALIAS_DIRS = {
    "views": LAYER_SCREEN,
    "view": LAYER_SCREEN,
    "utils": LAYER_REFACTOR,
    "helpers": LAYER_REFACTOR,
    "components": LAYER_WIDGET,
}

# Clean-architecture scaffolding this project deliberately does not use.
FORBIDDEN_DIRS = (
    "domain",
    "entities",
    "use_cases",
    "usecases",
    "repo_interface",
    "repo_impl",
    "presentations",
)

# The folders a complete feature is expected to have.
FEATURE_REQUIRED_DIRS = (
    "data/data_source",
    "data/models",
    "data/repos",
    "presentation/cubit",
    "presentation/screens",
)

# Soft target and hard ceiling on file length, per CLAUDE.md's size table.
_LINE_BUDGET = {
    LAYER_SCREEN: (70, 150),
    LAYER_REFACTOR: (120, 150),
    LAYER_WIDGET: (120, 150),
    LAYER_MODEL: (200, 400),
    LAYER_REPO: (120, 250),
    LAYER_DATA_SOURCE: (400, 900),
    LAYER_CUBIT: (400, 900),
}
_DEFAULT_BUDGET = (300, 600)

LAYER_LABELS = {
    LAYER_DATA_SOURCE: "data source",
    LAYER_MODEL: "model",
    LAYER_REPO: "repo",
    LAYER_CUBIT: "cubit",
    LAYER_REFACTOR: "refactor body",
    LAYER_SCREEN: "screen",
    LAYER_WIDGET: "widget",
    LAYER_CORE: "core",
    LAYER_APP: "app entry",
    LAYER_PACKAGE: "shared package",
    LAYER_PACKAGE_EXPORT: "package barrel",
    LAYER_UNKNOWN: "unclassified",
}


@dataclass(frozen=True)
class Location:
    """The architectural address of one Dart file."""

    project: str
    rel_path: str  # POSIX, relative to the source root
    lib_path: str  # POSIX, relative to lib/ — "" when the file is outside lib/
    feature: str
    layer: str
    core_area: str = ""  # for core files: di, routing, localization, theme, ...
    forbidden_dir: str = ""  # the offending segment, when one is present
    nonstandard_dir: str = ""  # a recognised-but-misnamed folder, e.g. `views/`

    @property
    def is_feature(self) -> bool:
        return bool(self.feature)

    @property
    def is_presentation(self) -> bool:
        return self.layer in PRESENTATION_LAYERS

    @property
    def is_data(self) -> bool:
        return self.layer in DATA_LAYERS

    @property
    def is_ui(self) -> bool:
        return self.layer in UI_LAYERS

    @property
    def label(self) -> str:
        return LAYER_LABELS.get(self.layer, self.layer)

    @property
    def line_budget(self) -> tuple[int, int]:
        """(soft target, hard ceiling) line counts for this layer."""
        return _LINE_BUDGET.get(self.layer, _DEFAULT_BUDGET)

    def describe(self) -> str:
        bits = [self.project]
        if self.feature:
            bits.append(self.feature)
        bits.append(self.label)
        return " | ".join(b for b in bits if b)


def classify(rel_path: str, *, project: str = "") -> Location:
    """Map a source-root-relative path to its architectural location.

    `rel_path` is POSIX and relative to the root of the Flutter project or
    package (so it usually starts with `lib/`).
    """
    parts = PurePosixPath(rel_path).parts
    forbidden = next((p for p in parts if p.lower() in FORBIDDEN_DIRS), "")

    if "lib" not in parts:
        return Location(project, rel_path, "", "", LAYER_UNKNOWN, forbidden_dir=forbidden)

    lib_index = parts.index("lib")
    below = parts[lib_index + 1 :]
    lib_path = "/".join(below)
    if not below:
        return Location(project, rel_path, "", "", LAYER_UNKNOWN, forbidden_dir=forbidden)

    head = below[0]
    filename = below[-1]

    # The package barrel: `lib/<package>.dart` next to `lib/src/`.
    if len(below) == 1 and filename.endswith(".dart"):
        layer = LAYER_APP if filename == "main.dart" or filename.endswith("_app.dart") else LAYER_PACKAGE_EXPORT
        return Location(project, rel_path, lib_path, "", layer, forbidden_dir=forbidden)

    if head == "features" and len(below) >= 2:
        feature = below[1]
        layer, alias = _feature_layer(below[2:])
        return Location(
            project,
            rel_path,
            lib_path,
            feature,
            layer,
            forbidden_dir=forbidden,
            nonstandard_dir=alias,
        )

    if head == "core":
        area = below[1] if len(below) > 2 else ""
        return Location(project, rel_path, lib_path, "", LAYER_CORE, core_area=area, forbidden_dir=forbidden)

    # corereusablepackage and friends keep their implementation under lib/src/.
    if head == "src":
        area = below[1] if len(below) > 2 else ""
        return Location(project, rel_path, lib_path, "", LAYER_PACKAGE, core_area=area, forbidden_dir=forbidden)

    return Location(project, rel_path, lib_path, "", LAYER_UNKNOWN, forbidden_dir=forbidden)


def _feature_layer(tail: tuple[str, ...]) -> tuple[str, str]:
    """Resolve (layer, nonstandard_dir) from the segments below `features/<name>/`."""
    for segment in tail:
        if segment in _FEATURE_DIRS:
            return _FEATURE_DIRS[segment], ""
    for segment in tail:
        if segment in _ALIAS_DIRS:
            return _ALIAS_DIRS[segment], segment
    # `data/foo.dart` or `presentation/foo.dart` with no recognised subfolder.
    if tail:
        if tail[0] == "data":
            return LAYER_MODEL, ""
        if tail[0] in ("presentation", "presentations"):
            return LAYER_WIDGET, ""
    return LAYER_UNKNOWN, ""


def expected_dir(feature: str, layer: str) -> str:
    """Where a file of `layer` belongs inside `lib/features/<feature>/`."""
    mapping = {
        LAYER_DATA_SOURCE: "data/data_source",
        LAYER_MODEL: "data/models",
        LAYER_REPO: "data/repos",
        LAYER_CUBIT: "presentation/cubit",
        LAYER_REFACTOR: "presentation/refactor",
        LAYER_SCREEN: "presentation/screens",
        LAYER_WIDGET: "presentation/widgets",
    }
    sub = mapping.get(layer)
    return f"lib/features/{feature}/{sub}" if sub else f"lib/features/{feature}"
