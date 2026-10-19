"""
tests/graph_v2/test_embedding_runtime.py

Embedding device selection and out-of-memory resilient encoding (graph_v2.embedding_runtime): MPS OOM is
simulated with a fake model, no model is downloaded.
"""
from __future__ import annotations

from typing import List

import pytest

from src.knowledge_graph.graph_v2 import embedding_runtime as er

from .fakes_embedding import MPS_OOM, FakeModel


@pytest.fixture
def cache_calls(monkeypatch) -> List[str]:
    calls: List[str] = []
    monkeypatch.setattr(er, "empty_device_cache", lambda device: calls.append(device))
    return calls


def test_is_out_of_memory() -> None:
    """MPS and CUDA out-of-memory RuntimeErrors are recognised; other errors are not."""
    assert er.is_out_of_memory(RuntimeError(MPS_OOM))
    assert er.is_out_of_memory(RuntimeError("CUDA out of memory. Tried to allocate 2 GiB"))
    assert not er.is_out_of_memory(RuntimeError("shape mismatch"))
    assert not er.is_out_of_memory(ValueError("out of memory"))


def test_resolve_device(monkeypatch) -> None:
    """auto -> None (SentenceTransformer picks), cpu -> cpu, mps only when available, unknown rejected."""
    import torch

    assert er.resolve_device("auto") is None and er.resolve_device("cpu") == "cpu"
    with pytest.raises(er.DeviceUnavailableError):
        er.resolve_device("cuda")
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    with pytest.raises(er.DeviceUnavailableError):
        er.resolve_device("mps")
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert er.resolve_device("mps") == "mps"


def test_ensure_max_seq_length() -> None:
    """An unset or too large max_seq_length is capped at 256 word pieces; a smaller one is kept."""
    assert er.ensure_max_seq_length(FakeModel(max_seq_length=None)) == 256
    assert er.ensure_max_seq_length(FakeModel(max_seq_length=512)) == 256
    assert er.ensure_max_seq_length(FakeModel(max_seq_length=128)) == 128
    assert er.ensure_max_seq_length(object()) is None


def test_empty_device_cache_is_safe_on_cpu() -> None:
    """Emptying the cache on CPU or an unknown device never raises."""
    er.empty_device_cache("cpu")
    er.empty_device_cache(None)
    er.empty_device_cache("mps:0")


def test_resilient_halves_batch_on_oom(cache_calls) -> None:
    """OOM at 32 and 16 halves the batch to 8 (kept for later chunks); vectors stay in order; the cache is emptied each time."""
    model = FakeModel(oom_above=8)
    embedder = er.ResilientEmbedder(model, batch_size=32, min_batch_size=4)
    texts = [f"text {'x' * i}" for i in range(40)]
    vectors = embedder.embed_documents(texts)
    assert len(vectors) == 40 and [v[0] for v in vectors] == [float(len(t) % 7) for t in texts]
    assert embedder.batch_size == 8 and embedder.requested_batch_size == 32
    assert embedder.oom_events == 2 and embedder.cpu_fallback_batches == 0
    assert cache_calls == ["mps:0", "mps:0"]
    assert [(c[0], c[1]) for c in model.calls] == [(32, 32), (32, 16), (32, 8), (8, 8)]
    assert all(device == "mps:0" for _, _, device in model.calls)


def test_resilient_falls_back_to_cpu_at_floor(cache_calls) -> None:
    """When even the floor batch runs out of MPS memory, that chunk is encoded on the CPU and counted; the next chunk tries MPS again."""
    model = FakeModel(oom_always=True)
    embedder = er.ResilientEmbedder(model, batch_size=16, min_batch_size=8)
    texts = [f"t{i}" for i in range(20)]
    vectors = embedder.embed_documents(texts)
    assert len(vectors) == 20 and [v[0] for v in vectors] == [float(len(t) % 7) for t in texts]
    assert model.calls == [(16, 16, "mps:0"), (16, 8, "mps:0"), (16, 8, "cpu"), (4, 8, "mps:0"), (4, 8, "cpu")]
    assert (embedder.batch_size, embedder.cpu_fallback_batches, embedder.oom_events) == (8, 2, 3)


def test_resilient_propagates_other_errors() -> None:
    """A non-OOM error is not swallowed."""
    model = FakeModel(oom_always=True, cpu_error_on_call=1)
    embedder = er.ResilientEmbedder(model, batch_size=8, min_batch_size=8)
    with pytest.raises(RuntimeError, match="cpu encode failed"):
        embedder.embed_documents(["a", "b"])
    with pytest.raises(ValueError):
        er.ResilientEmbedder(model, batch_size=0)
