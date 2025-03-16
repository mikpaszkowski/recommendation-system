import os
import sys
import json
import requests
from typing import Dict, List, Any, Optional

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set your LLM API key here
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

# API endpoint for the recommendation service
RECOMMENDATION_API_URL = "http://localhost:8000"

class LLMIntegration:
    """
    Integration with an LLM service for conversational recommendations.
    This example uses a generic LLM API interface that can be adapted to different providers.
    """
    
    def __init__(self, api_key: str = LLM_API_KEY, api_url: str = RECOMMENDATION_API_URL):
        """
        Initialize the LLM integration.
        
        Args:
            api_key: API key for the LLM service
            api_url: URL for the recommendation API
        """
        self.api_key = api_key
        self.api_url = api_url
        
        # Check if API key is set
        if not self.api_key:
            print("Warning: LLM API key not set. Please set the LLM_API_KEY environment variable.")
    
    def process_user_message(self, user_id: str, user_message: str) -> str:
        """
        Process a user message and generate a response using the LLM.
        
        Args:
            user_id: User identifier
            user_message: User message
            
        Returns:
            LLM-generated response
        """
        # Get recommendations from the API
        recommendations_response = self._get_recommendations(user_id, user_message)
        
        if not recommendations_response:
            return "I'm sorry, I couldn't process your request at this time."
        
        # Extract the prompt for the LLM
        prompt = recommendations_response.get("prompt", "")
        
        # Generate response using the LLM
        llm_response = self._generate_llm_response(prompt)
        
        # Update conversation history
        self._update_conversation(user_id, user_message, llm_response)
        
        return llm_response
    
    def _get_recommendations(self, user_id: str, query: str) -> Dict[str, Any]:
        """
        Get recommendations from the API.
        
        Args:
            user_id: User identifier
            query: User query
            
        Returns:
            API response
        """
        try:
            response = requests.post(
                f"{self.api_url}/recommend",
                json={
                    "user_id": user_id,
                    "query": query,
                    "num_recommendations": 5
                }
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error getting recommendations: {response.text}")
                return {}
        except Exception as e:
            print(f"Error calling recommendation API: {str(e)}")
            return {}
    
    def _generate_llm_response(self, prompt: str) -> str:
        """
        Generate a response using the LLM.
        This is a placeholder that should be replaced with actual LLM API calls.
        
        Args:
            prompt: Prompt for the LLM
            
        Returns:
            LLM-generated response
        """
        # This is a placeholder for the actual LLM API call
        # In a real implementation, you would call your LLM API here
        
        if not self.api_key:
            # Return a mock response if no API key is set
            return "Based on your preferences, I recommend the following items: [mock recommendations]"
        
        try:
            # Example implementation for OpenAI API
            # Replace this with your actual LLM API implementation
            import openai
            openai.api_key = self.api_key
            
            response = openai.Completion.create(
                model="gpt-3.5-turbo-instruct",
                prompt=prompt,
                max_tokens=300,
                temperature=0.3
            )
            
            return response.choices[0].text.strip()
        except Exception as e:
            print(f"Error generating LLM response: {str(e)}")
            return "I'm sorry, I couldn't generate a response at this time."
    
    def _update_conversation(self, user_id: str, user_message: str, assistant_message: str) -> None:
        """
        Update conversation history in the recommendation API.
        
        Args:
            user_id: User identifier
            user_message: User message
            assistant_message: Assistant message
        """
        try:
            response = requests.post(
                f"{self.api_url}/update_conversation",
                json={
                    "user_id": user_id,
                    "user_message": user_message,
                    "assistant_message": assistant_message
                }
            )
            
            if response.status_code != 200:
                print(f"Error updating conversation: {response.text}")
        except Exception as e:
            print(f"Error calling update_conversation API: {str(e)}")

def main():
    """
    Main function to demonstrate the LLM integration.
    """
    # Initialize the LLM integration
    llm_integration = LLMIntegration()
    
    # Example conversation
    user_id = "user_123"
    
    # First user message
    user_message = "I'm looking for items under $50 with good ratings"
    print(f"User: {user_message}")
    
    # Process user message
    assistant_response = llm_integration.process_user_message(user_id, user_message)
    print(f"Assistant: {assistant_response}")
    
    # Second user message
    user_message = "Do you have anything with better features?"
    print(f"User: {user_message}")
    
    # Process user message
    assistant_response = llm_integration.process_user_message(user_id, user_message)
    print(f"Assistant: {assistant_response}")

if __name__ == "__main__":
    main() 