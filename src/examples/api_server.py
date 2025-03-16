import os
import sys
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recommendation_engine.lightfm_recommender import LightFMRecommender
from llm_interface.recommendation_api import RecommendationAPI
from utils.data_preprocess import load_preprocessed_data

# Initialize FastAPI app
app = FastAPI(title="LLM-Compatible Recommendation API")

# Global variables to store the recommendation API
recommendation_api = None

# Define request and response models
class QueryRequest(BaseModel):
    user_id: str
    query: str
    num_recommendations: Optional[int] = 5

class ExplanationRequest(BaseModel):
    user_id: str
    item_id: str

class ConversationUpdateRequest(BaseModel):
    user_id: str
    user_message: str
    assistant_message: str

class RecommendationResponse(BaseModel):
    recommendations: List[Dict[str, Any]]
    prompt: str
    extracted_preferences: Dict[str, Any]

class ExplanationResponse(BaseModel):
    explanation: str
    prompt: Optional[str] = None
    item_details: Optional[Dict[str, Any]] = None

@app.on_event("startup")
async def startup_event():
    """Initialize the recommendation API on startup."""
    global recommendation_api
    
    try:
        # Load preprocessed data
        interactions, user_id_map, item_id_map, item_data = load_preprocessed_data()
        
        # Create LightFM recommender
        recommender = LightFMRecommender(
            model_path="lightfm_model.pkl",
            interactions_data=interactions,
            user_id_map=user_id_map,
            item_id_map=item_id_map,
            item_data=item_data
        )
        
        # Create recommendation API
        recommendation_api = RecommendationAPI(recommender=recommender)
        
        print("Recommendation API initialized successfully.")
    except Exception as e:
        print(f"Error initializing recommendation API: {str(e)}")
        print("Please make sure the preprocessed data and model files are available.")

@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "LLM-Compatible Recommendation API"}

@app.post("/recommend", response_model=RecommendationResponse)
async def recommend(request: QueryRequest):
    """Process a natural language query and return recommendations."""
    if recommendation_api is None:
        raise HTTPException(status_code=503, detail="Recommendation API not initialized")
    
    try:
        result = recommendation_api.process_query(
            user_id=request.user_id,
            query=request.query,
            num_recommendations=request.num_recommendations
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/explain", response_model=ExplanationResponse)
async def explain(request: ExplanationRequest):
    """Get an explanation for why an item was recommended."""
    if recommendation_api is None:
        raise HTTPException(status_code=503, detail="Recommendation API not initialized")
    
    try:
        result = recommendation_api.get_explanation(
            user_id=request.user_id,
            item_id=request.item_id
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update_conversation")
async def update_conversation(request: ConversationUpdateRequest):
    """Update conversation history with a new turn."""
    if recommendation_api is None:
        raise HTTPException(status_code=503, detail="Recommendation API not initialized")
    
    try:
        recommendation_api.update_conversation(
            user_id=request.user_id,
            user_message=request.user_message,
            assistant_message=request.assistant_message
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 