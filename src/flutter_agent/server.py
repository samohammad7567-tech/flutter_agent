"""MCP stdio server exposing the Flutter agent's tools.

Built against the mcp 2.x SDK (`mcp.server.mcpserver.MCPServer`), the same shape
as docs-mcp. One installation serves every Flutter project, because the index is
global: `flutter_search` deliberately spans all registered source roots so a
pattern can be found wherever it was first written.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import sys
from typing import Annotated

from pydantic import Field

from . import __version__, service
from .config import DEFAULT_MAX_RESPONSE_CHARS, DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT

SERVER_NAME = "flutter-agent"

INSTRUCTIONS = """\
The local Flutter clean-architecture agent for this user's own codebases.

Before writing or reviewing Flutter code, prefer these tools over generic Flutter \
knowledge - they answer from this user's real corpus and architecture rules:

* flutter_pattern - how this codebase already does X (rule + golden example + \
past corrections). Call it BEFORE implementing a feature.
* flutter_search  - semantic search over the Dart corpus, filterable by layer \
(cubit, screen, data_source, widget, ...), feature or project.
* flutter_component - what the shared reusable package exports, and real call \
sites. Call it before writing any new widget, to avoid duplicating one.
* flutter_check   - static architecture-rule violations for a file or folder.
* flutter_scaffold - generate a complete feature folder in the house layout.
* flutter_lesson_add - record a correction after the user corrects you, so the \
mistake is not repeated in a later session.

