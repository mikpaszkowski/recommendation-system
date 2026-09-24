"""
Centralized Neo4j vector search query builder.

Encapsulates the vector search Cypher generation in one place.
Uses the modern Cypher 25 VECTOR SEARCH syntax.
"""

def build_vector_search_query(
    index_name: str,
    k: int,
    *,
    yield_alias: str = "node",
    score_alias: str = "score",
    where_clause: str = "",
    return_clause: str = "",
    order_by: str = "",
    limit: int | None = None,
) -> str:
    """
    Build a Cypher query for vector search.
    Compatible with Neo4j 5.x (CALL db.index.vector.queryNodes).
    """
    parts = [
        f"CALL db.index.vector.queryNodes('{index_name}', {k}, $vector)",
        f"YIELD node AS {yield_alias}, score AS {score_alias}",
    ]
    if where_clause:
        parts.append(f"WHERE {where_clause}")
    if return_clause:
        parts.append(return_clause)
    if order_by:
        parts.append(f"ORDER BY {order_by}")
    if limit is not None:
        parts.append(f"LIMIT {limit}")
    return "\n".join(parts)
