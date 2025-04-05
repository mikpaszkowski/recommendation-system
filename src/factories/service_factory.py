"""Factory for creating and configuring application services."""

import os
import logging
from typing import Optional
from pathlib import Path

from src.recommendation_engine.recommenders.content_hybrid_item_based_rec import ContentHybridItemBasedRec
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm.abstract_llm_handler import LLMHandlerInterface
from src.llm_interface.recommendation_api import RecommendationAPI
from src.llm_interface.preference_parser import PreferenceParser
from src.llm_interface.prompt_constructor import PromptConstructor
from src.dialog_manager.simple_dialog_manager import SimpleDialogManager
from src.user.profile_manager import InMemoryUserProfileManager
from src.conversation.history_manager import InMemoryConversationManager

# Configure logging
logger = logging.getLogger(__name__)

class ServiceFactory:
    """Factory for creating and configuring application services."""
    
    _instance = None
    _initialized = False
    
    # Services that will be cached
    _content_recommender = None
    _llm_handler = None
    _dialog_manager = None
    
    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super(ServiceFactory, cls).__new__(cls)
        return cls._instance
    
    def initialize(self, force: bool = False) -> None:
        """
        Initialize all services.
        
        Args:
            force: If True, reinitialize even if already initialized
        """
        if self._initialized and not force:
            logger.info("Services already initialized")
            return
            
        logger.info("Initializing application services...")
        
        try:
            # The initialization is performed lazily
            self._initialized = True
            logger.info("Services initialization complete")
        except Exception as e:
            logger.error(f"Error initializing services: {e}")
            self._initialized = False
            raise
    
    def get_content_recommender(self) -> ContentHybridItemBasedRec:
        """
        Get the content-based recommender.
        
        Returns:
            Content-based recommender instance
        """
        if self._content_recommender is None:
            logger.info("Initializing content recommender...")
            
            try:
                content_hybrid_item_based_rec = ContentHybridItemBasedRec()
                self._content_recommender = content_hybrid_item_based_rec.get_model()
                logger.info("Content recommender initialized")
            except Exception as e:
                logger.error(f"Failed to initialize content recommender: {e}")
                raise
                
        return self._content_recommender
    
    def get_llm_handler(self) -> LLMHandlerInterface:
        """
        Get the LLM handler.
        
        Returns:
            LLM handler instance
        """
        if self._llm_handler is None:
            logger.info("Initializing LLM handler...")
            
            try:
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    logger.warning("OPENAI_API_KEY not found in environment variables")
                    
                self._llm_handler = SimpleLLMHandler(api_key=api_key)
                logger.info("LLM handler initialized")
            except Exception as e:
                logger.error(f"Failed to initialize LLM handler: {e}")
                raise
                
        return self._llm_handler
    
    def get_dialog_manager(self) -> SimpleDialogManager:
        """
        Get the dialog manager with all dependencies.
        
        Returns:
            Dialog manager instance with all dependencies initialized
        """
        if self._dialog_manager is None:
            logger.info("Initializing dialog manager and dependencies...")
            
            try:
                # Get or create the recommender
                recommender = self.get_content_recommender()
                
                # Get or create the LLM handler
                llm_handler = self.get_llm_handler()
                
                # Create preference parser
                preference_parser = PreferenceParser()
                
                # Create prompt constructor
                prompt_constructor = PromptConstructor()
                
                # Create user profile manager
                profile_manager = InMemoryUserProfileManager()
                
                # Create conversation history manager
                conversation_manager = InMemoryConversationManager()
                
                # Create recommendation API
                recommendation_api = RecommendationAPI(
                    recommender=recommender,
                    preference_parser=preference_parser,
                    prompt_constructor=prompt_constructor,
                )
                
                # Create dialog manager
                self._dialog_manager = SimpleDialogManager(
                    recommendation_api=recommendation_api,
                    llm_handler=llm_handler
                )
                
                logger.info("Dialog manager initialized")
            except Exception as e:
                logger.error(f"Failed to initialize dialog manager: {e}")
                raise
                
        return self._dialog_manager 