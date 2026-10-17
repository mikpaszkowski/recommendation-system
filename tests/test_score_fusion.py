"""
Unit tests for src/tools/score_fusion.py (Retrieval Score Redesign R1).

Covers Technical Specification acceptance criteria AC-001 … AC-006: MaxP gives no
fan-out credit, exact RRF values, competition ranking, order independence, ablation
arms, score bounds and environment selection.
"""
import itertools
import math

import pytest

from src.tools.score_fusion import (
    CHANNELS,
    FUSION_ARMS,
    ChannelHit,
    FusionConfig,
    competition_ranks,
    fuse,
)

# Brainstorm example for ret_021 (brainstorm.html): best title similarity, attribute and review match similarities
BRAINSTORM_PRODUCTS = {
    "C920": (0.773, [0.71, 0.66], []),
    "QuickCam": (0.650, [0.58], [0.72, 0.70, 0.69, 0.68, 0.67, 0.66, 0.66, 0.66]),
    "NoName": (0.742, [0.69, 0.64, 0.61], []),
    "Cover": (0.550, [], [0.66, 0.65, 0.64, 0.63, 0.63, 0.62, 0.62, 0.62, 0.61, 0.61, 0.61, 0.60, 0.60, 0.58]),
    "Mic": (0.580, [0.70], [0.70, 0.67, 0.66, 0.65, 0.64, 0.64]),
    "Ring": (0.520, [], [0.69, 0.67, 0.66, 0.66, 0.65, 0.65, 0.65, 0.64, 0.64, 0.64, 0.64, 0.63, 0.63, 0.63, 0.63, 0.62, 0.62, 0.62, 0.61, 0.61]),
}


def _brainstorm_hits():
    """Raw (non-deduplicated) channel hits, one per matching node, as Neo4j would see them."""
    hits = {"product": [], "attribute": [], "review": []}
    for asin, (title, attrs, revs) in BRAINSTORM_PRODUCTS.items():
        hits["product"].append(ChannelHit(asin, title, "Product Title Match"))
        hits["attribute"].extend(ChannelHit(asin, s, f"attr {i}") for i, s in enumerate(attrs))
        hits["review"].extend(ChannelHit(asin, s, f"review {i}") for i, s in enumerate(revs))
    return hits


def test_fan_out_gives_no_extra_credit():
    """AC-001: 50 attribute hits with best similarity 0.8 count the same as a single 0.8 hit."""
    hub = [ChannelHit("HUB", 0.8, "a")] + [ChannelHit("HUB", 0.8 - 0.001 * i, f"a{i}") for i in range(1, 50)]
    single = [ChannelHit("ONE", 0.8, "a")]
    config = FusionConfig(name="attr_only", channels=("attribute",))

    fused = {fc.asin: fc.score for fc in fuse({"attribute": hub + single}, config)}

    assert fused["HUB"] == pytest.approx(fused["ONE"])
    assert fused["HUB"] == pytest.approx(1.0 / 61)


def test_rrf_score_matches_formula():
    """AC-002: score = sum_c w_c / (60 + rank_c)."""
    hits = {
        "product": [ChannelHit("A", 0.9, "p"), ChannelHit("B", 0.8, "p")],
        "attribute": [ChannelHit("B", 0.7, "a"), ChannelHit("A", 0.6, "a")],
        "review": [ChannelHit("B", 0.5, "r")],
    }
    fused = {fc.asin: fc for fc in fuse(hits, FUSION_ARMS["rrf3"])}

    assert fused["A"].score == pytest.approx(1 / 61 + 1 / 62)
    assert fused["B"].score == pytest.approx(1 / 62 + 1 / 61 + 1 / 61)
    assert fused["B"].channels["review"].rank == 1
    assert "review" not in fused["A"].channels


def test_brainstorm_example_orders():
    """AC-002: the brainstorm's ret_021 example reproduces the published rrf3 and rrf2 orders."""
    hits = _brainstorm_hits()

    rrf3 = [fc.asin for fc in fuse(hits, FUSION_ARMS["rrf3"])]
    rrf2 = [fc.asin for fc in fuse(hits, FUSION_ARMS["rrf2"])]

    assert rrf3 == ["QuickCam", "Mic", "C920", "NoName", "Ring", "Cover"]
    assert rrf2 == ["C920", "NoName", "Mic", "QuickCam", "Cover", "Ring"]


def test_competition_ranks_share_ties():
    """AC-003: equal similarities share the best rank (1, 2, 2, 4); ties order by asin."""
    hits = [ChannelHit("D", 0.5, "d"), ChannelHit("C", 0.7, "c"), ChannelHit("A", 0.9, "a"), ChannelHit("B", 0.7, "b")]

    ranks = competition_ranks(hits)

    assert {asin: ev.rank for asin, ev in ranks.items()} == {"A": 1, "B": 2, "C": 2, "D": 4}
    assert list(ranks) == ["A", "B", "C", "D"]


def test_competition_ranks_keep_best_duplicate():
    """Duplicated ASINs keep their highest similarity and that match's reason."""
    ranks = competition_ranks([ChannelHit("A", 0.4, "weak"), ChannelHit("A", 0.9, "strong")])

    assert ranks["A"].similarity == 0.9
    assert ranks["A"].reason == "strong"


def test_fusion_is_order_independent():
    """AC-003: any permutation of the input lists yields the same fused order and scores."""
    hits = _brainstorm_hits()
    expected = [(fc.asin, fc.score) for fc in fuse(hits, FUSION_ARMS["rrf3"])]

    for permutation in itertools.islice(itertools.permutations(range(len(hits["review"]))), 0, 50, 7):
        shuffled = dict(hits)
        shuffled["review"] = [hits["review"][i] for i in permutation]
        shuffled["product"] = list(reversed(hits["product"]))
        assert [(fc.asin, fc.score) for fc in fuse(shuffled, FUSION_ARMS["rrf3"])] == expected


