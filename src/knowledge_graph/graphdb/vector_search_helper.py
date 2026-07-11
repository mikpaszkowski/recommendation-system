"""
Centralized Neo4j vector search query builder.

Encapsulates the vector search Cypher generation in one place.
Currently uses CALL db.index.vector.queryNodes() (deprecated but functional).
When Neo4j 2025.x+ is confirmed, migrate to VECTOR SEARCH syntax here.
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
    
    Args:
        index_name: Name of the vector index to query
        k: Number of nearest neighbors to find
        yield_alias: Alias for the matched node
        score_alias: Alias for the similarity score
        where_clause: Optional WHERE clause for post-filtering
        return_clause: Optional RETURN clause
        order_by: Optional ORDER BY clause
        limit: Optional LIMIT value
        
    Returns:
        Cypher query string
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
