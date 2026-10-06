"""Local sentence-transformers embedding, on CUDA when the GPU is usable (copied verbatim from docs-mcp)."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .config import device_override, model_name

# Keep every tokenizer/BLAS stack from oversubscribing threads inside the MCP
# server process, which otherwise stalls short queries on a laptop CPU.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_LOCK = threading.Lock()


@dataclass(frozen=True)
class DeviceInfo:
    device: str  # "cuda" or "cpu"
    name: str
    cuda_available: bool
    torch_version: str = ""
    cuda_version: str | None = None
    total_memory_mb: int | None = None
    reason: str = ""

    def describe(self) -> str:
        if self.device == "cuda":
            mem = f", {self.total_memory_mb} MB VRAM" if self.total_memory_mb else ""
            return f"cuda ({self.name}{mem}, torch {self.torch_version}/cu{self.cuda_version})"
        return f"cpu ({self.name}){f' - {self.reason}' if self.reason else ''}"


def detect_device() -> DeviceInfo:
    """Pick the embedding device. Honours FLUTTER_AGENT_DEVICE, else auto-detects CUDA."""
    override = device_override()
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - torch is a hard dependency at runtime
        return DeviceInfo("cpu", "unknown", False, reason=f"torch unavailable: {exc}")

    available = False
    try:
        available = bool(torch.cuda.is_available())
    except Exception as exc:  # driver mismatch, WSL quirks, etc.
        return DeviceInfo(
            "cpu", "unknown", False, torch.__version__, reason=f"cuda probe failed: {exc}"
        )

    cuda_ver = getattr(torch.version, "cuda", None)

    if override == "cpu":
        return DeviceInfo(
            "cpu", "forced", available, torch.__version__, cuda_ver, reason="FLUTTER_AGENT_DEVICE=cpu"
        )

    if not available:
        reason = (
            "no CUDA-capable device visible to torch"
            if cuda_ver
            else "torch was installed without CUDA support (CPU-only wheel)"
        )
        if override == "cuda":
            reason = f"FLUTTER_AGENT_DEVICE=cuda requested but unusable: {reason}"
        return DeviceInfo("cpu", "cpu", False, torch.__version__, cuda_ver, reason=reason)

    try:
        props = torch.cuda.get_device_properties(0)
        return DeviceInfo(
            device="cuda",
            name=props.name,
            cuda_available=True,
            torch_version=torch.__version__,
            cuda_version=cuda_ver,
            total_memory_mb=int(props.total_memory // (1024 * 1024)),
        )
    except Exception as exc:
        return DeviceInfo(
            "cpu", "cpu", True, torch.__version__, cuda_ver, reason=f"GPU init failed: {exc}"
        )


class Embedder:
    """Lazily-loaded sentence-transformers model producing L2-normalised vectors."""

    def __init__(self, model: str | None = None, device: str | None = None):
        self.model_id = model or model_name()
        self._device = device
        self._model = None
        self._info: DeviceInfo | None = None

    @property
    def info(self) -> DeviceInfo:
        if self._info is None:
            self._info = detect_device()
        return self._info

    @property
    def device(self) -> str:
        return self._device or self.info.device

    def _ensure(self):
        if self._model is None:
            with _LOCK:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_id, device=self.device)
        return self._model

    @property
    def dimension(self) -> int:
        return int(self._ensure().get_sentence_embedding_dimension())

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int = 32,
        show_progress: bool = False,
        is_query: bool = False,
    ) -> np.ndarray:
        """Embed texts into a float32 (n, dim) array of unit vectors.

        Unit vectors mean FAISS inner product == cosine similarity.
        """
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")

        model = self._ensure()
        prompt_name = None
        # Models like BGE/E5 ship an asymmetric query prompt; use it when present.
        if is_query:
            prompts = getattr(model, "prompts", None) or {}
            for candidate in ("query", "s2p_query", "search_query"):
                if candidate in prompts:
                    prompt_name = candidate
                    break

        kwargs = dict(
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
        )
        if prompt_name:
            kwargs["prompt_name"] = prompt_name

        vectors = model.encode(texts, **kwargs)
        return np.asarray(vectors, dtype="float32")


@lru_cache(maxsize=4)
def get_embedder(model: str | None = None, device: str | None = None) -> Embedder:
    """Process-wide cached embedder, so the model loads at most once per config."""
    return Embedder(model=model, device=device)
