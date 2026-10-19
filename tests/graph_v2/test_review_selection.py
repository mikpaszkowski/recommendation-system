"""
tests/graph_v2/test_review_selection.py

Review ID, rank key, top-K selection and embed ranks (FR-011, FR-012): AC-004 … AC-007.
"""
from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import List

from src.knowledge_graph.graph_v2.csv_io import read_import_csv
from src.knowledge_graph.graph_v2.review_selection import (
    ReviewCandidate,
    TopKSelector,
    assign_embed_ranks,
    load_pair_set,
    make_review_id,
    mark_train_pairs,
    select_top_reviews_reference,
)


def _cand(review_id: str, helpful: int = 0, verified: bool = True, ts: int = 0, offset: int = 0, has_text: bool = True) -> ReviewCandidate:
    return ReviewCandidate(helpful, verified, ts, review_id, offset, has_text, "U")


def test_cap_and_tie_order_on_25_reviews(fixture_build) -> None:
    """AC-004: the 25-review fixture product keeps exactly the expected 20 review_ids with cap_rank 1 … 20 in order."""
    _, base = fixture_build
    rid = lambda user, ts: make_review_id(user, "T001", ts)  # noqa: E731
    tie = lambda *pairs: sorted(rid(u, t) for u, t in pairs)  # noqa: E731
    expected: List[str] = (
        tie(("U001", 1600000000000), ("U002", 1600000000000))
        + [rid("U004", 1500000000000), rid("U003", 1700000000000)]
        + tie(("U005", 1600000000000), ("U006", 1600000000000))
        + tie(("U007", 1650000000000), ("U008", 1650000000000))
        + [rid(f"U{i:03d}", 1600000000000 + i) for i in (14, 13, 12, 11, 10)]
        + [rid(f"U{i:03d}", 1600000000000 - i) for i in (15, 16, 17, 18, 19)]
        + [rid("U009", 1660000000000), rid("U023", 1500000000023)]
    )
    about = {r[":START_ID(Review)"]: r[":END_ID(ParentProduct)"] for r in read_import_csv(base / "import" / "rels_about_product.csv")}
    rows = [r for r in read_import_csv(base / "import" / "nodes_review.csv") if about[r["review_id:ID(Review)"]] == "T001"]
    rows.sort(key=lambda r: int(r["cap_rank:int"]))
    assert [r["review_id:ID(Review)"] for r in rows] == expected
    assert [int(r["cap_rank:int"]) for r in rows] == list(range(1, 21))


def test_selector_matches_reference_on_seeded_fixtures() -> None:
    """AC-005: TopKSelector equals select_top_reviews_reference on 50 seeded random fixtures with duplicates and ties."""
    for seed in range(50):
        rng = random.Random(seed)
        cap = rng.randint(1, 6)
        cands = [
            _cand(f"r{rng.randint(0, 12)}", helpful=rng.randint(0, 2), verified=rng.random() < 0.5,
                  ts=rng.randint(0, 3), offset=offset * 10)
            for offset in range(rng.randint(0, 40))
        ]
        selector = TopKSelector(cap)
        for cand in cands:
            selector.offer("P", cand)
        got = selector.ranked().get("P", [])
        want = select_top_reviews_reference(cands, cap)
        assert [(c.review_id, c.offset) for c in got] == [(c.review_id, c.offset) for c in want], seed
        assert selector.offered_count == len(got) + selector.duplicate_count + selector.beyond_cap_count


def test_make_review_id_formula() -> None:
    """AC-006: make_review_id equals md5(f"{user_id}-{asin}-{timestamp}")."""
    assert make_review_id("U1", "B0", 1600000000000) == hashlib.md5(b"U1-B0-1600000000000").hexdigest()


def test_duplicate_review_id_better_rank_key_wins() -> None:
    """AC-006: same review_id collapses to the better rank key and is counted as duplicate_review_id."""
    selector = TopKSelector(5)
    selector.offer("P", _cand("dup", helpful=0, offset=0))
    selector.offer("P", _cand("other", helpful=1, offset=10))
    selector.offer("P", _cand("dup", helpful=3, offset=20))
    ranked = selector.ranked()["P"]
    assert [(c.review_id, c.helpful_vote) for c in ranked] == [("dup", 3), ("other", 1)]
    assert selector.duplicate_count == 1 and selector.beyond_cap_count == 0


def test_duplicate_review_id_equal_key_earlier_offset_wins(fixture_build) -> None:
    """AC-006: with equal rank keys the lower byte offset wins."""
    selector = TopKSelector(5)
    selector.offer("P", _cand("dup", helpful=2, offset=100))
    selector.offer("P", _cand("dup", helpful=2, offset=200))
    assert [c.offset for c in selector.ranked()["P"]] == [100]
    result, base = fixture_build
    assert result.lineage.counts.reviews.duplicate_review_id == 2
    bodies = [r["review_body"] for r in read_import_csv(base / "import" / "nodes_review.csv")]
    assert "dup high wins" in bodies and "dup low" not in bodies
    assert "first copy" in bodies and "second copy" not in bodies


def test_embed_ranks_skip_blank_reviews() -> None:
    """AC-007: embed_rank 1 … 5 for the first five non-blank reviews; a blank review gets None and uses no slot."""
    flags = [True, True, False, True, True, True, True, True]
    ranked = [_cand(f"r{i}", has_text=flag) for i, flag in enumerate(flags)]
    assert assign_embed_ranks(ranked, 5) == [1, 2, None, 3, 4, 5, None, None]


def test_embed_ranks_three_non_blank(fixture_build) -> None:
    """AC-007: a product with 3 non-blank reviews has exactly 3 embed ranks."""
    assert assign_embed_ranks([_cand(f"r{i}") for i in range(3)], 5) == [1, 2, 3]
    _, base = fixture_build
    about = {r[":START_ID(Review)"]: r[":END_ID(ParentProduct)"] for r in read_import_csv(base / "import" / "rels_about_product.csv")}
    t008 = [r for r in read_import_csv(base / "import" / "nodes_review.csv") if about[r["review_id:ID(Review)"]] == "T008"]
    assert sorted(int(r["embed_rank:int"]) for r in t008 if r["embed_rank:int"]) == [1, 2, 3]
    t002 = [r for r in read_import_csv(base / "import" / "nodes_review.csv") if about[r["review_id:ID(Review)"]] == "T002"]
    blank = [r for r in t002 if not r["review_title"] and not r["review_body"]]
    assert len(blank) == 1 and blank[0]["embed_rank:int"] == ""
    assert sorted(int(r["embed_rank:int"]) for r in t002 if r["embed_rank:int"]) == [1, 2, 3, 4]


def test_load_pair_set_and_mark_train(fixture_dir: Path) -> None:
    """AC-003 (support): split pairs are (user_id, parent_asin); mark_train_pairs returns the selected pairs found in train."""
    excluded = load_pair_set([fixture_dir / "Electronics.valid.csv", fixture_dir / "Electronics.test.csv"])
    assert excluded == {("U100", "T003"), ("U300", "T004"), ("U103", "T003")}
    selected = {("U101", "T003"), ("U102", "T003"), ("U001", "T001")}
    assert mark_train_pairs(fixture_dir / "Electronics.train.csv", selected) == {("U101", "T003"), ("U001", "T001")}
