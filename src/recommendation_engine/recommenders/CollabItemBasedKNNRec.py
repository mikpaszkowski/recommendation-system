import pandas as pd
import numpy as np
import json
import time
import logging
from typing import Dict, List, Tuple, Optional, Union, Any
from pathlib import Path
import os

# Use sklearn's train_test_split instead of Surprise's
from sklearn.model_selection import train_test_split as sklearn_train_test_split
from surprise import Dataset, Reader
from surprise import KNNWithMeans
from surprise import accuracy

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CollabItemBasedKNNRec:
    """
    KNN-based collaborative filtering recommendation system for Amazon products.
    This implementation uses the Surprise library with a focus on item-based collaborative filtering,
    where items are recommended based on their similarity to items the user has rated highly.
    """
    
    def __init__(
        self,
        k_neighbors: int = 10,
        sim_option: str = 'pearson_baseline',
        min_ratings: int = 5,
        rating_scale: Tuple[int, int] = (1, 5),
        sample_frac: Optional[float] = None,
        min_k: int = 1,
        verbose: bool = True
    ):
        """
        Initialize the KNN recommender.
        
        Args:
            k_neighbors: Number of neighbors for KNN algorithm
            sim_option: Similarity measure ('pearson_baseline', 'cosine', 'msd', 'pearson')
            min_ratings: Minimum number of ratings for an item to be considered
            rating_scale: Min and max values for the rating scale
            sample_frac: If set, randomly sample this fraction of ratings from training data (for memory efficiency)
            min_k: Minimum number of neighbors for prediction (can help with memory usage)
            verbose: Whether to show progress during training
        """
        self.k_neighbors = k_neighbors
        self.sim_option = sim_option
        self.min_ratings = min_ratings
        self.rating_scale = rating_scale
        self.sample_frac = sample_frac
        self.min_k = min_k
        self.verbose = verbose
        
        # Will be initialized when data is loaded
        self.train_df = None
        self.valid_df = None
        self.test_df = None
        self.filtered_train = None
        self.filtered_test = None
        self.filtered_valid = None
        self.model = None
        self.trainset = None
        self.validset = None
        self.testset = None
        
        # Keep mappings between internal and raw ids
        self.item_to_raw_id = None
        self.user_to_raw_id = None
        self.raw_to_item_id = None
        self.raw_to_user_id = None
        
        logger.info(f"Initialized KNNRecommender with k={k_neighbors}, sim_option={sim_option}")
    
    def load_data(self, data_dir: str) -> None:
        """
        Load pre-split Electronics datasets from the specified directory.
        
        Args:
            data_dir: Directory containing Electronics.train.csv, Electronics.valid.csv, and Electronics.test.csv
        """
        try:
            data_dir = Path(data_dir)
            
            # Load train, validation and test sets
            temp_df = pd.read_csv(data_dir / "Electronics.train.csv")
            logger.info(f"Training data shape: {temp_df.shape}, columns: {list(temp_df.columns)}")

            # Use sklearn's train_test_split instead of Surprise's
            train_df, test_df = sklearn_train_test_split(temp_df, test_size=0.2, random_state=42)
            
            self.train_df = train_df
            self.test_df = test_df
            self.valid_df = pd.read_csv(data_dir / "Electronics.valid.csv")
            
            
            # Ensure correct column names
            required_columns = ['user_id', 'parent_asin', 'rating']
            datasets = {
                'train': self.train_df,
                'valid': self.valid_df,
                'test': self.test_df
            }
            
            for name, df in datasets.items():
                # Check if using alternative column names
                alt_columns = {'userId': 'user_id', 'productId': 'parent_asin', 'Rating': 'rating', 'asin': 'parent_asin'}
                for alt, req in alt_columns.items():
                    if alt in df.columns and req not in df.columns:
                        df = df.rename(columns={alt: req})
                datasets[name] = df
            
            self.train_df, self.valid_df, self.test_df = datasets['train'], datasets['valid'], datasets['test']
            
            # Verify required columns exist after potential renaming
            for name, df in datasets.items():
                if not all(col in df.columns for col in required_columns):
                    missing_cols = [col for col in required_columns if col not in df.columns]
                    raise ValueError(f"{name} dataset missing required columns: {missing_cols}")
            
            logger.info(f"Loaded {len(self.train_df)} training ratings")
            logger.info(f"Loaded {len(self.valid_df)} validation ratings")
            logger.info(f"Loaded {len(self.test_df)} test ratings")
            
            # Filter out items with few ratings from training set
            self._filter_items()
            
            # Process the 'history' column in each dataset
            for name, df in datasets.items():
                if 'history' in df.columns:
                    # Convert string representation of history to actual lists
                    df['history'] = df['history'].apply(lambda x: [] if pd.isna(x) else str(x).split())
            
            # Prepare data for Surprise library
            self._prepare_surprise_data()
            
        except Exception as e:
            logger.error(f"Error loading ratings data: {e}")
            raise
    
    def _filter_items(self) -> None:
        """Filter out items with fewer than min_ratings ratings from train/val/test set."""
        item_counts = self.train_df['parent_asin'].value_counts()
        popular_items = item_counts[item_counts >= self.min_ratings].index
        
        self.filtered_train = self.train_df[self.train_df['parent_asin'].isin(popular_items)].copy()
        self.filtered_test = self.test_df[self.test_df['parent_asin'].isin(popular_items)].copy()
        self.filtered_valid = self.valid_df[self.valid_df['parent_asin'].isin(popular_items)].copy()
        
        # Apply sampling if specified
        if self.sample_frac and self.sample_frac < len(self.filtered_train):
            logger.info(f"Sampling {self.sample_frac} ratings from {len(self.filtered_train)} available ratings")
            self.filtered_train = self.filtered_train.sample(frac=self.sample_frac, random_state=42)
            self.filtered_test = self.filtered_test.sample(frac=self.sample_frac, random_state=42)
            self.filtered_valid = self.filtered_valid.sample(frac=self.sample_frac, random_state=42)
            
        
        filtered_out_train = len(self.train_df) - len(self.filtered_train)
        filtered_out_test = len(self.test_df) - len(self.filtered_test)
        filtered_out_valid = len(self.valid_df) - len(self.filtered_valid)
        logger.info(f"Filtered out {filtered_out_train} training ratings ({filtered_out_train/len(self.train_df):.2%})")
        logger.info(f"Filtered out {filtered_out_test} test ratings ({filtered_out_test/len(self.test_df):.2%})")
        logger.info(f"Filtered out {filtered_out_valid} validation ratings ({filtered_out_valid/len(self.valid_df):.2%})")
        logger.info(f"Remaining: {len(self.filtered_train)} ratings for {len(popular_items)} items")
    
    def _prepare_surprise_data(self) -> None:
        """Prepare data for the Surprise library."""
        # Create a Reader object for the rating scale
        reader = Reader(rating_scale=self.rating_scale)
        
        # Load the datasets into the Surprise format
        self.trainset = Dataset.load_from_df(
            self.filtered_train[['user_id', 'parent_asin', 'rating']],
            reader
        ).build_full_trainset()
        
        self.validset = [(uid, iid, r) for uid, iid, r in 
                        zip(self.valid_df['user_id'], 
                            self.valid_df['parent_asin'],
                            self.valid_df['rating'])]
        
        self.testset = [(uid, iid, r) for uid, iid, r in 
                       zip(self.test_df['user_id'],
                           self.test_df['parent_asin'],
                           self.test_df['rating'])]
        
        # Store mappings between Surprise internal ids and raw ids
        self.item_to_raw_id = {i: self.trainset.to_raw_iid(i) for i in self.trainset.all_items()}
        self.user_to_raw_id = {u: self.trainset.to_raw_uid(u) for u in self.trainset.all_users()}
        
        # Create reverse mappings
        self.raw_to_item_id = {v: k for k, v in self.item_to_raw_id.items()}
        self.raw_to_user_id = {v: k for k, v in self.user_to_raw_id.items()}
        
        logger.info(f"Prepared data with {self.trainset.n_users} users and {self.trainset.n_items} items")
    
    def train(self) -> None:
        """Train the KNN collaborative filtering model with memory optimizations."""
        if self.trainset is None:
            raise ValueError("No training data available. Call load_data() first.")
        
        try:
            # Initialize the KNN model with memory optimizations
            self.model = KNNWithMeans(
                k=self.k_neighbors,
                min_k=self.min_k,  # Allow predictions with fewer neighbors
                sim_options={
                    'name': self.sim_option,
                    'user_based': False,  # Item-based collaborative filtering
                    'shrinkage': 100,  # Shrinkage parameter to deal with noise in similarity computation
                },
                verbose=self.verbose
            )
            
            # Train the model
            start_time = time.time()
            self.model.fit(self.trainset)
            training_time = time.time() - start_time
            
            logger.info(f"Model trained in {training_time:.2f} seconds")
            
            # Evaluate on validation set
            if self.validset:
                valid_rmse = self.evaluate(dataset='valid')
                logger.info(f"Validation RMSE: {valid_rmse:.4f}")
                
        except MemoryError as e:
            logger.error("Memory error during training. Try reducing sample_size or increasing min_ratings.")
            raise
        except Exception as e:
            logger.error(f"Error during training: {e}")
            raise
    
    def evaluate(self, dataset: str = 'test') -> float:
        """
        Evaluate the model on the specified dataset.
        
        Args:
            dataset: Which dataset to evaluate on ('valid' or 'test')
            
        Returns:
            RMSE (Root Mean Squared Error) of the model
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        eval_set = self.validset if dataset == 'valid' else self.testset
        if eval_set is None:
            raise ValueError(f"No {dataset} data available.")
        
        # Make predictions on the evaluation set
        predictions = self.model.test(eval_set)
        
        # Calculate RMSE
        rmse = accuracy.rmse(predictions)
        logger.info(f"Model evaluation on {dataset} set - RMSE: {rmse:.4f}")
        
        return rmse
    
    def get_user_recommendations(
        self, 
        user_id: str, 
        n_recommendations: int = 10,
        exclude_rated: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get personalized recommendations for a user using KNN collaborative filtering.
        
        Args:
            user_id: ID of the user to get recommendations for
            n_recommendations: Number of recommendations to return
            exclude_rated: Whether to exclude items the user has already rated
            
        Returns:
            List of recommended items with scores and explanations
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Check if user exists in the training data
        if user_id not in self.raw_to_user_id:
            logger.warning(f"User {user_id} not found in training data")
            return []
        
        # Get all items
        all_items = list(self.item_to_raw_id.keys())
        
        # Get items the user has already rated
        user_internal_id = self.raw_to_user_id[user_id]
        # The ur attribute contains tuples of (item_id, rating)
        rated_items = {j for (j, _) in self.trainset.ur[user_internal_id]}
        
        # Get candidate items (exclude already rated if requested)
        if exclude_rated:
            candidate_items = [i for i in all_items if i not in rated_items]
        else:
            candidate_items = all_items
        
        # Generate predictions for all candidate items
        predictions = []
        for item_internal_id in candidate_items:
            item_id = self.item_to_raw_id[item_internal_id]
            
            try:
                # Get prediction
                prediction = self.model.predict(user_id, item_id)
                
                # Store prediction details
                predictions.append({
                    'item_id': item_id,
                    'estimated_rating': prediction.est,
                    'details': prediction.details
                })
            except Exception as e:
                logger.warning(f"Could not generate prediction for item {item_id}: {e}")
                continue
        
        # Sort predictions by estimated rating (descending)
        predictions.sort(key=lambda x: x['estimated_rating'], reverse=True)
        
        # Take top N recommendations
        top_recommendations = predictions[:n_recommendations]
        
        # Enhance recommendations with explanations
        recommendations = []
        for i, rec in enumerate(top_recommendations):
            item_id = rec['item_id']
            score = rec['estimated_rating']
            
            # Create enhanced recommendation
            recommendation = {
                'rank': i + 1,
                'item_id': item_id,
                'score': score,
                'explanation': self._generate_explanation(user_id, item_id, score, rec['details'])
            }
            
            recommendations.append(recommendation)
        
        return recommendations
    
    def get_similar_items(
        self, 
        item_id: str, 
        n_items: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get items similar to a given item using the trained model.
        
        Args:
            item_id: ID of the item to find similarities for
            n_items: Number of similar items to return
            
        Returns:
            List of similar items with similarity scores and explanations
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Check if item exists in the training data
        if item_id not in self.raw_to_item_id:
            logger.warning(f"Item {item_id} not found in training data")
            return []
        
        # Get inner ID for the item
        item_inner_id = self.raw_to_item_id[item_id]
        
        # Get neighbors (similar items)
        neighbors = []
        
        # Access the item-item similarity matrix from the model
        sim_matrix = self.model.sim
        
        for other_inner_id in range(self.trainset.n_items):
            if other_inner_id != item_inner_id:
                similarity = sim_matrix[item_inner_id, other_inner_id]
                
                # Skip if similarity is NaN (can happen with some similarity measures)
                if np.isnan(similarity):
                    continue
                
                other_item_id = self.item_to_raw_id[other_inner_id]
                neighbors.append((other_item_id, similarity))
        
        # Sort by similarity (descending)
        neighbors.sort(key=lambda x: x[1], reverse=True)
        
        # Take top N similar items
        top_similar = neighbors[:n_items]
        
        # Create formatted response
        similar_items = []
        for i, (similar_item_id, similarity) in enumerate(top_similar):
            similar_items.append({
                'rank': i + 1,
                'item_id': similar_item_id,
                'similarity': similarity,
                'explanation': self._generate_similarity_explanation(item_id, similar_item_id, similarity)
            })
        
        return similar_items
    
    def _generate_explanation(self, user_id: str, item_id: str, score: float, details: Dict) -> str:
        """
        Generate an explanation for a recommendation.
        
        Args:
            user_id: ID of the user
            item_id: ID of the recommended item
            score: Predicted score
            details: Prediction details from the model
            
        Returns:
            Explanation string
        """
        # Get the top contributors to this recommendation
        neighbors_info = details.get('neighbors', [])
        
        if not neighbors_info:
            # Fall back to a generic explanation if no neighbors info
            if score > 4:
                return "This item is highly recommended based on your rating patterns."
            elif score > 3:
                return "This item matches your general preferences."
            else:
                return "This item might be of interest based on your rating history."
        
        # Get the top 3 similar items that contributed to this recommendation
        top_neighbors = sorted(neighbors_info, key=lambda x: abs(x[1]), reverse=True)[:3]
        
        # Create an explanation based on similar items
        if top_neighbors:
            similar_items = []
            for inner_id, rating, _ in top_neighbors:
                similar_item_id = self.item_to_raw_id[inner_id]
                similar_items.append(similar_item_id)
            
            if len(similar_items) == 1:
                return f"Recommended because it is similar to {similar_items[0]} that you've rated."
            elif len(similar_items) == 2:
                return f"Recommended because it is similar to {similar_items[0]} and {similar_items[1]} that you've rated."
            else:
                return f"Recommended because it is similar to several items you've rated, including {similar_items[0]}, {similar_items[1]}, and {similar_items[2]}."
        
        # If no good explanation based on neighbors, fall back to score-based explanation
        if score > 4:
            return "This item is highly recommended based on your rating patterns."
        elif score > 3:
            return "This item matches your general preferences."
        else:
            return "This item might be of interest based on your rating history."
    
    def _generate_similarity_explanation(self, item_id: str, similar_item_id: str, similarity: float) -> str:
        """
        Generate an explanation for item similarity.
        
        Args:
            item_id: ID of the source item
            similar_item_id: ID of the similar item
            similarity: Similarity score
            
        Returns:
            Explanation string
        """
        if similarity > 0.8:
            return f"This item is very similar to {item_id} based on user rating patterns."
        elif similarity > 0.6:
            return f"This item is moderately similar to {item_id} based on how users have rated both items."
        else:
            return f"This item has some similarities to {item_id} according to user ratings."
    
    def save_model(self, filepath: str) -> None:
        """
        Save the trained model to a file.
        
        Args:
            filepath: Path to save the model
        """
        if self.model is None:
            raise ValueError("No model to save. Train the model first.")
        
        import pickle
        
        # Create a dictionary with all necessary data
        model_data = {
            'model': self.model,
            'item_to_raw_id': self.item_to_raw_id,
            'user_to_raw_id': self.user_to_raw_id,
            'raw_to_item_id': self.raw_to_item_id,
            'raw_to_user_id': self.raw_to_user_id,
            'k_neighbors': self.k_neighbors,
            'sim_option': self.sim_option,
            'min_ratings': self.min_ratings,
            'rating_scale': self.rating_scale,
            'sample_frac': self.sample_frac,
            'min_k': self.min_k,
            'verbose': self.verbose
        }
        
        # Save to file
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)
        
        logger.info(f"Model saved to {filepath}")
    
    @classmethod
    def load_model(cls, filepath: str) -> 'CollabItemBasedKNNRec':
        """
        Load a trained model from a file.
        
        Args:
            filepath: Path to the saved model
            
        Returns:
            Initialized KNNRecommender with loaded model
        """
        import pickle
        
        # Load data from file
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)
        
        # Create a new instance
        recommender = cls(
            k_neighbors=model_data['k_neighbors'],
            sim_option=model_data['sim_option'],
            min_ratings=model_data['min_ratings'],
            rating_scale=model_data['rating_scale'],
            sample_frac=model_data['sample_frac'],
            min_k=model_data['min_k'],
            verbose=model_data['verbose']
        )
        
        # Restore model and mappings
        recommender.model = model_data['model']
        recommender.item_to_raw_id = model_data['item_to_raw_id']
        recommender.user_to_raw_id = model_data['user_to_raw_id']
        recommender.raw_to_item_id = model_data['raw_to_item_id']
        recommender.raw_to_user_id = model_data['raw_to_user_id']
        
        logger.info(f"Model loaded from {filepath}")
        
        return recommender

    def analyze_data_stats(self) -> None:
        """
        Analyze and log statistics about users and items in the dataset.
        Provides insights about most active users and popular products.
        """
        if self.train_df is None:
            raise ValueError("No data available. Call load_data() first.")
            
        # Analyze user statistics
        user_ratings = self.train_df['user_id'].value_counts()
        top_users = user_ratings.head(10)
        
        logger.info("\n=== User Statistics ===")
        logger.info(f"Total unique users: {len(user_ratings)}")
        logger.info(f"Average ratings per user: {user_ratings.mean():.1f}")
        logger.info(f"Median ratings per user: {user_ratings.median():.1f}")
        logger.info("\nTop 10 Most Active Users:")
        for user_id, count in top_users.items():
            logger.info(f"User {user_id}: {count} ratings")
            
        # Analyze item statistics
        item_ratings = self.train_df['parent_asin'].value_counts()
        top_items = item_ratings.head(10)
        
        logger.info("\n=== Product Statistics ===")
        logger.info(f"Total unique products: {len(item_ratings)}")
        logger.info(f"Average ratings per product: {item_ratings.mean():.1f}")
        logger.info(f"Median ratings per product: {item_ratings.median():.1f}")
        logger.info("\nTop 10 Most Rated Products:")
        for item_id, count in top_items.items():
            logger.info(f"Product {item_id}: {count} ratings")
            
        # Analyze rating distribution
        rating_dist = self.train_df['rating'].value_counts().sort_index()
        
        logger.info("\n=== Rating Distribution ===")
        for rating, count in rating_dist.items():
            percentage = (count / len(self.train_df)) * 100
            logger.info(f"Rating {rating:.1f}: {count} ratings ({percentage:.1f}%)")
            
        # Calculate sparsity
        total_possible = len(user_ratings) * len(item_ratings)
        actual_ratings = len(self.train_df)
        sparsity = (1 - actual_ratings / total_possible) * 100
        
        logger.info(f"\nMatrix Sparsity: {sparsity:.2f}%")

    def _get_enhanced_user_profile(self, user_id: str) -> Dict[str, float]:
        """
        Create an enhanced user profile that combines explicit ratings with purchase history.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Dictionary mapping item_ids to their weights in the user profile
        """
        # Get user's internal ID
        user_internal_id = self.raw_to_user_id.get(user_id)
        if user_internal_id is None:
            return {}
        
        # Start with explicit ratings (higher weight)
        profile = {}
        for item_id, rating in self.trainset.ur[user_internal_id]:
            item_raw_id = self.item_to_raw_id[item_id]
            profile[item_raw_id] = rating * 2  # Double weight for explicit ratings
        
        # Add purchase history (lower weight but still significant)
        user_history = self.train_df[self.train_df['user_id'] == user_id]['history'].values
        if len(user_history) > 0:
            for history_list in user_history:
                for item_id in history_list:
                    if item_id in self.raw_to_item_id:  # Only include items in our training set
                        # If already rated, don't change weight; otherwise add with lower weight
                        if item_id not in profile:
                            profile[item_id] = 1.0  # Lower weight for implicit feedback
        
        return profile

    def _compute_enhanced_similarity(self, item_id1: str, item_id2: str) -> float:
        """
        Compute enhanced similarity between two items considering purchase history patterns.
        
        Args:
            item_id1: First item ID
            item_id2: Second item ID
            
        Returns:
            Enhanced similarity score
        """
        # Get base similarity from the trained model
        item_inner_id1 = self.raw_to_item_id.get(item_id1)
        item_inner_id2 = self.raw_to_item_id.get(item_id2)
        
        if item_inner_id1 is None or item_inner_id2 is None:
            return 0.0
        
        # Get model's similarity score (from explicit ratings)
        base_similarity = self.model.sim[item_inner_id1, item_inner_id2]
        
        # Calculate co-occurrence in purchase histories
        users_with_item1_history = set()
        users_with_item2_history = set()
        users_with_both_history = set()
        
        for _, row in self.train_df.iterrows():
            history = row['history']
            if item_id1 in history:
                users_with_item1_history.add(row['user_id'])
                if item_id2 in history:
                    users_with_both_history.add(row['user_id'])
            elif item_id2 in history:
                users_with_item2_history.add(row['user_id'])
        
        # Calculate Jaccard coefficient for co-occurrence
        users_with_either = users_with_item1_history.union(users_with_item2_history)
        if not users_with_either:
            history_similarity = 0.0
        else:
            history_similarity = len(users_with_both_history) / len(users_with_either)
        
        # Combine both similarities (0.7 * explicit ratings + 0.3 * purchase history)
        enhanced_similarity = 0.7 * base_similarity + 0.3 * history_similarity
        
        return enhanced_similarity

    def get_enhanced_recommendations(
        self, 
        user_id: str, 
        n_recommendations: int = 10,
        exclude_rated: bool = True,
        exclude_purchased: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get personalized recommendations considering both ratings and purchase history.
        
        Args:
            user_id: ID of the user to get recommendations for
            n_recommendations: Number of recommendations to return
            exclude_rated: Whether to exclude items the user has already rated
            exclude_purchased: Whether to exclude items the user has already purchased
            
        Returns:
            List of recommended items with scores and explanations
        """
        # Get enhanced user profile
        user_profile = self._get_enhanced_user_profile(user_id)
        
        if not user_profile:
            logger.warning(f"User {user_id} has no profile (no ratings or purchase history)")
            return []
        
        # Get items to exclude
        exclude_items = set()
        if exclude_rated or exclude_purchased:
            user_data = self.train_df[self.train_df['user_id'] == user_id]
            
            if exclude_rated:
                exclude_items.update(user_data['parent_asin'].values)
            
            if exclude_purchased:
                for history in user_data['history'].values:
                    exclude_items.update(history)
        
        # Calculate scores for all items
        item_scores = {}
        for item_internal_id in self.trainset.all_items():
            item_id = self.item_to_raw_id[item_internal_id]
            
            if item_id in exclude_items:
                continue
            
            # Calculate score based on similarity to items in user profile
            score = 0.0
            total_weight = 0.0
            
            for profile_item_id, weight in user_profile.items():
                # Use enhanced similarity
                similarity = self._compute_enhanced_similarity(item_id, profile_item_id)
                score += similarity * weight
                total_weight += abs(weight)
            
            if total_weight > 0:
                item_scores[item_id] = score / total_weight
        
        # Sort by score and take top N
        top_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)[:n_recommendations]
        
        # Generate recommendations with explanations
        recommendations = []
        for i, (item_id, score) in enumerate(top_items):
            recommendation = {
                'rank': i + 1,
                'item_id': item_id,
                'score': score,
                'explanation': self._generate_enhanced_explanation(user_id, item_id, score, user_profile)
            }
            recommendations.append(recommendation)
        
        return recommendations

    def _generate_enhanced_explanation(
        self, 
        user_id: str, 
        item_id: str, 
        score: float, 
        user_profile: Dict[str, float]
    ) -> str:
        """
        Generate an explanation for a recommendation that considers purchase history.
        
        Args:
            user_id: ID of the user
            item_id: ID of the recommended item
            score: Predicted score
            user_profile: User's profile with weighted items
            
        Returns:
            Explanation string
        """
        # Find top contributors to the recommendation
        top_contributors = []
        for profile_item_id, weight in user_profile.items():
            similarity = self._compute_enhanced_similarity(item_id, profile_item_id)
            contribution = similarity * weight
            if contribution > 0:
                top_contributors.append((profile_item_id, contribution, weight > 1.0))
        
        # Sort by contribution
        top_contributors.sort(key=lambda x: x[1], reverse=True)
        top_contributors = top_contributors[:3]
        
        if not top_contributors:
            return "This item matches your general preferences based on your ratings and purchase history."
        
        # Create explanation based on contributor type
        rated_items = [item_id for item_id, _, is_rated in top_contributors if is_rated]
        purchased_items = [item_id for item_id, _, is_rated in top_contributors if not is_rated]
        
        explanation_parts = []
        
        if rated_items:
            if len(rated_items) == 1:
                explanation_parts.append(f"you rated {rated_items[0]} highly")
            else:
                explanation_parts.append(f"you rated {', '.join(rated_items[:-1])} and {rated_items[-1]} highly")
        
        if purchased_items:
            if len(purchased_items) == 1:
                explanation_parts.append(f"you previously purchased {purchased_items[0]}")
            else:
                explanation_parts.append(f"you previously purchased {', '.join(purchased_items[:-1])} and {purchased_items[-1]}")
        
        if explanation_parts:
            return f"Recommended because {' and '.join(explanation_parts)}."
        else:
            return "This item matches your general preferences based on your ratings and purchase history."

