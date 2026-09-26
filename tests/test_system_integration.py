"""
tests/test_system_integration.py

Milestone 4 System Integration & Multi-Turn Verification Test Suite.
Verifies:
1. Multi-turn pipeline state accumulation and intent progression across 4 turns.
2. Strict adherence to canonical current_session_context JSON schema at every turn.
3. Constraint overrides, range modifications, and soft preference updates.
4. Downstream adapter compatibility (GraphSearchTool filters, legacy preferences, routing actions).
5. Clean offline execution of test scripts (scripts/run_preference_parser.py and scripts/run_multi_turn_dialogue.py).
6. Subprocess execution covering demo, mock, json-only, and single-utterance modes.

Executes 100% offline, deterministically, with no external OpenAI or Neo4j dependencies.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, List
from pathlib import Path

import pytest

from scripts.run_preference_parser import (
    DEMO_SCENARIOS,
    MockPreferenceParser,
    _extract_categories,
    _resolve_categories,
    process_dialogue_turn,
)
from src.dialog_manager.dialogue_manager import DialogueManager
from src.dialog_manager.session_adapter import (
    hard_constraints_to_structured_filters,
    session_context_to_structured_filters,
    session_context_to_dialogue_action,
    session_context_to_legacy_preferences,
)
from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContextWrapper,
    SessionIntent,
    SuggestedSystemAction,
)
from tests.e2e.schema_validator import assert_valid_session_context

REPO_ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# Pipeline Integration Tests
# ==============================================================================

class TestMultiTurnPipelineIntegration:
    """Verifies end-to-end multi-turn conversation accumulation and schema adherence."""

    def test_canonical_4turn_laptop_dialogue_progression(self):
        """
        Feed 4-turn college student laptop scenario:
        - Turn 1: initial_search (laptop, unready, missing price)
        - Turn 2: refining_options (budget < $1000, exclude ChromeOS, ready)
        - Turn 3: comparing_items (Apple vs Dell XPS)
        - Turn 4: finalizing_choice (MacBook Air M1 < $900, budget override)
        """
        dm = DialogueManager(critical_attributes=["category", "price"])
        parser = MockPreferenceParser()
        sess_id = "test_canon_4turn"

        turns = DEMO_SCENARIOS["college_laptop"]
        assert len(turns) == 4

        # --- Turn 1 ---
        _, w1, s1 = process_dialogue_turn(parser, dm, sess_id, turns[0], turn_num=1)
        assert_valid_session_context(w1.to_dict())
        ctx1 = w1.current_session_context
        assert ctx1.session_intent == SessionIntent.INITIAL_SEARCH
        assert ctx1.dialogue_state.ready_for_recommendation is False
        assert "price" in ctx1.dialogue_state.missing_critical_attributes
        assert ctx1.dialogue_state.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION
        assert len(ctx1.extracted_parameters.hard_constraints) == 1
        assert ctx1.extracted_parameters.hard_constraints[0].attribute == "category"
        assert len(ctx1.extracted_parameters.soft_preferences) == 2

        # --- Turn 2 ---
        _, w2, s2 = process_dialogue_turn(parser, dm, sess_id, turns[1], turn_num=2, prev_summary=s1)
        assert_valid_session_context(w2.to_dict())
        ctx2 = w2.current_session_context
        assert ctx2.session_intent == SessionIntent.REFINING_OPTIONS
        assert ctx2.dialogue_state.ready_for_recommendation is True
        assert len(ctx2.dialogue_state.missing_critical_attributes) == 0
        assert ctx2.dialogue_state.suggested_system_action == SuggestedSystemAction.PRESENT_RESULTS
        assert len(ctx2.extracted_parameters.hard_constraints) == 3

        # --- Turn 3 ---
        _, w3, s3 = process_dialogue_turn(parser, dm, sess_id, turns[2], turn_num=3, prev_summary=s2)
        assert_valid_session_context(w3.to_dict())
        ctx3 = w3.current_session_context
        assert ctx3.session_intent == SessionIntent.COMPARING_ITEMS
        assert ctx3.dialogue_state.ready_for_recommendation is True
        # Verify Apple and Dell soft preferences accumulated
        brands = [sp.value for sp in ctx3.extracted_parameters.soft_preferences if sp.category == "brand"]
        assert "Apple" in brands
        assert "Dell" in brands

        # --- Turn 4 ---
        _, w4, s4 = process_dialogue_turn(parser, dm, sess_id, turns[3], turn_num=4, prev_summary=s3)
        assert_valid_session_context(w4.to_dict())
        ctx4 = w4.current_session_context
        assert ctx4.session_intent == SessionIntent.FINALIZING_CHOICE
        assert ctx4.dialogue_state.ready_for_recommendation is True

        # Verify price constraint override: was 1000 in Turn 2, now 900 in Turn 4
        price_constraints = [c for c in ctx4.extracted_parameters.hard_constraints if c.attribute == "price"]
        assert len(price_constraints) == 1
        assert price_constraints[0].value == 900
        assert price_constraints[0].operator == ConstraintOperator.LESS_THAN

        # Verify model constraint added
        model_constraints = [c for c in ctx4.extracted_parameters.hard_constraints if c.attribute == "model"]
        assert len(model_constraints) == 1
        assert model_constraints[0].value == "MacBook Air M1"

    def test_topic_shift_and_reset_pipeline(self):
        """Verify topic shifting scenario and session reset."""
        dm = DialogueManager(critical_attributes=["category", "price"])
        parser = MockPreferenceParser()
        sess_id = "test_topic_shift_sess"

        turns = DEMO_SCENARIOS["topic_shift"]

        # Turn 1: gaming PC
        _, w1, _ = process_dialogue_turn(parser, dm, sess_id, turns[0], turn_num=1)
        assert_valid_session_context(w1.to_dict())
        assert w1.current_session_context.session_intent == SessionIntent.INITIAL_SEARCH

        # Turn 2: pivot to headphones
        _, w2, _ = process_dialogue_turn(parser, dm, sess_id, turns[1], turn_num=2)
        assert_valid_session_context(w2.to_dict())
        # Check categorical pivot was handled
        cats = [c.value for c in w2.current_session_context.extracted_parameters.hard_constraints if c.attribute == "category"]
        assert "headphones" in cats

        # Reset session
        dm.reset_session(sess_id)
        cleared = dm.get_context(sess_id)
        assert len(cleared.extracted_parameters.hard_constraints) == 0
        assert cleared.session_intent == SessionIntent.INITIAL_SEARCH


# ==============================================================================
# Downstream Adapter Conformance Tests
# ==============================================================================

class TestDownstreamAdapterIntegration:
    """Verifies that accumulated session context adapts cleanly to downstream systems."""

    def test_adapter_projection_from_multi_turn_state(self):
        """Ensure multi-turn state produces correct structured filters and legacy preferences."""
        dm = DialogueManager(critical_attributes=["category", "price"])
        parser = MockPreferenceParser()
        sess_id = "test_adapter_proj"

        for idx, text in enumerate(DEMO_SCENARIOS["college_laptop"], start=1):
            process_dialogue_turn(parser, dm, sess_id, text, turn_num=idx)

        ctx = dm.get_context(sess_id)

        # 1. GraphSearchTool filters via both adapters
        filters = hard_constraints_to_structured_filters(ctx.extracted_parameters.hard_constraints)
        assert filters["price_max"] == 900.0
        assert filters["category"] == "laptop"

        filters_from_ctx = session_context_to_structured_filters(ctx)
        assert filters_from_ctx["price_max"] == 900.0
        assert filters_from_ctx["category"] == "laptop"

        # 2. Legacy preferences dict
        legacy = session_context_to_legacy_preferences(ctx)
        assert "constraints" in legacy
        assert "current_session_context" in legacy
        assert legacy["constraints"]["price_max"] == 900.0

        # 3. Dialogue action
        action = session_context_to_dialogue_action(ctx)
        assert action in ("recommend", "present_results", "search", "RECOMMEND", "SEARCH")


# ==============================================================================
# Subprocess CLI Execution Tests
# ==============================================================================

class TestScriptSubprocessExecution:
    """Tests executing scripts via subprocess with various CLI argument combinations."""

    def test_run_preference_parser_demo_mock(self):
        """Execute python scripts/run_preference_parser.py --demo --mock."""
        cmd = [sys.executable, "scripts/run_preference_parser.py", "--demo", "--mock"]
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res.returncode == 0, f"Script failed with stderr:\n{res.stderr}"
        assert "RUNNING DEMO SCENARIO: COLLEGE_LAPTOP" in res.stdout
        assert "Demo Scenario Completed Successfully" in res.stdout
        assert "current_session_context" in res.stdout

    def test_run_preference_parser_single_utterance(self):
        """Execute python scripts/run_preference_parser.py --mock 'I need a laptop under 1000'."""
        cmd = [sys.executable, "scripts/run_preference_parser.py", "--mock", "I need a laptop under $1000"]
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res.returncode == 0, f"Script failed with stderr:\n{res.stderr}"
        assert "current_session_context" in res.stdout
        assert "TURN 1" in res.stdout

    def test_run_preference_parser_json_only(self):
        """Execute python scripts/run_preference_parser.py --demo --mock --json."""
        cmd = [sys.executable, "scripts/run_preference_parser.py", "--demo", "--mock", "--json"]
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res.returncode == 0, f"Script failed with stderr:\n{res.stderr}"
        
        # Verify valid JSON output
        parsed_blocks = []
        raw_stdout = res.stdout.strip()
        decoder = json.JSONDecoder()
        pos = 0
        while pos < len(raw_stdout):
            idx = raw_stdout.find('{"current_session_context"', pos)
            if idx == -1:
                idx = raw_stdout.find('{\n  "current_session_context"', pos)
            if idx == -1:
                break
            try:
                obj, end_idx = decoder.raw_decode(raw_stdout, idx)
                parsed_blocks.append(obj)
                pos = end_idx
            except json.JSONDecodeError:
                pos = idx + 1

        assert len(parsed_blocks) >= 4
        for blk in parsed_blocks:
            assert_valid_session_context(blk)

    def test_run_multi_turn_dialogue_alias_script(self):
        """Execute python scripts/run_multi_turn_dialogue.py --demo --mock."""
        cmd = [sys.executable, "scripts/run_multi_turn_dialogue.py", "--demo", "--mock"]
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res.returncode == 0, f"Script failed with stderr:\n{res.stderr}"
        assert "RUNNING DEMO SCENARIO" in res.stdout
        assert "current_session_context" in res.stdout

    def test_category_extraction_and_graceful_resolution(self):
        """Verify _extract_categories handles both schemas and _resolve_categories degrades gracefully."""
        payload = {
            "current_session_context": {
                "extracted_parameters": {
                    "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]
                }
            }
        }
        cats = _extract_categories(payload)
        assert "laptop" in cats

        # Offline category resolution should return None or dict without raising exceptions
        res = _resolve_categories(cats)
        assert res is None or isinstance(res, dict)
