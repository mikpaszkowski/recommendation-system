import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from langchain_core.messages import SystemMessage

from src.llm.simple_llm_handler import SimpleLLMHandler

logger = logging.getLogger(__name__)

CRITIC_SYSTEM_PROMPT = """
You are a Product Quality Verification Expert.
Your job is NOT to sell, but to give a brutally honest assessment of whether this product fits the user's specific needs.

USER PROFILE:
{user_persona_description}

PRODUCT TO EVALUATE:
Name: {product_name}
Features: {features}
Reviews/Pros/Cons: {unstructured_data}

TASK:
Analyze the product information and reviews in the context of the user's needs.
1. Does the product have hidden flaws that disqualify it for THIS specific user?
2. Assign a fit score (0-100).
3. Write a one-sentence justification ("reasoning").

OUTPUT FORMAT (JSON):
Return ONLY a valid, parseable JSON object with the structure below, without Markdown formatting:
{{
  "fit_score": 85,
  "reasoning": "Short justification...",
  "is_recommended": true
}}
"""

PHASE_A2_CRITIC_PROMPT = """
You are the final Arbitration and Quality Assurance Agent for a Recommendation System.
Your job is to evaluate a list of candidate products against a user's strict constraints and functional preferences.

## DIRECTIVES
1. Attribute Verification (Technical Fit): Cross-reference the candidate's exact technical attributes against the user's preferences to ruthlessly eliminate or demote "semantic betrayals". If the user explicitly requested "wireless" and the attributes say "wired", it MUST be demoted/rejected (is_recommended = false).
2. Review Verification (Functional Fit): Evaluate the provided user review snippets. If a user wants a "durable" item and reviews indicate it breaks easily, penalize it.
3. User-Decides Trade-off Formatting: If `relaxed_constraints` is present, it means the system couldn't find an exact match under their original hard constraints and had to compromise (e.g. widen budget). You MUST NOT silently approve this. You must formulate a clear `disclosure_statement` for the user to make the final financial/trade-off decision.

## CONTEXT
User Session Context (Preferences & Constraints):
{session_context}

MACS Relaxed Constraints (Compromises made to find these items):
{relaxed_constraints}

## CANDIDATES TO EVALUATE
{candidates_json}

## OUTPUT INSTRUCTIONS
Return ONLY a valid JSON object strictly matching this schema:
{{
  "ranked_candidates": [
    {{
      "id": "item_id_here",
      "title": "Item Title",
      "fit_score": 95, 
      "reasoning": "Reason for this score (technical/functional fit).",
      "is_recommended": true
    }}
  ],
  "disclosure_statement": "Your human-readable question asking the user to approve the trade-offs mentioned in Relaxed Constraints (leave null if no relaxed constraints).",
  "rationale": "Internal reasoning for the overall ranking and disclosure."
}}
"""

