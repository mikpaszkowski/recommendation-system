import json
import logging
import asyncio
import inspect
import os
from typing import Dict, Any, FrozenSet, List, Optional, Tuple

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from src.conversation.history_manager import InMemoryHistoryManager
from src.agents.state import ConversationState
from src.agents.critic_agent import CriticAgent
from src.tools.graph_search_tool import GraphSearchTool
from src.tools.profile_tool import ProfileTool
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm_interface.prompts.router_prompt import router_prompt_template
from src.llm_interface.prompt_constructor import PromptConstructor
from src.dialog_manager.dialogue_manager import DialogueManager
from src.dialog_manager.session_adapter import (
    CATALOG_SAFE_FILTER_KEYS,
    _coerce_numeric,
    extract_semantic_query,
    generate_attribute_unit_variations,
    hard_constraints_to_structured_filters,
    session_context_to_dialogue_action,
    session_context_to_soft_preferences,
    session_context_to_structured_filters,
    session_context_to_user_persona,
)
from src.dialog_manager.session_schema import SessionContext, CurrentSessionContextWrapper
from src.llm_interface.preference_parser import LLMPreferenceParser
from src.tools.kecr_tool import KnowledgePathExtractor

logger = logging.getLogger(__name__)

# RS-23 (R2a): filter keys that carry the requested product type, values that mean "no category",
# and the attributable reasons for a CLARIFY action (recorded as eval_trace["clarify_reason"])
CATEGORY_FILTER_KEYS: Tuple[str, ...] = ("category", "product_category", "product_type", "type", "categories")
NULL_CATEGORY_VALUES: FrozenSet[str] = frozenset({"", "none", "null", "unknown", "n/a", "any"})
CLARIFY_REASONS: FrozenSet[str] = frozenset({"router", "router_fallback", "parser_missing_category",
                                             "recovery_failed", "recovery_error"})

# Audit H-1 / FR-007a (spec §13 A-11): category recovery uses a recovered category only when the same
# search-params call reports product_type_decided == true. Verbatim spec text; no examples by design.
PRODUCT_TYPE_DECIDED_RULE = """- `product_type_decided` is true only if the user has named, or has committed to, one specific kind of
  product, in the current message, the conversation history or the active filters.
  Set it to false when the request names only who the product is for, an occasion or an interest, when it
  names a broad class that covers unrelated kinds of products, or when the user is still choosing between
  different kinds of products. When `product_type_decided` is false, `category` MUST be null.
"""

HYDE_PRODUCT_MAX_CHARS: int = 1000
HYDE_REVIEW_MAX_CHARS: int = 800

HYDE_GENERATION_RULE = """- `hyde_product` (Hypothetical Product Document for `product_embedding_index`):
  Write a concise hypothetical catalog entry (< 160 words) matching the exact catalog schema:
  "Product: <generic product title>. Category: <category>. Features: <comma-separated technical specs>. Description: <1-2 sentence technical overview>".
  Do NOT invent a brand or model code unless the user explicitly requested that brand. Convert negative
  preferences into affirmative technical specifications (e.g., "not loud" -> "Silent Linear Switches, Sound-Dampening Foam").
  When `product_type_decided` is false, `hyde_product` MUST be null.
- `hyde_review` (Hypothetical Customer Review for `review_embedding_index`):
  Write a concise first-person verified-purchaser review (< 800 characters) formatted as:
  "<Short Review Title>. <1-2 paragraph experiential review body>".
  Praise the user's subjective and experiential priorities (comfort, quietness, reliability, build quality, ease of setup)
  using affirmative phrasing without negation traps. When `product_type_decided` is false, `hyde_review` MUST be null.
"""


def _normalize_hyde_product(raw_hyde: Any, category: Optional[str] = None) -> Optional[str]:
    """
    Validates and normalises a hypothetical product document to match product_text_v1
    ('Product: ... Category: ... Features: ... Description: ...') within HYDE_PRODUCT_MAX_CHARS.
    Returns None for blank or null-like inputs (FR-HYDE-002).
    """
    if not isinstance(raw_hyde, str):
        return None
    cleaned = " ".join(raw_hyde.strip().split())
    if not cleaned or cleaned.lower() in NULL_CATEGORY_VALUES:
        return None
    if not cleaned.lower().startswith("product:"):
        cat_label = (category.strip() if isinstance(category, str) and category.strip() else None) or "Unknown"
        cleaned = f"Product: {cleaned}. Category: {cat_label}. Features: . Description: {cleaned}"
    return cleaned[:HYDE_PRODUCT_MAX_CHARS]


def _normalize_hyde_review(raw_hyde: Any) -> Optional[str]:
    """
    Validates and truncates a hypothetical customer review to HYDE_REVIEW_MAX_CHARS (800 chars).
    Returns None for blank or null-like inputs (FR-HYDE-002).
    """
    if not isinstance(raw_hyde, str):
        return None
    cleaned = " ".join(raw_hyde.strip().split())
    if not cleaned or cleaned.lower() in NULL_CATEGORY_VALUES:
        return None
    return cleaned[:HYDE_REVIEW_MAX_CHARS]


