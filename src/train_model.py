from recommendation_engine.recommenders.collab_item_based_knn_rec import CollabItemBasedKNNRec

def train_model():
    recommender = CollabItemBasedKNNRec()
    recommender.load_data("path/to/your/data")
    recommender.train()
    recommender.save_model("datasets/knn_model.pkl")

if __name__ == "__main__":
    train_model() 