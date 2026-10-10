"""
Database connection adapter for Neo4j operations.
Re-exports Neo4jConnector as Neo4jConnectionManager for unified database access.
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, List, Any

from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

logger = logging.getLogger(__name__)

# Primary alias per project convention
Neo4jConnectionManager = Neo4jConnector

__all__ = ["Neo4jConnectionManager", "Neo4jConnector"]
