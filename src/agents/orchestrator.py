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
                 critic_agent: Optional[CriticAgent] = None):
        
        self.graph_tool = graph_tool or GraphSearchTool()
        self.profile_tool = profile_tool or ProfileTool()
        self.llm_handler = llm_handler or SimpleLLMHandler()
        self.history_manager = history_manager or InMemoryHistoryManager()
        self.prompt_constructor = PromptConstructor()
        self.critic_agent = critic_agent or CriticAgent(llm_handler=self.llm_handler)
        
    def run(self, user_id: str, user_message: str) -> Dict[str, Any]:
        """
        Main entry point for the agent conversation loop.
        """
        logger.info(f"{'='*60}")
        logger.info(f"[STEP 0] New request from user={user_id}")
        logger.info(f"[STEP 0] Message: '{user_message}'")
        
        # 1. Initialize State
        state = self._initialize_state(user_id, user_message)
        logger.info(f"[STEP 1] State initialized")
        logger.info(f"  - History turns loaded: {len(state['messages']) - 1}")
        logger.info(f"  - Active filters from profile: {state.get('active_filters', {})}")
        logger.info(f"  - User profile keys: {list(state.get('user_profile', {}).keys())}")
        
        # 2. Router Step: Decide next action
        next_action, reasoning = self._decide_next_step(state)
        logger.info(f"[STEP 2] Router decision: {next_action}")
        logger.info(f"  - Reasoning: {reasoning}")
        state["next_step"] = next_action
        
        # 3. Execution Step
        logger.info(f"[STEP 3] Executing action: {next_action}")
        response_payload = self._execute_step(user_id, state)
        
        # 4. Save History (Post-Execution)
        agent_answer = response_payload.get("answer", "")
        self.history_manager.add_turn(user_id, user_message, agent_answer)
        logger.info(f"[STEP 4] History saved. Answer length: {len(agent_answer)} chars")
        logger.info(f"{'='*60}")
        
        return response_payload

    def _initialize_state(self, user_id: str, user_message: str) -> ConversationState:
        """Loads history and profile to build the initial state."""
        profile = self.profile_tool.get_profile(user_id)
        
        # Load persistent preferences as starting active filters if not present?
        # For now, we assume active_filters are effectively the session's working memory of constraints.
        # We initialize them from the user's permanent preferences.
        active_filters = profile.get("preferences", {}).copy()
        
        # NOTE: In a real persistent state system (e.g. Redis), we would load the specific 
        # 'session_state' here which might differ from long-term 'profile'.
        # For this MVP, we re-initialize from profile.
        
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
            "current_context": {},
            "user_profile": profile,
            "active_filters": active_filters
        }

    def _decide_next_step(self, state: ConversationState) -> tuple[str, str]:
        """Uses LLM to classify intent and pick the next step."""
        user_message = state["messages"][-1].content
        profile = state.get("user_profile", {})
        active_filters = state.get("active_filters", {})
        
        # Format history for prompt
        # We take the last 5 turns (excluding current)
        history_msgs = state["messages"][:-1]
        recent_history = history_msgs[-10:] # Last 5 turns (User+AI)
        history_text = "\n".join([f"{type(m).__name__}: {m.content}" for m in recent_history])
        if not history_text:
            history_text = "No recent history."
        
        prompt = router_prompt_template.format(
            history=history_text,
            user_profile=json.dumps(profile.get("preferences", {}), indent=2),
            active_filters=json.dumps(active_filters, indent=2),
            user_message=user_message
        )
        
        try:
            # Construct messages for the router
            messages = [HumanMessage(content=prompt)]
            response = self.llm_handler.query(messages)
            
            # Expecting JSON
            cleaned = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
            return data.get("action", "ANSWER"), data.get("reasoning", "")
        except Exception as e:
            logger.error(f"Router JSON parse error: {e}")
            # Fallback
            return "ANSWER", "Fallback due to error"

    def _execute_step(self, user_id: str, state: ConversationState) -> Dict[str, Any]:
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
            updates = self._generate_search_params(user_message, active_filters, history_text)
            logger.info(f"[STEP 3a] LLM returned:")
            logger.info(f"  - semantic_query: '{updates.get('semantic_query', '')}'")
            logger.info(f"  - structured_filters: {updates.get('structured_filters', {})}")
            logger.info(f"  - thought: {updates.get('thought', 'N/A')}")
            
            # 3b. Merge updates into active_filters
            new_filters = updates.get("structured_filters", {})
            for k, v in new_filters.items():
                active_filters[k] = v
            
            logger.info(f"[STEP 3b] Merged active filters: {active_filters}")
            state["active_filters"] = active_filters
            
            # 3c. Search (normalization + Cypher happens inside)
            logger.info(f"[STEP 3c] Calling GraphSearchTool.search()...")
            search_result = self.graph_tool.search(
                semantic_query=updates.get("semantic_query"),
                structured_filters=active_filters,
                limit=5
            )
            logger.info(f"[STEP 3c] Search result: strategy={search_result.get('strategy')}, count={search_result.get('count')}")
            if search_result.get('items'):
                for i, item in enumerate(search_result['items'][:3]):
                    logger.info(f"  - Item {i+1}: {item.get('title', '?')[:60]} | price={item.get('price')} | score={item.get('score', 0):.3f}")
            
            # 3d. Critic Agent Reranking (Context-Aware)
            logger.info(f"[STEP 3d] Fetching attributes and running Critic Agent for Contextual Reranking...")
            candidates = search_result.get("items", [])
            asins = [item.get("asin") for item in candidates if item.get("asin")]
            attributes_map = self.graph_tool.fetch_product_attributes(asins)
            
            # Use asyncio block for the async critic agent
            # Create a new event loop if needed, or use asyncio.run 
            # (Note: depending on UI framework, this might need an 'await' throughout if Orchestrator was async)
            try:
                 loop = asyncio.get_event_loop()
            except RuntimeError:
                 loop = asyncio.new_event_loop()
                 asyncio.set_event_loop(loop)
                 
            # Note: _execute_step is synchronous, so we use loop.run_until_complete
            reranked_top = loop.run_until_complete(
                self.critic_agent.evaluate_candidates(profile, candidates, attributes_map)
            )
            
            # Replace candidates with the top 3 recommended items from Critic
            search_result["items"] = reranked_top[:3]
            logger.info(f"[STEP 3d] Critic recommendation finished. Top items: {len(search_result['items'])}")

            # 3e. Generate final response
            logger.info(f"[STEP 3e] Constructing recommendation prompt...")
            prompt_messages = self.prompt_constructor.construct_recommendation_prompt(
                user_query=user_message,
                user_profile=profile,
                retrieved_items=search_result["items"],
                preferences=active_filters
            )
            
            logger.info(f"[STEP 3e] Querying LLM for final answer...")
            final_answer = self.llm_handler.query(prompt_messages)
            logger.info(f"[STEP 3e] Final answer generated ({len(final_answer)} chars)")
            
            result = {
                "answer": final_answer,
                "data": search_result,
                "action": "SEARCH"
            }

        elif action == "CLARIFY":
            # Generate a clarification question
            prompt = f"The user information is incomplete. Ask a clarifying question to better understand their needs regarding: {user_message}"
            messages = [
                SystemMessage(content="You are a helpful assistant."),
                HumanMessage(content=prompt)
            ]
            clarification = self.llm_handler.query(messages)
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
            answer = self.llm_handler.query(messages)
            result = {
                "answer": answer,
                "action": "ANSWER"
            }
            
        return result

    def _generate_search_params(self, user_message: str, current_filters: Dict[str, Any], history_text: str = "") -> Dict[str, Any]:
        """Uses LLM to generate semantic query and structured filters."""
        try:
            filters_context = json.dumps(current_filters, indent=2)
            prompt = f"{SEARCH_GENERATION_PROMPT}\n\n[CONVERSATION HISTORY]\n{history_text}\n\n[ACTIVE FILTERS]\n{filters_context}\n\n[USER MESSAGE]\n{user_message}"
            
            messages = [
                SystemMessage(content="You are a smart search query generator. Output valid JSON only, no comments."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm_handler.query(messages)
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