The architecture is strict: dumb UI, Cubit-owned behavior, data-source-owned \
persistence, no domain/ or use_cases/ layer, localization through LangKeys only.
"""


def _to_stderr(fn, *args, **kwargs):
    """Run work with stdout redirected.

    stdout is the MCP transport; a stray print from a model loader would corrupt
    the JSON-RPC stream, so anything a dependency writes goes to stderr instead.
    """
    with contextlib.redirect_stdout(sys.stderr):
        return fn(*args, **kwargs)


async def _run(fn, *args, **kwargs) -> str:
    """Run blocking work off the event loop, surfacing errors as tool text."""
    try:
        return await asyncio.to_thread(functools.partial(_to_stderr, fn, *args, **kwargs))
    except Exception as exc:  # never kill the server over one bad call
        return f"{type(exc).__name__}: {exc}"


LayerArg = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "Restrict to one architectural layer: data_source, model, repo, cubit, "
            "refactor, screen, widget, core."
        ),
    ),
]


def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(name=SERVER_NAME, version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        structured_output=False,  # text is the payload; a structured copy would double the tokens
        name="flutter_search",
        description=(
            "Semantic search over this user's real Dart corpus. Returns the matching "
            "declarations with project, feature, layer, symbol and line range. Use it "
            "to find how something is actually written here rather than guessing."
        ),
    )
    async def flutter_search(
        query: Annotated[str, Field(description="Natural-language description of what you need.")],
        limit: Annotated[
            int, Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)
        ] = DEFAULT_SEARCH_LIMIT,
        layer: LayerArg = None,
        feature: Annotated[str | None, Field(default=None, description="Feature folder name.")] = None,
        project: Annotated[str | None, Field(default=None, description="Project name.")] = None,
        kind: Annotated[
            str | None,
            Field(default=None, description="code | rule | pattern | lesson. Defaults to all."),
        ] = None,
        paths_only: Annotated[
            bool, Field(default=False, description="Omit source text, return locations only.")
        ] = False,
        max_chars: Annotated[
            int, Field(default=DEFAULT_MAX_RESPONSE_CHARS, ge=500)
        ] = DEFAULT_MAX_RESPONSE_CHARS,
    ) -> str:
        return await _run(
            service.search,
            query,
            limit=limit,
            kind=kind,
            project=project,
            feature=feature,
            layer=layer,
            show_text=not paths_only,
            budget=max_chars,
        )

    @server.tool(
        structured_output=False,
        name="flutter_pattern",
        description=(
            "How this codebase does X. Combines the architecture rule, a golden "
            "example from the real corpus, and any past corrections on the topic. "
            "Call this BEFORE implementing a feature, e.g. 'pagination', "
            "'image upload', 'error mapping', 'form validation'."
        ),
    )
    async def flutter_pattern(
        topic: Annotated[str, Field(description="The thing you are about to implement.")],
        limit: Annotated[int, Field(default=1, ge=1, le=10)] = 1,
    ) -> str:
        return await _run(service.pattern, topic, limit=limit)

    @server.tool(
        structured_output=False,
        name="flutter_component",
        description=(
            "The shared reusable package's catalog, or one component's definition plus "
            "real call sites. Call it with no name to list everything available, before "
            "writing any new widget - the component probably already exists."
        ),
    )
    async def flutter_component(
        name: Annotated[
            str, Field(default="", description="Component name, e.g. AppButton. Empty lists all.")
        ] = "",
    ) -> str:
        return await _run(service.component, name)

    @server.tool(
        structured_output=False,
        name="flutter_check",
        description=(
            "Static architecture-rule violations for a Dart file, a feature folder or a "
            "whole project: forbidden folders, self-imports, oversized files, backend "
            "calls in presentation, BuildContext in cubits, raw translation strings, "
            "LangKeys/ar.json/en.json drift, logic in repos, models without serialisation."
        ),
    )
    async def flutter_check(
        path: Annotated[str, Field(description="Absolute path to a .dart file or a directory.")],
        root: Annotated[
            str | None, Field(default=None, description="Project root, if not inferable.")
        ] = None,
        max_chars: Annotated[
            int, Field(default=DEFAULT_MAX_RESPONSE_CHARS, ge=500)
        ] = DEFAULT_MAX_RESPONSE_CHARS,
    ) -> str:
        return await _run(service.check, path, root=root, budget=max_chars)

    @server.tool(
        structured_output=False,
        name="flutter_refactor_plan",
        description=(
            "For an oversized or messy file: its rule violations, which methods to "
            "extract into presentation/refactor/ or presentation/widgets/ (largest "
            "first), and the closest clean precedent in the corpus. Returns a plan to "
            "execute, not an edit."
        ),
    )
    async def flutter_refactor_plan(
        path: Annotated[str, Field(description="Absolute path to the .dart file.")],
        root: Annotated[str | None, Field(default=None)] = None,
    ) -> str:
        return await _run(service.refactor_plan, path, root=root)

    @server.tool(
        structured_output=False,
        name="flutter_scaffold",
        description=(
            "Generate a complete feature folder (data_source, model, repo, cubit+state, "
            "body, screen, widget) in the house architecture, and add its localization "
            "keys to LangKeys plus every translation JSON. Dry run by default: it "
            "returns the full file contents for review. Pass write=true to apply."
        ),
    )
    async def flutter_scaffold(
        feature: Annotated[str, Field(description="Feature name, e.g. lesson_detail.")],
        root: Annotated[str, Field(description="Absolute path to the Flutter project root.")],
        write: Annotated[
            bool, Field(default=False, description="Write the files instead of planning them.")
        ] = False,
        force: Annotated[
            bool, Field(default=False, description="Overwrite files that already exist.")
        ] = False,
    ) -> str:
        return await _run(service.scaffold, feature, root=root, write=write, force=force)

    @server.tool(
        structured_output=False,
        name="flutter_lesson_add",
        description=(
            "Record one correction so it is recalled in later sessions. Call this when "
            "the user corrects your Flutter code, when flutter analyze rejects something "
            "you generated, or when flutter_check finds a violation you then fixed. "
            "Keep `right` concrete - a real snippet, not advice."
        ),
    )
    async def flutter_lesson_add(
        topic: Annotated[str, Field(description="Short description, e.g. 'cubit error handling'.")],
        right: Annotated[str, Field(description="The correct form, as code where possible.")],
        wrong: Annotated[str, Field(default="", description="What was written instead.")] = "",
        why: Annotated[str, Field(default="", description="Why the correct form is correct.")] = "",
        tags: Annotated[list[str] | None, Field(default=None)] = None,
        layer: LayerArg = None,
        feature: Annotated[str | None, Field(default=None)] = None,
        project: Annotated[str | None, Field(default=None)] = None,
        source_path: Annotated[
            str | None, Field(default=None, description="File that prompted the lesson.")
        ] = None,
        rule_id: Annotated[
            str | None, Field(default=None, description="Related rule id, e.g. R5.")
        ] = None,
    ) -> str:
        return await _run(
            service.lesson_add,
            topic,
            right,
            wrong=wrong,
            why=why,
            tags=tags or [],
            layer=layer or "",
            feature=feature or "",
            project=project or "",
            source_path=source_path or "",
            rule_id=rule_id or "",
        )

    @server.tool(
        structured_output=False,
        name="flutter_lessons",
        description=(
            "Recall recorded corrections, by relevance when given a query, else the most "
            "recent. Useful at the start of a task to see what went wrong here before."
        ),
    )
    async def flutter_lessons(
        query: Annotated[str, Field(default="", description="Topic to recall. Empty = recent.")] = "",
        limit: Annotated[int, Field(default=10, ge=1, le=50)] = 10,
    ) -> str:
        return await _run(service.lessons_list, query, limit=limit)

    @server.tool(
        structured_output=False,
        name="flutter_reindex",
        description=(
            "Re-scan every registered source root and embed only new or changed files. "
            "Call it after generating or editing a lot of Dart so search stays current."
        ),
    )
    async def flutter_reindex(
        force: Annotated[
            bool, Field(default=False, description="Discard the index and re-embed everything.")
        ] = False,
    ) -> str:
        return await _run(service.reindex, force=force)

    @server.tool(
        structured_output=False,
        name="flutter_status",
        description=(
            "Index health: registered sources, model, embedding device (CUDA/CPU), file "
            "and chunk counts per kind and layer, index size."
        ),
    )
    async def flutter_status() -> str:
        return await _run(lambda: service.sources_list() + "\n\n" + service.status())

    return server


def main() -> None:
    try:
        build_server().run(transport="stdio")
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