class CriticAgent:
    """
    Agent that performs Context-Aware Reranking using LLM Reasoning
    over unstructured product data and user persona.
    """
    def __init__(self, llm_handler: SimpleLLMHandler = None):
        self.llm_handler = llm_handler or SimpleLLMHandler()

    async def evaluate_candidates(self, user_profile: Dict[str, Any], candidates: List[Dict[str, Any]], attributes_map: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Legacy evaluation method (Phase 1).
        """
        if not candidates:
            return []

        logger.info(f"[CriticAgent] Evaluating {len(candidates)} candidates...")
        user_persona = json.dumps(user_profile.get("preferences", {}), ensure_ascii=False)
        
        tasks = []
        for product in candidates:
            tasks.append(self._evaluate_single_product(user_persona, product, attributes_map))
            
        evaluated_products = await asyncio.gather(*tasks)
        
        recommended = [p for p in evaluated_products if p.get("is_recommended")]
        recommended.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
        return recommended

    async def _evaluate_single_product(self, user_persona: str, product: Dict[str, Any], attributes_map: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Legacy evaluation method."""
        import copy
        evaluated_product = copy.deepcopy(product)
        asin = product.get("asin")
        attributes = attributes_map.get(asin, []) if asin else []
        
        unstructured_text = "\n".join([f"- {a['name']}: {a['value']} (Source: {a['source']})" for a in attributes])
        if not unstructured_text:
            unstructured_text = "No additional reviews or pros/cons available in the database."

        features = f"Price: {product.get('price')} | Brand: {product.get('brand')} | Category: {product.get('category')}"
        
        prod_title = product.get("title") or product.get("asin") or "Unknown Product"
        prompt = CRITIC_SYSTEM_PROMPT.format(
            user_persona_description=user_persona,
            product_name=prod_title,
            features=features,
            unstructured_data=unstructured_text
        )

        try:
            response_text = await self.llm_handler.aquery([SystemMessage(content=prompt)])
            cleaned_json = response_text.replace("```json", "").replace("```", "").strip()
            result = json.loads(cleaned_json)
            evaluated_product["semantic_score"] = result.get("fit_score", 0)
            evaluated_product["reasoning"] = result.get("reasoning", "")
            evaluated_product["is_recommended"] = result.get("is_recommended", False)
            
            title_display = str(prod_title)[:70]
            status_tag = "✅ APPROVED" if evaluated_product["is_recommended"] else "❌ REJECTED"
            logger.info(
                f"[CriticAgent] {status_tag}: '{title_display}' | "
                f"Fit Score: {evaluated_product['semantic_score']}/100 | "
                f"Reason: {evaluated_product['reasoning']}"
            )
            
        except Exception as e:
            title_display = str(prod_title)[:70]
            logger.error(f"[CriticAgent] Failed to evaluate product {title_display}: {e}")
            evaluated_product["semantic_score"] = product.get("score", 0) * 100
            evaluated_product["reasoning"] = "Evaluation error."
            evaluated_product["is_recommended"] = True
            logger.info(
                f"[CriticAgent] ⚠️ FALLBACK APPROVED (Eval Error): '{title_display}'"
            )
            
        return evaluated_product

    async def evaluate_candidate_tradeoffs(
        self,
        candidates: List[Dict[str, Any]],
        session_context: Any,
        relaxed_constraints: List[str] = None
    ) -> Dict[str, Any]:
        """
        Phase A2: Contextual Selection-then-Rerank via CriticAgent.
        """
        if not candidates:
            return {
                "ranked_candidates": [],
                "disclosure_statement": None,
                "rationale": "No candidates to evaluate."
            }
            
        relaxed_constraints = relaxed_constraints or []
        
        prompt_candidates = []
        for c in candidates:
            prompt_candidates.append({
                "id": c.get("id") or c.get("asin", "unknown"),
                "title": c.get("title", "Unknown"),
                "price": c.get("price"),
                "attributes": c.get("attributes", []), 
                "reviews": [r.get("review_text", "") for r in c.get("reviews", [])[:3]]
            })
            
        if hasattr(session_context, "model_dump_json"):
            context_str = session_context.model_dump_json(indent=2)
        elif isinstance(session_context, dict):
            context_str = json.dumps(session_context, indent=2)
        else:
            context_str = str(session_context)
            
        prompt = PHASE_A2_CRITIC_PROMPT.format(
            session_context=context_str,
            relaxed_constraints=json.dumps(relaxed_constraints, indent=2) if relaxed_constraints else "None",
            candidates_json=json.dumps(prompt_candidates, indent=2)
        )
        
        try:
            response_text = await self.llm_handler.aquery([SystemMessage(content=prompt)])
            cleaned_json = response_text.replace("```json", "").replace("```", "").strip()
            result = json.loads(cleaned_json)
            
            ranked_map = {str(rc["id"]): rc for rc in result.get("ranked_candidates", [])}
            
            final_candidates = []
            for c in candidates:
                cid = str(c.get("id") or c.get("asin", "unknown"))
                if cid in ranked_map:
                    rc = ranked_map[cid]
                    c["semantic_score"] = rc.get("fit_score", 0)
                    c["critic_reasoning"] = rc.get("reasoning", "")
                    c["is_recommended"] = rc.get("is_recommended", True)
                    
                    c_title = str(c.get("title") or c.get("asin") or "Unknown Product")[:70]
                    status_tag = "✅ APPROVED" if c["is_recommended"] else "❌ REJECTED"
                    logger.info(
                        f"[CriticAgent:Tradeoffs] {status_tag}: '{c_title}' | "
                        f"Fit Score: {c['semantic_score']}/100 | "
                        f"Reason: {c['critic_reasoning']}"
                    )
                    
                    if c["is_recommended"]:
                        final_candidates.append(c)
                        
            final_candidates.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
            
            return {
                "ranked_candidates": final_candidates,
                "disclosure_statement": result.get("disclosure_statement"),
                "rationale": result.get("rationale", "Parsed successfully.")
            }
            
        except Exception as e:
            logger.error(f"[CriticAgent] LLM parsing failed in evaluate_candidate_tradeoffs: {e}")
            return {
                "ranked_candidates": candidates,
                "disclosure_statement": "I had to compromise on your constraints to find these options. Please review." if relaxed_constraints else None,
                "rationale": "LLM evaluation failed, returning original list."
            }
