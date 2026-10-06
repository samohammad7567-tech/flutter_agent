"""The learning loop: corrections captured from sessions, indexed and recallable.

A lesson is one durable correction — what was written, what it should have been,
and why. They are appended to a JSONL file that is version-controllable and
human-editable, indexed alongside the code so retrieval surfaces them next to the
pattern they correct, and exportable as an instruction/response dataset once
there are enough of them to fine-tune on.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .chunk import Chunk
from .config import KIND_LESSON, knowledge_home

LESSONS_FILENAME = "lessons.jsonl"


@dataclass
class Lesson:
    """One correction worth remembering."""

    topic: str
    right: str
    id: str = ""
    wrong: str = ""
    why: str = ""
    tags: list[str] = field(default_factory=list)
    layer: str = ""
    feature: str = ""
    project: str = ""
    source_path: str = ""
    rule_id: str = ""
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()

    @property
    def title(self) -> str:
        return self.topic.strip() or f"lesson {self.id}"

    def as_markdown(self) -> str:
        """The form that gets embedded and shown back to the caller."""
        out = [f"## {self.title}"]
        context = " | ".join(b for b in (self.project, self.feature, self.layer) if b)
        if context:
            out.append(f"Applies to: {context}")
        if self.rule_id:
            out.append(f"Rule: {self.rule_id}")
        if self.tags:
            out.append(f"Tags: {', '.join(self.tags)}")
        if self.wrong.strip():
            out.append(f"\nWrong:\n{self.wrong.rstrip()}")
        out.append(f"\nRight:\n{self.right.rstrip()}")
        if self.why.strip():
            out.append(f"\nWhy: {self.why.strip()}")
        if self.source_path:
            out.append(f"\nSeen in: {self.source_path}")
        return "\n".join(out)


def lessons_dir() -> Path:
    return knowledge_home() / "lessons"


def lessons_path() -> Path:
    return lessons_dir() / LESSONS_FILENAME


def load_all() -> list[Lesson]:
    """Read every lesson. A corrupt line is skipped, never fatal."""
    path = lessons_path()
    if not path.is_file():
        return []
    out: list[Lesson] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict) or "right" not in raw:
            continue
        known = {f for f in Lesson.__dataclass_fields__}
        out.append(Lesson(**{k: v for k, v in raw.items() if k in known}))
    return out


def add(
    topic: str,
    right: str,
    *,
    wrong: str = "",
    why: str = "",
    tags: list[str] | None = None,
    layer: str = "",
    feature: str = "",
    project: str = "",
    source_path: str = "",
    rule_id: str = "",
) -> Lesson:
    """Append one lesson. Returns the stored record."""
    if not topic.strip():
        raise ValueError("a lesson needs a topic")
    if not right.strip():
        raise ValueError("a lesson needs the correct form in `right`")

    lesson = Lesson(
        topic=topic.strip(),
        right=right,
        wrong=wrong,
        why=why,
        tags=[t.strip() for t in (tags or []) if t.strip()],
        layer=layer,
        feature=feature,
        project=project,
        source_path=source_path,
        rule_id=rule_id,
    )
    path = lessons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(asdict(lesson), ensure_ascii=False) + "\n")
    return lesson


def delete(lesson_id: str) -> bool:
    """Remove a lesson that turned out to be wrong. Rewrites the file."""
    path = lessons_path()
    if not path.is_file():
        return False
    existing = load_all()
    kept = [lesson for lesson in existing if lesson.id != lesson_id]
    if len(kept) == len(existing):
        return False
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for lesson in kept:
            handle.write(json.dumps(asdict(lesson), ensure_ascii=False) + "\n")
    tmp.replace(path)
    return True


def to_chunks(lessons: list[Lesson]) -> list[Chunk]:
    """One chunk per lesson — they are already the right size to embed."""
    out: list[Chunk] = []
    for index, lesson in enumerate(lessons, start=1):
        out.append(
            Chunk(
                text=lesson.as_markdown(),
                heading=lesson.title,
                heading_path=["lesson", lesson.title] + lesson.tags,
                level=2,
                line_start=index,
                line_end=index,
                kind=KIND_LESSON,
                project=lesson.project,
                feature=lesson.feature,
                layer=lesson.layer,
                symbol=lesson.id,
                symbol_kind="lesson",
            )
        )
    return out


def export_dataset(out_path: Path | str, *, system: str = "") -> int:
    """Write lessons as instruction/response JSONL for a later QLoRA run.

    Deliberately plain: `messages` triples, no template baked in, so the training
    script owns the chat format rather than this file.
    """
    default_system = (
        "You are a senior Flutter engineer working in a strict clean architecture: "
        "dumb UI, Cubit-owned behavior, data-source-owned persistence."
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for lesson in load_all():
            prompt = _prompt_for(lesson)
            if not prompt:
                continue
            record = {
                "messages": [
                    {"role": "system", "content": system or default_system},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": _answer_for(lesson)},
                ],
                "meta": {
                    "id": lesson.id,
                    "layer": lesson.layer,
                    "rule_id": lesson.rule_id,
                    "tags": lesson.tags,
                },
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
    return written


def _prompt_for(lesson: Lesson) -> str:
    context = " | ".join(b for b in (lesson.feature, lesson.layer) if b)
    header = f"{lesson.topic} ({context})" if context else lesson.topic
    if lesson.wrong.strip():
        return f"{header}\n\nWhat is wrong with this, and what should it be?\n\n{lesson.wrong.rstrip()}"
    return f"{header}\n\nShow the correct implementation for this codebase."


def _answer_for(lesson: Lesson) -> str:
    parts = [lesson.right.rstrip()]
    if lesson.why.strip():
        parts.append(f"\nWhy: {lesson.why.strip()}")
    return "\n".join(parts)
