import logging
import re
from typing import Dict, Any, List, Optional, Sequence, Set

from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
from src.knowledge_graph.graphdb.resolver_service import ResolverService
from src.knowledge_graph.graphdb.vector_search_helper import build_vector_search_query
from src.tools.score_fusion import (
    CHANNELS,
    LEGACY_SOFT_BONUS_UNIT,
    ChannelHit,
    FusedCandidate,
    FusionConfig,
    fuse,
)

logger = logging.getLogger(__name__)

BRAND_CONFIDENCE = 0.85
CATEGORY_CONFIDENCE = 0.70
CATEGORY_MARGIN = 0.05

CHANNEL_INDEXES = {
    "product": "product_embedding_index",
    "attribute": "attribute_embedding_index",
    "review": "review_embedding_index",
}

DETAIL_QUERY = """
MATCH (node:ParentProduct) WHERE node.parent_asin IN $asins
OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
RETURN node.parent_asin AS asin, node.title AS title, node.price AS price, b.name AS brand,
       collect(DISTINCT c.name) AS category, elementId(node) AS id,
       node.features AS features, node.details_text AS details_text,
       node.description AS description, node.avg_rating AS avg_rating
"""

# Constraint-satisfaction@K facts (R2a, FR-025): one batched, parameterised read per query.
# Attribute.numeric_value is never set by the current full ingest (batch_ingest.py reads
# processed_metadata.csv, which keeps only brand/material/color/style/size details), so the
# numeric list is empty on the live graph and Neo4j logs an unknown-property notice.
CONSTRAINT_FACTS_QUERY = """
UNWIND $asins AS asin
MATCH (p:ParentProduct {parent_asin: asin})
RETURN p.parent_asin AS asin,
       p.price AS price,
       p.title AS title,
       [(p)-[:HAS_BRAND]->(b:Brand) | b.name] AS brands,
       [(p)-[:HAS_ATTRIBUTE]->(a:Attribute)
          WHERE a.numeric_value IS NOT NULL AND toLower(a.attribute_name) IN $attribute_names
        | {name: toLower(a.attribute_name), value: a.numeric_value}] AS numeric_attributes
"""

