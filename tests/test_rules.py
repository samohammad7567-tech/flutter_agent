"""Each rule with a positive and a negative case."""
from __future__ import annotations

import json

import pytest

from flutter_agent.rules import ProjectContext, check_file, check_localization, check_path

FEATURE = "lib/features/archive"


def ids(findings) -> set[str]:
    return {f.rule_id for f in findings}


@pytest.fixture
def project(tmp_path):
    """A minimal but realistic Flutter project on disk."""
    (tmp_path / "pubspec.yaml").write_text("name: demo_app\n", encoding="utf-8")
    keys = tmp_path / "lib/core/localization/lang_keys.dart"
    keys.parent.mkdir(parents=True)
    keys.write_text(
        "class LangKeys {\n  LangKeys._();\n  static const archiveTitle = 'archive_title';\n}\n",
        encoding="utf-8",
    )
    tr = tmp_path / "assets/translations"
    tr.mkdir(parents=True)
    for locale in ("ar", "en"):
        (tr / f"{locale}.json").write_text(
            json.dumps({"archive_title": "Archive"}), encoding="utf-8"
        )
    return tmp_path


@pytest.fixture
def ctx(project):
    return ProjectContext.load(project)


def test_context_reads_package_and_keys(ctx):
    assert ctx.package == "demo_app"
    assert ctx.lang_keys == {"archiveTitle": "archive_title"}
    assert set(ctx.translations) == {"ar", "en"}


def test_r1_forbidden_and_nonstandard_folders(ctx):
    bad = check_file(f"{FEATURE}/domain/use_cases/get_items.dart", "class A {}", context=ctx)
    assert "R1" in ids(bad)
    assert any(f.severity == "error" for f in bad if f.rule_id == "R1")

    alias = check_file(f"{FEATURE}/views/archive_screen.dart", "class A {}", context=ctx)
    assert any(f.rule_id == "R1" and f.severity == "warning" for f in alias)

    good = check_file(f"{FEATURE}/presentation/screens/archive_screen.dart", "class A {}", context=ctx)
    assert "R1" not in ids(good)


def test_r2_self_import(ctx):
    src = "import 'package:demo_app/core/x.dart';\nimport 'package:flutter/material.dart';\n"
    found = check_file(f"{FEATURE}/presentation/cubit/archive_cubit.dart", src, context=ctx)
    r2 = [f for f in found if f.rule_id == "R2"]
    assert len(r2) == 1 and "demo_app" in r2[0].message

    relative = "import '../../data/repos/archive_repo.dart';\n"
    assert "R2" not in ids(check_file(f"{FEATURE}/presentation/cubit/a.dart", relative, context=ctx))


def test_r3_line_budget(ctx):
    rel = f"{FEATURE}/presentation/widgets/tile.dart"
    assert "R3" not in ids(check_file(rel, "class A {}\n" * 10, context=ctx))
    over = check_file(rel, "// x\n" * 200, context=ctx)
    assert any(f.rule_id == "R3" and f.severity == "error" for f in over)


def test_r4_screen_build_methods(ctx):
    src = """
class ArchiveScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) => _buildBody();
  Widget _buildBody() => const SizedBox();
}
"""
    rel = f"{FEATURE}/presentation/screens/archive_screen.dart"
    found = [f for f in check_file(rel, src, context=ctx) if f.rule_id == "R4"]
    assert len(found) == 1 and "_buildBody" in found[0].message

    # The same code in a refactor body is exactly where it belongs.
    body_rel = f"{FEATURE}/presentation/refactor/archive_body.dart"
    assert "R4" not in ids(check_file(body_rel, src, context=ctx))


def test_r5_backend_in_presentation(ctx):
    src = "class X { final db = FirebaseFirestore.instance; }"
    widget = check_file(f"{FEATURE}/presentation/widgets/tile.dart", src, context=ctx)
    assert "R5" in ids(widget)

    data_source = check_file(f"{FEATURE}/data/data_source/archive_data_source.dart", src, context=ctx)
    assert "R5" not in ids(data_source)


