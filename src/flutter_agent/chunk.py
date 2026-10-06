"""The unit stored in the index — shared by the Dart and Markdown chunkers.

Markdown chunks leave the architecture fields empty; Dart chunks fill them, and
that metadata is both prepended to the embedded text (so retrieval is layer-aware)
and stored as filterable columns.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import KIND_CODE


@dataclass
class Chunk:
    """A contiguous slice of one file, ready to be embedded."""

    text: str
    heading: str
    heading_path: list[str]
    level: int
    line_start: int
    line_end: int
    part: int = 0
    total_parts: int = 1

    # --- architecture metadata; empty for prose chunks ---
    kind: str = KIND_CODE
    project: str = ""
    feature: str = ""
    layer: str = ""
    symbol: str = ""
    symbol_kind: str = ""

    @property
    def breadcrumb(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else "(document root)"

    def metadata_line(self) -> str:
        """Human- and embedder-readable summary of where this chunk sits."""
        bits = [b for b in (self.project, self.feature, self.layer, self.symbol) if b]
        return " | ".join(bits)

    def embed_text(self, file_label: str = "") -> str:
        """Text actually handed to the embedding model.

        The breadcrumb is prepended so a chunk deep inside a document still
        carries the topic of its parent headings; the metadata line does the same
        job for code, which has no headings of its own. Without it a `build`
        method is indistinguishable from every other `build` method in the corpus.
        """
        head = " > ".join(p for p in ([file_label] + self.heading_path) if p)
        body = f"{head}\n\n{self.text}" if head else self.text
        meta = self.metadata_line()
        return f"{meta}\n{body}" if meta else body
