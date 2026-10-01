import pytest
import asyncio
from typing import Dict, Any, List
from unittest.mock import AsyncMock

from src.agents.critic_agent import CriticAgent

@pytest.fixture
def mock_llm_handler():
    return AsyncMock()

def test_evaluate_candidate_tradeoffs_semantic_betrayal(mock_llm_handler):
    mock_llm_handler.aquery.return_value = """
    ```json
    {
      "ranked_candidates": [
        {
          "id": "1",
          "title": "Wireless Mouse",
          "fit_score": 95,
          "reasoning": "Fits wireless requirement.",
          "is_recommended": true
        },
        {
          "id": "2",
          "title": "Wired Mouse",
          "fit_score": 10,
          "reasoning": "Semantic betrayal: Wired instead of wireless.",
          "is_recommended": false
        }
      ],
      "disclosure_statement": null,
      "rationale": "Filtered wired mouse."
    }
    ```
    """
    critic = CriticAgent(llm_handler=mock_llm_handler)
    candidates = [{"id": "1", "title": "Wireless Mouse"}, {"id": "2", "title": "Wired Mouse"}]
    
    result = asyncio.run(critic.evaluate_candidate_tradeoffs(candidates, {"preferences": "Wireless"}))
    
    assert len(result["ranked_candidates"]) == 1
    assert result["ranked_candidates"][0]["id"] == "1"
    assert result["disclosure_statement"] is None

def test_evaluate_candidate_tradeoffs_macs_disclosure(mock_llm_handler):
    mock_llm_handler.aquery.return_value = """
    ```json
    {
      "ranked_candidates": [
        {
          "id": "1",
          "title": "Expensive Monitor",
          "fit_score": 90,
          "reasoning": "Good fit but expensive.",
          "is_recommended": true
        }
      ],
      "disclosure_statement": "I couldn't find an exact match under your budget, but I found this highly-reviewed option for $450. Would you be willing to expand your budget?",
      "rationale": "MACS triggered, prepared trade-off."
    }
    ```
    """
    critic = CriticAgent(llm_handler=mock_llm_handler)
    candidates = [{"id": "1", "title": "Expensive Monitor", "price": 450.0}]
    relaxed_constraints = ["Widened budget ceiling by 15%"]
    
    result = asyncio.run(critic.evaluate_candidate_tradeoffs(candidates, {}, relaxed_constraints))
    
    assert len(result["ranked_candidates"]) == 1
    assert "expand your budget" in result["disclosure_statement"]

def test_evaluate_candidate_tradeoffs_empty_candidates():
    critic = CriticAgent()
    result = asyncio.run(critic.evaluate_candidate_tradeoffs([], {}))
    assert result["ranked_candidates"] == []
    assert result["disclosure_statement"] is None
