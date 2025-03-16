import pandas as pd
import logging
from pathlib import Path
import time

from surprise import KNNWithMeans
from surprise import Dataset
from surprise import accuracy
from surprise import Reader

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleKNNRecommender:
    """
    A simplified KNN-based recommender using Surprise library.
    Focus on model training and evaluation.
    """
    
    def __init__(
        self,
        k_neighbors=5,
        sim_name='pearson_baseline',
        user_based=False,
        min_user_ratings=50
    ):
        """
        Initialize the simple KNN recommender.
        
        Args:
            k_neighbors: Number of neighbors for KNN algorithm
            sim_name: Similarity measure ('pearson_baseline', 'cosine', 'msd', 'pearson')
            user_based: Whether to use user-based (True) or item-based (False) collaborative filtering
            min_user_ratings: Minimum number of ratings a user must have
        """
        self.k_neighbors = k_neighbors
        self.sim_name = sim_name
        self.user_based = user_based
        self.min_user_ratings = min_user_ratings
        self.model = None
        self.reader = Reader(rating_scale=(1, 5))
        
        logger.info(f"Initialized SimpleKNNRecommender with k={k_neighbors}, "
                   f"sim_name={sim_name}, user_based={user_based}")
    
    def load_data(self, train_path, test_path=None):
        """
        Load training and testing data.
        
        Args:
            train_path: Path to the training data file
            test_path: Path to the testing data file (optional)
            
        Returns:
            trainset, testset for model training and evaluation
        """
        logger.info(f"Loading training data from {train_path}")
        train_df = pd.read_csv(train_path)
        logger.info(f"Training data shape: {train_df.shape}, columns: {list(train_df.columns)}")
        
        # Standardize column names
        if 'userId' in train_df.columns:
            train_df.rename(columns={'userId': 'user_id'}, inplace=True)
        if 'productId' in train_df.columns or 'asin' in train_df.columns or 'parent_asin' in train_df.columns:
            if 'productId' in train_df.columns:
                train_df.rename(columns={'productId': 'item_id'}, inplace=True)
            elif 'asin' in train_df.columns:
                train_df.rename(columns={'asin': 'item_id'}, inplace=True)
            else:
                train_df.rename(columns={'parent_asin': 'item_id'}, inplace=True)
        if 'Rating' in train_df.columns:
            train_df.rename(columns={'Rating': 'rating'}, inplace=True)
        
        # Filter users with at least min_user_ratings
        if self.min_user_ratings > 0:
            user_counts = train_df['user_id'].value_counts()
            active_users = user_counts[user_counts >= self.min_user_ratings].index
            train_df = train_df[train_df['user_id'].isin(active_users)]
            logger.info(f"Filtered to {len(train_df)} ratings from {len(active_users)} users with at least {self.min_user_ratings} ratings")
        
        # Ensure we only select the required columns for Surprise
        # Surprise needs exactly three columns: user ID, item ID, and ratings
        logger.info(f"Columns after preprocessing: {list(train_df.columns)}")
        surprise_df = train_df[['user_id', 'item_id', 'rating']]
        logger.info(f"Passing {surprise_df.shape[1]} columns to Surprise: {list(surprise_df.columns)}")
        
        # Load into Surprise dataset format
        train_data = Dataset.load_from_df(surprise_df, self.reader)
        trainset = train_data.build_full_trainset()
        
        testset = None
        if test_path:
            logger.info(f"Loading test data from {test_path}")
            test_df = pd.read_csv(test_path)
            
            # Apply the same column renaming
            if 'userId' in test_df.columns:
                test_df.rename(columns={'userId': 'user_id'}, inplace=True)
            if 'productId' in test_df.columns or 'asin' in test_df.columns or 'parent_asin' in test_df.columns:
                if 'productId' in test_df.columns:
                    test_df.rename(columns={'productId': 'item_id'}, inplace=True)
                elif 'asin' in test_df.columns:
                    test_df.rename(columns={'asin': 'item_id'}, inplace=True)
                else:
                    test_df.rename(columns={'parent_asin': 'item_id'}, inplace=True)
            if 'Rating' in test_df.columns:
                test_df.rename(columns={'Rating': 'rating'}, inplace=True)
            
            # Convert to Surprise testset format (list of (user_id, item_id, rating) tuples)
            testset = [(uid, iid, r) for uid, iid, r in 
                      zip(test_df['user_id'], test_df['item_id'], test_df['rating'])]
            
            logger.info(f"Prepared {len(testset)} test ratings")
        
        return trainset, testset
    
    def train(self, trainset):
        """
        Train the KNN model.
        
        Args:
            trainset: Surprise trainset object
            
        Returns:
            Trained model
        """
        if trainset is None:
            raise ValueError("No training data provided.")
        
        start_time = time.time()
        
        # Initialize the KNN model
        self.model = KNNWithMeans(
            k=self.k_neighbors,
            sim_options={
                'name': self.sim_name,
                'user_based': self.user_based
            }
        )
        
        # Train the model
        self.model.fit(trainset)
        
        training_time = time.time() - start_time
        logger.info(f"Trained {'user-based' if self.user_based else 'item-based'} "
                   f"KNN model in {training_time:.2f} seconds")
        
        return self.model
    
    def evaluate(self, testset):
        """
        Evaluate the model on test data.
        
        Args:
            testset: Surprise testset (list of (user_id, item_id, rating) tuples)
            
        Returns:
            RMSE score
        """
        if self.model is None:
            raise ValueError("No trained model. Call train() first.")
        
        if testset is None:
            raise ValueError("No test data provided.")
        
        # Make predictions on the test set
        start_time = time.time()
        predictions = self.model.test(testset)
        eval_time = time.time() - start_time
        
        # Calculate RMSE
        rmse = accuracy.rmse(predictions)
        logger.info(f"Evaluated model in {eval_time:.2f} seconds")
        logger.info(f"Test RMSE: {rmse:.4f}")
        
        return rmse


# Example usage
if __name__ == "__main__":
    # Define data paths
    data_dir = Path('../../../datasets')
    train_path = data_dir / "Electronics.train.csv"
    test_path = data_dir / "Electronics.test.csv"
    
    try:
        # Initialize recommender
        recommender = SimpleKNNRecommender(
            k_neighbors=5,
            sim_name='pearson_baseline',
            user_based=False,  # Using item-based collaborative filtering
            min_user_ratings=50  # Only consider users with at least 50 ratings
        )
        
        # Load data - add more error details if it fails
        try:
            trainset, testset = recommender.load_data(train_path, test_path)
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            # Print some info about the dataset for debugging
            try:
                df = pd.read_csv(train_path)
                logger.info(f"Dataset columns: {df.columns}")
                logger.info(f"Dataset sample: {df.head(2)}")
            except Exception as e2:
                logger.error(f"Couldn't read dataset for debug info: {e2}")
            raise
        
        # Train model
        recommender.train(trainset)
        
        # Evaluate model
        rmse = recommender.evaluate(testset)
        print(f"Item-based Model : Test Set")
        print(f"RMSE: {rmse:.4f}")
    except Exception as e:
        logger.error(f"ERROR: {e}", exc_info=True) 