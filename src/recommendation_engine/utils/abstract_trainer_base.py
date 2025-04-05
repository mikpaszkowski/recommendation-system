from abc import ABC, abstractmethod

# nice-to-have separate implementation for each trainer

class AbstractTrainerBase(ABC):
    """
    Abstract base class for classes that train recommendation models.
    """

    @abstractmethod
    def train(self, save_model: bool = False) -> None:
        """
        Train the recommendation model.
        """
        pass

    @abstractmethod
    def evaluate(self, dataset: str = 'test') -> float:
        """
        Evaluate the recommendation model.
        """
        pass
