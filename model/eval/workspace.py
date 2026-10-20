"""A throwaway copy of the golden project, used as the ground a generated file stands on.

Rules R2 and R7 need project-wide facts -- the package name, the LangKeys
constants, the translation files -- so a generated Dart file cannot be judged in
isolation. `tests/fixtures/quick_tasks` already supplies all of that and is
asserted clean by `test_fixture_project.py`, which makes it the honest baseline:
anything the checker reports after we drop a file in came from that file.

The copy is per-run and disposable. Writing generated code into the real fixture
would let one bad run poison the test suite.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from flutter_agent.rules import Finding, check_path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "quick_tasks"

# Copying .dart_tool and the platform folders costs seconds per run and buys
# nothing: the checker reads lib/, assets/ and pubspec.yaml and nothing else.
_SKIP_DIRS = {".dart_tool", ".idea", "android", "ios", "windows", "linux", "macos", "web", "build"}


@dataclass
class Scored:
    """One generated file, after the checker has had its say."""

    prompt_id: str
    target: str
    findings: list[Finding]
    empty: bool = False  # the generator produced nothing we could extract

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> int:
        return len(self.findings) - self.errors

    @property
    def clean(self) -> bool:
        return not self.empty and not self.findings

    def rule_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.rule_id] = counts.get(finding.rule_id, 0) + 1
        return counts


class Workspace:
    """A scratch Flutter project you can drop generated files into and check."""

    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def create(cls, at: Path) -> "Workspace":
        if not (FIXTURE / "pubspec.yaml").is_file():
            raise FileNotFoundError(f"golden fixture missing at {FIXTURE}")
        if at.exists():
            shutil.rmtree(at)
        at.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            FIXTURE,
            at,
            ignore=lambda _dir, names: [n for n in names if n in _SKIP_DIRS],
        )
        return cls(at)

    def place(self, target: str, code: str) -> Path:
        """Write generated code at its intended path inside the project."""
        path = self.root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8", newline="\n")
        return path

    def check(self, target: str) -> list[Finding]:
        """Run R1-R11 over one placed file.

        Single-file checks skip R8 (LangKeys/ar/en agreement) and R12 (required
        feature folders) by design -- both are project-wide facts that a single
        generated file cannot be blamed for. `check_project` covers them.
        """
        findings, _ = check_path(self.root / target, root=self.root)
        return findings

    def check_project(self) -> list[Finding]:
        """Whole-project pass, which does include R8 and R12."""
        findings, _ = check_path(self.root / "lib", root=self.root)
        return findings

    def analyze(self, target: str | None = None) -> tuple[int, str]:
        """`dart analyze`, if a Dart SDK is on PATH. Returns (error_count, output).

        Returns (-1, reason) when the SDK or the package deps are missing, so a
        machine without Flutter still gets rule scores instead of a crash.
        """
        dart = shutil.which("dart")
        if not dart:
            return -1, "dart not on PATH"
        if not (self.root / ".dart_tool" / "package_config.json").is_file():
            return -1, "deps not resolved; run pub_get() first"

        where = str(self.root / target) if target else str(self.root)
        try:
            result = subprocess.run(
                [dart, "analyze", "--no-fatal-warnings", where],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=self.root,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return -1, f"dart analyze failed: {exc}"

        output = result.stdout + result.stderr
        errors = sum(1 for line in output.splitlines() if line.strip().startswith("error"))
        return errors, output

    def pub_get(self) -> tuple[bool, str]:
        """Resolve deps once per workspace. Slow, and only needed for `analyze`."""
        flutter = shutil.which("flutter")
        if not flutter:
            return False, "flutter not on PATH"
        try:
            result = subprocess.run(
                [flutter, "pub", "get"],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=self.root,
                env={**os.environ, "PUB_CACHE": os.environ.get("PUB_CACHE", "")},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"pub get failed: {exc}"
        return result.returncode == 0, (result.stdout + result.stderr).strip()

    def destroy(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
