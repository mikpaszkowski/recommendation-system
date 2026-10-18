"""
tests/test_live_eval_gold_annotations.py

Appendix A gold annotations on the legacy-21 benchmark (Technical Specification AC-011, FR-012, FR-013).
"""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.evaluation.constraint_satisfaction import parse_gold_constraints, validate_gold_annotations

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = REPO_ROOT / "live_eval_dataset.json"
TARGET_DERIVED_FIELDS = ("structured_filters", "preferences", "target_asin", "target_title")


@pytest.fixture(scope="module")
def benchmark() -> List[Dict[str, Any]]:
    return json.loads(BENCHMARK.read_text(encoding="utf-8"))


def test_annotations_validate(benchmark):
    assert validate_gold_annotations(benchmark) == []


def test_all_items_are_type_explicit_search(benchmark):
    assert len(benchmark) == 21
    assert all(item["type_explicit"] is True for item in benchmark)
    assert all(item["gold_action"] == "SEARCH" for item in benchmark)
    assert all(isinstance(item["gold_product_type"], str) and item["gold_product_type"] for item in benchmark)


def test_constraint_counts_match_appendix_a(benchmark):
    kinds = Counter(c["kind"] for item in benchmark for c in item["gold_constraints"])
    assert kinds == {"price": 12, "brand": 7, "numeric": 19}
    no_constraints = sorted(item["query_id"] for item in benchmark if not item["gold_constraints"])
    assert no_constraints == [
        "live_eval_camera_02", "live_eval_headphone_01", "live_eval_headphone_03", "live_eval_mouse_02",
    ]


def test_evidence_is_quoted_from_the_utterance(benchmark):
    for item in benchmark:
        for constraint in item["gold_constraints"]:
            assert constraint["evidence"].lower() in item["utterance"].lower(), (item["query_id"], constraint)


def test_numeric_constraints_have_no_graph_attribute_names(benchmark):
    """Option 1 (Gate #3): the live graph has no Attribute.numeric_value, so every list stays empty."""
    numeric = [c for item in benchmark for c in parse_gold_constraints(item["gold_constraints"]) if c.kind == "numeric"]
    assert len(numeric) == 19
    assert all(c.graph_attribute_names == () for c in numeric)


def test_selected_labels(benchmark):
    by_id = {item["query_id"]: [c.label for c in parse_gold_constraints(item["gold_constraints"])] for item in benchmark}
    assert by_id["live_eval_charger_01"] == ["price<=60", "output_power=65W", "port_count>=4ports", "usb_c_port_count>=3ports"]
    assert by_id["live_eval_phone_03"] == ["price<=220", "brand+Apple"]
    assert by_id["live_eval_laptop_03"] == ["price<=750", "screen_size=15.6in", "refresh_rate>=144Hz"]


def test_target_derived_fields_unchanged_against_head(benchmark):
    try:
        proc = subprocess.run(
            ["git", "show", "HEAD:live_eval_dataset.json"], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        pytest.skip(f"git unavailable: {e}")
    if proc.returncode != 0:
        pytest.skip("live_eval_dataset.json is not in git HEAD")
    head = {item["query_id"]: item for item in json.loads(proc.stdout)}
    for item in benchmark:
        old = head[item["query_id"]]
        for field in TARGET_DERIVED_FIELDS + ("utterance", "peer_asins", "ground_truth_asins"):
            assert item.get(field) == old.get(field), (item["query_id"], field)
        assert set(old) <= set(item)