SEARCH_GENERATION_PROMPT = """
YOUR GOAL: Help the user find the perfect product by translating their request into search arguments.

[CONTEXT]
You are given the user's CURRENT MESSAGE, the CONVERSATION HISTORY, and the currently ACTIVE FILTERS.

[TASK]
1. Analyze if the user is MODIFYING existing filters, ADDING new ones, or STARTING OVER.
2. Generate a JSON containing the *updates* to the filters, a semantic query, and hypothetical product/review documents (HyDE).

[OUTPUT FORMAT (JSON)]
{
  "thought": "Reasoning about what changed.",
  "product_type_decided": true,  // false if the user has not committed to one specific kind of product
  "structured_filters": { 
     "brand": "Samsung",  // specific constraint
     "price_max": 2000, 
     "category": "laptop"  // the product type the user asked for, or null if undecided
  },
  "semantic_query": "high performance gaming...", // abstract visualization of the product
  "hyde_product": "Product: High-Performance Gaming Laptop. Category: Laptops. Features: Dedicated GPU, 144Hz Display, 16GB RAM, Fast NVMe SSD. Description: Built for modern gaming and heavy multitasking with high refresh rate visuals.",
  "hyde_review": "Runs modern games smoothly and stays cool. I bought this laptop for gaming and university work. Frame rates are consistently high, the screen is crisp, and the cooling fan is surprisingly quiet under load.",
  "_thinking": "Detailed step-by-step reasoning"
}

[RULES]
- `category` is the kind of product the user is asking for, in the user's own words (the head noun of the
  product phrase, without its modifiers). If the user has not decided what kind of product they want
  (e.g. they are choosing between kinds of products or only describe a need), set `category` to null.
  Never guess a category.
""" + PRODUCT_TYPE_DECIDED_RULE + HYDE_GENERATION_RULE + """- Copy numbers exactly as the user states them; never rescale, round or convert units.
- If user says "actually under 1500", UPDATE `price_max` to 1500.
- If user says "show me Dell instead", UPDATE `brand` to "Dell".
- If user says "what about that one?", use context to identify "that one".
"""

