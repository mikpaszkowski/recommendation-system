from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any

# nice-to-have separate implementation for each recommender loader

class AbstractRecommenderDataLoader:

    @abstractmethod
    def get_model(self) -> Any:
        """
        Get the trained model instance.
        
        Returns:
            The trained model
        """
        pass

    @abstractmethod
    def train(self) -> None:
        """
        Train the model on the loaded data.
        """
        pass

    @abstractmethod
    def evaluate(self, dataset: str = 'test') -> float:
        """
        Validate model performance on validation set.
        
        Returns:
            Validation metric score
        """
        pass

    @abstractmethod
    def load_data(self, data_dir: str) -> None:
        """
        Load training, validation and test data.
        
        Args:
            data_dir: Directory containing the data files
        """
        pass

    @abstractmethod
    def save_model(self, filepath: str) -> None:
        """
        Save trained model to file.
        
        Args:
            filepath: Path to save the model
        """
        pass

    @classmethod
    @abstractmethod
    def load_model(cls, filepath: str) -> Any:
        """
        Load a trained model from file.
        
        Args:
            filepath: Path to the saved model
            
        Returns:
            Loaded model instance
        """
        pass