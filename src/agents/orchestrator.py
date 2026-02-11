import json
import logging
from typing import Dict, Any, List, Optional

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from src.agents.state import ConversationState
from src.tools.graph_search_tool import GraphSearchTool
from src.tools.profile_tool import ProfileTool
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm_interface.prompts.router_prompt import router_prompt_template
from src.llm_interface.prompt_constructor import PromptConstructor

logger = logging.getLogger(__name__)

class AgentOrchestrator:
    """
    Main Orchestrator for the Multi-Agent Recommendation System.
    Implements a Router/State Machine pattern.
    """
    
    def __init__(self, 
                 graph_tool: Optional[GraphSearchTool] = None,
                 profile_tool: Optional[ProfileTool] = None,
                 llm_handler: Optional[SimpleLLMHandler] = None):
        
        self.graph_tool = graph_tool or GraphSearchTool()
        self.profile_tool = profile_tool or ProfileTool()
        self.llm_handler = llm_handler or SimpleLLMHandler()
        self.prompt_constructor = PromptConstructor()
        
    def run(self, user_id: str, user_message: str) -> Dict[str, Any]:
        """
        Main entry point for the agent conversation loop.
        """
        logger.info(f"AgentOrchestrator: Processing message from {user_id}: {user_message}")
        
        # 1. Initialize State
        state = self._initialize_state(user_id, user_message)
        
        # 2. Router Step: Decide next action
        next_action, reasoning = self._decide_next_step(state)
        logger.info(f"AgentOrchestrator: Router decision -> {next_action} ({reasoning})")
        state["next_step"] = next_action
        
        # 3. Execution Step
        response_payload = self._execute_step(user_id, state)
        
        return response_payload

    def _initialize_state(self, user_id: str, user_message: str) -> ConversationState:
        """Loads history and profile to build the initial state."""
        profile = self.profile_tool.get_profile(user_id)
        # History is managed by ProfileManager implicitly in this setup, 
        # or we might need a HistoryManager.
        # For now, let's assume we pull history from profile["history"] or similar if needed,
        # but the tools might handle history themselves or we pass it.
        # The prompt constructor manages history formatting usually.
        # We will retrieve history from the profile manager's history link if available, 
        # or we might need to inject HistoryManager here too.
        
        # NOTE: In strict MA, orchestrator holds state. Here we are adapting legacy.
        # We will pass the profile which contains "history" (interaction history) 
        # but for conversation history (messages), we might need to fetch it.
        # Let's use the ProfileTool for now or assume HistoryManager is used outside/inside.
        # Actually, `preference_agent_flow` had `history_manager`. We should probably utilize it.
        # For this step, I will stick to what `ProfileTool` and `GraphSearchTool` need.
        
        return {
            "messages": [HumanMessage(content=user_message)],
            "next_step": None,
            "current_context": {},
            "user_profile": profile
        }

    def _decide_next_step(self, state: ConversationState) -> tuple[str, str]:
        """Uses LLM to classify intent and pick the next step."""
        user_message = state["messages"][-1].content
        profile = state.get("user_profile", {})
        
        history_text = "No recent history." # Placeholder
        
        prompt = router_prompt_template.format(
            history=history_text,
            user_profile=json.dumps(profile.get("preferences", {}), indent=2),
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
        
        result = {}
        
        if action == "SEARCH":
            # 1. Extract recent prefs
            raw_prefs = self.profile_tool.parser.extract_preferences(user_message)
            formatted_prefs = self.profile_tool.parser.format_for_recommender(raw_prefs)
            quantified_prefs = self.profile_tool.quantifier.quantify(formatted_prefs)
            
            # 2. Search
            search_result = self.graph_tool.search(
                query=user_message,
                preferences=quantified_prefs,
                user_profile=profile
            )
            
            # 3. Generate Response
            prompt_messages = self.prompt_constructor.construct_recommendation_prompt(
                user_query=user_message,
                user_profile=profile,
                retrieved_items=search_result.get("items", []),
                preferences=quantified_prefs
            )
            
            final_answer = self.llm_handler.query(prompt_messages)
            
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
