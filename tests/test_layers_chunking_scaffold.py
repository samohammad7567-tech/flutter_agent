"""Layer classification, Dart chunking, scaffolding and the lesson store."""
from __future__ import annotations

import json

import pytest

from flutter_agent import lessons, scaffold
from flutter_agent.config import SourceConfig
from flutter_agent.dart_chunker import chunk_dart
from flutter_agent.layers import classify

# --------------------------------------------------------------------------- layers


@pytest.mark.parametrize(
    "path,layer,feature",
    [
        ("lib/features/archive/data/data_source/x.dart", "data_source", "archive"),
        ("lib/features/archive/data/models/x.dart", "model", "archive"),
        ("lib/features/archive/data/repos/x.dart", "repo", "archive"),
        ("lib/features/archive/presentation/cubit/x.dart", "cubit", "archive"),
        ("lib/features/archive/presentation/refactor/x.dart", "refactor", "archive"),
        ("lib/features/archive/presentation/screens/x.dart", "screen", "archive"),
        ("lib/features/archive/presentation/widgets/x.dart", "widget", "archive"),
        ("lib/core/di/service_locator.dart", "core", ""),
        ("lib/src/widgets/app_button.dart", "package", ""),
        ("lib/main.dart", "app", ""),
        ("lib/corereusablepackage.dart", "package_export", ""),
    ],
)
def test_classify(path, layer, feature):
    location = classify(path, project="demo")
    assert (location.layer, location.feature) == (layer, feature)


def test_classify_flags_forbidden_and_alias_folders():
    assert classify("lib/features/a/domain/x.dart").forbidden_dir == "domain"
    alias = classify("lib/features/a/views/x.dart")
    assert alias.layer == "screen" and alias.nonstandard_dir == "views"


def test_line_budget_differs_by_layer():
    screen = classify("lib/features/a/presentation/screens/x.dart")
    data = classify("lib/features/a/data/data_source/x.dart")
    assert screen.line_budget[1] < data.line_budget[1]


# -------------------------------------------------------------------------- chunking


def test_each_declaration_becomes_a_chunk():
    src = "class A {\n  void a() {}\n}\n\nclass B {\n  void b() {}\n}\n"
    chunks, title = chunk_dart(
        src, location=classify("lib/features/f/presentation/cubit/x.dart", project="p"),
        config=SourceConfig(), path="x.dart",
    )
    assert [c.symbol for c in chunks] == ["A", "B"]
    assert title == "A"
    assert chunks[0].project == "p" and chunks[0].feature == "f"
    assert chunks[0].layer == "cubit"


def test_oversized_class_splits_at_member_boundaries_and_repeats_the_header():
    body = "\n".join(f"  void method{i}() {{\n    print({i});\n  }}" for i in range(40))
    src = f"class Big extends Cubit<S> {{\n{body}\n}}\n"
    config = SourceConfig(max_chunk_chars=400)
    chunks, _ = chunk_dart(
        src, location=classify("lib/features/f/presentation/cubit/x.dart"), config=config, path="x.dart"
    )
    assert len(chunks) > 1
    assert all(c.total_parts == len(chunks) for c in chunks)
    # Every part carries the class header, so a middle chunk still has context.
    assert all("class Big" in c.text for c in chunks)
    # Method bodies are never cut in half: the only unbalanced brace in a part is
    # the repeated class header's, and the final part closes it.
    for chunk in chunks[:-1]:
        assert chunk.text.count("{") - chunk.text.count("}") == 1
    assert chunks[-1].text.count("{") == chunks[-1].text.count("}")
    assert all(c.text.count("print(") >= 1 for c in chunks)


def test_barrel_file_is_kept_whole():
    src = "library pkg;\n\nexport 'src/widgets/app_button.dart';\n"
    chunks, _ = chunk_dart(
        src, location=classify("lib/pkg.dart", project="pkg"), config=SourceConfig(), path="pkg.dart"
    )
    assert len(chunks) == 1 and "app_button" in chunks[0].text


def test_embed_text_carries_the_metadata_header():
    chunks, _ = chunk_dart(
        "class A {}\n",
        location=classify("lib/features/archive/presentation/cubit/x.dart", project="bilhikma"),
        config=SourceConfig(),
        path="x.dart",
    )
    header = chunks[0].embed_text("x.dart").split("\n")[0]
    assert "bilhikma" in header and "archive" in header and "cubit" in header


# ------------------------------------------------------------------------ scaffold


