import json
import logging
import asyncio
from typing import Dict, Any, List, Optional

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
    hard_constraints_to_structured_filters,
    session_context_to_structured_filters,
    session_context_to_dialogue_action,
    session_context_to_user_persona,
    extract_semantic_query,
)
from src.dialog_manager.session_schema import SessionContext, CurrentSessionContextWrapper
from src.llm_interface.preference_parser import LLMPreferenceParser
from src.tools.kecr_tool import KnowledgePathExtractor

logger = logging.getLogger(__name__)

SEARCH_GENERATION_PROMPT = """
YOUR GOAL: Help the user find the perfect product by translating their request into search arguments.

[CONTEXT]
You are given the user's CURRENT MESSAGE, the CONVERSATION HISTORY, and the currently ACTIVE FILTERS.

[TASK]
1. Analyze if the user is MODIFYING existing filters, ADDING new ones, or STARTING OVER.
2. Generate a JSON containing the *updates* to the filters and a semantic query.

[OUTPUT FORMAT (JSON)]
{
  "thought": "Reasoning about what changed.",
  "structured_filters": { 
     "brand": "Samsung",  // specific constraint
     "price_max": 2000, 
     "category": "laptop"
  },
  "semantic_query": "high performance gaming...", // abstract visualization of the product
  "_thinking": "Detailed step-by-step reasoning"
}

[RULES]
- If user says "actually under 1500", UPDATE `price_max` to 150.
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
                 candidate_limit: int = 20):
        
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
        
    async def run(self, user_id: str, user_message: str, session_id: Optional[str] = None) -> Dict[str, Any]:
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
            "active_filters": active_filters
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

            extracted_hard = current_context.get("extracted_parameters", {}).get("hard_constraints", []) if isinstance(current_context, dict) else []
            has_category = bool(
                active_filters.get("category")
                or current_context.get("category")
                or any(
                    isinstance(c, dict) and c.get("attribute") == "category"
                    for c in extracted_hard
                )
            )
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
            elif action == "SEARCH" and not ready and missing:
                # Only clarify if truly critical attributes (e.g. completely missing category) are absent
                if "category" in missing:
                    logger.info(f"Guardrail: Critical category missing. Switching SEARCH -> CLARIFY.")
                    action = "CLARIFY"
                    reasoning = f"Missing critical category ({', '.join(missing)}). Clarification required before searching."

            return action, reasoning
        except Exception as e:
            logger.error(f"Router JSON parse error: {e}. Falling back to dialogue action '{suggested_action}'.")
            return suggested_action, f"Fallback to dialogue action due to error: {e}"

    async def _execute_step(self, user_id: str, state: ConversationState, session_context: Optional[SessionContext] = None) -> Dict[str, Any]:
        """Executes the determined action."""
        action = state["next_step"]
        user_message = state["messages"][-1].content
        profile = state.get("user_profile", {})
        active_filters = state.get("active_filters", {})
        
        # Helper to get history text
        history_msgs = state["messages"][:-1]
        history_text = "\n".join([f"{type(m).__name__}: {m.content}" for m in history_msgs[-6:]])
        
        result = {}
        
        if action == "SEARCH":
            # 3a. Generate Hybrid Search Parameters (Merging with Active Filters)
            logger.info(f"[STEP 3a] Generating search params via LLM...")
            updates = await self._generate_search_params(user_message, active_filters, history_text)
            logger.info(f"[STEP 3a] LLM returned:")
            logger.info(f"  - semantic_query: '{updates.get('semantic_query', '')}'")
            logger.info(f"  - structured_filters: {updates.get('structured_filters', {})}")
            logger.info(f"  - thought: {updates.get('thought', 'N/A')}")
            
            # 3b. Merge updates into active_filters
            new_filters = updates.get("structured_filters", {})
            for k, v in new_filters.items():
                active_filters[k] = v
                
            if session_context:
                session_filters = session_context_to_structured_filters(session_context)
                for k, v in session_filters.items():
                    if k not in active_filters or active_filters[k] is None:
                        active_filters[k] = v
            
            logger.info(f"[STEP 3b] Merged active filters: {active_filters}")
            state["active_filters"] = active_filters
            
            # Semantic query with fallback to extract_semantic_query
            semantic_query = updates.get("semantic_query")
            if not semantic_query and session_context:
                semantic_query = extract_semantic_query(session_context)
            if not semantic_query:
                semantic_query = user_message

            logger.info("==============================================")
            logger.info("--- 2. Building Payload for Search Engine ---")
            logger.info("==============================================")
            logger.info(f"📝 Semantic Query (Vector): '{semantic_query}'")
            logger.info(f"🎯 Structured Filters (Cypher): {json.dumps(active_filters, indent=2, default=str)}")
                
            # 3c. Search (normalization + Cypher happens inside)
            logger.info("==============================================")
            logger.info("--- 3. Executing Multi-Index Hybrid Search ---")
            logger.info("==============================================")
            search_result = self.graph_tool.search(
                semantic_query=semantic_query,
                structured_filters=active_filters,
                limit=self.candidate_limit
            )
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
                
            reranked_top = await self.critic_agent.evaluate_candidates(critic_profile, candidates, attributes_map)
            
            # Replace candidates with the top 3 recommended items from Critic
            search_result["items"] = reranked_top[:3]
            logger.info(f"[STEP 3d] Critic recommendation finished. Approved {len(reranked_top)} / {len(candidates)} candidates.")
            if not reranked_top:
                logger.warning("[STEP 3d] ⚠️ Critic Agent rejected all candidates (failed constraints or missing requested features).")

            # =========================================================================
            # STEP 3d.5: Phase A4 Knowledge-Enhanced Reasoning Path Extraction (KECR)
            # =========================================================================
            logger.info(f"[STEP 3d.5] Extracting Knowledge-Enhanced Reasoning Paths (KECR)...")
            extraction_result = self.kecr_tool.extract_paths(
                user_id=user_id,
                candidate_items=search_result["items"],
                session_context=session_context
            )
            graph_reasoning_paths = extraction_result.serialized_evidence_dict
            logger.info(f"[STEP 3d.5] Extracted {len(graph_reasoning_paths)} reasoning paths for {len(search_result['items'])} items.")

            # 3e. Generate final response
            logger.info(f"[STEP 3e] Constructing recommendation prompt...")
            prompt_messages = self.prompt_constructor.construct_recommendation_prompt(
                user_query=user_message,
                user_profile=profile,
                retrieved_items=search_result["items"],
                preferences=active_filters,
                graph_reasoning_paths=graph_reasoning_paths
            )
            
            logger.info(f"[STEP 3e] Querying LLM for final answer...")
            final_answer = await self.llm_handler.aquery(prompt_messages)
            logger.info(f"[STEP 3e] Final answer generated ({len(final_answer)} chars)")
            
            critic_verdict = {
                "status": "success" if reranked_top else "rejected_all",
                "pruned_count": len(candidates) - len(reranked_top),
                "approved_count": len(reranked_top),
                "total_candidates": len(candidates)
            }

            result = {
                "answer": final_answer,
                "data": search_result,
                "action": "SEARCH",
                "eval_trace": {
                    "raw_candidates": candidates,
                    "critic_reranked": reranked_top,
                    "critic_verdict": critic_verdict,
                    "graph_evidence": graph_reasoning_paths,
                    "search_metadata": search_result.get("metadata", {})
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
            result = {
                "answer": clarification,
                "action": "CLARIFY"
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
        """Uses LLM to generate semantic query and structured filters."""
        try:
            filters_context = json.dumps(current_filters, indent=2, default=str)
            prompt = f"{SEARCH_GENERATION_PROMPT}\n\n[CONVERSATION HISTORY]\n{history_text}\n\n[ACTIVE FILTERS]\n{filters_context}\n\n[USER MESSAGE]\n{user_message}"
            
            messages = [
                SystemMessage(content="You are a smart search query generator. Output valid JSON only, no comments."),
                HumanMessage(content=prompt)
            ]
            
            response = await self.llm_handler.aquery(messages)
            logger.debug(f"Raw LLM response for search params: {response[:300]}")
            cleaned = self._clean_llm_json(response)
            parsed = json.loads(cleaned)
            logger.info(f"Search params parsed successfully")
            return parsed
        except Exception as e:
            logger.error(f"Search Param Generation failed: {e}")
            logger.error(f"Raw LLM response was: {response[:500] if 'response' in dir() else 'N/A'}")
            # Fallback: Use raw message as semantic query, no filters
            return {
                "semantic_query": user_message,
                "structured_filters": {}
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

