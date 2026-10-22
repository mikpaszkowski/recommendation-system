"""
v1 embedding text templates and skip-empty rules (Technical Specification Graph Rebuild §4.1.4, G-4, G-5).

Pure functions that reproduce the v1 texts of `backfill_embeddings.py` and
`backfill_category_embeddings.py` exactly, so v1 -> v2 embeddings stay comparable. They are shared
by `scripts/graph_ingestion/post_import_v2.py`, `BackfillService` and
`backfill_category_embeddings.py`. The only change against v1 is skip-empty: a builder returns
None for content-free input, and None is never sent to the model.
"""
from __future__ import annotations

from typing import Dict, Literal, Optional, Sequence, Set

from src.knowledge_graph.graphdb.attribute_normalizer import AttributeNormalizer

TEMPLATE_IDS: Dict[str, str] = {
    "ParentProduct": "product_v1", "Review": "review_v1", "Brand": "brand_v1",
    "Attribute": "attribute_v1", "Category": "category_v1",
}
REVIEW_MAX_CHARS = 800
PRODUCT_MAX_ATTRIBUTES = 5
CATEGORY_TITLE_MAX_WORDS = 10
BRAND_DOMAIN = "consumer electronics"
GENERIC_KEYS: Set[str] = {"feature", "bullet_point", "product_feature", "about_this_item"}
ProductContentRule = Literal["title_description_features", "title_description"]
DEFAULT_PRODUCT_CONTENT_RULE: ProductContentRule = "title_description_features"


def _non_blank(value: Optional[str]) -> bool:
    """True for a string that is non-blank after stripping."""
    return isinstance(value, str) and bool(value.strip())


def has_product_content(
    title: Optional[str],
    description: Optional[str],
    features: Optional[Sequence[str]],
    rule: ProductContentRule = DEFAULT_PRODUCT_CONTENT_RULE,
) -> bool:
    """True if title, description or (under the default rule) any feature is non-blank after stripping.
    `rule="title_description"` is the OQ-1 alternative recorded in build_params.json."""
    if _non_blank(title) or _non_blank(description):
        return True
    if rule == "title_description":
        return False
    if rule != "title_description_features":
        raise ValueError(f"unknown product content rule: {rule!r}")
    return any(_non_blank(item) for item in (features or []))


def product_text_v1(
    title: Optional[str],
    category: Optional[str],
    attribute_pairs: Sequence[str],
    description: Optional[str],
    features: Optional[Sequence[str]],
    rule: ProductContentRule = DEFAULT_PRODUCT_CONTENT_RULE,
) -> Optional[str]:
    """None if not has_product_content(...); else
    f"Product: {title or ''}. Category: {category or 'Unknown'}. Features: {', '.join(attribute_pairs[:5])}. Description: {description or ''}".
    `features` decides emptiness only; it is not part of the v1 text (K-6 deferred)."""
    if not has_product_content(title, description, features, rule):
        return None
    pairs = ", ".join(list(attribute_pairs)[:PRODUCT_MAX_ATTRIBUTES])
    return f"Product: {title or ''}. Category: {category or 'Unknown'}. Features: {pairs}. Description: {description or ''}"


def attribute_pair_v1(name: Optional[str], value: Optional[str]) -> str:
    """v1 product-fetch pair `name + ': ' + coalesce(value, '')` used in the product text."""
    return f"{name or ''}: {value or ''}"


def review_text_v1(title: Optional[str], body: Optional[str]) -> Optional[str]:
    """None if both blank; else f"{title or ''}. {body or ''}"[:REVIEW_MAX_CHARS]."""
    if not _non_blank(title) and not _non_blank(body):
        return None
    return f"{title or ''}. {body or ''}"[:REVIEW_MAX_CHARS]


def brand_text_v1(name: str) -> str:
    """f"Brand: {name}. Domain: consumer electronics"."""
    return f"Brand: {name}. Domain: {BRAND_DOMAIN}"


def attribute_text_v1(name: str, value: str) -> str:
    """v1 rule: normalised value alone for GENERIC_KEYS names, else f"{name}: {AttributeNormalizer.normalize(value, name)}"."""
    name = name or ""
    normalized = AttributeNormalizer.normalize(value or "", name)
    if name.lower().strip() in GENERIC_KEYS:
        return normalized
    return f"{name}: {normalized}"


def category_text_v1(name: str, path: Optional[Sequence[str]], sample_titles: Sequence[Optional[str]]) -> str:
    """v1 backfill_category_embeddings text: "Category: {name}. Context: ... . Related items: ...."
    (titles cut to 10 words; "Context: Root Category" when path has <= 1 element; "Related items: None"
    when the sample list is empty)."""
    path_list = list(path or [])
    context = f"Context: {', '.join(path_list[:-1])}" if len(path_list) > 1 else "Context: Root Category"
    titles = list(sample_titles or [])
    if titles:
        cleaned = [" ".join(title.split()[:CATEGORY_TITLE_MAX_WORDS]) for title in titles if title]
        related = f"Related items: {', '.join(cleaned)}"
    else:
        related = "Related items: None"
    return f"Category: {name or ''}. {context}. {related}."


def category_parent_text_legacy(name: Optional[str], parent_name: Optional[str]) -> str:
    """The other v1 category form, from BackfillService.backfill_categories: f"Category: {name}. Parent: {parent or 'Root'}".
    Not a v2 template; used by BackfillService and pre-flight P-09 only."""
    return f"Category: {name}. Parent: {parent_name or 'Root'}"
