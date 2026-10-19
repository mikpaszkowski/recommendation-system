"""
tests/test_graph_cypher_prompt.py

G-12 prompt cleanup in graph_cypher_prompt.py (Technical Specification Graph Rebuild FR-036): AC-039.
"""
from __future__ import annotations

from src.llm_interface.prompts.graph_cypher_prompt import prompt


def test_no_legacy_schema_terms() -> None:
    """AC-039: the prompt contains none of Variant, PriceRange, IN_PRICE_RANGE, IS_VARIANT_OF."""
    text = prompt()
    for term in ("Variant", "PriceRange", "IN_PRICE_RANGE", "IS_VARIANT_OF"):
        assert term not in text, term


def test_context_placeholder_kept() -> None:
    """AC-039: the prompt still contains {context}."""
    assert "{context}" in prompt()


def test_budget_example_orders_by_price() -> None:
    """AC-039: the budget example orders by pp.price ASC and requires pp.price IS NOT NULL."""
    text = prompt()
    start = text.index("Show me budget headphones.")
    example = text[start:text.index("</output>", start)]
    assert "AND pp.price IS NOT NULL" in example and "ORDER BY pp.price ASC LIMIT $limit" in example
    assert "do not invent a ceiling; keep products with a known price and sort by `pp.price ASC`" in text
