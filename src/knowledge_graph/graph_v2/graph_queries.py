"""
Read-only Cypher collectors shared by the graph v2 CLIs (preflight P-07/P-08, export_v1_snapshot,
validate_graph H-18/R-08, post_import guard and stamp, import restore-test comparison).

Every function takes an open session (or anything with `.run(cypher, **params)`), runs only
parameterised read queries, and never writes. Labels and relationship types are taken from
`db.labels()` / `db.relationshipTypes()` or from module constants, never from user input (NFR-008).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

PRODUCTS_UNTITLED_QUERY = (
    "MATCH (p:ParentProduct) WHERE p.title IS NULL OR trim(p.title) = '' RETURN count(p) AS n"
)
REVIEWS_EMBEDDED_QUERY = "MATCH (r:Review) WHERE r.embedding IS NOT NULL RETURN count(r) AS n"
REVIEW_EMBEDDED_PRODUCTS_QUERY = (
    "MATCH (r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct) WHERE r.embedding IS NOT NULL "
    "RETURN count(DISTINCT p) AS n"
)
NEO4J_COMPONENTS_QUERY = (
    "CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition"
)
GRAPH_VERSION_QUERY = "MATCH (g:GraphVersion) RETURN properties(g) AS props"


def scalar(session: Any, cypher: str, **params: Any) -> int:
    """Single `n` from a count query; raises on failure (callers decide whether to degrade)."""
    record = session.run(cypher, **params).single()
    if record is None:
        raise RuntimeError(f"count query returned no row: {cypher.strip()[:80]}")
    return int(record["n"])


def count_nodes_by_label(session: Any) -> Dict[str, int]:
    """label -> node count for every label in `db.labels()` (count store lookups, sorted keys)."""
    labels = sorted(record["label"] for record in session.run("CALL db.labels() YIELD label RETURN label"))
    counts: Dict[str, int] = {}
    for label in labels:
        escaped = label.replace("`", "``")
        counts[label] = scalar(session, f"MATCH (n:`{escaped}`) RETURN count(n) AS n")
    return counts


def count_relationships_by_type(session: Any) -> Dict[str, int]:
    """type -> relationship count for every type in `db.relationshipTypes()`."""
    types = sorted(
        record["relationshipType"]
        for record in session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
    )
    counts: Dict[str, int] = {}
    for rel_type in types:
        escaped = rel_type.replace("`", "``")
        counts[rel_type] = scalar(session, f"MATCH ()-[r:`{escaped}`]->() RETURN count(r) AS n")
    return counts


def neo4j_components(session: Any) -> Dict[str, Optional[str]]:
    """{name, version, edition} from dbms.components()."""
    record = session.run(NEO4J_COMPONENTS_QUERY).single()
    if record is None:
        return {"name": None, "version": None, "edition": None}
    return {"name": record["name"], "version": record["version"], "edition": record["edition"]}


def graph_version_nodes(session: Any) -> List[Dict[str, Any]]:
    """Properties of every (:GraphVersion) node (0, 1 or more)."""
    return [dict(record["props"]) for record in session.run(GRAPH_VERSION_QUERY)]


def collect_graph_snapshot(session: Any) -> Dict[str, Any]:
    """§5.4 snapshot: counts per label and type, products_untitled, reviews_embedded, review_embedded_products, neo4j_version."""
    return {
        "nodes": count_nodes_by_label(session),
        "relationships": count_relationships_by_type(session),
        "products_untitled": scalar(session, PRODUCTS_UNTITLED_QUERY),
        "reviews_embedded": scalar(session, REVIEWS_EMBEDDED_QUERY),
        "review_embedded_products": scalar(session, REVIEW_EMBEDDED_PRODUCTS_QUERY),
        "neo4j_version": neo4j_components(session).get("version"),
    }


BENCHMARK_TARGET_QUERY = """
MATCH (p:ParentProduct {parent_asin: $asin})
RETURN p.title AS title, p.price AS price,
       [(p)-[:HAS_BRAND]->(b:Brand) | b.name] AS brands,
       [(p)-[:BELONGS_TO_CATEGORY]->(c:Category) | c.name] AS categories,
       COUNT { (:Review)-[:ABOUT_PRODUCT]->(p) } AS review_nodes
"""


def benchmark_target_facts(session: Any, query_id: str, target_asin: str) -> Mapping[str, Any]:
    """title, price, brands, categories and review_nodes for one benchmark target (graph_versions/v1/benchmark_targets.json)."""
    record = session.run(BENCHMARK_TARGET_QUERY, asin=target_asin).single()
    if record is None:
        return {"query_id": query_id, "target_asin": target_asin, "title": None, "price": None,
                "brands": [], "categories": [], "review_nodes": 0, "present": False}
    return {
        "query_id": query_id, "target_asin": target_asin, "title": record["title"], "price": record["price"],
        "brands": sorted(record["brands"] or []), "categories": sorted(record["categories"] or []),
        "review_nodes": int(record["review_nodes"] or 0), "present": True,
    }
