import os
import sys
import pandas as pd
import numpy as np
import joblib
from lightfm import LightFM
from lightfm.evaluation import precision_at_k

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.data_preprocess import preprocess_data, save_preprocessed_data

def train_model(interactions, user_id_map, item_id_map, item_data, output_path="lightfm_model.pkl"):
    """
    Train a LightFM model on the preprocessed data.
    
    Args:
        interactions: Sparse matrix of user-item interactions
        user_id_map: Dictionary mapping user IDs to indices
        item_id_map: Dictionary mapping item IDs to indices
        item_data: DataFrame with item metadata
        output_path: Path to save the trained model
        
    Returns:
        Trained LightFM model
    """
    print("Training LightFM model...")
    
    # Split data into train/test
    train = interactions.copy()
    test = interactions.copy()
    train.data = np.random.binomial(1, 0.8, train.data.shape) * train.data  # 80% train
    
    # Train model
    model = LightFM(loss='warp', no_components=100, learning_rate=0.05, item_alpha=0.0001, user_alpha=0.0001)
    model.fit(train, epochs=30, verbose=True)
    
    # Evaluate precision@10
    test_precision = precision_at_k(model, test, k=10).mean()
    print(f"Test Precision@10: {test_precision:.4f}")
    
    # Save model
    joblib.dump(model, output_path)
    print(f"Model saved as {output_path}")
    
    return model

def main():
    """
    Main function to preprocess data and train the model.
    """
    print("Preprocessing data...")
    try:
        interactions, user_id_map, item_id_map, item_data = preprocess_data()
    except FileNotFoundError:
        print("Dataset file not found. Please make sure the online_retail_dataset.xlsx file is in the correct location.")
        return
    
    print(f"Interactions matrix shape: {interactions.shape}")
    print(f"Number of users: {len(user_id_map)}")
    print(f"Number of items: {len(item_id_map)}")
    print(f"Item data shape: {item_data.shape}")
    
    # Save preprocessed data
    save_preprocessed_data(interactions, user_id_map, item_id_map, item_data)
    
    # Train model
    train_model(interactions, user_id_map, item_id_map, item_data)
    
    print("Data preprocessing and model training completed successfully.")

if __name__ == "__main__":
    main() 