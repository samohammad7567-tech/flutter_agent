"""Score generated Dart against the rules this repo already enforces.

    python -m model.eval.harness score   --from-dir runs/claude/raw --name claude
    python -m model.eval.harness run     --model Qwen/Qwen2.5-Coder-3B-Instruct --condition full
    python -m model.eval.harness compare runs/base-full/report.json runs/tuned-bare/report.json

The number that matters is not the total. It is the per-rule table: a fine-tune
that stops emitting raw '.tr()' keys but still puts Firestore in a widget has
learned a lint, not an architecture. Reporting one aggregate score would hide
exactly that.

Every run writes raw model output next to the report. When a score looks wrong
it is almost always the extractor or the prompt, and without the raw text there
is no way to tell which.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from flutter_agent.rules import RULES

from .extract import dart_from
from .generate import DirGenerator, HfGenerator, load_system
from .workspace import Scored, Workspace

HERE = Path(__file__).resolve().parent
DEFAULT_PROMPTS = HERE / "prompts.jsonl"
RUNS = HERE.parent / "runs"


def load_prompts(path: Path) -> list[dict]:
    prompts = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            prompts.append(json.loads(line))
        except ValueError as exc:
            raise SystemExit(f"{path}:{line_no}: bad JSON -- {exc}") from exc
    if not prompts:
        raise SystemExit(f"no prompts in {path}")
    return prompts


def score_one(workspace: Workspace, prompt: dict, raw: str) -> Scored:
    code = dart_from(raw)
    if not code:
        return Scored(prompt["id"], prompt["target"], findings=[], empty=True)
    workspace.place(prompt["target"], code)
    return Scored(prompt["id"], prompt["target"], findings=workspace.check(prompt["target"]))


def report(name: str, condition: str, scored: list[Scored], analyze: dict | None) -> dict:
    rule_counts: dict[str, int] = {}
    for item in scored:
        for rule_id, count in item.rule_counts().items():
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + count

    return {
        "name": name,
        "condition": condition,
        "prompts": len(scored),
        "clean_files": sum(1 for s in scored if s.clean),
        "empty_files": sum(1 for s in scored if s.empty),
        "errors": sum(s.errors for s in scored),
        "warnings": sum(s.warnings for s in scored),
        "by_rule": dict(sorted(rule_counts.items(), key=lambda kv: kv[0])),
        "analyze": analyze or {},
        "per_prompt": [
            {
                "id": s.prompt_id,
                "target": s.target,
                "empty": s.empty,
                "errors": s.errors,
                "warnings": s.warnings,
                "findings": [asdict(f) for f in s.findings],
            }
            for s in scored
        ],
    }


def print_report(data: dict) -> None:
    total = data["prompts"]
    print(f"\n{data['name']}  (condition: {data['condition']})")
    print("-" * 64)
    print(f"  prompts          {total}")
    print(f"  clean files      {data['clean_files']}/{total}")
    if data["empty_files"]:
        print(f"  no code emitted  {data['empty_files']}  <- extractor found nothing")
    print(f"  errors           {data['errors']}")
    print(f"  warnings         {data['warnings']}")

    if data["by_rule"]:
        print("\n  violations by rule")
        for rule_id, count in data["by_rule"].items():
            print(f"    {rule_id:<4} {count:>4}  {RULES.get(rule_id, '')}")

    analyze = data.get("analyze") or {}
    if analyze.get("ran"):
        print(f"\n  dart analyze     {analyze['errors']} error(s)")
    elif analyze.get("reason"):
        print(f"\n  dart analyze     skipped -- {analyze['reason']}")

    failed = [p for p in data["per_prompt"] if p["errors"] or p["empty"]]
    if failed:
        print("\n  failing prompts")
        for item in failed:
            why = "no code emitted" if item["empty"] else f"{item['errors']} error(s)"
            print(f"    {item['id']:<28} {why}")


def write_run(out: Path, data: dict, raw: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    raw_dir = out / "raw"
    raw_dir.mkdir(exist_ok=True)
    for prompt_id, text in raw.items():
        (raw_dir / f"{prompt_id}.txt").write_text(text, encoding="utf-8")


def execute(args, completions) -> int:
    """completions: (prompt) -> raw model text."""
    prompts = load_prompts(Path(args.prompts))
    out = Path(args.out) if args.out else RUNS / args.name
    workspace = Workspace.create(out / "workspace")

    raw: dict[str, str] = {}
    scored: list[Scored] = []
    for index, prompt in enumerate(prompts, 1):
        print(f"[{index}/{len(prompts)}] {prompt['id']}", file=sys.stderr)
        text = completions(prompt)
        raw[prompt["id"]] = text
        scored.append(score_one(workspace, prompt, text))

    analyze: dict = {"ran": False, "reason": "not requested"}
    if args.analyze:
        ok, message = workspace.pub_get()
        if not ok:
            analyze = {"ran": False, "reason": message}
        else:
            errors, output = workspace.analyze()
            analyze = (
                {"ran": True, "errors": errors, "output": output[-4000:]}
                if errors >= 0
                else {"ran": False, "reason": output}
            )

    data = report(args.name, getattr(args, "condition", "n/a"), scored, analyze)
    write_run(out, data, raw)
    print_report(data)
    print(f"\nwritten to {out}")

    if not args.keep_workspace:
        workspace.destroy()
    return 0


def cmd_score(args) -> int:
    source = DirGenerator(Path(args.from_dir))
    if not source.root.is_dir():
        raise SystemExit(f"no such directory: {source.root}")
    return execute(args, lambda prompt: source.read_for(prompt["id"]))


def cmd_run(args) -> int:
    system = load_system(args.condition)
    generator = HfGenerator(
        args.model,
        adapter=args.adapter,
        four_bit=not args.full_precision,
        temperature=args.temperature,
    )
    if not args.name:
        args.name = f"{Path(args.model).name}-{args.condition}"
    return execute(args, lambda prompt: generator.complete(system, prompt["instruction"]))


def cmd_compare(args) -> int:
    left = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right = json.loads(Path(args.right).read_text(encoding="utf-8"))

    print(f"\n{'':<10} {left['name'][:22]:>22} {right['name'][:22]:>22}  delta")
    print("-" * 64)

    def row(label: str, a, b, lower_is_better: bool = True) -> None:
        delta = b - a
        mark = "" if delta == 0 else (" better" if (delta < 0) == lower_is_better else " worse")
        print(f"{label:<10} {a:>22} {b:>22}  {delta:+d}{mark}")

    row("clean", left["clean_files"], right["clean_files"], lower_is_better=False)
    row("errors", left["errors"], right["errors"])
    row("warnings", left["warnings"], right["warnings"])
    row("empty", left["empty_files"], right["empty_files"])

    rules = sorted(set(left["by_rule"]) | set(right["by_rule"]))
    if rules:
        print("\n  by rule")
        for rule_id in rules:
            a = left["by_rule"].get(rule_id, 0)
            b = right["by_rule"].get(rule_id, 0)
            print(f"  {rule_id:<8} {a:>22} {b:>22}  {b - a:+d}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="model.eval.harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def shared(p):
        p.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
        p.add_argument("--out", default=None, help="run directory (default: model/runs/<name>)")
        p.add_argument("--analyze", action="store_true", help="also run flutter pub get + dart analyze")
        p.add_argument("--keep-workspace", action="store_true", help="leave the scratch project on disk")

    p = sub.add_parser("score", help="Score pre-generated files: one <prompt id>.dart per prompt.")
    p.add_argument("--from-dir", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--condition", default="n/a")
    shared(p)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("run", help="Generate with a local model, then score.")
    p.add_argument("--model", required=True)
    p.add_argument("--adapter", default=None, help="LoRA adapter directory")
    p.add_argument("--condition", default="full", choices=["bare", "full"])
    p.add_argument("--name", default=None)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--full-precision", action="store_true", help="skip 4-bit; needs more than 6 GB")
    shared(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("compare", help="Diff two report.json files.")
    p.add_argument("left")
    p.add_argument("right")
    p.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
