from typing import Dict, Any, List, Optional
import logging

from src.knowledge_graph.graphdb.graph_query_manager import GraphQueryManager

logger = logging.getLogger(__name__)

class GraphSearchTool:
    """
    Tool for searching the Knowledge Graph for products based on user preferences.
    Wraps GraphQueryManager.
    """
    def __init__(self, graph_query_manager: Optional[GraphQueryManager] = None):
        self.manager = graph_query_manager or GraphQueryManager()

    def search(self, query: str, preferences: Dict[str, Any], user_profile: Optional[Dict[str, Any]] = None, history: Optional[List] = None) -> Dict[str, Any]:
        """
        Executes the search via GraphQueryManager.
        
        Args:
            query: The user's natural language query.
            preferences: Structured preferences (weighted).
            user_profile: The full user profile context.
            history: Conversation history.
            
        Returns:
            A dictionary containing:
            - "items": List of found products.
            - "count": Number of items found.
            - "status": "success", "no_results", or "error".
            - "metadata": Detailed metadata (e.g. Cypher query used, though not exposed here by default).
        """
        logger.info(f"GraphSearchTool: Searching for '{query}' with preferences")
        
        try:
            items = self.manager.retrieve_items(
                user_query=query,
                preferences=preferences,
                user_profile=user_profile,
                conversation_history=history
            )
            
            return {
                "items": items,
                "count": len(items),
                "status": "success" if items else "no_results"
            }
        except Exception as e:
            logger.error(f"GraphSearchTool error: {e}")
            return {
                "items": [],
                "count": 0,
                "status": "error",
                "error": str(e)
            }
