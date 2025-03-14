from lightfm import LightFM
from lightfm.evaluation import precision_at_k
from data_preprocess import preprocess_data
import joblib

import numpy as np

def run_training():
    interactions = preprocess_data()

    # Split data into train/test
    train = interactions.copy()
    test = interactions.copy()
    train.data = np.random.binomial(1, 0.8, train.data.shape) * train.data  # 80% train

    # Train model
    model = LightFM(loss='warp', no_components=100, learning_rate=0.05, item_alpha=0.0001, user_alpha=0.0001)
    model.fit(train, epochs=200, verbose=True)

    # Evaluate precision@10
    test_precision = precision_at_k(model, test, k=10).mean()
    print(f"Test Precision@10: {test_precision:.4f}")

    joblib.dump(model, 'lightfm_model.pkl')
    print("Model saved as lightfm_model.pkl")

if __name__ == '__main__':
    run_training()