def test_r5_ignores_mentions_in_comments_and_strings(ctx):
    src = "// FirebaseFirestore is called by the data source\nconst note = 'SharedPreferences';\n"
    assert "R5" not in ids(check_file(f"{FEATURE}/presentation/widgets/t.dart", src, context=ctx))


def test_r6_context_in_cubit(ctx):
    rel = f"{FEATURE}/presentation/cubit/archive_cubit.dart"
    bad = "class C { void go(BuildContext context) => Navigator.of(context).pop(); }"
    assert "R6" in ids(check_file(rel, bad, context=ctx))

    good = "class C { void go() => emit(state.copyWith(done: true)); }"
    assert "R6" not in ids(check_file(rel, good, context=ctx))


def test_r7_raw_translation_keys_and_hardcoded_text(ctx):
    rel = f"{FEATURE}/presentation/widgets/tile.dart"
    raw = check_file(rel, "Text('archive_title'.tr())", context=ctx)
    assert any(f.rule_id == "R7" and f.severity == "error" for f in raw)

    hardcoded = check_file(rel, "const w = Text('Saved items');", context=ctx)
    assert any(f.rule_id == "R7" and f.severity == "warning" for f in hardcoded)

    good = check_file(rel, "Text(LangKeys.archiveTitle.tr())", context=ctx)
    assert "R7" not in ids(good)


def test_r7_allows_interpolation_and_symbols(ctx):
    rel = f"{FEATURE}/presentation/widgets/tile.dart"
    src = "Text('$count'); Text('-'); Text('');"
    assert "R7" not in ids(check_file(rel, src, context=ctx))


def test_r8_localization_drift(project):
    (project / "assets/translations/en.json").write_text(
        json.dumps({"archive_title": "Archive", "extra_key": "Extra"}), encoding="utf-8"
    )
    findings = check_localization(ProjectContext.load(project))
    messages = " ".join(f.message for f in findings)
    # Present in en.json but not ar.json, and declared in neither LangKeys.
    assert "extra_key" in messages
    assert any(f.severity == "error" for f in findings)


def test_r8_silent_when_everything_agrees(ctx):
    assert check_localization(ctx) == []


def test_r9_repo_logic(ctx):
    rel = f"{FEATURE}/data/repos/archive_repo.dart"
    bad = "class R { Future<void> f() async { if (x) { return; } } }"
    assert "R9" in ids(check_file(rel, bad, context=ctx))

    good = "class R { Future<void> f() => dataSource.f(); }"
    assert "R9" not in ids(check_file(rel, good, context=ctx))


def test_r11_model_serialisation(ctx):
    rel = f"{FEATURE}/data/models/archive_model.dart"
    bare = "class ArchiveModel { final String id = ''; }"
    assert "R11" in ids(check_file(rel, bare, context=ctx))

    # One direction is intentional for request/response models.
    one_way = "class ArchiveModel { Map<String, dynamic> toJson() => {}; }"
    assert "R11" not in ids(check_file(rel, one_way, context=ctx))


def test_r12_skips_grouping_folders(project):
    base = project / "lib/features/auth"
    (base / "login/data/data_source").mkdir(parents=True)
    (base / "login/data/models").mkdir(parents=True)
    (base / "login/data/repos").mkdir(parents=True)
    (base / "login/presentation/cubit").mkdir(parents=True)
    (base / "login/presentation/screens").mkdir(parents=True)

    findings, _ = check_path(project / "lib", include_localization=False)
    r12 = [f for f in findings if f.rule_id == "R12"]
    # `auth/` is a grouping folder; `auth/login` is complete. Neither is reported.
    assert r12 == []


def test_clean_file_produces_nothing(ctx):
    src = """
import 'package:flutter/material.dart';

import '../../data/models/archive_model.dart';

class ArchiveTile extends StatelessWidget {
  const ArchiveTile({super.key, required this.item});

  final ArchiveModel item;

  @override
  Widget build(BuildContext context) => ListTile(title: Text(item.title));
}
"""
    assert check_file(f"{FEATURE}/presentation/widgets/archive_tile.dart", src, context=ctx) == []
