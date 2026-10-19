"""
Taxon tree builder (FR-010, K-7, G-3, §5.1.2).

Built from the raw `categories` lists. `taxon_id` is the normalised levels joined with " > " (case
kept). Every prefix of a product's path becomes a Taxon; the product gets one IN_TAXON edge to its
deepest level (which may be an inner node). BROADER points child -> parent; multiple roots are
allowed. Two different level tuples that produce the same `taxon_id` abort the build.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

TAXON_SEPARATOR = " > "


class TaxonIdCollisionError(ValueError):
    """Two different level tuples map to the same taxon_id (e.g. ["A > B"] and ["A", "B"]); the transform exits 2."""


class TaxonRow(NamedTuple):
    """One `nodes_taxon.csv` row."""

    taxon_id: str
    name: str
    path: Tuple[str, ...]
    depth: int                 # len(path); roots have depth 1
    product_count: int         # products assigned to this node or any descendant
    direct_product_count: int  # products whose IN_TAXON points here


def normalize_levels(value: Any) -> Tuple[str, ...]:
    """Strips each level, drops blank levels, keeps case and order; non-list -> (). Non-string items are dropped."""
    if not isinstance(value, list):
        return ()
    return tuple(level.strip() for level in value if isinstance(level, str) and level.strip())


def taxon_id_for(levels: Sequence[str]) -> str:
    """`TAXON_SEPARATOR.join(levels)`."""
    return TAXON_SEPARATOR.join(levels)


class TaxonomyBuilder:
    """Accumulates product paths and produces deterministic Taxon rows, BROADER edges and IN_TAXON assignments."""

    def __init__(self) -> None:
        """Creates an empty tree."""
        self._paths: Dict[str, Tuple[str, ...]] = {}
        self._has_children: Set[str] = set()
        self._assignments: Dict[str, str] = {}
        self._without_taxon: "Counter[str]" = Counter()

    def add_product(self, parent_asin: str, levels: Sequence[str], main_category: Optional[str]) -> Optional[str]:
        """Registers every prefix of `levels`; returns the deepest taxon_id, or None for an empty path
        (counted per main_category, "" for none). Raises TaxonIdCollisionError if a taxon_id maps to two paths."""
        path = tuple(levels)
        if not path:
            self._without_taxon[main_category or ""] += 1
            return None
        parent_id: Optional[str] = None
        taxon_id = ""
        for depth in range(1, len(path) + 1):
            prefix = path[:depth]
            taxon_id = taxon_id_for(prefix)
            known = self._paths.get(taxon_id)
            if known is None:
                self._paths[taxon_id] = prefix
            elif known != prefix:
                raise TaxonIdCollisionError(
                    f"taxon_id {taxon_id!r} maps to two level paths: {list(known)} and {list(prefix)}"
                )
            if parent_id is not None:
                self._has_children.add(parent_id)
            parent_id = taxon_id
        self._assignments[parent_asin] = taxon_id
        return taxon_id

    def nodes(self) -> List[TaxonRow]:
        """All Taxon rows sorted by taxon_id, with subtree and direct product counts."""
        direct: "Counter[str]" = Counter(self._assignments.values())
        subtree: "Counter[str]" = Counter()
        for taxon_id, count in direct.items():
            path = self._paths[taxon_id]
            for depth in range(1, len(path) + 1):
                subtree[taxon_id_for(path[:depth])] += count
        return [
            TaxonRow(
                taxon_id=taxon_id, name=path[-1], path=path, depth=len(path),
                product_count=subtree[taxon_id], direct_product_count=direct[taxon_id],
            )
            for taxon_id, path in sorted(self._paths.items())
        ]

    def broader_edges(self) -> List[Tuple[str, str]]:
        """(child taxon_id, parent taxon_id) for every non-root, sorted."""
        return sorted(
            (taxon_id, taxon_id_for(path[:-1])) for taxon_id, path in self._paths.items() if len(path) > 1
        )

    def assignments(self) -> List[Tuple[str, str]]:
        """(parent_asin, taxon_id) IN_TAXON pairs, sorted."""
        return sorted(self._assignments.items())

    def products_without_taxon(self) -> Dict[str, int]:
        """Products with an empty path, by main_category ("" for none)."""
        return dict(sorted(self._without_taxon.items()))

    def roots(self) -> List[str]:
        """taxon_ids of depth 1, sorted."""
        return sorted(taxon_id for taxon_id, path in self._paths.items() if len(path) == 1)

    def max_depth(self) -> int:
        """Greatest depth in the tree (0 when empty)."""
        return max((len(path) for path in self._paths.values()), default=0)

    def inner_node_assignments(self) -> int:
        """Number of products whose IN_TAXON points to a Taxon that has at least one child."""
        return sum(1 for taxon_id in self._assignments.values() if taxon_id in self._has_children)
