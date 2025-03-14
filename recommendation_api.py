from fastapi import FastAPI
from fastapi.responses import JSONResponse
import numpy as np
import joblib
from data_preprocess import preprocess_data
import pandas as pd
from scipy.sparse import coo_matrix

app = FastAPI()

# Mock trained model (replace with your actual trained model)
model = joblib.load("lightfm_model.pkl")
print("Model loaded from lightfm_model.pkl")


@app.get("/recommend")
async def get_recommendations(user_id: int, top_k: int = 5):
    try:
        interactions, user_id_map, item_id_map = preprocess_data()
        # return JSONResponse({"response": str(user_id_map)}, status_code=200)
        # Convert user_id to internal index
        user_idx = user_id_map.get(user_id, -1)
        if user_idx == -1:
            return JSONResponse({"error": "User not found"}, status_code=404)
        
        # Predict scores for all items
        scores = model.predict(user_idx, np.arange(interactions.shape[1]))
        
        # Get top-k item indices
        top_items = np.argsort(-scores)[:top_k]
        
        # Convert indices back to product IDs
        item_ids = [list(item_id_map.keys())[idx] for idx in top_items]
        
        return {"user_id": user_id, "recommendations": item_ids}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)