class AgentOrchestrator:
    """
    Main Orchestrator for the Multi-Agent Recommendation System.
    Implements a Router/State Machine pattern.
    """
    
    def __init__(self, 
                 graph_tool: Optional[GraphSearchTool] = None,
                 profile_tool: Optional[ProfileTool] = None,
                 llm_handler: Optional[SimpleLLMHandler] = None,
                 history_manager: Optional[InMemoryHistoryManager] = None,
                 critic_agent: Optional[CriticAgent] = None,
                 dialogue_manager: Optional[DialogueManager] = None,
                 preference_parser: Optional[LLMPreferenceParser] = None,
                 kecr_tool: Optional[KnowledgePathExtractor] = None,
                 candidate_limit: int = 20,
                 category_recovery: Optional[bool] = None):
        """
        Args:
            category_recovery: RS-23 option C. When the guardrail would switch a router SEARCH to
                CLARIFY because the category is missing, first try to recover it from one
                `_generate_search_params` call. None reads ORCH_CATEGORY_RECOVERY (default on;
                "0", "false" or "no" disable it, reproducing the pre-R2 guardrail exactly).
        """
        
        self.graph_tool = graph_tool or GraphSearchTool()
        self.profile_tool = profile_tool or ProfileTool()
        self.llm_handler = llm_handler or SimpleLLMHandler()
        self.history_manager = history_manager or InMemoryHistoryManager()
        self.prompt_constructor = PromptConstructor()
        self.critic_agent = critic_agent or CriticAgent(llm_handler=self.llm_handler)
        self.dialogue_manager = dialogue_manager or DialogueManager()
        self.preference_parser = preference_parser or LLMPreferenceParser(llm_handler=self.llm_handler)
        self.kecr_tool = kecr_tool or KnowledgePathExtractor(db_connector=self.graph_tool.db)
        self.candidate_limit = candidate_limit
        self.category_recovery = self._resolve_category_recovery(category_recovery)

    @staticmethod
    def _resolve_category_recovery(flag: Optional[bool]) -> bool:
        """Explicit flag wins; otherwise ORCH_CATEGORY_RECOVERY (default "1") decides."""
        if flag is not None:
            return bool(flag)
        raw = os.getenv("ORCH_CATEGORY_RECOVERY", "1")
        return str(raw).strip().lower() not in ("0", "false", "no")
        
    async def run(
        self,
        user_id: str,
        user_message: str,
        session_id: Optional[str] = None,
        mask_review_asins: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point for the agent conversation loop.
        """
        effective_session_id = session_id or user_id
        logger.info(f"{'='*60}")
        logger.info(f"[STEP 0] New request from user={user_id} (session={effective_session_id})")
        logger.info(f"[STEP 0] Message: '{user_message}'")
        
        # 1. Preference Extraction & Multi-Turn State Accumulation
        logger.info(f"[STEP 1a] Extracting preferences via preference_parser...")
        try:
            extraction = self.preference_parser.extract_preferences(user_message)
            logger.info("✅ Extracted SessionContext payload:")
            if hasattr(extraction, "model_dump_json"):
                logger.info(extraction.model_dump_json(indent=2))
            else:
                logger.info(json.dumps(extraction, indent=2, default=str))
        except Exception as e:
            logger.warning(f"Preference extraction error: {e}. Falling back to empty extraction.")
            extraction = {}
            
        logger.info(f"[STEP 1b] Updating dialogue state in DialogueManager...")
        session_context = self.dialogue_manager.update_turn(
            session_id=effective_session_id,
            user_message=user_message,
            extraction=extraction
        )

        # 2. Initialize State
        state = await self._initialize_state(user_id, user_message, session_context=session_context)
        if mask_review_asins:
            state["mask_review_asins"] = list(mask_review_asins)
        logger.info(f"[STEP 1c] State initialized")
        logger.info(f"  - History turns loaded: {len(state['messages']) - 1}")
        logger.info(f"  - Active filters from profile/session: {state.get('active_filters', {})}")
        logger.info(f"  - User profile keys: {list(state.get('user_profile', {}).keys())}")
        logger.info(f"  - Session intent: {session_context.session_intent.value if hasattr(session_context.session_intent, 'value') else session_context.session_intent}")
        logger.info(f"  - Ready for recommendation: {session_context.dialogue_state.ready_for_recommendation}")
        
        # 3. Router Step: Decide next action
        next_action, reasoning = await self._decide_next_step(state)
        logger.info(f"[STEP 2] Router decision: {next_action}")
        logger.info(f"  - Reasoning: {reasoning}")
        state["next_step"] = next_action
        
        # 4. Execution Step
        logger.info(f"[STEP 3] Executing action: {next_action}")
        response_payload = await self._execute_step(user_id, state, session_context=session_context)
        
        # 5. Save History (Post-Execution)
        agent_answer = response_payload.get("answer", "")
        self.history_manager.add_turn(user_id, user_message, agent_answer)
        logger.info(f"[STEP 4] History saved. Answer length: {len(agent_answer)} chars")
        logger.info(f"{'='*60}")
        
        # Include session_context in payload for transparent downstream verification
        response_payload["session_context"] = session_context.to_dict()
        
        return response_payload

    async def _initialize_state(self, user_id: str, user_message: str, session_context: Optional[SessionContext] = None) -> ConversationState:
        """Loads history and profile to build the initial state."""
        profile = self.profile_tool.get_profile(user_id)
        if not isinstance(profile, dict):
            profile = {"preferences": {}, "history": []}
        elif profile.get("preferences") is None:
            profile = {**profile, "preferences": {}}
            
        raw_prefs = profile.get("preferences")
        active_filters = raw_prefs.copy() if isinstance(raw_prefs, dict) else {}
        
        # Retrieve active session context if not explicitly passed
        if session_context is None:
            session_context = self.dialogue_manager.get_context(user_id)
            
        # Synchronize active_filters with structured filters from session context
        session_filters = session_context_to_structured_filters(session_context)
        active_filters.update(session_filters)
        
        history = self.history_manager.get_history(user_id)
        # Convert history to BaseMessages if needed, or just keep raw for logic.
        # State expects List[BaseMessage]
        messages = []
        for turn in reversed(history): # History is most recent first
             if "user" in turn:
                 messages.append(HumanMessage(content=turn["user"]))
             if "assistant" in turn:
                 messages.append(AIMessage(content=turn["assistant"]))
        
        messages.append(HumanMessage(content=user_message))

        return {
            "messages": messages,
            "next_step": None,
            "current_context": session_context.to_dict(),
            "user_profile": profile,
            "active_filters": active_filters,
            "search_params": None,
            "category_resolution": None,
            "clarify_reason": None,
        }

    async def _decide_next_step(self, state: ConversationState) -> tuple[str, str]:
        """Uses LLM to classify intent and pick the next step."""
        user_message = state["messages"][-1].content
        profile = state.get("user_profile", {})
        active_filters = state.get("active_filters", {})
        current_context = state.get("current_context", {})
        suggested_action = session_context_to_dialogue_action(current_context)
        
        # Format history for prompt
        # We take the last 5 turns (excluding current)
        history_msgs = state["messages"][:-1]
        recent_history = history_msgs[-10:] # Last 5 turns (User+AI)
        history_text = "\n".join([f"{type(m).__name__}: {m.content}" for m in recent_history])
        if not history_text:
            history_text = "No recent history."

        # RS-23 (R2a): per-turn category attribution, reset every turn
        state["search_params"] = None
        extracted_hard = current_context.get("extracted_parameters", {}).get("hard_constraints", []) if isinstance(current_context, dict) else []
        parser_category = self._category_from_hard_constraints(extracted_hard)
        present_category, present_source = self._present_category(active_filters, current_context, parser_category)
        has_category = present_category is not None
        resolution: Dict[str, Any] = {
            "parser_category": parser_category,
            "category": None,
            "source": None,
            "guardrail_triggered": False,
            "recovery_attempted": False,
            "recovery_outcome": None,
            "recovery_product_type_decided": None,
            "recovery_discarded_category": None,
        }
        clarify_reason: Optional[str] = None

        try:
            profile_prefs = profile.get("preferences", {}) if isinstance(profile, dict) else {}
            if profile_prefs is None:
                profile_prefs = {}
            prompt = router_prompt_template.format(
                history=history_text,
                user_profile=json.dumps(profile_prefs, indent=2, default=str),
                active_filters=json.dumps(active_filters, indent=2, default=str),
                user_message=user_message
            )
            # Construct messages for the router
            messages = [HumanMessage(content=prompt)]
            response = await self.llm_handler.aquery(messages)
            
            # Expecting JSON
            cleaned = self._clean_llm_json(response)
            data = json.loads(cleaned)
            raw_action = data.get("action", "ANSWER")
            action = str(raw_action).upper().strip() if isinstance(raw_action, str) else "ANSWER"
            reasoning = data.get("reasoning", "")
            
            # Affirmative Brand Immunization: If user provided both category and brand, proceed directly to SEARCH
            dialogue_state = current_context.get("dialogue_state", {})
            ready = dialogue_state.get("ready_for_recommendation", True)
            missing = dialogue_state.get("missing_critical_attributes", [])

            has_brand = bool(
                active_filters.get("brand")
                or any(
                    isinstance(c, dict) and c.get("attribute") == "brand" and c.get("operator") in ("include", "equal")
                    for c in extracted_hard
                )
            )

            if action == "CLARIFY" and has_category and has_brand:
                logger.info("Immunization: User has specified category and brand. Overriding CLARIFY -> SEARCH.")
                action = "SEARCH"
                reasoning = "Category and preferred brand provided; initiating targeted graph search."
            elif action == "SEARCH" and not ready and missing and "category" in missing:
                # RS-23: clarify only when no source has a product type (has_category, then recovery)
                resolution["guardrail_triggered"] = True
                if has_category:
                    resolution.update(category=present_category, source=present_source)
                    logger.info(f"Guardrail: category '{present_category}' present via {present_source}; keeping SEARCH.")
                elif not self.category_recovery:
                    logger.info("Guardrail: Critical category missing (recovery disabled). Switching SEARCH -> CLARIFY.")
                    action, clarify_reason = "CLARIFY", "parser_missing_category"
                    reasoning = f"Missing critical category ({', '.join(missing)}). Clarification required before searching."
                else:
                    resolution["recovery_attempted"] = True
                    rec = await self._recover_category(state)
                    resolution["recovery_outcome"] = rec["outcome"]
                    resolution["recovery_product_type_decided"] = rec.get("product_type_decided")
                    resolution["recovery_discarded_category"] = rec.get("discarded_category")
                    logger.info("[STEP 2] Category recovery: outcome=%s category=%r product_type_decided=%r discarded=%r",
                                rec["outcome"], rec["category"], rec.get("product_type_decided"),
                                rec.get("discarded_category"))
                    if rec["outcome"] == "found":
                        resolution.update(category=rec["category"], source="search_params")
                        reasoning = f"{reasoning} (category '{rec['category']}' recovered from search parameters)"
                    elif rec["outcome"] == "error":
                        action, clarify_reason = "CLARIFY", "recovery_error"
                        reasoning = "Category recovery failed with an LLM error; clarification required before searching."
                    else:
                        # "undecided" (H-1 gate) and "null_category" both clarify as recovery_failed
                        action, clarify_reason = "CLARIFY", "recovery_failed"
                        reasoning = f"Missing critical category ({', '.join(missing)}). Clarification required before searching."

            # SEARCH turns that never reached the guardrail (incl. brand immunisation) rely on the present category
            if action == "SEARCH" and resolution["category"] is None and has_category:
                resolution.update(category=present_category, source=present_source)
            if action == "CLARIFY" and clarify_reason is None:
                clarify_reason = "router"
            if action == "CLARIFY":
                resolution["category"] = None
                resolution["source"] = None

            state["category_resolution"] = resolution
            state["clarify_reason"] = clarify_reason
            return action, reasoning
        except Exception as e:
            logger.error(f"Router JSON parse error: {e}. Falling back to dialogue action '{suggested_action}'.")
            if suggested_action == "CLARIFY":
                resolution["category"] = None
                resolution["source"] = None
            elif suggested_action == "SEARCH" and has_category and resolution.get("category") is None:
                resolution.update(category=present_category, source=present_source)
            state["category_resolution"] = resolution
            state["clarify_reason"] = "router_fallback" if suggested_action == "CLARIFY" else None
            return suggested_action, f"Fallback to dialogue action due to error: {e}"

    async def _execute_step(self, user_id: str, state: ConversationState, session_context: Optional[SessionContext] = None) -> Dict[str, Any]:
        """Executes the determined action."""
        action = state["next_step"]
        user_message = state["messages"][-1].content
        profile = state.get("user_profile", {})
        active_filters = state.get("active_filters", {})
        
        result = {}
        
        if action == "SEARCH":
            # 3a. Generate Hybrid Search Parameters (Merging with Active Filters).
            # RS-23 (FR-008): a category-recovery turn already made this call; reuse its result.
            reused_params = state.get("search_params")
            if reused_params is not None:
                logger.info(f"[STEP 3a] Reusing search params from category recovery (no second LLM call).")
                updates = reused_params
                search_params_source = "recovery"
            else:
                logger.info(f"[STEP 3a] Generating search params via LLM...")
                updates = await self._generate_search_params(user_message, active_filters, self._search_history_text(state))
                search_params_source = "search_branch"
            logger.info(f"[STEP 3a] LLM returned:")
            logger.info(f"  - semantic_query: '{updates.get('semantic_query', '')}'")
            logger.info(f"  - structured_filters: {updates.get('structured_filters', {})}")
            logger.info(f"  - thought: {updates.get('thought', 'N/A')}")
            
            # 3b. Merge updates into active_filters
            new_filters = updates.get("structured_filters") or {}
            for k, v in new_filters.items():
                active_filters[k] = v
                
            if session_context:
                session_filters = session_context_to_structured_filters(session_context)
                for k, v in session_filters.items():
                    if k not in active_filters or active_filters[k] is None:
                        active_filters[k] = v
            
            # Requirement R1 & R2: Partition active_filters into catalog-safe structured filters
            # and demote arbitrary EAV/spec constraints into soft preferences for additive scoring.
            catalog_filters: Dict[str, Any] = {}
            demoted_from_filters: List[Dict[str, Any]] = []

            for k, v in active_filters.items():
                if v is None or v == "":
                    continue
                k_lower = str(k).lower().strip()

                # Normalize catalog fields to canonical GraphSearchTool keys
                if k_lower in ("price_max", "max_price", "budget", "cost") or (k_lower.startswith("price") and any(k_lower.endswith(s) for s in ("_max", "_less_than", "_lte", "<="))):
                    num = _coerce_numeric(v)
                    if num is not None:
                        catalog_filters["price_max"] = num
                elif k_lower in ("price_min", "min_price") or (k_lower.startswith("price") and any(k_lower.endswith(s) for s in ("_min", "_greater_than", "_gte", ">="))):
                    num = _coerce_numeric(v)
                    if num is not None:
                        catalog_filters["price_min"] = num
                elif k_lower == "price":
                    num = _coerce_numeric(v)
                    if num is not None:
                        catalog_filters["price_max"] = num
                elif k_lower in ("brand", "make", "manufacturer", "store"):
                    if isinstance(v, list):
                        catalog_filters["brands"] = [str(x).strip() for x in v]
                    else:
                        catalog_filters["brand"] = str(v).strip()
                elif k_lower in ("brands",):
                    if isinstance(v, list):
                        catalog_filters["brands"] = [str(x).strip() for x in v]
                    else:
                        catalog_filters["brand"] = str(v).strip()
                elif k_lower in ("exclude_brand", "exclude_brands", "brand_exclude", "excluded_brand"):
                    catalog_filters["exclude_brand"] = str(v).strip()
                elif k_lower in ("category", "product_category", "product_type", "type"):
                    if isinstance(v, list):
                        catalog_filters["categories"] = [str(x).strip() for x in v]
                    else:
                        catalog_filters["category"] = str(v).strip()
                elif k_lower in ("categories",):
                    if isinstance(v, list):
                        catalog_filters["categories"] = [str(x).strip() for x in v]
                    else:
                        catalog_filters["category"] = str(v).strip()
                elif k_lower in ("exclude_category", "category_exclude", "excluded_category"):
                    catalog_filters["exclude_category"] = str(v).strip()
                elif k_lower in ("excluded_asins", "exclude_asins", "exclude_asin"):
                    catalog_filters["excluded_asins"] = v if isinstance(v, list) else [str(v).strip()]
                else:
                    attr_name = k_lower
                    for suffix in ("_min", "_max", "_equal", "_less_than", "_greater_than", "_exclude", "_exact"):
                        if attr_name.endswith(suffix):
                            attr_name = attr_name[:-len(suffix)]
                            break
                    polarity = -1.0 if "exclude" in k_lower else 1.0
                    val_str = str(int(v)) if isinstance(v, (int, float)) and float(v).is_integer() else str(v).strip()
                    if not val_str or val_str.lower() == "none":
                        continue
                    demoted_from_filters.append({
                        "category": attr_name,
                        "value": val_str,
                        "polarity": polarity,
                        "confidence": 1.0,
                        "evidence": f"Demoted from structured filter key '{k}'",
                    })
                    unit_variations = generate_attribute_unit_variations(attr_name, val_str)
                    for u_val in unit_variations:
                        demoted_from_filters.append({
                            "category": attr_name,
                            "value": u_val,
                            "polarity": polarity,
                            "confidence": 1.0,
                            "evidence": f"Demoted unit variation: {attr_name} {u_val}",
                        })

            # Retrieve soft preferences from session context (including demoted hard constraints)
            soft_preferences: List[Dict[str, Any]] = []
            if session_context:
                soft_preferences.extend(session_context_to_soft_preferences(session_context, include_demoted=True))

            seen_sp = {(sp.get("category", "").lower(), str(sp.get("value", "")).lower(), float(sp.get("polarity", 1.0))) for sp in soft_preferences}
            for d in demoted_from_filters:
                d_key = (d["category"].lower(), d["value"].lower(), float(d.get("polarity", 1.0)))
                if d_key not in seen_sp:
                    seen_sp.add(d_key)
                    soft_preferences.append(d)

            logger.info(f"[STEP 3b] Merged active filters (raw): {active_filters}")
            logger.info(f"[STEP 3b] Catalog-safe filters (Cypher): {catalog_filters}")
            logger.info(f"[STEP 3b] Soft preferences (Additive scoring): {len(soft_preferences)} entries")
            state["active_filters"] = catalog_filters
            
            # Semantic query with fallback to extract_semantic_query
            semantic_query = updates.get("semantic_query")
            if not semantic_query and session_context:
                semantic_query = extract_semantic_query(session_context)
            if not semantic_query:
                semantic_query = user_message

            hyde_product = _normalize_hyde_product(
                updates.get("hyde_product"),
                self._category_from_filters(catalog_filters),
            )
            hyde_review = _normalize_hyde_review(updates.get("hyde_review"))

            logger.info("==============================================")
            logger.info("--- 2. Building Payload for Search Engine ---")
            logger.info("==============================================")
            logger.info(f"📝 Semantic Query (Vector): '{semantic_query}'")
            if hyde_product:
                logger.info(f"📦 HyDE Product (product_embedding_index): '{hyde_product}'")
            if hyde_review:
                logger.info(f"⭐ HyDE Review (review_embedding_index): '{hyde_review}'")
            logger.info(f"🎯 Structured Filters (Cypher): {json.dumps(catalog_filters, indent=2, default=str)}")
                
            # 3c. Search (normalization + Cypher happens inside)
            logger.info("==============================================")
            logger.info("--- 3. Executing Multi-Index Hybrid Search ---")
            logger.info("==============================================")
            search_kwargs: Dict[str, Any] = {
                "semantic_query": semantic_query,
                "structured_filters": catalog_filters,
                "limit": self.candidate_limit,
            }
            masked_reviews = state.get("mask_review_asins")
            try:
                sig = inspect.signature(self.graph_tool.search)
                has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                if "soft_preferences" in sig.parameters or has_var_kw:
                    search_kwargs["soft_preferences"] = soft_preferences
                if masked_reviews and ("mask_review_asins" in sig.parameters or has_var_kw):
                    search_kwargs["mask_review_asins"] = list(masked_reviews)
                if hyde_product and ("hyde_product" in sig.parameters or has_var_kw):
                    search_kwargs["hyde_product"] = hyde_product
                if hyde_review and ("hyde_review" in sig.parameters or has_var_kw):
                    search_kwargs["hyde_review"] = hyde_review
            except Exception:
                search_kwargs["soft_preferences"] = soft_preferences
                if masked_reviews:
                    search_kwargs["mask_review_asins"] = list(masked_reviews)
                if hyde_product:
                    search_kwargs["hyde_product"] = hyde_product
                if hyde_review:
                    search_kwargs["hyde_review"] = hyde_review

            try:
                search_result = self.graph_tool.search(**search_kwargs)
            except TypeError as te:
                if "soft_preferences" in str(te) and "soft_preferences" in search_kwargs:
                    search_kwargs.pop("soft_preferences")
                    search_result = self.graph_tool.search(**search_kwargs)
                else:
                    raise
            # Exact search request, so evaluation can replay it through other fusion arms (R1)
            search_request = dict(search_kwargs)
            items_found = search_result.get('items', [])
            logger.info(f"✅ Search successful! Found {len(items_found)} items.")
            for i, item in enumerate(items_found):
                logger.info(f"\n[{i+1}] {item.get('title')}")
                logger.info(f"    Brand: {item.get('brand')}")
                logger.info(f"    Price: ${item.get('price')}")
                logger.info(f"    Category: {item.get('category')}")
                logger.info(f"    Hybrid Score: {item.get('score', 0):.4f}")
                reasons = item.get("match_reasons")
                if reasons:
                    logger.info("    Match Reasons:")
                    for r in reasons:
                        logger.info(f"      - {r}")
            
            # 3d. Critic Agent Reranking (Context-Aware)
            logger.info("==============================================")
            logger.info("--- 4. Fetching Detailed Attributes & Critic Reranking ---")
            logger.info("==============================================")
            candidates = list(items_found)
            search_result["raw_candidates"] = candidates
            asins = [item.get("asin") for item in candidates if item.get("asin")]
            if masked_reviews:
                try:
                    attr_sig = inspect.signature(self.graph_tool.fetch_product_attributes)
                    if "mask_review_asins" in attr_sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in attr_sig.parameters.values()):
                        attributes_map = self.graph_tool.fetch_product_attributes(asins, mask_review_asins=list(masked_reviews))
                    else:
                        attributes_map = self.graph_tool.fetch_product_attributes(asins)
                except Exception:
                    attributes_map = self.graph_tool.fetch_product_attributes(asins)
            else:
                attributes_map = self.graph_tool.fetch_product_attributes(asins)

            for i, item in enumerate(candidates):
                asin = item.get("asin")
                raw_attrs = attributes_map.get(asin, [])
                if isinstance(raw_attrs, dict):
                    item_attrs = [{"name": k, "value": v, "source": "catalog"} for k, v in raw_attrs.items()]
                elif isinstance(raw_attrs, list):
                    item_attrs = [a if isinstance(a, dict) else {"name": str(a), "value": "", "source": "catalog"} for a in raw_attrs]
                else:
                    item_attrs = []
                technical = [a for a in item_attrs if a.get('source') != 'user_review']
                reviews = [a for a in item_attrs if a.get('source') == 'user_review']
                logger.info(f"\n[{i+1}] {item.get('title')} (ASIN: {asin})")
                if technical:
                    logger.info(f"  Technical Specs ({len(technical)}):")
                    for tech in technical[:5]:
                        logger.info(f"    - {tech.get('name')}: {tech.get('value')}")
                    if len(technical) > 5:
                        logger.info(f"    - ... and {len(technical)-5} more.")
                if reviews:
                    logger.info(f"  User Reviews ({len(reviews)}):")
                    for rev in reviews[:3]:
                        logger.info(f"    - {rev.get('name')}")
            
            # Enrich profile with session persona for Critic Agent
            critic_profile = dict(profile)
            if session_context:
                critic_profile["preferences"] = session_context_to_user_persona(session_context)
            elif soft_preferences:
                critic_profile.setdefault("preferences", {})

            # Ensure any demoted filters from LLM search updates are represented in Critic persona
            if isinstance(critic_profile.get("preferences"), dict):
                prefs_dict = critic_profile["preferences"]

                def _has_quality(qualities: List[Any], val_str: str) -> bool:
                    v_low = val_str.lower()
                    for q in qualities:
                        q_str = str(q).lower()
                        if q_str == v_low or q_str.startswith(f"{v_low} (") or q_str.startswith(f"{v_low} "):
                            return True
                    return False

                for sp in soft_preferences:
                    val = sp.get("value")
                    if val is None or val == "" or str(val).lower() == "none":
                        continue
                    cat = sp.get("category", "")
                    pol = float(sp.get("polarity", 1.0))
                    if pol > 0:
                        desc = f"{val} (category: {cat}, polarity: {pol:+.1f})"
                        if not _has_quality(prefs_dict.get("preferred_qualities", []), str(val)):
                            prefs_dict.setdefault("preferred_qualities", []).append(desc)
                    elif pol < 0:
                        desc = f"{val} (category: {cat}, polarity: {pol:+.1f})"
                        if not _has_quality(prefs_dict.get("disliked_qualities", []), str(val)):
                            prefs_dict.setdefault("disliked_qualities", []).append(desc)
                
            reranked_top = await self.critic_agent.evaluate_candidates(critic_profile, candidates, attributes_map)
            
            fallback_partial_items: List[Dict[str, Any]] = []
            if reranked_top:
                # Replace candidates with the top 3 recommended items from Critic
                search_result["items"] = reranked_top[:3]
                logger.info(f"[STEP 3d] Critic recommendation finished. Approved {len(reranked_top)} / {len(candidates)} candidates.")
            else:
                logger.warning(
                    "[STEP 3d] ⚠️ Critic Agent rejected all candidates (failed constraints or missing requested features). "
                    "Falling back to top-3 RRF partial matches with explicit Critic caveats."
                )
                evaluated_by_asin = {
                    p.get("asin"): p
                    for p in (getattr(self.critic_agent, "last_evaluated_candidates", None) or [])
                    if isinstance(p, dict) and p.get("asin")
                }
                for cand in candidates[:3]:
                    partial_item = dict(cand)
                    partial_item["partial_match"] = True
                    eval_entry = evaluated_by_asin.get(cand.get("asin"))
                    if eval_entry and eval_entry.get("reasoning"):
                        partial_item["critic_reasoning"] = eval_entry["reasoning"]
                    else:
                        partial_item.setdefault(
                            "critic_reasoning",
                            "Candidate did not satisfy all requested technical or review constraints during Critic verification.",
                        )
                    fallback_partial_items.append(partial_item)
                search_result["items"] = fallback_partial_items
                search_result["partial_matches_only"] = True

            # =========================================================================
            # STEP 3d.5: Graph Evidence Path Extraction (template metapaths inspired by KECR/PGPR)
            # =========================================================================
            logger.info("[STEP 3d.5] Extracting Graph Evidence Paths (template metapaths inspired by KECR/PGPR)...")
            extraction_result = self.kecr_tool.extract_paths(
                user_id=user_id,
                candidate_items=search_result["items"],
                session_context=session_context
            )
            graph_reasoning_paths = extraction_result.serialized_evidence_dict
            logger.info(f"[STEP 3d.5] Extracted {len(graph_reasoning_paths)} reasoning paths for {len(search_result['items'])} items.")

            # 3e. Generate final response
            logger.info(f"[STEP 3e] Constructing recommendation prompt...")
            prompt_kwargs: Dict[str, Any] = {
                "user_query": user_message,
                "user_profile": profile,
                "retrieved_items": search_result["items"],
                "preferences": active_filters,
                "graph_reasoning_paths": graph_reasoning_paths,
            }
            relaxed_list = list(search_result.get("relaxed_constraints") or [])
            if relaxed_list:
                try:
                    pc_sig = inspect.signature(self.prompt_constructor.construct_recommendation_prompt)
                    if "relaxed_constraints" in pc_sig.parameters or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in pc_sig.parameters.values()
                    ):
                        prompt_kwargs["relaxed_constraints"] = relaxed_list
                except Exception:
                    prompt_kwargs["relaxed_constraints"] = relaxed_list

            prompt_messages = self.prompt_constructor.construct_recommendation_prompt(**prompt_kwargs)
            
            logger.info(f"[STEP 3e] Querying LLM for final answer...")
            final_answer = await self.llm_handler.aquery(prompt_messages)
            logger.info(f"[STEP 3e] Final answer generated ({len(final_answer)} chars)")
            
            critic_verdict = {
                "status": "success" if reranked_top else "rejected_all",
                "pruned_count": len(candidates) - len(reranked_top),
                "approved_count": len(reranked_top),
                "total_candidates": len(candidates),
                "fallback_partial_count": len(fallback_partial_items),
            }

            result = {
                "answer": final_answer,
                "data": search_result,
                "action": "SEARCH",
                "eval_trace": {
                    "raw_candidates": candidates,
                    "critic_reranked": reranked_top,
                    "fallback_partial_items": fallback_partial_items,
                    "critic_verdict": critic_verdict,
                    "graph_evidence": graph_reasoning_paths,
                    "search_metadata": search_result.get("metadata", {}),
                    "search_request": search_request,
                    # RS-23 attribution (FR-009)
                    "category_resolution": self._resolution_for_trace(state),
                    "clarify_reason": None,
                    "search_params_source": search_params_source,
                    "search_params_fallback": updates.get("param_source") == "fallback",
                    "relaxed_constraints": relaxed_list,
                }
            }

        elif action == "CLARIFY":
            # Generate a clarification question enriched with missing critical attributes if available
            missing_attrs = []
            if session_context:
                missing_attrs = session_context.dialogue_state.missing_critical_attributes
            if missing_attrs:
                prompt = f"The user is looking for a product, but critical details are missing: {', '.join(missing_attrs)}. Ask a polite clarifying question to find out their requirements for {', '.join(missing_attrs)} regarding: {user_message}"
            else:
                prompt = f"The user information is incomplete. Ask a clarifying question to better understand their needs regarding: {user_message}"
            messages = [
                SystemMessage(content="You are a helpful assistant."),
                HumanMessage(content=prompt)
            ]
            clarification = await self.llm_handler.aquery(messages)
            clarify_reason = state.get("clarify_reason") or "router"
            result = {
                "answer": clarification,
                "action": "CLARIFY",
                "eval_trace": {
                    "category_resolution": self._resolution_for_trace(state),
                    "clarify_reason": clarify_reason,
                },
            }

        elif action == "UPDATE_PROFILE":
            # Update profile then answer (or confirm)
            self.profile_tool.update_preferences_from_conversation(user_id, user_message)
            result = {
                "answer": "I've updated your preferences. Is there anything specific you'd like to find now?",
                "action": "UPDATE_PROFILE"
            }

        elif action == "READ_PROFILE":
             # Summarize profile
             answer = f"Based on what you've told me, you like: {json.dumps(profile.get('preferences', {}))}"
             result = {
                 "answer": answer,
                 "action": "READ_PROFILE"
             }

        else: # ANSWER (Default)
            # Chit-chat
            messages = [
                SystemMessage(content="You are a helpful assistant. Respond to the user politely."),
                HumanMessage(content=user_message)
            ]
            answer = await self.llm_handler.aquery(messages)
            result = {
                "answer": answer,
                "action": "ANSWER"
            }
            
        return result

    async def _generate_search_params(self, user_message: str, current_filters: Dict[str, Any], history_text: str = "") -> Dict[str, Any]:
        """
        Uses LLM to generate semantic query and structured filters.

        The result carries `param_source`: "llm" for a parsed response, "fallback" when the call
        failed (exception, unparsable JSON, a non-object payload or an "Error: ..." string from
        SimpleLLMHandler.aquery). The fallback uses the raw message as semantic query, no filters.

        Parsed results always carry the top-level `product_type_decided` exactly as the LLM returned
        it (None when the key is missing). Only `_recover_category` reads it (FR-007a); the SEARCH
        branch merges only `structured_filters`. The fallback result has no `product_type_decided`
        key, and recovery reports it as "error".
        """
        response: Optional[str] = None
        try:
            filters_context = json.dumps(current_filters, indent=2, default=str)
            prompt = f"{SEARCH_GENERATION_PROMPT}\n\n[CONVERSATION HISTORY]\n{history_text}\n\n[ACTIVE FILTERS]\n{filters_context}\n\n[USER MESSAGE]\n{user_message}"
            
            messages = [
                SystemMessage(content="You are a smart search query generator. Output valid JSON only, no comments."),
                HumanMessage(content=prompt)
            ]
            
            response = await self.llm_handler.aquery(messages)
            if not isinstance(response, str):
                raise ValueError(f"LLM returned a non-string response of type {type(response).__name__}")
            if response.strip().startswith("Error:"):
                raise RuntimeError(f"LLM handler reported an error: {response.strip()[:200]}")
            logger.debug(f"Raw LLM response for search params: {response[:300]}")
            cleaned = self._clean_llm_json(response)
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError(f"Search params JSON is a {type(parsed).__name__}, expected an object")
            if not isinstance(parsed.get("structured_filters"), dict):
                parsed["structured_filters"] = {}
            decided = parsed.get("product_type_decided")
            parsed["product_type_decided"] = decided
            if decided is False or (isinstance(decided, str) and decided.strip().lower() == "false"):
                parsed["hyde_product"] = None
                parsed["hyde_review"] = None
            else:
                cat_hint = self._category_from_filters(parsed["structured_filters"]) or self._category_from_filters(current_filters)
                if "hyde_product" in parsed:
                    parsed["hyde_product"] = _normalize_hyde_product(parsed.get("hyde_product"), cat_hint)
                if "hyde_review" in parsed:
                    parsed["hyde_review"] = _normalize_hyde_review(parsed.get("hyde_review"))
            parsed["param_source"] = "llm"
            logger.info(f"Search params parsed successfully")
            return parsed
        except Exception as e:
            logger.error(f"Search Param Generation failed: {e}")
            logger.error(f"Raw LLM response was: {response[:500] if isinstance(response, str) else 'N/A'}")
            # Fallback: Use raw message as semantic query, no filters
            return {
                "semantic_query": user_message,
                "structured_filters": {},
                "param_source": "fallback",
            }

    @staticmethod
    def _category_from_filters(filters: Any) -> Optional[str]:
        """
        First usable category value under CATEGORY_FILTER_KEYS (a string, or the first item of a
        list); None for missing, non-string or NULL_CATEGORY_VALUES (case-insensitive, stripped).
        """
        if not isinstance(filters, dict):
            return None
        for key in CATEGORY_FILTER_KEYS:
            value = filters.get(key)
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            if not isinstance(value, str):
                continue
            cleaned = value.strip()
            if cleaned.lower() in NULL_CATEGORY_VALUES:
                continue
            return cleaned
        return None

    @staticmethod
    def _category_from_hard_constraints(hard_constraints: Any) -> Optional[str]:
        """First usable category value among session-context hard constraints (non-exclude operators)."""
        if not isinstance(hard_constraints, (list, tuple)):
            return None
        for constraint in hard_constraints:
            if not isinstance(constraint, dict):
                continue
            attribute = str(constraint.get("attribute") or "").strip().lower()
            operator = str(constraint.get("operator") or "").strip().lower()
            if attribute not in CATEGORY_FILTER_KEYS or operator == "exclude":
                continue
            value = AgentOrchestrator._category_from_filters({"category": constraint.get("value")})
            if value is not None:
                return value
        return None

    @classmethod
    def _present_category(cls, active_filters: Any, current_context: Any,
                          parser_category: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """
        The category already available before any recovery, with its source: the parser's hard
        constraint first ("parser"), then the active filters ("active_filters", which also carry
        profile and accumulated session filters), then `current_context["category"]`
        ("session_context"). (None, None) when no source has one.
        """
        if parser_category is not None:
            return parser_category, "parser"
        from_filters = cls._category_from_filters(active_filters)
        if from_filters is not None:
            return from_filters, "active_filters"
        if isinstance(current_context, dict):
            from_context = cls._category_from_filters({"category": current_context.get("category")})
            if from_context is not None:
                return from_context, "session_context"
        return None, None

    @staticmethod
    def _search_history_text(state: ConversationState) -> str:
        """History text for _generate_search_params: the last 6 messages before the current one."""
        history_msgs = state["messages"][:-1]
        return "\n".join([f"{type(m).__name__}: {m.content}" for m in history_msgs[-6:]])

    async def _recover_category(self, state: ConversationState) -> Dict[str, Any]:
        """
        RS-23 option C: one _generate_search_params call before the guardrail clarifies. The result
        is stored in state["search_params"] so the SEARCH branch reuses it (no second call).
        The recovered category is not written back into the DialogueManager session (spec §3.4,
        Open Question 4): a later turn without a category recovers again, until AI-07 merges the
        parser and the search-params call into one source of truth.

        Audit H-1 / FR-007a: the recovered category is used only when the same call also returned
        `product_type_decided` as the JSON boolean `true`. Outcomes are checked in the order
        error -> undecided -> null_category -> found:
          - "error": the call raised or fell back (`param_source == "fallback"`).
          - "undecided": the flag is not `True` (false, missing, null, or a non-boolean such as
            "true" or 1); a usable category the call returned is discarded and reported.
          - "null_category": the flag is `True` but there is no usable category.
          - "found": the flag is `True` and a usable category is present.

        Returns:
            {"category": Optional[str],
             "outcome": "found" | "undecided" | "null_category" | "error",
             "product_type_decided": Optional[bool],  # the flag when it is a boolean, else None
             "discarded_category": Optional[str]}     # set only for "undecided"
        """
        user_message = state["messages"][-1].content
        active_filters = state.get("active_filters", {}) or {}
        try:
            params = await self._generate_search_params(user_message, active_filters, self._search_history_text(state))
        except Exception as e:
            logger.error(f"[STEP 2] Category recovery call failed: {e}")
            return {"category": None, "outcome": "error", "product_type_decided": None, "discarded_category": None}
        state["search_params"] = params
        if params.get("param_source") == "fallback":
            return {"category": None, "outcome": "error", "product_type_decided": None, "discarded_category": None}
        raw_flag = params.get("product_type_decided")
        flag: Optional[bool] = raw_flag if isinstance(raw_flag, bool) else None
        category = self._category_from_filters(params.get("structured_filters"))
        if raw_flag is not True:
            return {"category": None, "outcome": "undecided", "product_type_decided": flag,
                    "discarded_category": category}
        if category is None:
            return {"category": None, "outcome": "null_category", "product_type_decided": True,
                    "discarded_category": None}
        return {"category": category, "outcome": "found", "product_type_decided": True,
                "discarded_category": None}

    @staticmethod
    def _resolution_for_trace(state: ConversationState) -> Dict[str, Any]:
        """Copy of state["category_resolution"] for eval_trace, with the full key set even if routing was skipped."""
        resolution = state.get("category_resolution") or {}
        return {
            "parser_category": resolution.get("parser_category"),
            "category": resolution.get("category"),
            "source": resolution.get("source"),
            "guardrail_triggered": bool(resolution.get("guardrail_triggered", False)),
            "recovery_attempted": bool(resolution.get("recovery_attempted", False)),
            "recovery_outcome": resolution.get("recovery_outcome"),
            "recovery_product_type_decided": resolution.get("recovery_product_type_decided"),
            "recovery_discarded_category": resolution.get("recovery_discarded_category"),
        }

    @staticmethod
    def _clean_llm_json(raw: str) -> str:
        """Clean LLM output to produce valid JSON (strip markdown, comments, trailing commas)."""
        import re
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        # Remove single-line JS comments (// ...)
        cleaned = re.sub(r'//[^\n]*', '', cleaned)
        # Remove trailing commas before } or ]
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
        return cleaned

    def get_session_context(self, session_id: str) -> CurrentSessionContextWrapper:
        """Direct accessor to dialogue manager session wrapper."""
        return self.dialogue_manager.get_wrapper(session_id)

    def reset_session(self, session_id: str) -> None:
        """Reset dialogue state for a given session/user."""
        self.dialogue_manager.reset_session(session_id)

