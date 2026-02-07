import logging
from typing import List, Union
import os

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    Service for generating text embeddings using sentence-transformers.
    Defaults to 'all-MiniLM-L6-v2' for a good balance of speed and performance.
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if SentenceTransformer is None:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Please run `pip install sentence-transformers`."
            )
        
        logger.info(f"Loading embedding model: {model_name}")
        # Use a local cache if desired, but default behavior is usually fine
        self.model = SentenceTransformer(model_name)
        self.dimension = self.model.get_sentence_embedding_dimension()
        logger.info(f"Model loaded. Dimension: {self.dimension}")

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single string.
        """
        if not text:
            return []
        embeddings = self.model.encode(text, convert_to_numpy=True)
        return embeddings.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of strings.
        """
        if not texts:
            return []
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()
