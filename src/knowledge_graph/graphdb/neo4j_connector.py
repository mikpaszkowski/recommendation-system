"""Neo4j database connector for knowledge graph operations."""

import os
import logging
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable, AuthError
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


class Neo4jConnector:
    """
    A connector class for Neo4j database operations.
    
    This class manages connections to a Neo4j database using credentials
    from environment variables. It provides methods for executing queries,
    managing transactions, and ensuring proper resource cleanup.
    
    Environment Variables:
        NEO4J_URI: The URI of the Neo4j database (e.g., bolt://localhost:7687)
        NEO4J_USER: The username for authentication
        NEO4J_PASSWORD: The password for authentication
        NEO4J_DATABASE: The database name (default: neo4j)
    
    Example:
        >>> connector = Neo4jConnector()
        >>> connector.connect()
        >>> result = connector.execute_query("MATCH (n) RETURN count(n) as count")
        >>> connector.close()
        
        Or using context manager:
        >>> with Neo4jConnector() as connector:
        ...     result = connector.execute_query("MATCH (n) RETURN count(n)")
    """
    
    def __init__(self, env_path: Optional[str] = None):
        """
        Initialize the Neo4j connector.
        
        Args:
            env_path: Optional path to .env file. If not provided, looks for .env
                     in the current directory or parent directories.
        """
        # Load environment variables
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()
        
        # Get configuration from environment variables
        self.uri = os.getenv("NEO4J_URI")
        self.user = os.getenv("NEO4J_USER")
        self.password = os.getenv("NEO4J_PASSWORD")
        self.database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        # Validate required environment variables
        self._validate_config()
        
        # Driver instance (initialized on connect)
        self._driver: Optional[Driver] = None
        self._is_connected = False
    
    def _validate_config(self) -> None:
        """Validate that all required configuration is present."""
        missing = []
        if not self.uri:
            missing.append("NEO4J_URI")
        if not self.user:
            missing.append("NEO4J_USER")
        if not self.password:
            missing.append("NEO4J_PASSWORD")
        
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Please ensure they are set in your .env file."
            )
    
    def connect(self) -> None:
        """
        Establish connection to the Neo4j database.
        
        Raises:
            ServiceUnavailable: If the database is not reachable
            AuthError: If authentication fails
        """
        if self._is_connected:
            logger.warning("Already connected to Neo4j database")
            return
        
        try:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
            # Verify connectivity
            self._driver.verify_connectivity()
            self._is_connected = True
            logger.info(f"Successfully connected to Neo4j at {self.uri}")
        except ServiceUnavailable as e:
            logger.error(f"Failed to connect to Neo4j at {self.uri}: {e}")
            raise
        except AuthError as e:
            logger.error(f"Authentication failed for user {self.user}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error connecting to Neo4j: {e}")
            raise
    
    def close(self) -> None:
        """Close the database connection and cleanup resources."""
        if self._driver is not None:
            self._driver.close()
            self._is_connected = False
            logger.info("Neo4j connection closed")
    
    def is_connected(self) -> bool:
        """
        Check if the connector is currently connected to the database.
        
        Returns:
            bool: True if connected, False otherwise
        """
        return self._is_connected and self._driver is not None
    
    @contextmanager
    def session(self, **kwargs) -> Session:
        """
        Context manager for Neo4j sessions.
        
        Args:
            **kwargs: Additional arguments to pass to the session
        
        Yields:
            Session: A Neo4j session object
            
        Example:
            >>> with connector.session() as session:
            ...     result = session.run("MATCH (n) RETURN n LIMIT 10")
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to database. Call connect() first.")
        
        session = self._driver.session(database=self.database, **kwargs)
        try:
            yield session
        finally:
            session.close()
    
    def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query and return results.
        
        Args:
            query: The Cypher query to execute
            parameters: Optional parameters for the query
            database: Optional database name (overrides default)
        
        Returns:
            List of dictionaries containing query results
            
        Example:
            >>> results = connector.execute_query(
            ...     "MATCH (p:Product {asin: $asin}) RETURN p",
            ...     parameters={"asin": "B001234567"}
            ... )
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to database. Call connect() first.")
        
        db = database or self.database
        parameters = parameters or {}
        
        try:
            with self._driver.session(database=db) as session:
                result = session.run(query, parameters)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            logger.debug(f"Query: {query}, Parameters: {parameters}")
            raise
    
    def execute_write_transaction(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a write transaction (CREATE, UPDATE, DELETE operations).
        
        Args:
            query: The Cypher query to execute
            parameters: Optional parameters for the query
            database: Optional database name (overrides default)
        
        Returns:
            List of dictionaries containing query results
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to database. Call connect() first.")
        
        db = database or self.database
        parameters = parameters or {}
        
        def _execute_write(tx):
            result = tx.run(query, parameters)
            return [dict(record) for record in result]
        
        try:
            with self._driver.session(database=db) as session:
                return session.execute_write(_execute_write)
        except Exception as e:
            logger.error(f"Error executing write transaction: {e}")
            logger.debug(f"Query: {query}, Parameters: {parameters}")
            raise
    
    def execute_read_transaction(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a read transaction (MATCH, RETURN operations).
        
        Args:
            query: The Cypher query to execute
            parameters: Optional parameters for the query
            database: Optional database name (overrides default)
        
        Returns:
            List of dictionaries containing query results
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to database. Call connect() first.")
        
        db = database or self.database
        parameters = parameters or {}
        
        def _execute_read(tx):
            result = tx.run(query, parameters)
            return [dict(record) for record in result]
        
        try:
            with self._driver.session(database=db) as session:
                return session.execute_read(_execute_read)
        except Exception as e:
            logger.error(f"Error executing read transaction: {e}")
            logger.debug(f"Query: {query}, Parameters: {parameters}")
            raise
    
    def verify_connection(self) -> bool:
        """
        Verify that the connection to the database is working.
        
        Returns:
            bool: True if connection is valid, False otherwise
        """
        if not self.is_connected():
            return False
        
        try:
            self._driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error(f"Connection verification failed: {e}")
            return False
    
    def get_database_info(self) -> Dict[str, Any]:
        """
        Get information about the connected database.
        
        Returns:
            Dictionary containing database information
        """
        query = """
        CALL dbms.components() YIELD name, versions, edition
        RETURN name, versions, edition
        """
        try:
            results = self.execute_query(query)
            if results:
                return results[0]
            return {}
        except Exception as e:
            logger.error(f"Failed to get database info: {e}")
            return {}
    
    def clear_database(self) -> None:
        """
        Clear all nodes and relationships from the database.
        
        WARNING: This will delete all data in the database!
        Use with caution, typically only in development/testing.
        """
        query = "MATCH (n) DETACH DELETE n"
        try:
            self.execute_write_transaction(query)
            logger.info("Database cleared successfully")
        except Exception as e:
            logger.error(f"Failed to clear database: {e}")
            raise
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
    
    def __repr__(self) -> str:
        """String representation of the connector."""
        status = "connected" if self._is_connected else "disconnected"
        return f"Neo4jConnector(uri={self.uri}, database={self.database}, status={status})"