# Example usage
if __name__ == "__main__":
    # Define paths
    data_dir = Path('../../../datasets')
    model_path = data_dir / 'knn_model.pkl'
    
    # Try to load existing model first
    if os.path.exists(model_path):
        logger.info(f"Loading existing model from {model_path}")
        recommender = CollabItemBasedKNNRec.load_model(model_path)
        recommender.load_data(data_dir)
    else:
        logger.info("Training new model...")
        # Initialize recommender with memory-effself.model.simicient settings
        recommender = CollabItemBasedKNNRec(
            k_neighbors=10,
            min_ratings=20,  # Increased minimum ratings threshold
            sample_frac=0.05,  # Sample 1M ratings for training
            min_k=1,  # Allow predictions with fewer neighbors
            verbose=True
        )
        
        # Load and analyze data
        recommender.load_data(data_dir)
        recommender.analyze_data_stats()
        
        # Train model
        recommender.train()
        
        # Save the trained model
        logger.info(f"Saving model to {model_path}")
        recommender.save_model(model_path)
    
    # Evaluate model
    # rmse = recommender.evaluate()
    
    # Get recommendations for a user
    recommendations = recommender.get_user_recommendations('AHPJHWUFX7DFIVS5B3XNEK7JLSAQ', n_recommendations=5)
    print("\nRecommendations for user:")
    for rec in recommendations:
        print(f"{rec['rank']}. {rec['item_id']} (Score: {rec['score']:.2f}) - {rec['explanation']}")
    
    # Get similar items
    similar_items = recommender.get_similar_items('B083TH1B45', n_items=5)
    print("\nItems similar to item:")
    for item in similar_items:
        print(f"{item['rank']}. {item['item_id']} (Similarity: {item['similarity']:.2f}) - {item['explanation']}")