class GraphSearchTool:
    """
    Tool for searching the Knowledge Graph using Hybrid Semantic Search.
    Combines Vector Search (for semantic understanding) with Cypher Filtering (for hard constraints).
    """
    BRAND_CONFIDENCE = BRAND_CONFIDENCE
    CATEGORY_CONFIDENCE = CATEGORY_CONFIDENCE
    CATEGORY_MARGIN = CATEGORY_MARGIN
    def __init__(self, db_connector: Optional[Neo4jConnector] = None, embedding_service: Optional[EmbeddingService] = None, resolver: Optional[ResolverService] = None, fusion_config: Optional[FusionConfig] = None):
        try:
            self.db = db_connector or Neo4jConnector()
            # Ensure connection is open if not passed in
            if not db_connector:
                 self.db.connect()
        except Exception as e:
            logger.error(f"Failed to initialize Neo4jConnector: {e}")
            self.db = None

        # Cross-channel fusion arm (R1): rrf3 by default, overridable per call for ablation replay.
        # Read after Neo4jConnector, which loads .env, so RETRIEVAL_FUSION_ARM set there is honoured.
        self.fusion_config = fusion_config or FusionConfig.from_env()

        try:
            self.embedder = embedding_service or EmbeddingService()
        except Exception as e:
            logger.error(f"Failed to initialize EmbeddingService: {e}")
            self.embedder = None

        try:
            self.resolver = resolver or ResolverService(connector=self.db, embed_svc=self.embedder)
        except Exception as e:
            logger.warning(f"Failed to initialize ResolverService: {e}. Filter normalization disabled.")
            self.resolver = None

    @staticmethod
    def _clean_params_for_metadata(params: Dict[str, Any]) -> Dict[str, Any]:
        """Summarizes high-dimensional embedding vectors for telemetry metadata."""
        cleaned = {}
        for k, v in params.items():
            is_vector_like = isinstance(v, (list, tuple)) or (
                hasattr(v, "__len__") and (hasattr(v, "shape") or hasattr(v, "tolist"))
            )
            if is_vector_like:
                try:
                    dim = len(v)
                    if dim > 50:
                        cleaned[k] = f"<vector dim={dim}>"
                        continue
                except Exception:
                    pass
            cleaned[k] = v
        return cleaned

    @staticmethod
    def _group_soft_preferences(soft_preferences: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Groups soft preferences so that unit variations of the same underlying requirement
        (e.g., '128', '128GB', '128 GB' for storage) belong to a single group and award
        at most one bonus unit per requirement, while distinct values (e.g., '128' vs '256')
        remain in separate groups.
        """
        from src.dialog_manager.session_adapter import generate_attribute_unit_variations

        groups: List[Dict[str, Any]] = []
        for sp in soft_preferences:
            raw_val = sp.get("value")
            if raw_val is None or raw_val == "":
                continue
            val = str(raw_val).lower().strip()
            if not val or val == "none":
                continue
            cat = str(sp.get("category", "") or "").lower().strip()
            polarity = float(sp.get("polarity", 0.5))
            pol_sign = -1 if polarity < 0 else 1
            req_id = sp.get("requirement_id")

            variations = {val}
            for v in generate_attribute_unit_variations(cat, val):
                variations.add(v.lower().strip())

            matched_group = None
            for g in groups:
                if g["pol_sign"] != pol_sign:
                    continue
                if req_id is not None and g["req_id"] is not None:
                    if req_id == g["req_id"]:
                        matched_group = g
                        break
                    else:
                        continue
                if g["cat"] == cat and (val in g["variations"] or bool(variations & g["all_unit_forms"])):
                    matched_group = g
                    break

            if matched_group is not None:
                matched_group["entries"].append(sp)
                matched_group["variations"].add(val)
                matched_group["all_unit_forms"].update(variations)
            else:
                groups.append({
                    "req_id": req_id,
                    "cat": cat,
                    "pol_sign": pol_sign,
                    "variations": {val},
                    "all_unit_forms": set(variations),
                    "entries": [sp],
                })

        return [g["entries"] for g in groups]

    def search(self, 
               semantic_query: Optional[str] = "", 
               structured_filters: Optional[Dict[str, Any]] = None, 
               limit: int = 5,
               # Legacy/Fallback arguments to avoid breaking existing calls if any
               query: Optional[str] = None,
               preferences: Optional[Dict[str, Any]] = None,
               soft_preferences: Optional[List[Dict[str, Any]]] = None,
               fusion_config: Optional[FusionConfig] = None) -> Dict[str, Any]:
        """
        Executes a search using one of three strategies:
        1. Hybrid (Semantic + Filters) - PREFERRED
        2. Vector Only (Semantic)
        3. Filter Only (Cypher)
        
        Args:
            semantic_query: User's intent for vector search (e.g. "powerful gaming laptop").
            structured_filters: Hard constraints (e.g. {"price_max": 2000, "brand": "Asus"}).
            limit: Number of results to return.
            query: Alias for semantic_query (legacy support).
            preferences: Alias for structured_filters (legacy support).
            soft_preferences: List of flexible desires for additive scoring.
            fusion_config: Fusion arm for this call; defaults to the tool's configured arm.
        """
        # Handle aliases/legacy args
        text = semantic_query or query
        raw_filters = structured_filters or preferences or {}
        filters = dict(raw_filters)
        soft_preferences = soft_preferences or []
        config = fusion_config or self.fusion_config
        
        logger.info(f"[GST] Input: text='{text}', raw_filters={raw_filters}, fusion='{config.name}'")
        
        # Normalize filters before searching
        if self._filters_present(filters):
            logger.info(f"[GST] Normalizing filters...")
            filters = self._normalize_filters(filters)
            logger.info(f"[GST] Normalized filters: {filters}")
        # Applied-filter telemetry (R2a, FR-016): the filters after normalisation, before MACS relaxation
        normalized_filters = dict(filters)
        
        if not self.db or not self.embedder:
             return {"status": "error", "message": "Database or Embedder not initialized.", "items": [], "metadata": {"cypher": "", "params": {}}}

        try:
            result = {"status": "error", "items": []}
            # STRATEGY 1: HYBRID (Most common and desired)
            if text and self._filters_present(filters):
                logger.info(f"[GST] Strategy: HYBRID (text + filters)")
                result = self._execute_hybrid_search(text, filters, raw_filters, limit, config)
                
                # MACS Progressive Relaxation
                relaxed_constraints = []
                if result.get("count", 0) < 3:
                    logger.warning(f"[GST] MACS Triggered: Candidate yield {result.get('count', 0)} < 3. Initiating relaxation cascade.")
                    
                    # Pass 1: Widen Budget
                    relaxed = False
                    if "price_max" in filters:
                        filters["price_max"] = filters["price_max"] * 1.15
                        relaxed_constraints.append("Widened budget ceiling by 15%")
                        relaxed = True
                    if "price_min" in filters:
                        filters["price_min"] = filters["price_min"] * 0.85
                        relaxed_constraints.append("Lowered budget floor by 15%")
                        relaxed = True
                        
                    if relaxed:
                        result = self._execute_hybrid_search(text, filters, raw_filters, limit, config)
                    
                    # Pass 2: Drop Category constraint if still failing
                    if result.get("count", 0) < 3 and ("category" in filters or "categories" in filters):
                        logger.warning(f"[GST] MACS Triggered: Yield still < 3. Dropping category constraint.")
                        filters.pop("category", None)
                        filters.pop("categories", None)
                        relaxed_constraints.append("Dropped explicit category constraint (relying purely on vector search)")
                        result = self._execute_hybrid_search(text, filters, raw_filters, limit, config)
                
                if relaxed_constraints:
                    result["relaxed_constraints"] = relaxed_constraints
                    
            # STRATEGY 2: VECTOR ONLY (No specific filters)
            elif text and not self._filters_present(filters):
                logger.info(f"[GST] Strategy: VECTOR_ONLY (text only, no meaningful filters)")
                result = self._execute_vector_search(text, limit, config)

            # STRATEGY 3: FILTER ONLY (Parametric query)
            elif self._filters_present(filters) and not text:
                logger.info(f"[GST] Strategy: FILTER_ONLY (filters only)")
                result = self._execute_cypher_search(filters, raw_filters, limit)
            else:
                return {"status": "error", "message": "No search criteria provided.", "items": [], "metadata": {"cypher": "", "params": {}}}
                
            # ADDITIVE SCORING (Pillar 1/2)
            if soft_preferences and result.get("items"):
                # Bonus per matched preference is scaled to the fused-score range so it can reorder
                # close candidates but not override fusion; legacy sum and filter-only scores keep 0.2
                if config.method == "sum" or result.get("strategy") == "filter_only":
                    bonus_unit = LEGACY_SOFT_BONUS_UNIT
                else:
                    bonus_unit = config.soft_bonus_unit()
                sp_groups = self._group_soft_preferences(soft_preferences)
                logger.info(
                    f"[GST] Applying Additive Scoring for {len(soft_preferences)} soft preferences "
                    f"({len(sp_groups)} distinct requirement groups, unit={bonus_unit:.4f})."
                )
                for item in result["items"]:
                    title_lower = (item.get("title") or "").lower()
                    brand_lower = (item.get("brand") or "").lower()
                    reasons_str = " ".join(item.get("match_reasons") or []).lower()
                    
                    base_score = item.get("score", 0.0)
                    bonus = 0.0
                    for group in sp_groups:
                        matched_deltas: List[float] = []
                        for sp in group:
                            raw_val = sp.get("value")
                            if raw_val is None or raw_val == "":
                                continue
                            val = str(raw_val).lower().strip()
                            if not val or val == "none":
                                continue
                            cat = str(sp.get("category", "") or "").lower().strip()
                            polarity = float(sp.get("polarity", 0.5))
                            
                            # Add heuristic bonus if value appears in title, brand or match reasons
                            if val.isdigit():
                                # Require digit boundaries so numbers (e.g. 128, 256, 1) do not match
                                # as substrings of larger numbers (1280, 2560x1440, 2021)
                                if re.search(r"(?<!\d)" + re.escape(val) + r"(?!\d)", title_lower):
                                    matched_deltas.append(polarity * bonus_unit)
                            elif (val in title_lower or (val in brand_lower and cat == 'brand') or val in reasons_str):
                                matched_deltas.append(polarity * bonus_unit)
                        if matched_deltas:
                            # Apply at most one bonus per requirement group (max magnitude among unit variations)
                            bonus += max(matched_deltas, key=lambda d: abs(d))
                            
                    item["score"] = base_score + bonus
                    item["soft_bonus"] = bonus
                
                # Re-sort after additive scoring
                result["items"] = sorted(result["items"], key=lambda x: x.get("score", 0), reverse=True)

            if not isinstance(result.get("metadata"), dict):
                result["metadata"] = {}
            result["metadata"]["normalized_filters"] = normalized_filters
            return result

        except Exception as e:
            logger.error(f"[GST] Execution error: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "items": [], "metadata": {"cypher": "", "params": {}}}

    def _execute_hybrid_search(self, text: str, filters: Dict[str, Any], raw_filters: Dict[str, Any], limit: int, config: Optional[FusionConfig] = None) -> Dict[str, Any]:
        """Vector retrieval over all enabled channels with hard filters applied before ranking."""
        config = config or self.fusion_config
        query_vector = self.embedder.embed_query(text)
        logger.info(f"[GST:Hybrid] Embedded query (dim={len(query_vector)})")

        where_clauses, params = self._build_filters(filters, raw_filters)
        where_str = " AND ".join(where_clauses) if where_clauses else "1=1"
        logger.info(f"[GST:Hybrid] WHERE clauses: {where_str}")

        if config.method == "sum":
            return self._execute_legacy_sum_search(query_vector, where_str, params, limit, config, strategy="hybrid_multi_index")
        return self._execute_fused_search(query_vector, where_str, params, limit, config, strategy="hybrid_multi_index")

    def _execute_vector_search(self, text: str, limit: int, config: Optional[FusionConfig] = None) -> Dict[str, Any]:
        """Vector retrieval over all enabled channels without filters."""
        config = config or self.fusion_config
        query_vector = self.embedder.embed_query(text)
        logger.info(f"[GST:Vector] Embedded query (dim={len(query_vector)}), searching top {limit}")

        if config.method == "sum":
            return self._execute_legacy_sum_search(query_vector, None, {}, limit, config, strategy="vector_only")
        return self._execute_fused_search(query_vector, None, {}, limit, config, strategy="vector_only")

    @staticmethod
    def _build_channel_query(channel: str, where_str: Optional[str]) -> str:
        """
        Builds one channel's MaxP query: each ParentProduct once, with its best similarity
        in the channel and the reason text of that best match, filtered before ranking.
        """
        where_line = f"WHERE {where_str}" if where_str else ""
        if channel == "product":
            query = build_vector_search_query(
                CHANNEL_INDEXES["product"],
                "$k",
                yield_alias="node",
                score_alias="score",
                return_clause=f"""WITH node, score, 'Product Title Match' AS reason
{where_line}
RETURN node.parent_asin AS asin, score AS similarity, reason
ORDER BY similarity DESC, asin ASC
LIMIT $depth""",
            )
            return "\n".join(line for line in query.splitlines() if line.strip())
        if channel == "attribute":
            match_clause = "MATCH (node:ParentProduct)-[:HAS_ATTRIBUTE]->(hit)"
            reason_expr = "'Attribute Match: ' + coalesce(hit.attribute_name, '') + '=' + coalesce(hit.attribute_value, hit.normalized_value, '')"
        elif channel == "review":
            match_clause = "MATCH (hit)-[:ABOUT_PRODUCT]->(node:ParentProduct)"
            reason_expr = "'Review Match: ' + coalesce(hit.review_title, '')"
        else:
            raise ValueError(f"Unknown retrieval channel '{channel}'. Valid channels: {list(CHANNELS)}")

        query = build_vector_search_query(
            CHANNEL_INDEXES[channel],
            "$k",
            yield_alias="hit",
            score_alias="score",
            return_clause=f"""{match_clause}
{where_line}
WITH node, score, {reason_expr} AS reason
ORDER BY score DESC, reason ASC
WITH node, max(score) AS similarity, head(collect(reason)) AS reason
RETURN node.parent_asin AS asin, similarity, reason
ORDER BY similarity DESC, asin ASC
LIMIT $depth""",
        )
        return "\n".join(line for line in query.splitlines() if line.strip())

    def _execute_fused_search(self, query_vector: List[float], where_str: Optional[str], filter_params: Dict[str, Any],
                              limit: int, config: FusionConfig, strategy: str) -> Dict[str, Any]:
        """
        Runs one MaxP query per enabled channel, fuses the ranked lists (RRF or CC) and
        fetches display details for the fused top `limit`. Every item carries its
        per-channel rank, similarity and reason under `fusion`.
        """
        tag = "Hybrid" if where_str else "Vector"
        params: Dict[str, Any] = dict(filter_params)
        params["vector"] = query_vector
        params["k"] = limit * config.ann_k_per_limit
        params["depth"] = config.channel_depth

        channel_queries = {channel: self._build_channel_query(channel, where_str) for channel in config.channels}
        channel_hits: Dict[str, List[ChannelHit]] = {}

        with self.db.session() as session:
            for channel, cypher in channel_queries.items():
                rows = [dict(record) for record in session.run(cypher, params)]
                channel_hits[channel] = [
                    ChannelHit(asin=row["asin"], similarity=float(row["similarity"]), reason=row.get("reason") or "")
                    for row in rows
                    if row.get("asin") and row.get("similarity") is not None
                ]
                logger.info(f"[GST:{tag}] Channel '{channel}': {len(channel_hits[channel])} products")

            fused: List[FusedCandidate] = fuse(channel_hits, config)[:limit]
            details: Dict[str, Dict[str, Any]] = {}
            if fused:
                detail_rows = session.run(DETAIL_QUERY, {"asins": [fc.asin for fc in fused]})
                details = {row["asin"]: row for row in (dict(record) for record in detail_rows)}

        items: List[Dict[str, Any]] = []
        for fc in fused:
            detail = details.get(fc.asin)
            if detail is None:
                logger.warning(f"[GST:{tag}] Fused candidate {fc.asin} missing from detail query; dropped.")
                continue
            ordered_channels = [c for c in config.channels if c in fc.channels]
            items.append({
                "title": detail.get("title"),
                "price": detail.get("price"),
                "brand": detail.get("brand"),
                "category": detail.get("category") or [],
                "features": detail.get("features"),
                "details_text": detail.get("details_text"),
                "description": detail.get("description"),
                "avg_rating": detail.get("avg_rating"),
                "score": fc.score,
                "fused_score": fc.score,
                "soft_bonus": 0.0,
                "id": detail.get("id"),
                "asin": fc.asin,
                "match_reasons": [fc.channels[c].reason for c in ordered_channels],
                "fusion": {
                    "method": config.name,
                    "channels": {
                        c: {"rank": fc.channels[c].rank, "similarity": fc.channels[c].similarity, "reason": fc.channels[c].reason}
                        for c in ordered_channels
                    },
                },
            })

        logger.info(f"[GST:{tag}] Fused ({config.name}) results: {len(items)} items found")
        for i, item in enumerate(items):
            ranks = {c: ev["rank"] for c, ev in item["fusion"]["channels"].items()}
            logger.info(f"  [{i+1}] score={item['score']:.4f} | ranks={ranks} | title={str(item.get('title', ''))[:50]}")

        combined_cypher = "\n\n".join(f"// channel: {c}\n{q}" for c, q in channel_queries.items())
        combined_cypher += f"\n\n// details\n{DETAIL_QUERY.strip()}"
        clean_params = self._clean_params_for_metadata(params)
        return {
            "status": "success",
            "items": items,
            "count": len(items),
            "strategy": strategy,
            "metadata": {
                "cypher": combined_cypher,
                "params": clean_params,
                "channel_queries": channel_queries,
                "channel_counts": {c: len(h) for c, h in channel_hits.items()},
                "fusion": config.to_dict(),
            },
        }

    def _execute_legacy_sum_search(self, query_vector: List[float], where_str: Optional[str], filter_params: Dict[str, Any],
                                   limit: int, config: FusionConfig, strategy: str) -> Dict[str, Any]:
        """
        Pre-R1 ranking kept as the `sum_legacy` ablation arm: UNION of the three indexes and
        sum(score) over every matching node (weights 1.0 / 0.8 / 0.9), filtered after aggregation.
        """
        tag = "Hybrid" if where_str else "Vector"
        params: Dict[str, Any] = dict(filter_params)
        params["vector"] = query_vector
        params["k"] = limit * config.ann_k_per_limit

        # GAP-003 Compliance: Use central helper to generate the vector search fragments
        prod_vector = build_vector_search_query(
            "product_embedding_index", 
            "$k", 
            yield_alias="node", 
            score_alias="score", 
            return_clause="RETURN node AS p, score, 'Product Title Match' AS match_reason"
        )
        
        attr_vector = build_vector_search_query(
            "attribute_embedding_index", 
            "$k", 
            yield_alias="node", 
            score_alias="score", 
            return_clause="MATCH (p:ParentProduct)-[:HAS_ATTRIBUTE]->(node)\nRETURN p, score * 0.8 AS score, 'Attribute Match: ' + node.attribute_name + '=' + coalesce(node.attribute_value, node.normalized_value, '') AS match_reason"
        )
        
        rev_vector = build_vector_search_query(
            "review_embedding_index", 
            "$k", 
            yield_alias="node", 
            score_alias="score", 
            return_clause="MATCH (node)-[:ABOUT_PRODUCT]->(p:ParentProduct)\nRETURN p, score * 0.9 AS score, 'Review Match: ' + coalesce(node.review_title, '') AS match_reason"
        )

        where_line = f"WHERE {where_str}" if where_str else ""
        cypher = f"""
        CALL {{
            WITH $vector AS vector
            {prod_vector.replace('$vector', 'vector')}
            
            UNION
            
            WITH $vector AS vector
            {attr_vector.replace('$vector', 'vector')}
            
            UNION
            
            WITH $vector AS vector
            {rev_vector.replace('$vector', 'vector')}
        }}
        WITH p AS node, sum(score) AS total_score, collect(match_reason) AS match_reasons
        {where_line}
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, total_score as score, elementId(node) as id, node.parent_asin as asin,
               match_reasons, node.features as features, node.details_text as details_text,
               node.description as description, node.avg_rating as avg_rating
        ORDER BY score DESC
        LIMIT $limit
        """
        params["limit"] = limit
        
        logger.info(f"[GST:{tag}] Legacy sum(score) Cypher:\n" + cypher)

        with self.db.session() as session:
            result = session.run(cypher, params)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:{tag}] Results: {len(items)} items found")
        clean_params = self._clean_params_for_metadata(params)
        return {
            "status": "success",
            "items": items,
            "count": len(items),
            "strategy": strategy,
            "metadata": {"cypher": cypher, "params": clean_params, "fusion": config.to_dict()},
        }

    def _execute_cypher_search(self, filters: Dict[str, Any], raw_filters: Dict[str, Any], limit: int) -> Dict[str, Any]:
        where_clauses, params = self._build_filters(filters, raw_filters)
        where_str = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        cypher = f"""
        MATCH (node:ParentProduct)
        WHERE {where_str}
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        WITH node, b, c,
             coalesce(node.rating, node.avg_rating, 0.0) AS raw_rating,
             coalesce(node.rating_count, node.review_count, 0) AS raw_count,
             coalesce(node.price, 999999.0) AS sort_price
        WITH node, b, c, sort_price,
             ((10.0 * 4.0 + (toFloat(raw_count) * raw_rating)) / (10.0 + toFloat(raw_count))) AS bayes_rating,
             log(1.0 + CASE WHEN toFloat(raw_count) > 500.0 THEN 500.0 ELSE toFloat(raw_count) END) AS volume_factor
        WITH node, b, c, sort_price,
             (bayes_rating * volume_factor) AS relevance_score
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, relevance_score as score, elementId(node) as id, node.parent_asin as asin,
               node.features as features, node.details_text as details_text,
               node.description as description, node.avg_rating as avg_rating
        ORDER BY score DESC, coalesce(price, 999999.0) ASC
        LIMIT {limit}
        """
        
        logger.info(f"[GST:Filter] Cypher:\n{cypher}\nParams: {params}")

        with self.db.session() as session:
            result = session.run(cypher, params)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:Filter] Results: {len(items)} items found")
        for i, item in enumerate(items):
            logger.info(f"  [{i+1}] price={item.get('price')} | brand={item.get('brand')} | cat={item.get('category')} | title={str(item.get('title', ''))[:70]}")
            
        clean_params = self._clean_params_for_metadata(params)
        return {
            "status": "success",
            "items": items,
            "count": len(items),
            "strategy": "filter_only",
            "metadata": {"cypher": cypher, "params": clean_params},
        }

    def fetch_product_attributes(self, asins: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetches unstructured attributes (e.g. pros/cons, opinions, reviews) for given products.
        Returns a dictionary mapping ASIN to a list of attributes and recent reviews.
        """
        if not self.db or not asins:
            return {}

        # Query attributes
        cypher_attr = """
        MATCH (p:ParentProduct)-[r:HAS_ATTRIBUTE]->(a:Attribute)
        WHERE p.parent_asin IN $asins
        RETURN p.parent_asin AS asin, a.attribute_name AS name, a.attribute_value AS value, a.source AS source
        """
        
        # Query reviews per product (up to $reviews_per_product per ASIN, ordered by Graph v2 properties)
        cypher_rev = """
        UNWIND $asins AS asin
        CALL {
            WITH asin
            MATCH (r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct {parent_asin: asin})
            RETURN p.parent_asin AS prod_asin,
                   r.review_title AS name,
                   r.review_body AS value,
                   'user_review' AS source
            ORDER BY coalesce(r.helpful_vote, r.helpful_votes, 0) DESC,
                     coalesce(r.verified, false) DESC,
                     coalesce(r.timestamp, 0) DESC
            LIMIT $reviews_per_product
        }
        RETURN prod_asin AS asin, name, value, source
        """
        
        logger.info(f"[GST:Attributes] Fetching attributes and reviews for {len(asins)} products...")
        
        result_map = {asin: [] for asin in asins}
        
        try:
            with self.db.session() as session:
                # 1. Fetch Attributes
                result_attr = session.run(cypher_attr, asins=asins)
                for record in result_attr:
                    asin = record["asin"]
                    if asin in result_map:
                        result_map[asin].append({
                            "name": record["name"],
                            "value": str(record["value"])[:200], # truncate to avoid huge context per attr
                            "source": record["source"]
                        })
                        
                # 2. Fetch Reviews (bounded per product at query level and guarded in Python)
                result_rev = session.run(cypher_rev, asins=asins, reviews_per_product=5)
                for record in result_rev:
                    asin = record["asin"]
                    if asin in result_map and sum(1 for a in result_map[asin] if a["source"] == 'user_review') < 5:
                        result_map[asin].append({
                            "name": f"Review: {record['name']}",
                            "value": str(record["value"])[:300], # truncate long reviews
                            "source": record["source"]
                        })
                        
            logger.info(f"[GST:Attributes] Fetched attributes and reviews for {len(result_map)} products.")
            return result_map
        except Exception as e:
            logger.error(f"[GST:Attributes] Error fetching attributes/reviews: {e}", exc_info=True)
            return {}

    def match_category(self, asins: List[str], category: Any, raw_category: Optional[str] = None) -> Set[str]:
        """
        Returns the subset of `asins` that satisfies the `_build_filters` category predicate
        (taxonomy traversal or title match). Used by the type-precision@K evaluation metric.

        `category` is the (normalised) category value; `raw_category` is the value as requested,
        which `_build_filters` uses for the title condition, exactly as `search` applies it
        (target-admitting category rate, FR-015). Without it both use `category` (unchanged).
        """
        if isinstance(category, (list, tuple)):
            category = category[0] if category else None
        if isinstance(raw_category, (list, tuple)):
            raw_category = raw_category[0] if raw_category else None
        if not self.db or not asins or not category:
            return set()

        where_clauses, params = self._build_filters({"category": str(category)}, {"category": str(raw_category or category)})
        params["asins"] = list(asins)
        cypher = (
            "MATCH (node:ParentProduct) WHERE node.parent_asin IN $asins AND "
            + " AND ".join(where_clauses)
            + " RETURN node.parent_asin AS asin"
        )
        try:
            with self.db.session() as session:
                return {dict(record)["asin"] for record in session.run(cypher, params)}
        except Exception as e:
            logger.error(f"[GST:Category] Category match failed for '{category}' over {len(asins)} products: {e}", exc_info=True)
            return set()

    def fetch_constraint_facts(self, asins: List[str], attribute_names: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        Facts for constraint-satisfaction@K verdicts, fetched with one parameterised query.

        Returns:
            {asin: {"price": Optional[float], "title": str, "brands": List[str],
                    "numeric_attributes": List[{"name": str, "value": float}]}};
            ASINs missing from the graph are absent; {} on error (logged) or empty input.
        """
        unique_asins = [a for a in dict.fromkeys(asins or []) if a]
        if not self.db or not unique_asins:
            return {}
        names = list(dict.fromkeys(str(n).strip().lower() for n in (attribute_names or []) if str(n).strip()))
        try:
            with self.db.session() as session:
                rows = [dict(record) for record in session.run(CONSTRAINT_FACTS_QUERY, {"asins": unique_asins, "attribute_names": names})]
        except Exception as e:
            logger.error(f"[GST:Facts] Constraint fact fetch failed for {len(unique_asins)} products: {e}", exc_info=True)
            return {}
        facts: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            asin = row.get("asin")
            if not asin:
                continue
            facts[asin] = {
                "price": row.get("price"),
                "title": row.get("title") or "",
                "brands": [b for b in (row.get("brands") or []) if isinstance(b, str)],
                "numeric_attributes": [
                    {"name": str(a.get("name")), "value": a.get("value")}
                    for a in (row.get("numeric_attributes") or []) if isinstance(a, dict)
                ],
            }
        return facts

    def fetch_review_embedded_asins(self) -> Set[str]:
        """
        Returns the products that have at least one embedded Review, i.e. the products the
        review channel can retrieve. Used by the popularity-bias@K evaluation metric.
        """
        if not self.db:
            return set()
        cypher = """
        MATCH (r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct)
        WHERE r.embedding IS NOT NULL
        RETURN DISTINCT p.parent_asin AS asin
        """
        try:
            with self.db.session() as session:
                return {dict(record)["asin"] for record in session.run(cypher) if dict(record).get("asin")}
        except Exception as e:
            logger.error(f"[GST] Failed to fetch review-embedded products: {e}", exc_info=True)
            return set()

    def _build_filters(self, filters: Dict[str, Any], raw_filters: Dict[str, Any] = None):
        """Build WHERE clauses for filters. Uses EXISTS subqueries for relationship-based filters."""
        logger.debug(f"[GST] Building filters for payload: {filters}")
        where_clauses = []
        params = {}
        raw_filters = raw_filters or {}
        
        for key, value in filters.items():
            if value is None or value == "" or (isinstance(value, (list, tuple)) and not value):
                logger.debug(f"[GST] Skipping empty filter key: {key}")
                continue
            
            if key == "price_max":
                where_clauses.append("(node.price IS NULL OR node.price <= $price_max)")
                params["price_max"] = float(value)
            elif key == "price_min":
                where_clauses.append("(node.price IS NULL OR node.price >= $price_min)")
                params["price_min"] = float(value)
            elif key == "excluded_asins" and isinstance(value, list) and value:
                where_clauses.append("NOT node.parent_asin IN $excluded_asins")
                params["excluded_asins"] = value
            elif key == "brand" and not isinstance(value, (list, tuple)):
                if filters.get("brands"):
                    # Handled together in the 'brands' OR-list predicate below
                    continue
                raw_brand = raw_filters.get("brand", value)
                if isinstance(raw_brand, (list, tuple)):
                    raw_brand = raw_brand[0] if raw_brand else value
                where_clauses.append(
                    "(EXISTS { MATCH (node)-[:HAS_BRAND]->(b:Brand) "
                    "WHERE toLower(b.name) = toLower($brand_filter) "
                    "   OR toLower(b.name) CONTAINS toLower($brand_filter) "
                    "   OR toLower($brand_filter) CONTAINS toLower(b.name) } "
                    "OR toLower(node.title) CONTAINS toLower($raw_brand_filter))"
                )
                params["brand_filter"] = value
                params["raw_brand_filter"] = raw_brand
            elif key == "brands" or (key == "brand" and isinstance(value, (list, tuple))):
                brand_list = [str(b).strip() for b in (value if isinstance(value, (list, tuple)) else [value]) if str(b).strip()]
                if key == "brands" and isinstance(filters.get("brand"), str) and filters["brand"].strip():
                    if filters["brand"].strip() not in brand_list:
                        brand_list.append(filters["brand"].strip())
                raw_source = raw_filters.get(key) or raw_filters.get("brands") or raw_filters.get("brand") or brand_list
                raw_brand_list = [str(b).strip() for b in (raw_source if isinstance(raw_source, (list, tuple)) else [raw_source]) if str(b).strip()]
                if not raw_brand_list:
                    raw_brand_list = list(brand_list)
                where_clauses.append(
                    "(EXISTS { MATCH (node)-[:HAS_BRAND]->(b:Brand) "
                    "WHERE ANY(bf IN $brands_filter WHERE toLower(b.name) = toLower(bf) "
                    "   OR toLower(b.name) CONTAINS toLower(bf) "
                    "   OR toLower(bf) CONTAINS toLower(b.name)) } "
                    "OR ANY(rbf IN $raw_brands_filter WHERE toLower(node.title) CONTAINS toLower(rbf)))"
                )
                params["brands_filter"] = brand_list
                params["raw_brands_filter"] = raw_brand_list
            elif key == "exclude_brand" and not isinstance(value, (list, tuple)):
                if filters.get("exclude_brands"):
                    continue
                raw_ex_brand = raw_filters.get("exclude_brand", value)
                if isinstance(raw_ex_brand, (list, tuple)):
                    raw_ex_brand = raw_ex_brand[0] if raw_ex_brand else value
                where_clauses.append(
                    "NOT (EXISTS { MATCH (node)-[:HAS_BRAND]->(eb:Brand) "
                    "WHERE toLower(eb.name) = toLower($exclude_brand) "
                    "   OR toLower(eb.name) CONTAINS toLower($exclude_brand) "
                    "   OR toLower($exclude_brand) CONTAINS toLower(eb.name) } "
                    "OR toLower(node.title) CONTAINS toLower($raw_ex_brand_filter))"
                )
                params["exclude_brand"] = value
                params["raw_ex_brand_filter"] = raw_ex_brand
            elif key == "exclude_brands" or (key == "exclude_brand" and isinstance(value, (list, tuple))):
                ex_brand_list = [str(b).strip() for b in (value if isinstance(value, (list, tuple)) else [value]) if str(b).strip()]
                if key == "exclude_brands" and isinstance(filters.get("exclude_brand"), str) and filters["exclude_brand"].strip():
                    if filters["exclude_brand"].strip() not in ex_brand_list:
                        ex_brand_list.append(filters["exclude_brand"].strip())
                raw_ex_source = raw_filters.get(key) or raw_filters.get("exclude_brands") or raw_filters.get("exclude_brand") or ex_brand_list
                raw_ex_brand_list = [str(b).strip() for b in (raw_ex_source if isinstance(raw_ex_source, (list, tuple)) else [raw_ex_source]) if str(b).strip()]
                if not raw_ex_brand_list:
                    raw_ex_brand_list = list(ex_brand_list)
                where_clauses.append(
                    "NOT (EXISTS { MATCH (node)-[:HAS_BRAND]->(eb:Brand) "
                    "WHERE ANY(ebf IN $exclude_brands_filter WHERE toLower(eb.name) = toLower(ebf) "
                    "   OR toLower(eb.name) CONTAINS toLower(ebf) "
                    "   OR toLower(ebf) CONTAINS toLower(eb.name)) } "
                    "OR ANY(rebf IN $raw_exclude_brands_filter WHERE toLower(node.title) CONTAINS toLower(rebf)))"
                )
                params["exclude_brands_filter"] = ex_brand_list
                params["raw_exclude_brands_filter"] = raw_ex_brand_list
            elif key == "category" and not isinstance(value, (list, tuple)):
                if filters.get("categories"):
                    continue
                raw_cat = raw_filters.get("category", value)
                if isinstance(raw_cat, (list, tuple)):
                    raw_cat = raw_cat[0] if raw_cat else value
                raw_cat = str(raw_cat)
                tokens = [t.strip().lower() for t in raw_cat.split() if len(t.strip()) > 2]

                # Construct conjunction of token matches to handle intervening modifiers in product titles
                if len(tokens) > 1:
                    escaped_tokens = [t.replace("'", "\\'") for t in tokens]
                    token_clauses = " AND ".join([f"toLower(node.title) CONTAINS '{et}'" for et in escaped_tokens])
                    title_condition = f"({token_clauses})"
                else:
                    escaped_raw = re.escape(raw_cat).replace("'", "\\'")
                    title_condition = f"toLower(node.title) =~ '(?i).*(^|[^a-z]){escaped_raw}(s)?([^a-z]|$).*'"

                where_clauses.append(f"""
                (
                    EXISTS {{
                        MATCH (node)-[:BELONGS_TO_CATEGORY]->(leaf:Category)-[:SUBCATEGORY_OF*0..3]->(c:Category)
                        WHERE c.name =~ ('(?i).*(^|[^a-z])' + $category_filter + '(s)?([^a-z]|$).*')
                           OR leaf.name =~ ('(?i).*(^|[^a-z])' + $category_filter + '(s)?([^a-z]|$).*')
                    }}
                    OR {title_condition}
                )
                """)
                params["category_filter"] = value
                params["raw_category_filter"] = raw_cat
            elif key == "categories" or (key == "category" and isinstance(value, (list, tuple))):
                cat_list = [str(c).strip() for c in (value if isinstance(value, (list, tuple)) else [value]) if str(c).strip()]
                if key == "categories" and isinstance(filters.get("category"), str) and filters["category"].strip():
                    if filters["category"].strip() not in cat_list:
                        cat_list.append(filters["category"].strip())
                raw_cat_source = raw_filters.get(key) or raw_filters.get("categories") or raw_filters.get("category") or cat_list
                raw_cat_list = [str(c).strip() for c in (raw_cat_source if isinstance(raw_cat_source, (list, tuple)) else [raw_cat_source]) if str(c).strip()]
                if not raw_cat_list:
                    raw_cat_list = list(cat_list)

                cat_regexes = [f"(?i).*(^|[^a-z]){re.escape(c)}(s)?([^a-z]|$).*" for c in cat_list]
                raw_cat_regexes = [f"(?i).*(^|[^a-z]){re.escape(rc)}(s)?([^a-z]|$).*" for rc in raw_cat_list]
                where_clauses.append("""
                (
                    EXISTS {
                        MATCH (node)-[:BELONGS_TO_CATEGORY]->(leaf:Category)-[:SUBCATEGORY_OF*0..3]->(c:Category)
                        WHERE ANY(cat_rx IN $categories_filter WHERE c.name =~ cat_rx OR leaf.name =~ cat_rx)
                    }
                    OR ANY(raw_rx IN $raw_categories_filter WHERE toLower(node.title) =~ raw_rx)
                )
                """)
                params["categories_filter"] = cat_regexes
                params["raw_categories_filter"] = raw_cat_regexes
            # EAV Numeric filters dynamically intercepted with toFloat fallback for string attribute values
            elif key.endswith("_min") and key != "price_min":
                attr_name = key.replace("_min", "")
                where_clauses.append(f"""
                EXISTS {{
                    MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute)
                    WHERE a.attribute_name = '{attr_name}'
                      AND COALESCE(
                          a.numeric_value,
                          toFloat(split(replace(replace(a.attribute_value, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                          toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
                              a.attribute_value,
                              'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
                      ) >= ${key}
                }}
                """)
                params[key] = float(value)
            elif key.endswith("_max") and key != "price_max":
                attr_name = key.replace("_max", "")
                where_clauses.append(f"""
                EXISTS {{
                    MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute)
                    WHERE a.attribute_name = '{attr_name}'
                      AND COALESCE(
                          a.numeric_value,
                          toFloat(split(replace(replace(a.attribute_value, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                          toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
                              a.attribute_value,
                              'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
                      ) <= ${key}
                }}
                """)
                params[key] = float(value)
            elif key.endswith("_exact"):
                attr_name = key.replace("_exact", "")
                where_clauses.append(f"""
                EXISTS {{
                    MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute)
                    WHERE a.attribute_name = '{attr_name}'
                      AND COALESCE(
                          a.numeric_value,
                          toFloat(split(replace(replace(a.attribute_value, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                          toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
                              a.attribute_value,
                              'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
                      ) = ${key}
                }}
                """)
                params[key] = float(value)
            else:
                logger.warning(f"[GST] Ignoring unhandled filter key: '{key}' = {value}")
            
        return where_clauses, params

    def _normalize_single_brand(self, raw_val: str, label: str = "brand") -> str:
        """Resolve a single brand string via ResolverService, falling back to raw_val."""
        BRAND_CONFIDENCE = getattr(self, "BRAND_CONFIDENCE", 0.85)
        try:
            matches = self.resolver.resolve_brand(raw_val, k=1)
            if matches and matches[0]["score"] >= BRAND_CONFIDENCE:
                logger.info(f"[GST] ✓ Normalized {label} '{raw_val}' → '{matches[0]['name']}' (score: {matches[0]['score']:.3f})")
                return matches[0]["name"]
            elif matches:
                logger.warning(f"[GST] ✗ {label.capitalize()} '{raw_val}' best match '{matches[0]['name']}' score={matches[0]['score']:.3f} < {BRAND_CONFIDENCE}. Keeping raw value for title fallback.")
            else:
                logger.warning(f"[GST] ✗ No {label} match for '{raw_val}'. Keeping raw value for title fallback.")
        except Exception as e:
            logger.warning(f"[GST] {label.capitalize()} normalization failed: {e}")
        return raw_val

    def _normalize_single_category(self, raw_val: str) -> str:
        """Resolve a single category string via ResolverService with margin check, falling back to raw_val."""
        CATEGORY_CONFIDENCE = getattr(self, "CATEGORY_CONFIDENCE", 0.70)
        CATEGORY_MARGIN = getattr(self, "CATEGORY_MARGIN", 0.05)
        try:
            matches = self.resolver.resolve_category(raw_val, k=3)
            if matches and matches[0]["score"] >= CATEGORY_CONFIDENCE:
                # Check candidate margin against runner-up candidates to prevent cross-domain drift
                has_margin = True
                if matches[0]["score"] < 0.85 and len(matches) > 1:
                    top = matches[0]
                    top_name = top.get("name", "").lower()
                    top_path = [p.lower() for p in (top.get("path") or [])]

                    # Find the first runner-up candidate that is a true cross-domain competitor.
                    # Candidates that contain the top candidate's name or share taxonomy lineage
                    # belong to the same taxonomic branch and are not cross-domain competitors.
                    comp_candidate = None
                    for runner_up in matches[1:]:
                        ru_name = runner_up.get("name", "").lower()
                        ru_path = [p.lower() for p in (runner_up.get("path") or [])]
                        if top_name in ru_name or ru_name in top_name or ru_name in top_path or top_name in ru_path:
                            continue
                        comp_candidate = runner_up
                        break

                    if comp_candidate is not None:
                        margin = top["score"] - comp_candidate["score"]
                        if margin < CATEGORY_MARGIN:
                            has_margin = False
                            logger.warning(
                                f"[GST] ✗ Category '{raw_val}' failed margin check: "
                                f"top match '{top['name']}' ({top['score']:.3f}) vs "
                                f"runner-up '{comp_candidate['name']}' ({comp_candidate['score']:.3f}), "
                                f"diff={margin:.3f} < {CATEGORY_MARGIN}. Keeping raw value for title fallback."
                            )
                    elif len(matches) > 1 and not (top_name in matches[1].get("name", "").lower() or matches[1].get("name", "").lower() in top_name):
                        margin = top["score"] - matches[1]["score"]
                        if margin < CATEGORY_MARGIN:
                            has_margin = False
                            logger.warning(
                                f"[GST] ✗ Category '{raw_val}' failed margin check: "
                                f"top match '{top['name']}' ({top['score']:.3f}) vs "
                                f"runner-up '{matches[1]['name']}' ({matches[1]['score']:.3f}), "
                                f"diff={margin:.3f} < {CATEGORY_MARGIN}. Keeping raw value for title fallback."
                            )

                if has_margin:
                    logger.info(f"[GST] ✓ Normalized category '{raw_val}' → '{matches[0]['name']}' (score: {matches[0]['score']:.3f})")
                    return matches[0]["name"]
            elif matches:
                logger.warning(f"[GST] ✗ Category '{raw_val}' best match '{matches[0]['name']}' score={matches[0]['score']:.3f} < {CATEGORY_CONFIDENCE}. Keeping raw value for title fallback.")
                candidates = [(m['name'], round(m['score'], 3)) for m in matches]
                logger.info(f"[GST]   Top candidates: {candidates}")
            else:
                logger.warning(f"[GST] ✗ No category match for '{raw_val}'. Keeping raw value for title fallback.")
        except Exception as e:
            logger.warning(f"[GST] Category normalization failed: {e}")
        return raw_val

    def _normalize_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize filter values to canonical graph node names using ResolverService.
        
        Confidence thresholds:
        - Brand: 0.85 (brand names are precise nouns, require high similarity to avoid Sennheiser -> Senso false positives)
        - Category: 0.70 (recalibrated with candidate margin check >= 0.05 to reliably resolve plurals and inflections while blocking cross-domain drift)
        
        NOTE: If normalization fails or confidence is low, the filter is NO LONGER dropped.
        Instead, it remains as the raw string so that the Cypher title fallback logic 
        (e.g., `OR toLower(node.title) CONTAINS $raw`) can still attempt a textual match.
        """
        if not self.resolver:
            logger.warning("[GST] ResolverService not available. Skipping normalization.")
            return filters
        
        normalized = dict(filters)

        # Normalize brand / brands
        if "brand" in normalized and normalized["brand"]:
            if isinstance(normalized["brand"], (list, tuple)):
                normalized["brand"] = [self._normalize_single_brand(str(b), "brand") for b in normalized["brand"] if b]
            else:
                normalized["brand"] = self._normalize_single_brand(str(normalized["brand"]), "brand")

        if "brands" in normalized and normalized["brands"]:
            if isinstance(normalized["brands"], (list, tuple)):
                normalized["brands"] = [self._normalize_single_brand(str(b), "brands") for b in normalized["brands"] if b]
            else:
                normalized["brands"] = [self._normalize_single_brand(str(normalized["brands"]), "brands")]

        # Normalize exclude_brand / exclude_brands
        if "exclude_brand" in normalized and normalized["exclude_brand"]:
            if isinstance(normalized["exclude_brand"], (list, tuple)):
                normalized["exclude_brand"] = [self._normalize_single_brand(str(b), "exclude_brand") for b in normalized["exclude_brand"] if b]
            else:
                normalized["exclude_brand"] = self._normalize_single_brand(str(normalized["exclude_brand"]), "exclude_brand")

        if "exclude_brands" in normalized and normalized["exclude_brands"]:
            if isinstance(normalized["exclude_brands"], (list, tuple)):
                normalized["exclude_brands"] = [self._normalize_single_brand(str(b), "exclude_brands") for b in normalized["exclude_brands"] if b]
            else:
                normalized["exclude_brands"] = [self._normalize_single_brand(str(normalized["exclude_brands"]), "exclude_brands")]

        # Normalize category / categories
        if "category" in normalized and normalized["category"]:
            if isinstance(normalized["category"], (list, tuple)):
                normalized["category"] = [self._normalize_single_category(str(c)) for c in normalized["category"] if c]
            else:
                normalized["category"] = self._normalize_single_category(str(normalized["category"]))

        if "categories" in normalized and normalized["categories"]:
            if isinstance(normalized["categories"], (list, tuple)):
                normalized["categories"] = [self._normalize_single_category(str(c)) for c in normalized["categories"] if c]
            else:
                normalized["categories"] = [self._normalize_single_category(str(normalized["categories"]))]

        return normalized

    def _filters_present(self, filters: Optional[Dict[str, Any]]) -> bool:
        """Check if any meaningful (non-None) filters exist."""
        if not filters:
            return False
        return any(v is not None for v in filters.values())
