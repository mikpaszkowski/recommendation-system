import json
import sys
from pathlib import Path
import logging

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.llm_interface.recommendation_api import RecommendationAPI
from src.recommendation_engine.recommenders import ContentHybridItemBasedRec
from src.recommendation_engine.recommenders import CollabItemBasedKNNRec
from src.llm.simple_llm_handler import SimpleLLMHandler

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    
    try:
        # collab_item_based_rec = CollabItemBasedKNNRec()
        # collab_item_based_rec_model = collab_item_based_rec.get_model()
        
        # if collab_item_based_rec_model is None:
        #     logger.error("Failed to load model. Please ensure the model file exists and is properly trained.")
        #     return
        
        # # Get user recommendations
        # user_id = 'AHPJHWUFX7DFIVS5B3XNEK7JLSAQ'
        # recommendations = collab_item_based_rec_model.get_user_recommendations(user_id, n_recommendations=5)
        # print(f"\nRecommendations for user {user_id}:")
        # for rec in recommendations:
        #     print(f"{rec['rank']}. {rec['item_id']} (Score: {rec['score']:.2f}) - {rec['explanation']}")
        
        # # Get similar items
        # item_id = 'B083TH1B45'
        # similar_items = collab_item_based_rec_model.get_similar_items(item_id, n_items=5)
        # print(f"\nItems similar to item {item_id}:")
        # for item in similar_items:
        #     print(f"{item['rank']}. {item['item_id']} (Similarity: {item['similarity']:.2f}) - {item['explanation']}")

        # content_hybrid_item_based_rec = ContentHybridItemBasedRec()
        # content_hybrid_item_based_rec_model = content_hybrid_item_based_rec.get_model()
        
        # num_of_recommendations = 5
        # product_id = "B075X8471B"
        
        # similar_items = content_hybrid_item_based_rec_model.get_similar_items(product_id, num_of_recommendations)
        # print(f"\nItems similar to '{product_id}':")
        # for item in similar_items:
        #     print(f"{item['rank']}. {item['item_id']} (Score: {item['similarity_score']:.2f}) - {item['explanation']} \nDetails: {item['details']}\n")


        # query = "ASUS Laptop"
        # recommendations = content_hybrid_item_based_rec_model.get_recommendations_by_text(query, num_of_recommendations)
        # print(f"\nRecommendations for '{query}':")
        # for rec in recommendations:
        #     print(f"{rec['rank']}. {rec['item_id']} (Score: {rec['similarity_score']:.2f}) - {rec['explanation']} \nDetails: {rec['details']}")

        # recommendation_api = RecommendationAPI(
        #     recommender=content_hybrid_item_based_rec_model
        # )
        
        # user_id = 'AHPJHWUFX7DFIVS5B3XNEK7JLSAQ'
        # query = "I am interested in new mobile phone with a very good camera and price under $500"
        # num_recommendations = 5
        
        # result = recommendation_api.process_query(
        #     user_id=str(user_id),
        #     query=query,
        #     num_recommendations=num_recommendations
        # )
        
        #  # Print extracted preferences
        # print("\nExtracted Preferences:")
        # print(json.dumps(result['extracted_preferences'], indent=2))
        
        # # Print recommendations
        # print("\nTop Recommendations:")
        # for i, item in enumerate(result['recommendations'], 1):
        #     details = item['details']
        #     print(f"{i}. {details['title']} - ${details['price']} - Rating: {details['average_rating']}/5.0")
        
        # # Print prompt for LLM
        # print("\nPrompt for LLM:")
        # print(result['prompt'])
        
        llm_handler = SimpleLLMHandler()
        response = llm_handler.extract_preferences('Szukam letnich butów górskich na wyjazd w góry z twardą podeszwą do 500 zł')
        print("\nResponse from LLM:")
        print(response)

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        raise

if __name__ == "__main__":
    main()
    