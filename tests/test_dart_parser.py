"""Lexing and structure tests - the parts everything else is built on."""
from __future__ import annotations

from flutter_agent.dart_parser import mask_source, parse_dart


def test_masking_blanks_comments_and_strings_preserving_length():
    src = "final a = 'he}llo'; // }\nfinal b = 1;\n"
    masked, literals = mask_source(src)
    assert len(masked) == len(src)
    assert masked.count("\n") == src.count("\n")
    # Braces hidden in a string or a comment must not survive into the mask.
    assert "}" not in masked
    assert "final a =" in masked and "final b = 1;" in masked
    assert [lit.value for lit in literals] == ["he}llo"]


def test_masking_handles_nested_block_comments():
    src = "/* outer /* inner */ still comment */ final x = 1;\n"
    masked, _ = mask_source(src)
    assert "final x = 1;" in masked
    assert "outer" not in masked and "inner" not in masked


def test_masking_handles_same_quote_inside_interpolation():
    # Legal Dart: interpolation re-enters expression context.
    src = "final s = '${map['key']} tail';\nfinal after = 2;\n"
    masked, _ = mask_source(src)
    assert "final after = 2;" in masked
    assert "key" not in masked


def test_masking_handles_raw_and_triple_quoted_strings():
    src = "final a = r'C:\\path\\{';\nfinal b = '''multi\n}line''';\nfinal c = 3;\n"
    masked, _ = mask_source(src)
    assert "final c = 3;" in masked
    assert "{" not in masked and "}" not in masked


def test_named_parameter_braces_do_not_split_a_constructor():
    src = """
class ArchiveCubit extends Cubit<ArchiveState> {
  ArchiveCubit({required this.repo}) : super(const ArchiveState());

  final ArchiveRepo repo;
}
"""
    parsed = parse_dart(src)
    assert len(parsed.declarations) == 1
    decl = parsed.declarations[0]
    assert decl.name == "ArchiveCubit"
    assert decl.extends == "Cubit<ArchiveState>"
    kinds = {(m.kind, m.name) for m in decl.members}
    assert ("constructor", "ArchiveCubit") in kinds
    assert ("field", "repo") in kinds


def test_members_are_classified_and_bounded():
    src = """
class Thing {
  const Thing(this.id);
  factory Thing.empty() => const Thing('');

  final String id;
  static const int max = 3;

  String get label => id;
  set label(String v) {}

  Future<void> load() async {
    if (id.isEmpty) {
      return;
    }
  }
}
"""
    parsed = parse_dart(src)
    members = {m.name: m for m in parsed.declarations[0].members}
    assert members["Thing"].kind == "constructor"
    assert members["Thing.empty"].kind == "constructor"
    assert members["id"].kind == "field"
    assert members["max"].is_static
    assert members["label"].kind in ("getter", "setter")
    assert members["load"].kind == "method"
    # The method body's nested braces must be inside its own span.
    assert members["load"].line_end > members["load"].line_start


def test_directives_keep_their_uri():
    src = """
import 'package:flutter/material.dart';
import '../../data/repos/x_repo.dart';
export 'src/widgets/app_button.dart';
part 'x_state.dart';
"""
    parsed = parse_dart(src)
    assert [d.uri for d in parsed.imports] == [
        "package:flutter/material.dart",
        "../../data/repos/x_repo.dart",
    ]
    kinds = {d.kind for d in parsed.directives}
    assert {"import", "export", "part"} <= kinds


def test_arrow_body_with_map_literal_stays_one_declaration():
    src = "Map<String, int> build() => {'a': 1};\nint other() => 2;\n"
    parsed = parse_dart(src)
    assert [d.name for d in parsed.declarations] == ["build", "other"]


def test_enum_and_extension_are_recognised():
    src = """
enum Status { initial, loading }

extension on String {
  bool get isBlank => trim().isEmpty;
}
"""
    parsed = parse_dart(src)
    kinds = {d.kind for d in parsed.declarations}
    assert kinds == {"enum", "extension"}


def test_unterminated_string_does_not_swallow_the_file():
    src = "final bad = 'oops\nfinal good = 1;\n"
    masked, _ = mask_source(src)
    assert "final good = 1;" in masked
