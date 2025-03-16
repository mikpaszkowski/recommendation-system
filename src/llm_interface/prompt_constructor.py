from typing import Dict, List, Any, Optional
import json

class PromptConstructor:
    """
    Constructs prompts for LLM integration with the recommendation system.
    """
    
    def __init__(self, system_instruction: Optional[str] = None):
        """
        Initialize the prompt constructor.
        
        Args:
            system_instruction: Optional custom system instruction
        """
        self.system_instruction = system_instruction or self._default_system_instruction()
        
    def _default_system_instruction(self) -> str:
        """
        Default system instruction for the recommendation assistant.
        
        Returns:
            Default system instruction
        """
        return """You are a helpful recommendation assistant that helps users find products they might enjoy.
Your goal is to understand user preferences and provide personalized recommendations.
Follow these steps when responding to users:
1. Analyze the user's input to identify explicit preferences
2. Integrate with user profile and conversation context
3. Match against candidate items
4. Rank options based on match quality
5. Generate explanation for recommendations"""
    
    def construct_recommendation_prompt(self,
                                      user_query: str,
                                      user_profile: Optional[Dict[str, Any]] = None,
                                      conversation_history: Optional[List[Dict[str, str]]] = None,
                                      retrieved_items: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Construct a prompt for generating recommendations.
        
        Args:
            user_query: Current user query
            user_profile: Optional user profile information
            conversation_history: Optional conversation history
            retrieved_items: Optional list of retrieved items
            
        Returns:
            Constructed prompt
        """
        prompt_parts = []
        
        # Add system instruction
        prompt_parts.append(f"[SYSTEM]\n{self.system_instruction}\n")
        
        # Add user profile if available
        if user_profile:
            profile_text = self._format_user_profile(user_profile)
            prompt_parts.append(f"[USER PROFILE]\n{profile_text}\n")
        
        # Add conversation history if available
        if conversation_history:
            history_text = self._format_conversation_history(conversation_history)
            prompt_parts.append(f"[CONVERSATION HISTORY]\n{history_text}\n")
        
        # Add retrieved items if available
        if retrieved_items:
            items_text = self._format_retrieved_items(retrieved_items)
            prompt_parts.append(f"[RETRIEVED ITEMS]\n{items_text}\n")
        
        # Add reasoning process
        prompt_parts.append(self._get_reasoning_process())
        
        # Add current user query
        prompt_parts.append(f"[CURRENT USER REQUEST]\n{user_query}\n")
        
        return "\n".join(prompt_parts)
    
    def _format_user_profile(self, user_profile: Dict[str, Any]) -> str:
        """
        Format user profile for inclusion in the prompt.
        
        Args:
            user_profile: User profile information
            
        Returns:
            Formatted user profile text
        """
        profile_parts = []
        
        if "preferences" in user_profile:
            prefs = user_profile["preferences"]
            profile_parts.append("User preferences:")
            for category, values in prefs.items():
                if isinstance(values, list):
                    profile_parts.append(f"- {category}: {', '.join(values)}")
                else:
                    profile_parts.append(f"- {category}: {values}")
        
        if "history" in user_profile:
            history = user_profile["history"]
            profile_parts.append("\nPreviously interacted with:")
            for item in history[:5]:  # Limit to 5 items
                profile_parts.append(f"- {item.get('product_title', 'Unknown product')}")
        
        return "\n".join(profile_parts)
    
    def _format_conversation_history(self, conversation_history: List[Dict[str, str]]) -> str:
        """
        Format conversation history for inclusion in the prompt.
        
        Args:
            conversation_history: List of conversation turns
            
        Returns:
            Formatted conversation history text
        """
        history_parts = []
        
        for turn in conversation_history[-5:]:  # Limit to last 5 turns
            if "user" in turn:
                history_parts.append(f"User: {turn['user']}")
            if "assistant" in turn:
                history_parts.append(f"Assistant: {turn['assistant']}")
        
        return "\n".join(history_parts)
    
    def _format_retrieved_items(self, retrieved_items: List[Dict[str, Any]]) -> str:
        """
        Format retrieved items for inclusion in the prompt.
        
        Args:
            retrieved_items: List of retrieved items
            
        Returns:
            Formatted retrieved items text
        """
        items_parts = []
        
        for i, item in enumerate(retrieved_items, 1):
            items_parts.append(f"Item {i}:")
            items_parts.append(f"- Title: {item.get('product_title', 'Unknown')}")
            items_parts.append(f"- Category: {item.get('category', 'Unknown')}")
            items_parts.append(f"- Brand: {item.get('brand', 'Unknown')}")
            items_parts.append(f"- Price: ${item.get('price', 'Unknown')}")
            items_parts.append(f"- Rating: {item.get('rating', 'Unknown')}/5.0")
            items_parts.append(f"- Features: {item.get('features', 'None specified')}")
            items_parts.append(f"- Match score: {item.get('score', 0):.2f}")
            items_parts.append("")
        
        return "\n".join(items_parts)
    
    def _get_reasoning_process(self) -> str:
        """
        Get the reasoning process section for the prompt.
        
        Returns:
            Reasoning process text
        """
        return """[REASONING PROCESS]
Follow these steps to recommend:
1. Analyze the user's input to identify explicit preferences
   - What specific product attributes are they looking for?
   - What constraints or requirements have they mentioned?

2. Integrate with user profile and conversation context
   - How do their current preferences relate to their profile?
   - What have they liked or disliked in previous interactions?

3. Match against candidate items
   - Which items best match their stated preferences?
   - Which items match their implicit preferences from their profile?

4. Rank options based on match quality
   - Which items have the highest overall match score?
   - Consider both explicit and implicit preferences in ranking

5. Generate explanation for recommendations
   - Explain why each item was recommended
   - Connect recommendations to specific user preferences
   - Highlight key features that match their requirements
"""
    
    def construct_explanation_prompt(self,
                                   user_id: str,
                                   item: Dict[str, Any],
                                   user_profile: Optional[Dict[str, Any]] = None) -> str:
        """
        Construct a prompt for generating an explanation for a recommendation.
        
        Args:
            user_id: User identifier
            item: Item to explain
            user_profile: Optional user profile information
            
        Returns:
            Constructed prompt
        """
        prompt_parts = []
        
        # Add system instruction
        prompt_parts.append(f"[SYSTEM]\nYou are a helpful recommendation assistant. Your task is to explain why a specific item was recommended to a user in a natural, conversational way.\n")
        
        # Add user profile if available
        if user_profile:
            profile_text = self._format_user_profile(user_profile)
            prompt_parts.append(f"[USER PROFILE]\n{profile_text}\n")
        
        # Add item information
        item_text = self._format_item_for_explanation(item)
        prompt_parts.append(f"[ITEM INFORMATION]\n{item_text}\n")
        
        # Add explanation instruction
        prompt_parts.append(f"[TASK]\nExplain why this item was recommended to the user. Focus on matching the item's features with the user's preferences. Make the explanation conversational and helpful.\n")
        
        return "\n".join(prompt_parts)
    
    def _format_item_for_explanation(self, item: Dict[str, Any]) -> str:
        """
        Format item information for explanation prompt.
        
        Args:
            item: Item information
            
        Returns:
            Formatted item text
        """
        item_parts = []
        
        item_parts.append(f"Title: {item.get('product_title', 'Unknown')}")
        item_parts.append(f"Category: {item.get('category', 'Unknown')}")
        item_parts.append(f"Brand: {item.get('brand', 'Unknown')}")
        item_parts.append(f"Price: ${item.get('price', 'Unknown')}")
        item_parts.append(f"Rating: {item.get('rating', 'Unknown')}/5.0")
        item_parts.append(f"Features: {item.get('features', 'None specified')}")
        
        if "description" in item:
            item_parts.append(f"\nDescription: {item['description']}")
        
        return "\n".join(item_parts) 