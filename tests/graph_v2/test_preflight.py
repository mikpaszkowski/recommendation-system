"""
tests/graph_v2/test_preflight.py

Pre-flight error isolation and P-04 on Apple MPS (scripts/graph_ingestion/preflight_v2.py). The dry run is
injected (the fixture build's TransformResult), the model is a fake that raises the MPS out-of-memory error,
and Neo4j and Docker are fakes or skipped. Nothing reads datasets/raw/.
"""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, List

import pytest
from neo4j.exceptions import ServiceUnavailable

from src.knowledge_graph.graph_v2.embedding_runtime import DeviceUnavailableError
from src.knowledge_graph.graph_v2.lineage import InputVerificationError
from src.knowledge_graph.graph_v2.models import PreflightReport

from .fakes_embedding import FakeModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("preflight_v2_under_test", REPO_ROOT / "scripts" / "graph_ingestion" / "preflight_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PF = _module()


@pytest.fixture
def cache_calls(monkeypatch) -> List[Any]:
    calls: List[Any] = []
    monkeypatch.setattr(PF, "empty_device_cache", lambda device: calls.append(device))
    return calls


def _argv(tmp_path: Path, fixture_dir: Path, *extra: str) -> List[str]:
    return ["--out", str(tmp_path / "preflight_report.json"), "--meta", str(fixture_dir / "meta.jsonl"),
            "--reviews", str(fixture_dir / "reviews.jsonl"), "--sha256sums", str(fixture_dir / "SHA256SUMS"),
            "--splits-dir", str(fixture_dir), "--catalogue", str(fixture_dir / "catalogue.txt"),
            "--throughput-texts", "10", "--throughput-batch-sizes", "32", "8", "--skip-docker", *extra]


def _report(tmp_path: Path) -> PreflightReport:
    return PreflightReport.model_validate_json((tmp_path / "preflight_report.json").read_text(encoding="utf-8"))


def test_measure_throughput_retries_half_then_records_error(cache_calls) -> None:
    """P-04: an OOM batch size is retried once at half size; a second OOM is recorded for that size and the next size still runs."""
    model = FakeModel(oom_above=16, max_seq_length=None)
    texts = [f"text {i}" for i in range(10)]
    result = PF.measure_throughput(model, texts, [32, 128, 8], {"Review": 1000})
    assert result["device"] == "mps:0" and result["max_seq_length"] == 256 and model.max_seq_length == 256
    sizes = result["batch_sizes"]
    assert sizes["32"]["retried_after_oom"] is True and sizes["32"]["batch_size"] == 16 and "texts_per_s" in sizes["32"]
    assert sizes["128"]["retried_at"] == 64 and sizes["128"]["error"].startswith("RuntimeError: MPS backend out of memory")
    assert "texts_per_s" in sizes["8"] and set(result["texts_per_s"]) == {"32", "8"}
    assert result["best_batch_size"] in (16, 8) and "Review" in result["minutes_per_label"]
    assert [c[1] for c in model.calls] == [32, 16, 128, 64, 8]
    assert cache_calls.count("mps:0") >= 5


def test_measure_throughput_all_sizes_fail_raises(cache_calls) -> None:
    """P-04: when no batch size completes, the section raises (and is then recorded as failed by run_section)."""
    with pytest.raises(RuntimeError, match="no batch size completed"):
        PF.measure_throughput(FakeModel(oom_always=True), ["a"], [4], None)
    sections, failed = {}, []
    PF.run_section("p04", sections, failed, lambda: PF.measure_throughput(FakeModel(oom_always=True), ["a"], [4], None))
    assert failed == ["p04"] and sections["p04"]["error"].startswith("RuntimeError: no batch size completed")


def test_measure_throughput_non_oom_error_propagates() -> None:
    """P-04: a non-OOM encode error is not mistaken for memory pressure."""
    class Broken(FakeModel):
        def encode(self, *args, **kwargs):
            raise RuntimeError("tokenizer exploded")

    with pytest.raises(RuntimeError, match="tokenizer exploded"):
        PF.measure_throughput(Broken(), ["a"], [4], None)


def test_main_isolates_failed_sections_and_writes_report(fixture_build, fixture_dir: Path, tmp_path: Path, caplog, cache_calls) -> None:
    """A failed P-04 (MPS OOM at every size) and failed P-08/P-09 (v1 unreachable) are recorded; the other sections are kept and the report is written (exit 0)."""
    result, _ = fixture_build

    class _DeadSession:
        def run(self, *args, **kwargs):
            raise ServiceUnavailable("v1 is down")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    with caplog.at_level(logging.WARNING, logger="preflight_v2"):
        code = PF.main(_argv(tmp_path, fixture_dir), session_factory=_DeadSession, model=FakeModel(oom_always=True),
                       dry_run=lambda config: result)
    assert code == 0
    report = _report(tmp_path)
    assert report.failed_sections == ["p04", "p08", "p09"]
    assert report.p04_throughput["error"].startswith("RuntimeError: no batch size completed")
    assert report.p08_v1_snapshot["error"].startswith("ServiceUnavailable")
    assert report.p01_meta_coverage["products_written"] == 11 and report.p02_review_funnel["kept"] == 34
    assert report.p10_timing["dry_run_peak_rss_bytes"] > 0 and "timing_s" in report.p10_timing
    assert "v1_settings_error" in report.p07_environment and "error" not in report.p07_environment
    assert any("FAILED sections ['p04', 'p08', 'p09']" in r.getMessage() for r in caplog.records)


def test_main_success_with_skip_v1(fixture_build, fixture_dir: Path, tmp_path: Path, cache_calls) -> None:
    """With a healthy model and --skip-v1 nothing fails: P-04 records the device, P-08/P-09 are skipped."""
    result, _ = fixture_build
    model = FakeModel(oom_above=16)
    code = PF.main(_argv(tmp_path, fixture_dir, "--skip-v1"), model=model, dry_run=lambda config: result)
    report = _report(tmp_path)
    assert code == 0 and report.failed_sections == []
    assert report.p04_throughput["device"] == "mps:0" and report.p04_throughput["batch_sizes"]["32"]["retried_after_oom"] is True
    assert report.p04_throughput["texts"] == 10
    assert report.p08_v1_snapshot == {"skipped": True} and report.p09_template_conformance == {"skipped": True}
    assert report.p04_throughput["minutes_per_label"]["Review"] is not None


def test_main_dry_run_input_error_exits_2(fixture_dir: Path, tmp_path: Path) -> None:
    """A dry-run input error (e.g. SHA-256 mismatch) still exits 2 without a report."""
    def failing(config):
        raise InputVerificationError("SHA-256 mismatch")

    assert PF.main(_argv(tmp_path, fixture_dir, "--skip-v1"), model=FakeModel(), dry_run=failing) == 2
    assert not (tmp_path / "preflight_report.json").exists()


def test_main_dry_run_crash_still_writes_report(fixture_dir: Path, tmp_path: Path, cache_calls) -> None:
    """An unexpected dry-run failure marks P-01, P-02, P-03, P-05, P-06 and P-10 failed; P-04 still runs and the report is written."""
    def crashing(config):
        raise MemoryError("dry run ran out of memory")

    code = PF.main(_argv(tmp_path, fixture_dir, "--skip-v1"), model=FakeModel(), dry_run=crashing)
    report = _report(tmp_path)
    assert code == 0 and report.failed_sections == ["p01", "p02", "p03", "p05", "p06", "p10"]
    assert report.p01_meta_coverage == {"error": "MemoryError: dry run ran out of memory"}
    assert "texts_per_s" in report.p04_throughput and report.p04_throughput["minutes_per_label"] == {}


def test_main_model_load_failure_recorded_once(fixture_build, fixture_dir: Path, tmp_path: Path, monkeypatch, cache_calls) -> None:
    """--embed-device mps on a machine without MPS fails P-04 and P-09 with the same recorded error; the model load is attempted once."""
    result, _ = fixture_build
    attempts: List[str] = []

    def unavailable(choice):
        attempts.append(choice)
        raise DeviceUnavailableError("--embed-device mps requested, but torch reports MPS as unavailable")

    monkeypatch.setattr(PF, "load_model", unavailable)
    session = type("S", (), {"run": lambda self, *a, **k: [], "__enter__": lambda self: self, "__exit__": lambda self, *e: False})
    code = PF.main(_argv(tmp_path, fixture_dir, "--embed-device", "mps"), session_factory=session, dry_run=lambda config: result)
    report = _report(tmp_path)
    assert code == 0 and attempts == ["mps"]
    assert report.failed_sections == ["p04", "p08", "p09"]
    assert report.p08_v1_snapshot["error"].startswith("AttributeError")  # an unexpected bug is recorded, not fatal
    assert report.p04_throughput["error"].startswith("DeviceUnavailableError")
    assert json.loads((tmp_path / "preflight_report.json").read_text())["p09_template_conformance"]["error"].startswith("DeviceUnavailableError")


def test_parser_embed_device_flag() -> None:
    """--embed-device accepts auto, cpu and mps (default auto); the default batch sizes no longer include 512."""
    parser = PF.build_parser()
    assert parser.parse_args([]).embed_device == "auto" and parser.parse_args([]).throughput_batch_sizes == [32, 128]
    assert parser.parse_args(["--embed-device", "cpu"]).embed_device == "cpu"
    with pytest.raises(SystemExit):
        parser.parse_args(["--embed-device", "cuda"])
