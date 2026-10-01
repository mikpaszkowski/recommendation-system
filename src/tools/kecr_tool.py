"""
Phase A4 Knowledge-Enhanced Reasoning Path Extraction (KECR).
Extracts multi-hop reasoning paths bridging user history to conversational candidates.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from src.dialog_manager.session_schema import SessionContext
from src.dialog_manager.session_adapter import extract_semantic_query

logger = logging.getLogger(__name__)

class GraphReasoningPath(BaseModel):
    """Structured representation of a single extracted reasoning path."""
    target_asin: str = Field(description="ASIN of the recommended candidate item")
    target_title: str = Field(description="Full title of the candidate item")
    path_type: str = Field(description="'HISTORICAL_COMPATIBILITY' | 'BRAND_LOYALTY' | 'CO_PURCHASE' | 'CONVERSATIONAL_MATCH' | 'SPARSE_FALLBACK' | 'DUAL_CONTEXT'")
    composite_score: float = Field(ge=0.0, le=1.0, description="Fused path score (strictly bounded in [0.0, 1.0])")
    historical_score: float = Field(ge=0.0, le=1.0, description="Raw decay-weighted historical score")
    conversational_score: float = Field(ge=0.0, le=1.0, description="Conversational match score")
    historical_anchor_title: Optional[str] = Field(default=None, description="Title of past purchased item")
    historical_days_elapsed: Optional[int] = Field(default=None, description="Days elapsed since past purchase")
    shared_entity_name: Optional[str] = Field(default=None, description="Name of bridging node (attribute, brand, category)")
    reasoning_path: str = Field(description="Human-readable serialized reasoning path for [GRAPH EVIDENCE]")


class PathExtractionResult(BaseModel):
    """Overall payload returned by KnowledgePathExtractor."""
    user_id: Optional[str]
    gating_alpha: float = Field(ge=0.0, le=1.0, description="Historical weight factor (gamma)")
    total_paths_extracted: int
    paths: List[GraphReasoningPath]
    serialized_evidence_dict: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Formatted as [{'target_item': title, 'reasoning_path': path}] for PromptConstructor"
    )

    def to_evidence_dicts(self) -> List[Dict[str, str]]:
        """Guarantees strict dictionary contract for PromptConstructor._format_graph_evidence."""
        return [
            {
                "target_item": p.target_title,
                "reasoning_path": p.reasoning_path
            }
            for p in self.paths
        ]


class KnowledgePathExtractor:
    """
    Core engine for Phase A4 dual-context path extraction.
    Executes the Unified Dual-Context Cypher Query (Query 4) to extract multi-hop paths.
    """
    
    def __init__(self, db_connector: Optional[Any] = None):
        """
        Initialize the extractor.
        
        Args:
            db_connector: The Neo4j connector instance. If None, it will be lazily loaded 
                          or injected when `extract_paths` is called, though typically 
                          we pass it during initialization.
        """
        if db_connector is None:
            # Try to get the default connector if none provided
            from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
            self.db_connector = Neo4jConnector()
        else:
            self.db_connector = db_connector
            
    def _get_target_attributes_from_session(self, session_context: Optional[SessionContext]) -> List[Dict[str, Any]]:
        """Extract conversational target attributes from the session context."""
        if not session_context or not session_context.extracted_parameters:
            return []
            
        attr_list = []
        
        # Soft preferences
        soft_preferences = session_context.extracted_parameters.soft_preferences
        for sp in soft_preferences:
            attr_list.append({"name": sp.category, "val": sp.value})
            
        return attr_list
        
    def _determine_alpha(self, user_id: str, target_brand: Optional[str], target_category: Optional[str], target_attributes: List[Dict[str, Any]]) -> float:
        """
        Determine the gating factor (gamma / alpha).
        alpha is the weight for historical score.
        If the user is cold (no user_id), alpha = 0.0.
        If the query is sparse (no constraints), alpha = 1.0.
        Otherwise, alpha = 0.4 (standard).
        """
        if not user_id:
            return 0.0
            
        has_constraints = bool(target_brand or target_category or target_attributes)
        
        if not has_constraints:
            return 1.0
            
        return 0.4

    def extract_paths(self,
                      user_id: str,
                      candidate_items: List[Dict[str, Any]],
                      session_context: Optional[SessionContext] = None) -> PathExtractionResult:
        """
        Executes the dual-context path extraction against Neo4j.
        
        Args:
            user_id: The ID of the user requesting recommendations.
            candidate_items: The list of candidate items (asins) retrieved by the orchestrator.
            session_context: The current session context containing explicit conversational preferences.
            
        Returns:
            PathExtractionResult containing extracted paths and formatted evidence.
        """
        if not candidate_items:
            return PathExtractionResult(
                user_id=user_id,
                gating_alpha=0.0,
                total_paths_extracted=0,
                paths=[],
                serialized_evidence_dict=[]
            )

        candidate_asins = [item.get("asin", item.get("parent_asin", "")) for item in candidate_items]
        candidate_asins = [asin for asin in candidate_asins if asin]
        
        if not candidate_asins:
            return PathExtractionResult(
                user_id=user_id,
                gating_alpha=0.0,
                total_paths_extracted=0,
                paths=[],
                serialized_evidence_dict=[]
            )

        # Extract conversational intents
        target_brand = None
        target_category = None
        target_attributes = []
        
        if session_context and session_context.extracted_parameters:
            ep = session_context.extracted_parameters
            for hc in ep.hard_constraints:
                if hc.attribute == "brand":
                    target_brand = str(hc.value)
                elif hc.attribute == "category":
                    target_category = str(hc.value)
                
            target_attributes = self._get_target_attributes_from_session(session_context)

        alpha = self._determine_alpha(user_id, target_brand, target_category, target_attributes)
        
        # Build parameters for Cypher query
        now_iso = datetime.now().isoformat() + "Z"
        
        parameters = {
            "user_id": user_id or "",
            "candidate_asins": candidate_asins,
            "now_iso": now_iso,
            "target_brand": target_brand,
            "target_category": target_category,
            "target_attributes": target_attributes,
            "alpha": alpha,
            "half_life_days": 180.0,
            "max_attribute_degree": 50,
            "min_category_level": 2,
            "top_k": len(candidate_asins)
        }
        
        query = '''
UNWIND $candidate_asins AS cand_asin
MATCH (cand:ParentProduct {parent_asin: cand_asin})

// Subquery 1: Historical Evidence & Affinity (Guaranteed 1 Row per candidate)
CALL {
  WITH cand
  OPTIONAL MATCH (u:User {user_id: $user_id})-[:WROTE]->(rev:Review)-[r:REVIEWS]->(p_past:ParentProduct)
  WHERE $user_id <> "" AND r.rating >= 3.5 AND cand.parent_asin <> p_past.parent_asin
    AND NOT EXISTS { MATCH (u)-[:WROTE]->(:Review)-[:REVIEWS]->(cand) }
    AND r.timestamp_iso IS NOT NULL
    AND duration.inDays(datetime(r.timestamp_iso), datetime($now_iso)).days >= 0
  
  WITH cand, p_past, r,
       duration.inDays(datetime(r.timestamp_iso), datetime($now_iso)).days AS days_elapsed
  ORDER BY (exp(- (ln(2.0) / $half_life_days) * toFloat(days_elapsed)) * (r.rating / 5.0) * ((1.0 + 0.20 * CASE WHEN r.verified THEN 1.0 ELSE 0.0 END) / 1.20)) DESC
  LIMIT 3

  // Isolated Pattern Comprehensions: Decoupled, no Cartesian explosion, undirected co-purchase
  WITH cand, p_past, r, days_elapsed,
       exp(- (ln(2.0) / $half_life_days) * toFloat(days_elapsed)) * (r.rating / 5.0) * ((1.0 + 0.20 * CASE WHEN r.verified THEN 1.0 ELSE 0.0 END) / 1.20) AS hist_weight,
       [(p_past)-[bt:BOUGHT_TOGETHER]-(cand) | 
         "User bought together with previously purchased '" + coalesce(p_past.title, p_past.parent_asin) + "' (rated " + toString(r.rating) + "★, " + toString(days_elapsed) + "d ago)"
       ] AS bt_ev,
       [(p_past)-[:HAS_ATTRIBUTE]->(a:Attribute)<-[:HAS_ATTRIBUTE]-(cand) 
        WHERE COUNT { (a)<-[:HAS_ATTRIBUTE]-() } <= $max_attribute_degree | 
         "Shares attribute [" + a.attribute_name + ": " + coalesce(a.normalized_value, a.attribute_value, "") + "] with previously purchased '" + coalesce(p_past.title, p_past.parent_asin) + "' (rated " + toString(r.rating) + "★, " + toString(days_elapsed) + "d ago)"
       ] AS attr_ev,
       [(p_past)-[:BELONGS_TO_CATEGORY]->(c:Category)<-[:BELONGS_TO_CATEGORY]-(cand) 
        WHERE c.level >= $min_category_level | 
         "Shares specific category [" + c.name + "] with past favorite '" + coalesce(p_past.title, p_past.parent_asin) + "'"
       ] AS cat_ev

  WITH cand,
       collect(
         CASE WHEN size(bt_ev) > 0 OR size(attr_ev) > 0 OR size(cat_ev) > 0 THEN hist_weight ELSE 0.0 END
       ) AS weights,
       collect(bt_ev + attr_ev + cat_ev) AS all_bridge_lists

  // Guaranteed single row output: empty lists reduce cleanly to 0.0 and []
  RETURN round(CASE WHEN coalesce(reduce(acc = 0.0, w IN weights | acc + w), 0.0) > 1.0 
                    THEN 1.0 
                    ELSE coalesce(reduce(acc = 0.0, w IN weights | acc + w), 0.0) END, 4) AS s_hist,
         [reason IN reduce(acc = [], lst IN all_bridge_lists | acc + lst) WHERE reason IS NOT NULL][0..2] AS hist_paths
}

// Subquery 2: Conversational Evidence & Affinity (Guaranteed 1 Row per candidate)
CALL {
  WITH cand
  OPTIONAL MATCH (cand)-[:HAS_BRAND]->(b:Brand)
  WHERE $target_brand IS NOT NULL AND toLower(b.name) = toLower($target_brand)

  WITH cand, b,
       [(cand)-[:BELONGS_TO_CATEGORY]->(cat:Category) 
        WHERE $target_category IS NOT NULL AND toLower(cat.name) CONTAINS toLower($target_category) | cat.name] AS matched_cat_names,
       [(cand)-[:HAS_ATTRIBUTE]->(attr:Attribute) 
        WHERE size($target_attributes) > 0 
          AND ANY(f IN $target_attributes WHERE 
                toLower(attr.attribute_name) = toLower(f.name) 
                AND (f.val IS NULL OR toLower(coalesce(attr.normalized_value, attr.attribute_value, "")) CONTAINS toLower(toString(f.val)))) |
         "Matches requested feature: " + attr.attribute_name + " (" + coalesce(attr.normalized_value, attr.attribute_value, "") + ")"
       ] AS matched_attr_reasons

  // Normalize conversational score by active constraints to guarantee [0.0, 1.0] bounds
  WITH cand, b, matched_cat_names, matched_attr_reasons,
       (CASE WHEN $target_brand IS NOT NULL THEN 0.4 ELSE 0.0 END) +
       (CASE WHEN $target_category IS NOT NULL THEN 0.3 ELSE 0.0 END) +
       (CASE WHEN size($target_attributes) > 0 THEN 0.3 ELSE 0.0 END) AS active_conv_weight,
       (CASE WHEN b IS NOT NULL THEN 0.4 ELSE 0.0 END) +
       (CASE WHEN size(matched_cat_names) > 0 THEN 0.3 ELSE 0.0 END) +
       (CASE WHEN size(matched_attr_reasons) > 0 
             THEN 0.3 * (CASE WHEN (toFloat(size(matched_attr_reasons)) / toFloat(size($target_attributes))) > 1.0 
                              THEN 1.0 
                              ELSE (toFloat(size(matched_attr_reasons)) / toFloat(size($target_attributes))) END) 
             ELSE 0.0 END) AS earned_conv_score,
       [
         CASE WHEN b IS NOT NULL THEN "Directly matches requested brand: " + b.name ELSE NULL END,
         CASE WHEN size(matched_cat_names) > 0 THEN "Matches requested category: " + matched_cat_names[0] ELSE NULL END
       ] + matched_attr_reasons AS conv_reasons

  WITH cand,
       CASE WHEN active_conv_weight > 0.0 
            THEN round(CASE WHEN (earned_conv_score / active_conv_weight) > 1.0 
                            THEN 1.0 
                            ELSE (earned_conv_score / active_conv_weight) END, 4) 
            ELSE 0.0 END AS raw_conv_score,
       conv_reasons

  RETURN coalesce(raw_conv_score, 0.0) AS s_conv,
         [cr IN conv_reasons WHERE cr IS NOT NULL] AS conv_paths
}

// Score Fusion & Grounding Synthesis (Bounded in [0.0, 1.0])
WITH cand, s_hist, s_conv, hist_paths, conv_paths,
     round(CASE WHEN ($alpha * s_hist + (1.0 - $alpha) * s_conv) > 1.0 
                THEN 1.0 
                ELSE ($alpha * s_hist + (1.0 - $alpha) * s_conv) END, 4) AS composite_score,
     (hist_paths + conv_paths) AS all_evidence

ORDER BY composite_score DESC, coalesce(cand.avg_rating, 0.0) DESC
LIMIT $top_k

RETURN cand.parent_asin AS target_asin,
       cand.title AS target_item,
       composite_score,
       s_hist AS historical_score,
       s_conv AS conversational_score,
       CASE 
         WHEN size(all_evidence) > 0 
         THEN reduce(s = head(all_evidence), x IN tail(all_evidence) | s + "; " + x)
         ELSE "Top-rated category recommendation based on overall customer satisfaction (" + toString(coalesce(cand.avg_rating, 5.0)) + "★)."
       END AS reasoning_path;
        '''

        if hasattr(self.db_connector, "execute_query"):
            records = self.db_connector.execute_query(query, parameters=parameters)
        elif hasattr(self.db_connector, "execute_read"):
            res = self.db_connector.execute_read(query, parameters=parameters)
            records = res[0] if isinstance(res, tuple) and len(res) == 3 else res
        else:
            records = []

        graph_paths = []
        for row in records:
            # Determine path_type based on scores
            s_hist = row.get("historical_score", 0.0)
            s_conv = row.get("conversational_score", 0.0)
            reasoning = row.get("reasoning_path", "")
            
            if s_hist > 0 and s_conv > 0:
                path_type = "DUAL_CONTEXT"
            elif s_hist > 0:
                if "bought together" in reasoning.lower():
                    path_type = "CO_PURCHASE"
                elif "brand" in reasoning.lower():
                    path_type = "BRAND_LOYALTY"
                else:
                    path_type = "HISTORICAL_COMPATIBILITY"
            elif s_conv > 0:
                path_type = "CONVERSATIONAL_MATCH"
            else:
                path_type = "SPARSE_FALLBACK"

            path = GraphReasoningPath(
                target_asin=row["target_asin"],
                target_title=row["target_item"],
                path_type=path_type,
                composite_score=row["composite_score"],
                historical_score=s_hist,
                conversational_score=s_conv,
                reasoning_path=reasoning
            )
            graph_paths.append(path)

        result = PathExtractionResult(
            user_id=user_id,
            gating_alpha=alpha,
            total_paths_extracted=len(graph_paths),
            paths=graph_paths,
        )
        
        # Compute the serialized evidence dict manually as Pydantic won't auto-compute fields on init like this
        result.serialized_evidence_dict = result.to_evidence_dicts()
        
        return result
