"""Command-line entry point: `flutter-agent <command>`."""
from __future__ import annotations

import argparse
import sys

from . import __version__, service
from .config import DEFAULT_SEARCH_LIMIT


def _utf8_stdout() -> None:
    """Windows consoles still default to cp1252; stop that truncating output."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _progress(message: str) -> None:
    print(f"    {message}", file=sys.stderr)


def cmd_index(args) -> int:
    print(service.reindex(force=args.force, progress=_progress))
    return 0


def cmd_search(args) -> int:
    print(
        service.search(
            args.query,
            limit=args.limit,
            kind=args.kind,
            project=args.project,
            feature=args.feature,
            layer=args.layer,
            show_text=not args.paths_only,
        )
    )
    return 0


def cmd_component(args) -> int:
    print(service.component(args.name or ""))
    return 0


def cmd_pattern(args) -> int:
    print(service.pattern(args.topic, limit=args.limit))
    return 0


def cmd_check(args) -> int:
    report = service.check(args.path, root=args.root)
    print(report)
    return 1 if "[R" in report and " error]" in report else 0


def cmd_refactor(args) -> int:
    print(service.refactor_plan(args.path, root=args.root))
    return 0


def cmd_scaffold(args) -> int:
    print(service.scaffold(args.feature, root=args.root, write=args.write, force=args.force))
    return 0


def cmd_lesson_add(args) -> int:
    print(
        service.lesson_add(
            args.topic,
            args.right,
            wrong=args.wrong or "",
            why=args.why or "",
            tags=args.tag or [],
            layer=args.layer or "",
            feature=args.feature or "",
            project=args.project or "",
            source_path=args.source_path or "",
            rule_id=args.rule or "",
            reindex_now=not args.no_index,
        )
    )
    return 0


def cmd_lessons(args) -> int:
    print(service.lessons_list(args.query or "", limit=args.limit))
    return 0


def cmd_export_dataset(args) -> int:
    print(service.export_dataset(args.out))
    return 0


def cmd_sources(args) -> int:
    if args.action in ("add", "remove") and not args.path:
        print(f"`sources {args.action}` needs a path or source name.", file=sys.stderr)
        return 2
    if args.action == "add":
        print(service.sources_add(args.path))
    elif args.action == "remove":
        print(service.sources_remove(args.path))
    else:
        print(service.sources_list())
    return 0


def cmd_status(_args) -> int:
    print(service.status())
    return 0


def cmd_doctor(_args) -> int:
    print(service.gpu_report())
    return 0


def cmd_serve(_args) -> int:
    from .server import main as serve_main

    serve_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flutter-agent",
        description="Local Flutter clean-architecture agent: search your own corpus, "
        "enforce the layer rules, scaffold features, and remember corrections.",
    )
    parser.add_argument("--version", action="version", version=f"flutter-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("index", help="Index every registered source (incremental by default).")
    p.add_argument("--force", action="store_true", help="Re-embed everything from scratch.")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("search", help="Semantic search over the corpus.")
    p.add_argument("query")
    p.add_argument("-n", "--limit", type=int, default=DEFAULT_SEARCH_LIMIT)
    p.add_argument("--kind", default=None, help="code | rule | pattern | lesson")
    p.add_argument("--project", default=None)
    p.add_argument("--feature", default=None)
    p.add_argument("--layer", default=None, help="cubit, screen, data_source, widget, ...")
    p.add_argument("--paths-only", action="store_true", help="Omit the matched source text.")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("component", help="Shared-package catalog, or one component and its uses.")
    p.add_argument("name", nargs="?", default="")
    p.set_defaults(func=cmd_component)

    p = sub.add_parser("pattern", help="How this codebase does X: rules, examples, lessons.")
    p.add_argument("topic")
    p.add_argument("-n", "--limit", type=int, default=1)
    p.set_defaults(func=cmd_pattern)

    p = sub.add_parser("check", help="Report architecture-rule violations.")
    p.add_argument("path")
    p.add_argument("--root", default=None, help="Project root, if it cannot be inferred.")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("refactor", help="Suggest how to split an oversized file.")
    p.add_argument("path")
    p.add_argument("--root", default=None)
    p.set_defaults(func=cmd_refactor)

    p = sub.add_parser("scaffold", help="Generate a feature folder (dry run by default).")
    p.add_argument("feature")
    p.add_argument("--root", required=True, help="The Flutter project root.")
    p.add_argument("--write", action="store_true", help="Actually write the files.")
    p.add_argument("--force", action="store_true", help="Overwrite existing files.")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("lesson", help="Record a correction worth remembering.")
    p.add_argument("topic")
    p.add_argument("right", help="The correct form.")
    p.add_argument("--wrong", default=None, help="What was written instead.")
    p.add_argument("--why", default=None)
    p.add_argument("--tag", action="append", default=None)
    p.add_argument("--layer", default=None)
    p.add_argument("--feature", default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--source-path", default=None)
    p.add_argument("--rule", default=None, help="Rule id this lesson relates to, e.g. R5.")
    p.add_argument("--no-index", action="store_true", help="Skip the incremental reindex.")
    p.set_defaults(func=cmd_lesson_add)

    p = sub.add_parser("lessons", help="Recall recorded lessons.")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("-n", "--limit", type=int, default=10)
    p.set_defaults(func=cmd_lessons)

    p = sub.add_parser("export-dataset", help="Write lessons as instruction/response JSONL.")
    p.add_argument("out")
    p.set_defaults(func=cmd_export_dataset)

    p = sub.add_parser("sources", help="Manage the indexed source roots.")
    p.add_argument("action", choices=["list", "add", "remove"], nargs="?", default="list")
    p.add_argument("path", nargs="?", default="")
    p.set_defaults(func=cmd_sources)

    sub.add_parser("status", help="Index health and contents.").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="Verify CUDA/GPU usage.").set_defaults(func=cmd_doctor)
    sub.add_parser("serve", help="Run the MCP stdio server.").set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
