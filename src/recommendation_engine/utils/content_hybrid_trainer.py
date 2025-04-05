import logging
import time
import torch
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from src.recommendation_engine.utils.abstract_trainer_base import AbstractTrainerBase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ContentHybridTrainer(AbstractTrainerBase):
    """
    Trainer for the content-hybrid recommendation model.
    """
    
    def __init__(self, model_dir: str, batch_size: int = 32):
        self.model_dir = model_dir
        self.batch_size = batch_size
        self.tfidf_vectorizer = TfidfVectorizer(max_features=5000)
        self.sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
        self.sbert_embeddings = {}
        self.tfidf_matrix = None
        

    def train(self, save_model: bool = False) -> None:
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
    
        

