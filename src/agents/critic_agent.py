import json
import logging
import asyncio
from typing import Dict, Any, List

from langchain_core.messages import SystemMessage

from src.llm.simple_llm_handler import SimpleLLMHandler

logger = logging.getLogger(__name__)

CRITIC_SYSTEM_PROMPT = """
Jesteś Ekspertem ds. Weryfikacji Jakości Produktów. 
Twoim zadaniem NIE jest sprzedaż, ale brutalnie szczera ocena, czy dany produkt pasuje do specyficznych potrzeb użytkownika.

PROFIL UŻYTKOWNIKA:
{user_persona_description}

PRODUKT DO OCENY:
Nazwa: {product_name}
Cechy: {features}
Opinie/Wady/Zalety: {unstructured_data}

ZADANIE:
Przeanalizuj opinie o produkcie w kontekście potrzeb użytkownika.
1. Czy produkt posiada ukryte wady dyskwalifikujące go dla TEGO konkretnego użytkownika?
2. Przyznaj ocenę dopasowania (0-100).
3. Napisz 1 zdanie uzasadnienia ("Reasoning").

FORMAT OUTPUTU (JSON):
Zwróć TYLKO i WYŁĄCZNIE poprawny, parsowalny JSON o poniższej strukturze, bez pisania w Markdownie:
{{
  "fit_score": 85,
  "reasoning": "Krótkie uzasadnienie...",
  "is_recommended": true
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
        Asynchronously evaluates a list of product candidates.
        """
        if not candidates:
            return []

        logger.info(f"[CriticAgent] Evaluating {len(candidates)} candidates...")
        user_persona = json.dumps(user_profile.get("preferences", {}), ensure_ascii=False)
        
        tasks = []
        for product in candidates:
            tasks.append(self._evaluate_single_product(user_persona, product, attributes_map))
            
        evaluated_products = await asyncio.gather(*tasks)
        
        # Filter and sort
        recommended = [p for p in evaluated_products if p.get("is_recommended")]
        recommended.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
        
        logger.info(f"[CriticAgent] Evaluation complete. {len(recommended)} out of {len(candidates)} products recommended.")
        return recommended

    async def _evaluate_single_product(self, user_persona: str, product: Dict[str, Any], attributes_map: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Evaluates a single product asynchronously.
        """
        import copy
        evaluated_product = copy.deepcopy(product)
        
        # Prepare context data
        # Note: product variable is coming from GraphSearchTool and might have 'id' instead of 'asin' for Neo4j Element ID. 
        # But we need ASIN to match attributes. Let's extract ASIN from ElementID or use it if available.
        # However, GraphSearchTool doesn't default to returning ASIN unless we added it. Wait, the cypher for Vector search returns `elementId(node) as id` and doesn't return `parent_asin`. 
        # We need to make sure 'asin' is available, but for now we'll do our best.
        
        # To be safe, look for 'id' which might be the ASIN if we modified GT, or we'll need to modify GT to return parent_asin
        asin = product.get("asin")
        
        attributes = attributes_map.get(asin, []) if asin else []
        
        # Convert attributes to string representation mapped nicely
        unstructured_text = "\\n".join([f"- {a['name']}: {a['value']} (Source: {a['source']})" for a in attributes])
        if not unstructured_text:
            unstructured_text = "Brak dodatkowych opinii i wad/zalet w bazie."

        features = f"Cena: {product.get('price')} | Brand: {product.get('brand')} | Kategoria: {product.get('category')}"
        
        prompt = CRITIC_SYSTEM_PROMPT.format(
            user_persona_description=user_persona,
            product_name=product.get("title", "Unknown Product"),
            features=features,
            unstructured_data=unstructured_text
        )

        try:
            response_text = await self.llm_handler.aquery([SystemMessage(content=prompt)])
            
            # Clean and parse JSON
            cleaned_json = response_text.replace("```json", "").replace("```", "").strip()
            result = json.loads(cleaned_json)
            
            logger.info(f"[CriticAgent] LLM Result for '{product.get('asin', 'N/A')}': {result}")
            
            evaluated_product["semantic_score"] = result.get("fit_score", 0)
            evaluated_product["reasoning"] = result.get("reasoning", "")
            evaluated_product["is_recommended"] = result.get("is_recommended", False)
            
        except Exception as e:
            logger.error(f"[CriticAgent] Failed to evaluate product {product.get('title')}: {e}")
            # Fallback values if LLM fails
            evaluated_product["semantic_score"] = product.get("score", 0) * 100 # Fallback to vector score scale roughly
            evaluated_product["reasoning"] = "Błąd ewaluacji kontekstowej."
            evaluated_product["is_recommended"] = True # Keep it if we can't decide
            
        return evaluated_product
