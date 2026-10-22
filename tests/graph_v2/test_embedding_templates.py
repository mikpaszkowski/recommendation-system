"""
tests/graph_v2/test_embedding_templates.py

v1 embedding templates and skip-empty rules (§4.1.4): AC-022.
"""
from __future__ import annotations

from src.knowledge_graph.graphdb.attribute_normalizer import AttributeNormalizer
from src.knowledge_graph.graphdb.embedding_templates import (
    attribute_text_v1,
    brand_text_v1,
    category_parent_text_legacy,
    category_text_v1,
    has_product_content,
    product_text_v1,
    review_text_v1,
)


def test_product_text_v1_matches_v1_string() -> None:
    """AC-022: product_text_v1 reproduces the v1 BackfillService string, top 5 attribute pairs."""
    pairs = [f"K{i}: v{i}" for i in range(7)]
    assert product_text_v1("Cable", "All Electronics", pairs, "Desc", None) == (
        "Product: Cable. Category: All Electronics. Features: K0: v0, K1: v1, K2: v2, K3: v3, K4: v4. Description: Desc"
    )
    assert product_text_v1("Cable", None, [], None, ["f"]) == "Product: Cable. Category: Unknown. Features: . Description: "
    assert product_text_v1(None, "C", [], None, ["Only features"]) == "Product: . Category: C. Features: . Description: "


def test_product_text_none_without_content() -> None:
    """AC-022: None when title, description and features are all blank."""
    assert product_text_v1(None, "C", ["Color: Black"], "  ", [" ", ""]) is None
    assert product_text_v1("", None, [], None, None) is None
    assert has_product_content(None, None, ["x"]) is True


def test_product_content_rule_title_description() -> None:
    """OQ-1 (support): rule title_description treats a features-only product as content-free."""
    assert has_product_content(None, None, ["x"], rule="title_description") is False
    assert product_text_v1(None, "C", [], None, ["x"], rule="title_description") is None
    assert has_product_content("T", None, None, rule="title_description") is True


def test_review_text_v1() -> None:
    """AC-022: review_text_v1 matches v1, is None when title and body are blank, and is cut at 800 characters."""
    assert review_text_v1("Great", "Works") == "Great. Works"
    assert review_text_v1(None, "Works") == ". Works"
    assert review_text_v1("  ", "") is None and review_text_v1(None, None) is None
    long = review_text_v1("T", "x" * 1000)
    assert len(long) == 800 and long == ("T. " + "x" * 1000)[:800]


def test_brand_text_v1() -> None:
    """AC-022: brand_text_v1 matches v1."""
    assert brand_text_v1("Anker") == "Brand: Anker. Domain: consumer electronics"


def test_attribute_text_v1() -> None:
    """AC-022: attribute_text_v1 matches v1 for a generic key and a named key."""
    assert attribute_text_v1("Size", "16gb") == f"Size: {AttributeNormalizer.normalize('16gb', 'Size')}" == "Size: 16 GB"
    assert attribute_text_v1("feature", "Fast") == AttributeNormalizer.normalize("Fast", "feature")
    assert attribute_text_v1("Color", "Black") == f"Color: {AttributeNormalizer.normalize('Black', 'Color')}" == "Color: black"


def test_category_text_v1() -> None:
    """AC-022: category_text_v1 matches backfill_category_embeddings (root context, 10-word titles, no samples)."""
    long_title = " ".join(f"w{i}" for i in range(15))
    assert category_text_v1("Cables", None, [long_title, None, "Short one"]) == (
        "Category: Cables. Context: Root Category. Related items: w0 w1 w2 w3 w4 w5 w6 w7 w8 w9, Short one."
    )
    assert category_text_v1("Subwoofers", ["Electronics", "Car Audio", "Subwoofers"], []) == (
        "Category: Subwoofers. Context: Electronics, Car Audio. Related items: None."
    )
    assert category_parent_text_legacy("Cables", None) == "Category: Cables. Parent: Root"
