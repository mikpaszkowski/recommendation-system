import pytest
from src.llm_interface.prompt_constructor import PromptConstructor

def test_prompt_constructor_without_graph_paths():
    """
    Test AC-001 & AC-003: Signature accepts omission, and [GRAPH EVIDENCE] is omitted.
    """
    constructor = PromptConstructor()
    prompt = constructor.construct_recommendation_prompt(
        user_query="I need a laptop",
        retrieved_items=[{"details": {"title": "Macbook Air"}}]
    )
    
    # Check the HumanMessage content
    content = prompt[1].content
    
    assert "[GRAPH EVIDENCE]" not in content
    assert "Synthesize Evidence (CRITICAL)" not in content

def test_prompt_constructor_with_graph_paths():
    """
    Test AC-002 & AC-004: [GRAPH EVIDENCE] is included and Synthesized Grounding rules are enforced.
    """
    constructor = PromptConstructor()
    graph_paths = [
        {"target_item": "Macbook Air", "reasoning_path": "(User)-[BOUGHT]->(Macbook Air)"}
    ]
    
    prompt = constructor.construct_recommendation_prompt(
        user_query="I need a laptop",
        retrieved_items=[{"details": {"title": "Macbook Air"}}],
        graph_reasoning_paths=graph_paths
    )
    
    content = prompt[1].content
    
    # Check Evidence block injection
    assert "[GRAPH EVIDENCE]" in content
    assert "- Evidence for 'Macbook Air': (User)-[BOUGHT]->(Macbook Air)" in content
    
    # Check Synthesized Grounding rules
    assert "Synthesize Evidence (CRITICAL)" in content
    assert "connecting the User's Explicit Preferences directly to the [GRAPH EVIDENCE]" in content
