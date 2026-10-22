"""
tests/test_preference_prompt_r2.py

RS-23 option A (R2a): extraction prompt rules and examples (Technical Specification AC-001 … AC-003).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from src.llm_interface.preference_parser import (
    PRODUCT_TYPE_SCHEMA_HINT,
    LLMPreferenceParser,
    validate_hard_constraint,
)
from src.llm_interface.prompts import preference_extract_prompt as pep

# FR-002 contamination rule: the legacy-21 product types must not appear in the new texts
LEGACY_21_PRODUCT_TYPES = (
    "webcam", "camera", "bundle", "smartphone", "phone", "iphone", "charger", "adapter",
    "mouse", "headphones", "earbuds", "laptop", "chromebook", "keyboard",
)
INFLECTION_WORDS = ("plural", "singular", "lemma")
NEW_TEXTS = {
    "PRODUCT_TYPE_RULE": pep.PRODUCT_TYPE_RULE,
    "CATEGORY_CONSISTENCY_RULE": pep.CATEGORY_CONSISTENCY_RULE,
    "LONG_MODIFIER_EXAMPLE": pep.LONG_MODIFIER_EXAMPLE,
}


def _examples() -> Dict[int, Dict[str, Any]]:
    """Parses the OUTPUT JSON block of every <example_n> in SYSTEM_PROMPT."""
    parsed: Dict[int, Dict[str, Any]] = {}
    for match in re.finditer(r"<example_(\d+)>(.*?)</example_\1>", pep.SYSTEM_PROMPT, re.S):
        body = match.group(2)
        json_text = body.split("OUTPUT:", 1)[1].strip()
        parsed[int(match.group(1))] = json.loads(json_text)
    return parsed


def _hard(example: Dict[str, Any]) -> List[Dict[str, Any]]:
    return example["current_session_context"]["extracted_parameters"]["hard_constraints"]


def _soft(example: Dict[str, Any]) -> List[Dict[str, Any]]:
    return example["current_session_context"]["extracted_parameters"]["soft_preferences"]


class TestNewPromptTexts:
    """AC-001: rule texts and the long-modifier example are present and uncontaminated."""

    @pytest.mark.parametrize("name", sorted(NEW_TEXTS))
    def test_text_is_part_of_system_prompt(self, name):
        assert NEW_TEXTS[name] in pep.SYSTEM_PROMPT
        assert NEW_TEXTS[name] in pep.get_system_prompt()

    @pytest.mark.parametrize("name", sorted(NEW_TEXTS))
    def test_text_has_no_legacy_product_type(self, name):
        lowered = NEW_TEXTS[name].lower()
        leaked = [word for word in LEGACY_21_PRODUCT_TYPES if word in lowered]
        assert leaked == []

    @pytest.mark.parametrize("name", sorted(NEW_TEXTS))
    def test_text_has_no_inflection_instruction(self, name):
        lowered = NEW_TEXTS[name].lower()
        assert [word for word in INFLECTION_WORDS if word in lowered] == []

    def test_rules_sit_in_rule_4a_and_rule_5(self):
        prompt = pep.SYSTEM_PROMPT
        assert prompt.index("A. HARD CONSTRAINTS") < prompt.index("PRODUCT TYPE RULE") < prompt.index("B. SOFT PREFERENCES")
        assert prompt.index("5. DIALOGUE STATE TRACKING") < prompt.index("CONSISTENCY CHECK (category)") < prompt.index("6. MULTI-TURN")
        assert prompt.index("</example_6>") < prompt.index("<example_7>") < prompt.index("</examples>")

    def test_prompt_template_still_formats(self):
        messages = pep.get_prompt_template().format_messages(conversation_text="User: hello")
        assert "PRODUCT TYPE RULE" in messages[0].content
        assert "<example_7>" in pep.prompt("User: hello")


class TestExamples:
    """AC-002: every example parses and respects the hard-constraint taxonomy."""

    def test_seven_examples_parse(self):
        assert sorted(_examples()) == [1, 2, 3, 4, 5, 6, 7]

    def test_all_hard_constraints_are_valid(self):
        invalid = [
            (n, c) for n, ex in _examples().items() for c in _hard(ex) if not validate_hard_constraint(c)
        ]
        assert invalid == []

    def test_example_1_moves_operating_system_to_soft_preferences(self):
        example_1 = _examples()[1]
        assert all(c["attribute"] != "operating_system" for c in _hard(example_1))
        os_prefs = [p for p in _soft(example_1) if p["category"] == "operating_system"]
        assert os_prefs == [{
            "category": "operating_system", "value": "ChromeOS", "polarity": -1.0,
            "confidence": 1.0, "evidence": "I definitely do not want ChromeOS",
        }]

    def test_example_7_has_one_jacket_category_and_seven_modifiers(self):
        example_7 = _examples()[7]
        categories = [c for c in _hard(example_7) if c["attribute"] == "category"]
        assert categories == [{"attribute": "category", "operator": "include", "value": "jacket"}]
        assert {"attribute": "price", "operator": "less_than", "value": 180} in _hard(example_7)
        assert [p["category"] for p in _soft(example_7)] == [
            "weight", "waterproofing", "packability", "insulation", "use_case", "hood", "pockets",
        ]
        assert all(p["confidence"] == 0.9 and p["evidence"] for p in _soft(example_7))
        state = example_7["current_session_context"]["dialogue_state"]
        assert state == {"ready_for_recommendation": True, "missing_critical_attributes": [],
                         "suggested_system_action": "present_results"}


class TestSchemaInjection:
    """AC-003 (FR-005): the schema injection names the product type as the category hard constraint."""

    def test_schema_hint_sentence(self):
        assert PRODUCT_TYPE_SCHEMA_HINT == (
            "The product type the user names is the `category` hard constraint (see PRODUCT TYPE RULE); "
            "only its modifiers are soft_preferences."
        )

    def test_parser_system_prompt_contains_hint_inside_schema_block(self):
        parser = LLMPreferenceParser(llm_handler=MagicMock())
        prompt = parser.system_instruction
        start, end = prompt.index("<schema_injection>"), prompt.index("</schema_injection>")
        assert start < prompt.index(PRODUCT_TYPE_SCHEMA_HINT) < end
        assert "ALL other specifications MUST be classified as soft_preferences" in prompt