def test_name_derivation():
    assert scaffold.to_snake("LessonDetail") == "lesson_detail"
    assert scaffold.to_snake("lesson-detail") == "lesson_detail"
    assert scaffold.to_pascal("lesson_detail") == "LessonDetail"
    assert scaffold.to_camel("lesson_detail") == "lessonDetail"


def test_rejects_unusable_feature_names():
    with pytest.raises(ValueError):
        scaffold.names_for("  ")
    with pytest.raises(ValueError):
        scaffold.names_for("2fast")


def test_relative_import_from_screen_to_lang_keys():
    rel = scaffold._relative_import(
        "lib/features/archive/presentation/screens/archive_screen.dart",
        "lib/core/localization/lang_keys.dart",
    )
    assert rel == "../../../../core/localization/lang_keys.dart"


def test_plan_is_pure_and_complete(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    plan = scaffold.plan(tmp_path, "LessonDetail")

    assert plan.feature == "lesson_detail"
    paths = [f.path for f in plan.files]
    assert len(paths) == 8
    for expected in ("data/data_source", "data/models", "data/repos",
                     "presentation/cubit", "presentation/refactor",
                     "presentation/screens", "presentation/widgets"):
        assert any(expected in p for p in paths), expected
    # Planning writes nothing.
    assert not (tmp_path / "lib").exists()
    assert set(plan.keys) == {
        "lessonDetailTitle", "lessonDetailEmpty", "lessonDetailError", "lessonDetailLoadFailed"
    }


def test_apply_writes_files_and_localization(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    scaffold.apply(scaffold.plan(tmp_path, "archive"))

    cubit = (tmp_path / "lib/features/archive/presentation/cubit/archive_cubit.dart").read_text()
    assert "class ArchiveCubit extends Cubit<ArchiveState>" in cubit
    assert "part 'archive_state.dart';" in cubit
    # No unreplaced template tokens survive.
    assert "{{" not in cubit

    keys = (tmp_path / "lib/core/localization/lang_keys.dart").read_text()
    assert "archiveTitle" in keys and "archive_title" in keys

    for locale in ("ar", "en"):
        data = json.loads((tmp_path / f"assets/translations/{locale}.json").read_text(encoding="utf-8"))
        assert "archive_title" in data and "archive_load_failed" in data


def test_apply_refuses_to_clobber(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    scaffold.apply(scaffold.plan(tmp_path, "archive"))
    with pytest.raises(FileExistsError):
        scaffold.apply(scaffold.plan(tmp_path, "archive"))


def test_scaffold_passes_its_own_rules(tmp_path):
    from flutter_agent.rules import ProjectContext, check_file

    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    plan = scaffold.plan(tmp_path, "archive")
    scaffold.apply(plan)
    context = ProjectContext.load(tmp_path)

    for item in plan.files:
        findings = check_file(item.path, item.content, context=context)
        assert findings == [], f"{item.path}: {[f.format() for f in findings]}"


# ------------------------------------------------------------------------- lessons


def test_lesson_roundtrip_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUTTER_AGENT_KNOWLEDGE", str(tmp_path))

    lesson = lessons.add(
        "cubit error handling",
        "catch the feature exception and emit state.copyWith(errorKey: e.key)",
        wrong="catch (e) { print(e); }",
        why="the UI translates the key; printing loses it",
        tags=["cubit", "errors"],
        layer="cubit",
        rule_id="R6",
    )
    loaded = lessons.load_all()
    assert [l.id for l in loaded] == [lesson.id]
    assert loaded[0].tags == ["cubit", "errors"]

    chunks = lessons.to_chunks(loaded)
    assert chunks[0].kind == "lesson" and "errorKey" in chunks[0].text

    out = tmp_path / "dataset.jsonl"
    assert lessons.export_dataset(out) == 1
    record = json.loads(out.read_text(encoding="utf-8").strip())
    roles = [m["role"] for m in record["messages"]]
    assert roles == ["system", "user", "assistant"]

    assert lessons.delete(lesson.id) is True
    assert lessons.load_all() == []


def test_lesson_requires_topic_and_correction(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUTTER_AGENT_KNOWLEDGE", str(tmp_path))
    with pytest.raises(ValueError):
        lessons.add("", "something")
    with pytest.raises(ValueError):
        lessons.add("topic", "   ")


def test_corrupt_lesson_lines_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUTTER_AGENT_KNOWLEDGE", str(tmp_path))
    path = lessons.lessons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'not json\n{"topic":"t","right":"r"}\n{"topic":"no correction"}\n', encoding="utf-8"
    )
    assert [l.topic for l in lessons.load_all()] == ["t"]