def test_fused_ties_break_by_channel_count_then_similarity_then_asin():
    """FR-006: equal fused scores order by channels matched, best similarity, then asin."""
    config = FusionConfig(name="two", channels=("product", "attribute"))
    hits = {
        "product": [ChannelHit("X", 0.9, "p"), ChannelHit("Y", 0.9, "p")],
        "attribute": [ChannelHit("Z", 0.95, "a"), ChannelHit("W", 0.9, "a")],
    }

    order = [fc.asin for fc in fuse(hits, config)]

    # X and Y tie at product rank 1, Z is attribute rank 1: all three score 1/61, W (rank 2) scores 1/62.
    # Among the tie, Z has the best similarity; X and Y fall back to asin order.
    assert order == ["Z", "X", "Y", "W"]

    hits["attribute"].append(ChannelHit("X", 0.5, "a"))
    assert [fc.asin for fc in fuse(hits, config)][0] == "X"


def test_rrf2_ignores_review_channel():
    """AC-004: rrf2 never scores review hits."""
    hits = {"product": [ChannelHit("A", 0.5, "p")], "review": [ChannelHit("B", 0.99, "r")]}

    fused = fuse(hits, FUSION_ARMS["rrf2"])

    assert [fc.asin for fc in fused] == ["A"]


def test_weighted_rrf_applies_afp002_weights():
    """AC-004: wrrf3 uses 0.60 / 0.25 / 0.15."""
    hits = {c: [ChannelHit("A", 0.5, c)] for c in CHANNELS}

    fused = fuse(hits, FUSION_ARMS["wrrf3"])

    assert fused[0].score == pytest.approx((0.60 + 0.25 + 0.15) / 61)


def test_cc_normalises_and_stays_bounded():
    """AC-004: cc3 min-max normalises per channel, a constant list maps to 1.0, scores stay in [0, 1]."""
    hits = {
        "product": [ChannelHit("A", 0.9, "p"), ChannelHit("B", 0.7, "p"), ChannelHit("C", 0.5, "p")],
        "attribute": [ChannelHit("B", 0.6, "a"), ChannelHit("C", 0.6, "a")],
        "review": [],
    }

    fused = {fc.asin: fc.score for fc in fuse(hits, FUSION_ARMS["cc3"])}

    assert fused["A"] == pytest.approx(1 / 3)
    assert fused["B"] == pytest.approx(1 / 3 * 0.5 + 1 / 3)
    assert fused["C"] == pytest.approx(1 / 3)
    assert all(0.0 <= score <= 1.0 for score in fused.values())


def test_max_fused_score_per_arm():
    """AC-005: maximum attainable fused score per arm, and no fused score exceeds it."""
    assert FUSION_ARMS["rrf3"].max_fused_score() == pytest.approx(3 / 61)
    assert FUSION_ARMS["rrf2"].max_fused_score() == pytest.approx(2 / 61)
    assert FUSION_ARMS["wrrf3"].max_fused_score() == pytest.approx(1 / 61)
    assert FUSION_ARMS["cc3"].max_fused_score() == pytest.approx(1.0)
    assert math.isnan(FUSION_ARMS["sum_legacy"].max_fused_score())

    hits = _brainstorm_hits()
    for name in ("rrf3", "rrf2", "wrrf3", "cc3"):
        config = FUSION_ARMS[name]
        assert max(fc.score for fc in fuse(hits, config)) <= config.max_fused_score() + 1e-12


def test_soft_bonus_unit():
    """FR-008: unit = beta x max fused score; the legacy sum keeps 0.2."""
    assert FUSION_ARMS["rrf3"].soft_bonus_unit() == pytest.approx(0.25 * 3 / 61)
    assert FUSION_ARMS["cc3"].soft_bonus_unit() == pytest.approx(0.25)
    assert FUSION_ARMS["sum_legacy"].soft_bonus_unit() == pytest.approx(0.2)


def test_fuse_rejects_sum_method():
    """The legacy sum never goes through the Python fuser."""
    with pytest.raises(ValueError):
        fuse({"product": [ChannelHit("A", 0.5, "p")]}, FUSION_ARMS["sum_legacy"])


def test_from_env_selects_arm(monkeypatch):
    """AC-006: RETRIEVAL_FUSION_ARM selects the preset, case-insensitively."""
    monkeypatch.setenv("RETRIEVAL_FUSION_ARM", " CC3 ")

    assert FusionConfig.from_env().name == "cc3"


def test_from_env_unknown_falls_back(monkeypatch, caplog):
    """AC-006: an unknown arm logs a warning and falls back to rrf3."""
    monkeypatch.setenv("RETRIEVAL_FUSION_ARM", "borda")

    with caplog.at_level("WARNING"):
        config = FusionConfig.from_env()

    assert config.name == "rrf3"
    assert "borda" in caplog.text


def test_from_env_default(monkeypatch):
    """No variable set: rrf3."""
    monkeypatch.delenv("RETRIEVAL_FUSION_ARM", raising=False)

    assert FusionConfig.from_env() is FUSION_ARMS["rrf3"]


def test_to_dict_is_serialisable():
    """Config metadata is plain JSON."""
    import json

    payload = json.loads(json.dumps(FUSION_ARMS["wrrf3"].to_dict()))

    assert payload["name"] == "wrrf3"
    assert payload["weights"] == {"product": 0.60, "attribute": 0.25, "review": 0.15}
