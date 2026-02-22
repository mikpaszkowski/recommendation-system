import json
import logging
import os
from typing import Any, Dict

from graph_query_manager import GraphQueryManager


def _sample_payload() -> Dict[str, Any]:
    return {
        "user_query": "I want wireless noise-cancelling headphones under $300 from Sony or Bose.",
        "preferences": {
            "weighted_preferences": {
                "likes": [{"value": "noise cancelling headphones", "weight": 0.8}],
                "dislikes": [],
                "constraints": {
                    "brands": ["Sony", "Bose"],
                    "price_range": ["$150-$400"],
                    "categories": ["Headphones"],
                },
            },
            "intent": "recommendation",
            "notes": "Focus on wireless ANC headphones.",
        },
        "user_profile": {"preferences": {"likes": ["audio"]}},
        "conversation_history": [
            {"user": "I'm looking for better sound for travel."},
            {"assistant": "Do you have a budget in mind?"},
        ],
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("graph_query_mapping_test")

    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY is not set. Set it to run the LLM query.")
        return

    if not os.getenv("NEO4J_URI"):
        logger.error("NEO4J_URI is not set. Set Neo4j env vars to run the query.")
        return

    payload = _sample_payload()
    logger.info("Payload: %s", json.dumps(payload, indent=2))
    manager = GraphQueryManager()

    logger.info("Building Cypher query from sample preferences.")
    query_payload = manager.build_query(
        user_query=payload["user_query"],
        preferences=payload["preferences"],
        user_profile=payload["user_profile"],
        conversation_history=payload["conversation_history"],
    )
    logger.info("Generated query payload:\n%s", json.dumps(query_payload, indent=2))

    logger.info("Executing query and mapping results.")
    items = manager.retrieve_items(
        user_query=payload["user_query"],
        preferences=payload["preferences"],
        user_profile=payload["user_profile"],
        conversation_history=payload["conversation_history"],
    )
    logger.info("Mapped %d items.", len(items))
    logger.info("Mapped items sample:\n%s", json.dumps(items[:5], indent=2))


if __name__ == "__main__":
    main()

