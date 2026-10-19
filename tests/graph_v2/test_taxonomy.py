"""
tests/graph_v2/test_taxonomy.py

Taxon tree builder (FR-010): AC-012 (a) … (g).
"""
from __future__ import annotations

import pytest

from src.knowledge_graph.graph_v2.taxonomy import TaxonIdCollisionError, TaxonomyBuilder, normalize_levels


def _tree() -> TaxonomyBuilder:
    builder = TaxonomyBuilder()
    builder.add_product("P1", ["Electronics", "Television & Video", "Accessories", "Cables", "HDMI Cables"], "All Electronics")
    builder.add_product("P2", ["Electronics", "Computers & Accessories", "Accessories"], "Computers")
    builder.add_product("P3", ["Electronics", "Computers & Accessories"], "Computers")
    builder.add_product("P4", [], "Cell Phones & Accessories")
    builder.add_product("P5", ["Home Audio"], "Home Audio")
    builder.add_product("P6", [], None)
    return builder


def test_same_leaf_name_in_two_branches() -> None:
    """AC-012a: identical leaf names in two branches give two Taxon rows with different taxon_id and the same name."""
    rows = [row for row in _tree().nodes() if row.name == "Accessories"]
    assert len(rows) == 2 and len({row.taxon_id for row in rows}) == 2
    assert {row.taxon_id for row in rows} == {
        "Electronics > Television & Video > Accessories", "Electronics > Computers & Accessories > Accessories",
    }


def test_inner_level_assignment() -> None:
    """AC-012b: a product listed at an inner level is assigned to that inner node."""
    builder = _tree()
    assert dict(builder.assignments())["P3"] == "Electronics > Computers & Accessories"
    assert builder.inner_node_assignments() == 1


def test_empty_path_counted_by_main_category() -> None:
    """AC-012c: an empty list gives no IN_TAXON and is counted under its main_category."""
    builder = _tree()
    assigned = dict(builder.assignments())
    assert "P4" not in assigned and "P6" not in assigned
    assert builder.products_without_taxon() == {"": 1, "Cell Phones & Accessories": 1}


def test_multiple_roots_allowed() -> None:
    """AC-012d: two roots are allowed."""
    assert _tree().roots() == ["Electronics", "Home Audio"]


def test_broader_child_to_parent() -> None:
    """AC-012e: BROADER goes child -> parent with depth − 1."""
    builder = _tree()
    depth = {row.taxon_id: row.depth for row in builder.nodes()}
    edges = builder.broader_edges()
    assert ("Electronics > Television & Video", "Electronics") in edges
    assert all(depth[child] == depth[parent] + 1 for child, parent in edges)
    non_roots = [taxon_id for taxon_id, d in depth.items() if d > 1]
    assert sorted(child for child, _ in edges) == sorted(non_roots)
    assert builder.max_depth() == 5


def test_product_counts_subtree_and_direct() -> None:
    """AC-012f: product_count (subtree) and direct_product_count are correct."""
    rows = {row.taxon_id: row for row in _tree().nodes()}
    assert (rows["Electronics"].product_count, rows["Electronics"].direct_product_count) == (3, 0)
    cpa = rows["Electronics > Computers & Accessories"]
    assert (cpa.product_count, cpa.direct_product_count) == (2, 1)
    leaf = rows["Electronics > Television & Video > Accessories > Cables > HDMI Cables"]
    assert (leaf.product_count, leaf.direct_product_count, leaf.depth) == (1, 1, 5)
    assert leaf.path == ("Electronics", "Television & Video", "Accessories", "Cables", "HDMI Cables")
    assert (rows["Home Audio"].product_count, rows["Home Audio"].direct_product_count) == (1, 1)


def test_taxon_id_collision_raises() -> None:
    """AC-012g: levels ["A > B"] and ["A", "B"] raise TaxonIdCollisionError."""
    builder = TaxonomyBuilder()
    builder.add_product("P1", ["A > B"], None)
    with pytest.raises(TaxonIdCollisionError):
        builder.add_product("P2", ["A", "B"], None)


def test_normalize_levels() -> None:
    """AC-012 (support): levels are stripped, blank levels dropped, case and order kept, non-list -> ()."""
    assert normalize_levels(["Electronics", " ", " Computers & Accessories ", "", 5, "cables"]) == (
        "Electronics", "Computers & Accessories", "cables")
    assert normalize_levels("Electronics") == () and normalize_levels(None) == ()
