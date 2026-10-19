"""Fake SentenceTransformer-like model that raises the MPS out-of-memory RuntimeError on demand (no model download)."""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

MPS_OOM = ("MPS backend out of memory (MPS allocated: 3.03 GiB, other allocations: 16.92 GiB, max allowed: 20.13 GiB). "
           "Tried to allocate 291.38 MiB on private pool.")


class FakeModel:
    """encode() records (n_texts, batch_size, device); raises the MPS OOM error when the batch is too large for MPS."""

    def __init__(self, oom_above: Optional[int] = None, oom_always: bool = False, device: str = "mps:0",
                 max_seq_length: Optional[int] = 256, cpu_error_on_call: Optional[int] = None) -> None:
        self.oom_above = oom_above
        self.oom_always = oom_always
        self.device = device
        self.max_seq_length = max_seq_length
        self.cpu_error_on_call = cpu_error_on_call
        self.calls: List[Tuple[int, int, str]] = []

    def encode(self, texts: Sequence[str], batch_size: int = 32, convert_to_numpy: bool = True,
               show_progress_bar: bool = False, device: Optional[str] = None):
        device = device or self.device
        self.calls.append((len(texts), batch_size, device))
        if device.startswith("mps") and (self.oom_always or (self.oom_above is not None and batch_size > self.oom_above)):
            raise RuntimeError(MPS_OOM)
        if device == "cpu" and self.cpu_error_on_call is not None and len(self.calls) >= self.cpu_error_on_call:
            raise RuntimeError("cpu encode failed")
        return np.array([[float(len(text) % 7)] + [0.0] * 383 for text in texts])
