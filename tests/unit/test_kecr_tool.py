"""
Unit tests for the KnowledgePathExtractor (KECR) tool.
"""

import pytest
from unittest.mock import MagicMock
from src.tools.kecr_tool import KnowledgePathExtractor, PathExtractionResult, GraphReasoningPath
from src.dialog_manager.session_schema import SessionContext, ExtractedParameters, DialogueState, SessionIntent, HardConstraint, SoftPreference, ConstraintOperator

def test_kecr_tool_initialization():
    """Test that KnowledgePathExtractor initializes correctly."""
    mock_db = MagicMock()
    extractor = KnowledgePathExtractor(db_connector=mock_db)
    assert extractor.db_connector == mock_db

def test_extract_paths_empty_candidates():
    mock_db = MagicMock()
    extractor = KnowledgePathExtractor(db_connector=mock_db)
    
    result = extractor.extract_paths(user_id="U1", candidate_items=[])
    assert result.total_paths_extracted == 0
    assert len(result.paths) == 0
    assert result.serialized_evidence_dict == []

def test_extract_paths_returns_correct_schema():
    """Test that extract_paths returns a PathExtractionResult."""
    mock_db = MagicMock()
    
    # Mock Neo4j execute_query
    mock_db.execute_query.return_value = [
        {
            "target_asin": "B123",
            "target_item": "Cool Phone",
            "composite_score": 0.85,
            "historical_score": 0.45,
            "conversational_score": 0.40,
            "reasoning_path": "Matches requested feature: Color (Black)"
        }
    ]
    
    extractor = KnowledgePathExtractor(db_connector=mock_db)
    
    session_ctx = SessionContext(
        user_id="U1",
        session_id="S1",
        dialogue_state=DialogueState(),
        extracted_parameters=ExtractedParameters(
            hard_constraints=[HardConstraint(attribute="brand", operator=ConstraintOperator.EQUAL, value="Samsung")],
            soft_preferences=[SoftPreference(category="Color", value="Black", polarity=1.0)]
        ),
        session_intent=SessionIntent.INITIAL_SEARCH
    )
    
    result = extractor.extract_paths(user_id="U1", candidate_items=[{"asin": "B123"}], session_context=session_ctx)
    
    assert isinstance(result, PathExtractionResult)
    assert result.total_paths_extracted == 1
    assert result.paths[0].target_asin == "B123"
    assert result.paths[0].path_type == "DUAL_CONTEXT"  # Both > 0
    
def test_to_evidence_dicts_formatting():
    """Test that to_evidence_dicts formats the output correctly for the PromptConstructor."""
    mock_db = MagicMock()
    mock_db.execute_query.return_value = [
        {
            "target_asin": "B123",
            "target_item": "Cool Phone",
            "composite_score": 0.6,
            "historical_score": 0.6,
            "conversational_score": 0.0,
            "reasoning_path": "User bought together with previously purchased 'Case'"
        }
    ]
    
    extractor = KnowledgePathExtractor(db_connector=mock_db)
    
    result = extractor.extract_paths(user_id="U1", candidate_items=[{"asin": "B123"}])
    
    ev_dicts = result.serialized_evidence_dict
    assert len(ev_dicts) == 1
    assert ev_dicts[0]["target_item"] == "Cool Phone"
    assert ev_dicts[0]["reasoning_path"] == "User bought together with previously purchased 'Case'"
    assert result.paths[0].path_type == "CO_PURCHASE"

def test_extract_paths_determines_path_type_correctly():
    mock_db = MagicMock()
    # Test combinations of s_hist and s_conv
    mock_db.execute_query.return_value = [
        {
            "target_asin": "B1",
            "target_item": "Item 1",
            "composite_score": 0.0,
            "historical_score": 0.0,
            "conversational_score": 0.0,
            "reasoning_path": "Fallback"
        },
        {
            "target_asin": "B2",
            "target_item": "Item 2",
            "composite_score": 0.5,
            "historical_score": 0.0,
            "conversational_score": 0.5,
            "reasoning_path": "Matches brand"
        },
        {
            "target_asin": "B3",
            "target_item": "Item 3",
            "composite_score": 0.5,
            "historical_score": 0.5,
            "conversational_score": 0.0,
            "reasoning_path": "Shares specific category"
        }
    ]
    
    extractor = KnowledgePathExtractor(db_connector=mock_db)
    result = extractor.extract_paths(user_id="U1", candidate_items=[{"asin": "B1"}, {"asin": "B2"}, {"asin": "B3"}])
    
    types = [p.path_type for p in result.paths]
    assert types[0] == "SPARSE_FALLBACK"
    assert types[1] == "CONVERSATIONAL_MATCH"
    assert types[2] == "HISTORICAL_COMPATIBILITY"
