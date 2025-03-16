import pandas as pd
import numpy as np
import json
import re
import time
import os
from typing import Dict, List, Tuple, Optional, Union, Any
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import torch
from sentence_transformers import SentenceTransformer
import pickle
import sys
from pathlib import Path
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Get project root and data directory paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
print(f"PROJECT_ROOT: {PROJECT_ROOT}")
DATASET_DIR = PROJECT_ROOT / "datasets"

class ContentHybridItemBasedRec:
    """
    Hybrid content-based recommendation system combining TF-IDF and Sentence-BERT embeddings.
    This recommender analyzes product reviews and descriptions to find similar items based on
    content, without requiring user-item interactions.
    """
    
    def __init__(
        self,
        sbert_model_name: str = 'all-MiniLM-L6-v2',
        tfidf_max_features: int = 5000,
        batch_size: int = 32,
        tfidf_weight: float = 0.3,
        sbert_weight: float = 0.7,
        use_gpu: bool = torch.cuda.is_available(),
        model_dir: str = DATASET_DIR / "models" / "content_hybrid_item_based_rec"
    ):
        """
        Initialize the hybrid content-based recommender.
        
        Args:
            sbert_model_name: Name of the pre-trained sentence transformer model
            tfidf_max_features: Maximum number of features for TF-IDF
            batch_size: Batch size for processing texts with SBERT
            tfidf_weight: Weight for TF-IDF similarity in the hybrid score (0-1)
            sbert_weight: Weight for SBERT similarity in the hybrid score (0-1)
            use_gpu: Whether to use GPU for SBERT if available
        """
        self.sbert_model_name = sbert_model_name
        self.tfidf_max_features = tfidf_max_features
        self.batch_size = batch_size
        self.tfidf_weight = tfidf_weight
        self.sbert_weight = sbert_weight
        self.use_gpu = use_gpu
        self.model_dir = model_dir
        
        # Validate weights
        if not 0 <= tfidf_weight <= 1 or not 0 <= sbert_weight <= 1:
            raise ValueError("Weights must be between 0 and 1")
        
        if abs(tfidf_weight + sbert_weight - 1.0) > 1e-6:
            logger.warning(f"Weights don't sum to 1: {tfidf_weight} + {sbert_weight} = {tfidf_weight + sbert_weight}")
            # Normalize weights
            total = tfidf_weight + sbert_weight
            self.tfidf_weight = tfidf_weight / total
            self.sbert_weight = sbert_weight / total
            logger.info(f"Normalized weights: TF-IDF = {self.tfidf_weight:.2f}, SBERT = {self.sbert_weight:.2f}")
        
        # Will be initialized when data is loaded/processed
        self.product_texts = {}
        self.product_asins = []
        self.tfidf_vectorizer = None
        self.tfidf_matrix = None
        self.sbert_model = None
        self.sbert_embeddings = {}
        
        # Initialize TF-IDF vectorizer
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=self.tfidf_max_features,
            stop_words='english',
            min_df=2,  # Minimum document frequency
            ngram_range=(1, 2)  # Include bigrams
        )
        
        # Initialize SBERT model
        try:
            device = 'cuda' if self.use_gpu and torch.cuda.is_available() else 'cpu'
            self.sbert_model = SentenceTransformer(self.sbert_model_name, device=device)
            logger.info(f"SBERT model '{sbert_model_name}' loaded successfully on {device}")
        except Exception as e:
            logger.error(f"Error loading SBERT model: {e}")
            raise
        
        # Add new attribute for item details cache
        self.item_details = {}  # Dict[str, Dict[str, Any]]
    
    
    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text.
        
        Args:
            text: Raw text to clean
            
        Returns:
            Cleaned text
        """
        # Convert to lowercase
        text = text.lower()
        
        # Remove HTML tags
        text = re.sub(r'<.*?>', ' ', text)
        
        # Remove special characters and numbers, keeping spaces and alphanumeric
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Replace multiple spaces with a single space
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _build_tfidf_matrix(self) -> None:
        """Build TF-IDF matrix from product texts."""
        start_time = time.time()
        
        # Prepare corpus
        corpus = [self.product_texts[asin] for asin in self.product_asins]
        
        # Fit and transform corpus
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(corpus)
        
        logger.info(f"Built TF-IDF matrix with shape {self.tfidf_matrix.shape} in {time.time() - start_time:.2f} seconds")
    
    def _build_sbert_embeddings(self) -> None:
        """Build SBERT embeddings for all products."""
        if self.sbert_model is None:
            raise ValueError("SBERT model not initialized")
        
        start_time = time.time()
        
        # Process in batches to avoid memory issues
        for i in range(0, len(self.product_asins), self.batch_size):
            batch_asins = self.product_asins[i:i+self.batch_size]
            batch_texts = [self.product_texts[asin] for asin in batch_asins]
            
            # Encode texts to embeddings
            with torch.no_grad():
                batch_embeddings = self.sbert_model.encode(
                    batch_texts,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    batch_size=self.batch_size
                )
            
            # Store embeddings
            for j, asin in enumerate(batch_asins):
                self.sbert_embeddings[asin] = batch_embeddings[j]
            
            if i % (10 * self.batch_size) == 0 and i > 0:
                logger.info(f"Processed {i} items...")
        
        logger.info(f"Built SBERT embeddings for {len(self.sbert_embeddings)} items in {time.time() - start_time:.2f} seconds")
    
    def get_similar_items(
        self, 
        item_id: str, 
        n_recommendations: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get content-based recommendations similar to a given item.
        
        Args:
            item_id: ID of the item to find recommendations for
            n_recommendations: Number of recommendations to return
            
        Returns:
            List of recommended items with similarity scores and explanations
        """
        logger.info(f"Getting similar items for item {item_id}"
                    )
        if item_id not in self.product_asins:
            logger.warning(f"Item {item_id} not found in the database")
            return []
        
        # Get index of the item
        idx = self.product_asins.index(item_id)
        logger.info(f"Index of item {item_id}: {idx}")
        
        # Get TF-IDF similarity
        tfidf_sim = cosine_similarity(
            self.tfidf_matrix[idx:idx+1], 
            self.tfidf_matrix
        ).flatten()
        logger.info(f"TF-IDF similarity: {tfidf_sim}")
        
        # Get SBERT similarity
        item_embedding = self.sbert_embeddings[item_id].reshape(1, -1)
        sbert_sim = cosine_similarity(
            item_embedding, 
            np.array([self.sbert_embeddings[asin] for asin in self.product_asins])
        ).flatten()
        logger.info(f"SBERT similarity: {sbert_sim}")
        
        # Combine similarities with weights
        combined_sim = (self.tfidf_weight * tfidf_sim) + (self.sbert_weight * sbert_sim)
        
        # Get top similar items (excluding the item itself)
        similar_indices = combined_sim.argsort()[::-1][1:n_recommendations+1]
        
        # Create recommendations
        recommendations = []
        for i, idx in enumerate(similar_indices):
            similar_item_id = self.product_asins[idx]
            tfidf_score = tfidf_sim[idx]
            sbert_score = sbert_sim[idx]
            combined_score = combined_sim[idx]
            
            # Generate explanation
            explanation = self._generate_explanation(
                item_id, 
                similar_item_id, 
                combined_score, 
                tfidf_score, 
                sbert_score
            )
            
            recommendations.append({
                'rank': i + 1,
                'item_id': similar_item_id,
                'similarity_score': float(combined_score),
                'tfidf_score': float(tfidf_score),
                'sbert_score': float(sbert_score),
                'explanation': explanation
            })
        
        # Enhance recommendations with item details
        for item in recommendations:
            item['details'] = self.get_item_details(item['item_id'])
        
        return recommendations
    
    def get_recommendations_by_text(
        self, 
        query_text: str, 
        n_recommendations: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get content-based recommendations based on a text query.
        
        Args:
            query_text: Text query to find similar items for
            n_recommendations: Number of recommendations to return
            
        Returns:
            List of recommended items with similarity scores and explanations
        """
        
        logger.info(f"Getting recommendations by text: {query_text}")
        # Clean and preprocess the query text
        query_text = self._clean_text(query_text)
        logger.info(f"Cleander query text: {query_text}")
        
        # Get TF-IDF representation of the query
        query_tfidf = self.tfidf_vectorizer.transform([query_text])
        
        # Get SBERT embedding of the query
        query_sbert = self.sbert_model.encode([query_text], convert_to_numpy=True)
        
        # Calculate similarities
        tfidf_sim = cosine_similarity(
            query_tfidf, 
            self.tfidf_matrix
        ).flatten()
        
        logger.info(f"TF-IDF similarity: {tfidf_sim}")
        
        sbert_sim = cosine_similarity(
            query_sbert, 
            np.array([self.sbert_embeddings[asin] for asin in self.product_asins])
        ).flatten()
        
        logger.info(f"SBERT similarity: {sbert_sim}")
        # Combine similarities with weights
        combined_sim = (self.tfidf_weight * tfidf_sim) + (self.sbert_weight * sbert_sim)
        
        logger.info(f"Combined similarity: {combined_sim}")
        
        # Get top similar items
        top_indices = combined_sim.argsort()[::-1][:n_recommendations]
        
        # Create recommendations
        recommendations = []
        for i, idx in enumerate(top_indices):
            item_id = self.product_asins[idx]
            tfidf_score = tfidf_sim[idx]
            sbert_score = sbert_sim[idx]
            combined_score = combined_sim[idx]
            
            # Generate explanation
            explanation = self._generate_text_query_explanation(
                query_text, 
                item_id, 
                combined_score, 
                tfidf_score, 
                sbert_score
            )
            
            recommendations.append({
                'rank': i + 1,
                'item_id': item_id,
                'similarity_score': float(combined_score),
                'tfidf_score': float(tfidf_score),
                'sbert_score': float(sbert_score),
                'explanation': explanation
            })
        
        # Enhance recommendations with item details
        for item in recommendations:
            item['details'] = self.get_item_details(item['item_id'])
        
        return recommendations
    
    def _generate_explanation(
        self, 
        source_item_id: str, 
        similar_item_id: str, 
        combined_score: float, 
        tfidf_score: float, 
        sbert_score: float
    ) -> str:
        """
        Generate an explanation for content-based similarity.
        
        Args:
            source_item_id: ID of the source item
            similar_item_id: ID of the similar item
            combined_score: Combined similarity score
            tfidf_score: TF-IDF similarity score
            sbert_score: SBERT similarity score
            
        Returns:
            Explanation string
        """
        # Get most important words in common using TF-IDF
        source_idx = self.product_asins.index(source_item_id)
        similar_idx = self.product_asins.index(similar_item_id)
        
        # Get TF-IDF representations
        source_tfidf = self.tfidf_matrix[source_idx].toarray().flatten()
        similar_tfidf = self.tfidf_matrix[similar_idx].toarray().flatten()
        
        # Find common important terms
        common_terms = []
        feature_names = self.tfidf_vectorizer.get_feature_names_out()
        
        # Get indices of non-zero features in both items
        source_nonzero = set(source_tfidf.nonzero()[0])
        similar_nonzero = set(similar_tfidf.nonzero()[0])
        common_indices = source_nonzero.intersection(similar_nonzero)
        
        # Calculate importance as the product of TF-IDF values
        importance = {idx: source_tfidf[idx] * similar_tfidf[idx] for idx in common_indices}
        
        # Get top 3 most important common terms
        top_indices = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:3]
        common_terms = [feature_names[idx] for idx, _ in top_indices]
        
        # Generate explanation based on similarity scores
        if combined_score > 0.8:
            strength = "very similar"
        elif combined_score > 0.6:
            strength = "quite similar"
        elif combined_score > 0.4:
            strength = "somewhat similar"
        else:
            strength = "slightly similar"
        
        # Base explanation
        explanation = f"This item is {strength} to the original item"
        
        # Add common terms if available
        if common_terms:
            terms_str = ", ".join(common_terms)
            explanation += f", sharing key features like: {terms_str}"
        
        # Add additional context based on which similarity contributed more
        if tfidf_score > sbert_score * 1.2:  # TF-IDF score is significantly higher
            explanation += ". The items share many of the same specific words and phrases in their reviews."
        elif sbert_score > tfidf_score * 1.2:  # SBERT score is significantly higher
            explanation += ". The items are thematically similar in overall meaning and context."
        else:  # Scores are comparable
            explanation += ". The items share both specific words and overall themes."
        
        return explanation
    
    def _generate_text_query_explanation(
        self, 
        query_text: str, 
        item_id: str, 
        combined_score: float, 
        tfidf_score: float, 
        sbert_score: float
    ) -> str:
        """
        Generate an explanation for a text query match.
        
        Args:
            query_text: Original query text
            item_id: ID of the matching item
            combined_score: Combined similarity score
            tfidf_score: TF-IDF similarity score
            sbert_score: SBERT similarity score
            
        Returns:
            Explanation string
        """
        # Get TF-IDF representation of the query and the item
        query_tfidf = self.tfidf_vectorizer.transform([query_text]).toarray().flatten()
        item_idx = self.product_asins.index(item_id)
        item_tfidf = self.tfidf_matrix[item_idx].toarray().flatten()
        
        # Find common terms
        common_terms = []
        feature_names = self.tfidf_vectorizer.get_feature_names_out()
        
        # Get indices of non-zero features in both query and item
        query_nonzero = set(query_tfidf.nonzero()[0])
        item_nonzero = set(item_tfidf.nonzero()[0])
        common_indices = query_nonzero.intersection(item_nonzero)
        
        # Calculate importance as the product of TF-IDF values
        importance = {idx: query_tfidf[idx] * item_tfidf[idx] for idx in common_indices}
        
        # Get top 3 most important common terms
        top_indices = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:3]
        common_terms = [feature_names[idx] for idx, _ in top_indices]
        
        # Generate explanation based on similarity score
        if combined_score > 0.7:
            confidence = "strongly matches"
        elif combined_score > 0.5:
            confidence = "matches"
        elif combined_score > 0.3:
            confidence = "somewhat matches"
        else:
            confidence = "slightly matches"
        
        # Base explanation
        explanation = f"This item {confidence} your search"
        
        # Add common terms if available
        if common_terms:
            terms_str = ", ".join(common_terms)
            explanation += f" with key terms: {terms_str}"
        
        # Add additional context based on which similarity contributed more
        if tfidf_score > sbert_score * 1.2:  # TF-IDF score is significantly higher
            explanation += ". It contains many of the specific words from your search."
        elif sbert_score > tfidf_score * 1.2:  # SBERT score is significantly higher
            explanation += ". It matches the overall meaning of your search, though it may use different wording."
        
        return explanation
    
    def save_model(self, directory: str) -> None:
        """
        Save the model components to a directory.
        
        Args:
            directory: Directory to save the model
        """
        
        # Create directory if it doesn't exist
        os.makedirs(directory, exist_ok=True)
        
        # Save TF-IDF vectorizer
        with open(os.path.join(directory, 'tfidf_vectorizer.pkl'), 'wb') as f:
            pickle.dump(self.tfidf_vectorizer, f)
        
        # Save TF-IDF matrix (as sparse matrix)
        with open(os.path.join(directory, 'tfidf_matrix.pkl'), 'wb') as f:
            pickle.dump(self.tfidf_matrix, f)
        
        # Save SBERT embeddings
        with open(os.path.join(directory, 'sbert_embeddings.pkl'), 'wb') as f:
            pickle.dump(self.sbert_embeddings, f)
        
        # Save product texts and asins
        with open(os.path.join(directory, 'product_data.pkl'), 'wb') as f:
            pickle.dump({
                'product_texts': self.product_texts,
                'product_asins': self.product_asins,
                'item_details': self.item_details
            }, f)
        
        # Save configuration
        with open(os.path.join(directory, 'config.pkl'), 'wb') as f:
            pickle.dump({
                'sbert_model_name': self.sbert_model_name,
                'tfidf_max_features': self.tfidf_max_features,
                'batch_size': self.batch_size,
                'tfidf_weight': self.tfidf_weight,
                'sbert_weight': self.sbert_weight
            }, f)
        
        logger.info(f"Model saved to {directory}")
    
    @classmethod
    def load_model(cls, directory: str) -> 'ContentHybridItemBasedRec':
        """
        Load a saved model from a directory.
        
        Args:
            directory: Directory containing the saved model
            
        Returns:
            Initialized HybridContentRecommender with loaded model
        """
        
        if not os.path.exists(directory):
            logger.error(f"Directory {directory} does not exist")
            raise FileNotFoundError(f"Directory {directory} does not exist")
        
        # Load configuration
        with open(os.path.join(directory, 'config.pkl'), 'rb') as f:
            config = pickle.load(f)
        
        # Create a new instance
        recommender = cls(
            sbert_model_name=config['sbert_model_name'],
            tfidf_max_features=config['tfidf_max_features'],
            batch_size=config['batch_size'],
            tfidf_weight=config['tfidf_weight'],
            sbert_weight=config['sbert_weight']
        )
        
        # Load TF-IDF vectorizer
        with open(os.path.join(directory, 'tfidf_vectorizer.pkl'), 'rb') as f:
            recommender.tfidf_vectorizer = pickle.load(f)
        
        # Load TF-IDF matrix
        with open(os.path.join(directory, 'tfidf_matrix.pkl'), 'rb') as f:
            recommender.tfidf_matrix = pickle.load(f)
        
        # Load SBERT embeddings
        with open(os.path.join(directory, 'sbert_embeddings.pkl'), 'rb') as f:
            recommender.sbert_embeddings = pickle.load(f)
        
        # Load product data
        with open(os.path.join(directory, 'product_data.pkl'), 'rb') as f:
            product_data = pickle.load(f)
            recommender.product_texts = product_data['product_texts']
            recommender.product_asins = product_data['product_asins']
            recommender.item_details = product_data['item_details']
        
        logger.info(f"Model loaded from {directory}")
        
        return recommender
    
    def set_data(self, product_texts: Dict[str, str], product_asins: List[str], item_details: Dict[str, Dict[str, Any]]) -> None:
        """
        Load data that has been pre-processed by the AmazonDataProcessor.
        
        Args:
            product_texts: Dictionary mapping ASIN to combined text representation
            product_asins: List of product ASINs
            item_details: Dictionary mapping ASIN to item details (title, price, rating, etc.)
        """
        self.product_texts = product_texts
        self.product_asins = product_asins
        self.item_details = item_details
        
    def get_item_details(self, item_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific item.
        
        Args:
            item_id: ASIN of the item
            
        Returns:
            Dictionary containing item details (title, price, rating, etc.)
        """
        if item_id not in self.item_details:
            logger.warning(f"No details found for item {item_id}")
            return {}
            
        return self.item_details[item_id]
    
    def train_model(self, save_model: bool = False) -> None:
        """
        Train the model on the pre-processed data.
        """
        logger.info("Training model...")
        try:
            # Build TF-IDF matrix
            self._build_tfidf_matrix()
            
            # Build SBERT embeddings
            self._build_sbert_embeddings()
            
            logger.info("Model trained successfully")        
            
            if save_model:
                self.save_model(self.model_dir)
                logger.info(f"Model saved to {self.model_dir}")
                
        except Exception as e:
            logger.error(f"Error training model: {e}")
            exit(1)


# Add this near the bottom of the file, before the if __name__ == "__main__": block
def parse_args():
    parser = argparse.ArgumentParser(description='Content-Based Hybrid Recommender System')
    
    # Add arguments for different modes of operation
    parser.add_argument('--product_id', type=str, help='Product ID to find similar items')
    parser.add_argument('--query', type=str, help='Text query to find relevant items')
    parser.add_argument('--n_recommendations', type=int, default=5, help='Number of recommendations to return')
    
    return parser.parse_args()

if __name__ == "__main__":
    # Get command line arguments
    args = parse_args()
    
    # Add project root to Python path to enable imports
    sys.path.append(str(PROJECT_ROOT))
    
    # Import AmazonDataProcessor
    from src.utils.AmazonDataProcessor import load_processed_data_for_recommender, process_and_save_data
    
    # Define paths
    PROCESSED_DIR = DATASET_DIR / "processed_data"
    PROCESSED_COMBINE_DATA_FILE = PROCESSED_DIR / "combined_product_data.csv"
    PROCESSED_METADATA_FILE = PROCESSED_DIR / "processed_metadata.csv"
    PROCESSED_REVIEWS_FILE = PROCESSED_DIR / "processed_reviews.csv"
    metadata_file = DATASET_DIR / "meta_Electronics.jsonl"
    reviews_file = DATASET_DIR / "Electronics.jsonl"
    MODEL_DIR = DATASET_DIR / "models" / "content_hybrid_item_based_rec"
    
    # Create recommender
    recommender = ContentHybridItemBasedRec(
        sbert_model_name='all-MiniLM-L6-v2',
        tfidf_weight=0.3,
        sbert_weight=0.7
    )
    
    if os.path.exists(MODEL_DIR):
        print(f"Loading saved model from {MODEL_DIR}")
        recommender = recommender.load_model(MODEL_DIR)
    
    # Check if we have already processed data
    elif os.path.exists(PROCESSED_COMBINE_DATA_FILE) and os.path.exists(PROCESSED_METADATA_FILE) and os.path.exists(PROCESSED_REVIEWS_FILE):
        print(f"Loading pre-processed data from {PROCESSED_DIR}")
        
        # Use AmazonDataProcessor to load the data
        product_texts, product_asins, item_details = load_processed_data_for_recommender(PROCESSED_DIR)
        print('herere')
        # Load the data into the recommender
        recommender.set_data(product_texts, product_asins, item_details)
        recommender.train_model(save_model=True)
    else:
        logger.error(f"Pre-processed data files not found in {PROCESSED_DIR} - run AmazonDataProcessor to process the data")
        exit(1)

    
    # Now use the recommender for recommendations
    if args.product_id:
        similar_items = recommender.get_similar_items(args.product_id, args.n_recommendations)
        print(f"\nItems similar to '{args.product_id}':")
        for item in similar_items:
            print(f"{item['rank']}. {item['item_id']} (Score: {item['similarity_score']:.2f}) - {item['explanation']} \nDetails: {item['details']}\n")
    elif args.query:
        recommendations = recommender.get_recommendations_by_text(args.query, args.n_recommendations)
        print(f"\nRecommendations for '{args.query}':")
        for rec in recommendations:
            print(f"{rec['rank']}. {rec['item_id']} (Score: {rec['similarity_score']:.2f}) - {rec['explanation']} \nDetails: {rec['details']}")