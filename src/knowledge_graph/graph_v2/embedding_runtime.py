"""
Embedding device selection and out-of-memory resilient encoding for the graph v2 build
(pre-flight P-04 / P-09 and `post_import_v2.py embed`).

On Apple silicon SentenceTransformer picks the MPS device by default, and MPS shares the 16 GB of
unified memory with the rest of the process. Large batches can then fail with
`RuntimeError: MPS backend out of memory`. This module:
    - resolves `--embed-device {auto,cpu,mps}` to a SentenceTransformer device;
    - loads the model directly (not through `graphdb.embedding_service`, which is runtime retrieval
      code outside the §6.6 baseline allow-list) and makes sure `max_seq_length` is set (MiniLM: 256
      word pieces), so the tokenizer truncates every text;
    - wraps the model in `ResilientEmbedder`: on an out-of-memory error it empties the device cache
      and halves the batch size down to a floor, and then encodes that chunk on the CPU. Every change
      is logged and counted, and nothing already returned is recomputed.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
DEVICE_CHOICES = ("auto", "cpu", "mps")
DEFAULT_EMBED_BATCH_SIZE = 32
MIN_EMBED_BATCH_SIZE = 8
MINILM_MAX_SEQ_LENGTH = 256
CPU_DEVICE = "cpu"


class DeviceUnavailableError(ValueError):
    """The requested embedding device is not available on this machine."""


def is_out_of_memory(error: BaseException) -> bool:
    """True for torch device out-of-memory errors (MPS and CUDA raise RuntimeError subclasses saying 'out of memory')."""
    return isinstance(error, RuntimeError) and "out of memory" in str(error).lower()


def resolve_device(choice: str) -> Optional[str]:
    """`auto` -> None (SentenceTransformer picks), `cpu` -> "cpu", `mps` -> "mps" if available, else DeviceUnavailableError."""
    if choice not in DEVICE_CHOICES:
        raise DeviceUnavailableError(f"unknown embedding device {choice!r}; choose one of {DEVICE_CHOICES}")
    if choice == "auto":
        return None
    if choice == "mps":
        try:
            import torch
        except ImportError as e:
            raise DeviceUnavailableError(f"torch is not importable: {e}") from e
        if not torch.backends.mps.is_available():
            raise DeviceUnavailableError("--embed-device mps requested, but torch reports MPS as unavailable")
    return choice


def device_of(model: Any) -> str:
    """The device a SentenceTransformer (or fake) model currently sits on, as a string."""
    return str(getattr(model, "device", "unknown"))


def empty_device_cache(device: Optional[str]) -> None:
    """Releases cached allocator memory on MPS or CUDA; a no-op on CPU or when torch lacks the call."""
    if not device or device.startswith(CPU_DEVICE):
        return
    try:
        import torch
    except ImportError:
        return
    try:
        if device.startswith("mps") and hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
            torch.mps.empty_cache()
        elif device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except RuntimeError as e:
        logger.warning(f"[Embedding] could not empty the {device} cache: {e}")


def ensure_max_seq_length(model: Any, limit: int = MINILM_MAX_SEQ_LENGTH) -> Optional[int]:
    """Sets `model.max_seq_length` to `limit` when it is unset or larger, so every text is truncated; returns the value in force."""
    if not hasattr(model, "max_seq_length"):
        return None
    current = getattr(model, "max_seq_length", None)
    if current is None or current > limit:
        logger.warning(f"[Embedding] max_seq_length was {current}; capping it at {limit} word pieces")
        model.max_seq_length = limit
    return model.max_seq_length


def load_model(choice: str = "auto", model_name: str = MODEL_NAME) -> Any:
    """Loads the SentenceTransformer on the resolved device and caps max_seq_length; logs the device actually used."""
    device = resolve_device(choice)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(f"sentence-transformers is not installed: {e}") from e
    model = SentenceTransformer(model_name, device=device)
    ensure_max_seq_length(model)
    logger.info(f"[Embedding] {model_name} loaded on {device_of(model)} (requested {choice}), max_seq_length={model.max_seq_length}")
    return model


class ResilientEmbedder:
    """`embed_documents` over a SentenceTransformer that survives device out-of-memory errors.

    Texts are encoded in chunks of `batch_size`. On an out-of-memory error the device cache is
    emptied and the batch size is halved (the smaller size is kept for later chunks) until it
    reaches `min_batch_size`; a chunk that still fails at the floor is encoded on the CPU. Other
    errors propagate unchanged.
    """

    def __init__(self, model: Any, batch_size: int = DEFAULT_EMBED_BATCH_SIZE, min_batch_size: int = MIN_EMBED_BATCH_SIZE,
                 device: Optional[str] = None) -> None:
        """`device` defaults to the model's current device."""
        if batch_size < 1 or min_batch_size < 1:
            raise ValueError(f"batch sizes must be >= 1 (got {batch_size}, floor {min_batch_size})")
        self.model = model
        self.requested_batch_size = batch_size
        self.batch_size = batch_size
        self.min_batch_size = min(min_batch_size, batch_size)
        self.device = device or device_of(model)
        self.oom_events = 0
        self.cpu_fallback_batches = 0

    def _encode(self, texts: Sequence[str], batch_size: int, device: str) -> List[List[float]]:
        """One model.encode call on an explicit device (SentenceTransformer moves the model there)."""
        vectors = self.model.encode(list(texts), batch_size=batch_size, convert_to_numpy=True,
                                    show_progress_bar=False, device=device)
        return [list(map(float, vector)) for vector in vectors]

    def _encode_chunk(self, chunk: Sequence[str]) -> List[List[float]]:
        """Encodes one chunk, halving the batch on OOM, then falling back to the CPU at the floor."""
        while True:
            try:
                return self._encode(chunk, self.batch_size, self.device)
            except RuntimeError as e:
                if not is_out_of_memory(e):
                    raise
                self.oom_events += 1
                empty_device_cache(self.device)
                if self.batch_size > self.min_batch_size:
                    smaller = max(self.min_batch_size, self.batch_size // 2)
                    logger.warning(f"[Embedding] out of memory on {self.device} at batch size {self.batch_size}; retrying at {smaller}")
                    self.batch_size = smaller
                    continue
                logger.warning(
                    f"[Embedding] out of memory on {self.device} at the floor batch size {self.batch_size}; "
                    f"encoding this chunk of {len(chunk)} texts on the CPU"
                )
                vectors = self._encode(chunk, self.min_batch_size, CPU_DEVICE)
                self.cpu_fallback_batches += 1
                empty_device_cache(self.device)
                return vectors

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """One vector per text, in input order."""
        vectors: List[List[float]] = []
        start = 0
        while start < len(texts):
            chunk = texts[start:start + self.batch_size]
            vectors.extend(self._encode_chunk(chunk))
            start += len(chunk)
        return vectors
