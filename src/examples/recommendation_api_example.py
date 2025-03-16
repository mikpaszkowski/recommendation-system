import os
import sys
import pandas as pd
import numpy as np
import joblib
import json

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recommendation_engine.lightfm_recommender import LightFMRecommender
from llm_interface.preference_parser import PreferenceParser
from llm_interface.prompt_constructor import PromptConstructor
from llm_interface.recommendation_api import RecommendationAPI
from utils.data_preprocess import load_preprocessed_data

def main():
    """
    Main function to demonstrate the LLM-Compatible Recommendation API.
    """
    print("Loading preprocessed data...")
    try:
        interactions, user_id_map, item_id_map, item_data = load_preprocessed_data()
    except Exception as e:
        print(f"Error loading preprocessed data: {str(e)}")
        print("Please run the data preprocessing script first.")
        return
    
    print("Creating LightFM recommender...")
    # Create LightFM recommender
    recommender = LightFMRecommender(
        model_path="lightfm_model.pkl",
        interactions_data=interactions,
        user_id_map=user_id_map,
        item_id_map=item_id_map,
        item_data=item_data
    )
    
    print("Creating recommendation API...")
    # Create recommendation API
    recommendation_api = RecommendationAPI(
        recommender=recommender
    )
    
    # Simulate a conversation
    user_id = list(user_id_map.keys())[0]  # Use the first user from the dataset
    
    print("\n--- Conversation Simulation ---\n")
    
    # First user query
    user_query = "I'm looking for items under $50 with good ratings"
    print(f"User: {user_query}")
    
    # Process query
    result = recommendation_api.process_query(
        user_id=str(user_id),
        query=user_query,
        num_recommendations=3
    )
    
    # Print extracted preferences
    print("\nExtracted Preferences:")
    print(json.dumps(result['extracted_preferences'], indent=2))
    
    # Print recommendations
    print("\nTop Recommendations:")
    for i, item in enumerate(result['recommendations'], 1):
        print(f"{i}. {item['product_title']} - ${item['price']:.2f} - Rating: {item['rating']}/5.0")
    
    # Print prompt for LLM
    print("\nPrompt for LLM:")
    print(result['prompt'])
    
    # Simulate LLM response
    llm_response = "Based on your preference for items under $50 with good ratings, here are some recommendations that might interest you..."
    
    # Update conversation with LLM response
    recommendation_api.update_conversation(
        user_id=str(user_id),
        user_message=user_query,
        assistant_message=llm_response
    )
    
    # Second user query
    user_query = "Do you have anything with better features?"
    print(f"\nUser: {user_query}")
    
    # Process query
    result = recommendation_api.process_query(
        user_id=str(user_id),
        query=user_query,
        num_recommendations=3
    )
    
    # Print extracted preferences
    print("\nExtracted Preferences:")
    print(json.dumps(result['extracted_preferences'], indent=2))
    
    # Print recommendations
    print("\nTop Recommendations:")
    for i, item in enumerate(result['recommendations'], 1):
        print(f"{i}. {item['product_title']} - ${item['price']:.2f} - Rating: {item['rating']}/5.0")
    
    # Print prompt for LLM
    print("\nPrompt for LLM:")
    print(result['prompt'])
    
    # Get explanation for the first recommendation
    if result['recommendations']:
        item_id = result['recommendations'][0]['product_id']
        explanation_result = recommendation_api.get_explanation(
            user_id=str(user_id),
            item_id=item_id
        )
        
        print("\nExplanation for first recommendation:")
        print(explanation_result['explanation'])
        
        print("\nExplanation Prompt for LLM:")
        if explanation_result['prompt']:
            print(explanation_result['prompt'])
        else:
            print("No prompt available.")

if __name__ == "__main__":
    main() 