"""
Authoritative Schema Validator for Conversational Recommender System.
Strictly derived from ORIGINAL_REQUEST.md and PROJECT.md specifications.
"""
from typing import Any, Dict, List, Tuple
import jsonschema
from jsonschema import Draft7Validator

# Authoritative JSON Schema matching ORIGINAL_REQUEST.md
SESSION_CONTEXT_JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "CurrentSessionContextRoot",
    "type": "object",
    "required": ["current_session_context"],
    "additionalProperties": False,
    "properties": {
        "current_session_context": {
            "type": "object",
            "required": [
                "session_intent",
                "situational_context",
                "extracted_parameters",
                "dialogue_state",
            ],
            "additionalProperties": False,
            "properties": {
                "session_intent": {
                    "type": "string",
                    "enum": [
                        "initial_search",
                        "exploring_domain",
                        "refining_options",
                        "comparing_items",
                        "finalizing_choice",
                    ],
                },
                "situational_context": {
                    "type": "string",
                },
                "extracted_parameters": {
                    "type": "object",
                    "required": ["hard_constraints", "soft_preferences"],
                    "additionalProperties": False,
                    "properties": {
                        "hard_constraints": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["attribute", "operator", "value"],
                                "additionalProperties": False,
                                "properties": {
                                    "attribute": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "operator": {
                                        "type": "string",
                                        "enum": [
                                            "include",
                                            "exclude",
                                            "greater_than",
                                            "less_than",
                                            "equal",
                                        ],
                                    },
                                    "value": {
                                        "type": ["string", "number"],
                                    },
                                },
                            },
                        },
                        "soft_preferences": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "category",
                                    "value",
                                    "polarity",
                                    "confidence",
                                    "evidence",
                                ],
                                "additionalProperties": False,
                                "properties": {
                                    "category": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "value": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "polarity": {
                                        "type": "number",
                                        "minimum": -1.0,
                                        "maximum": 1.0,
                                    },
                                    "confidence": {
                                        "type": "number",
                                        "minimum": 0.0,
                                        "maximum": 1.0,
                                    },
                                    "evidence": {
                                        "type": "string",
                                    },
                                },
                            },
                        },
                    },
                },
                "dialogue_state": {
                    "type": "object",
                    "required": [
                        "ready_for_recommendation",
                        "missing_critical_attributes",
                        "suggested_system_action",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "ready_for_recommendation": {
                            "type": "boolean",
                        },
                        "missing_critical_attributes": {
                            "type": "array",
                            "items": {
                                "type": "string",
                            },
                        },
                        "suggested_system_action": {
                            "type": "string",
                            "enum": [
                                "ask_clarification",
                                "present_results",
                                "change_topic",
                            ],
                        },
                    },
                },
            },
        },
    },
}

_VALIDATOR = Draft7Validator(SESSION_CONTEXT_JSON_SCHEMA)


def validate_session_context_schema(data: Any) -> Tuple[bool, List[str]]:
    """
    Validate a dictionary payload against the canonical session context JSON Schema.
    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []
    if not isinstance(data, dict):
        return False, [f"Payload must be a dictionary, got {type(data).__name__}"]

    for error in _VALIDATOR.iter_errors(data):
        path = ".".join(str(p) for p in error.path)
        errors.append(f"[{path or 'root'}]: {error.message}")

    return len(errors) == 0, errors


def assert_valid_session_context(data: Any) -> None:
    """
    Assert that the payload strictly adheres to the JSON schema.
    Raises AssertionError with formatted error messages on failure.
    """
    is_valid, errors = validate_session_context_schema(data)
    if not is_valid:
        error_summary = "\n  - " + "\n  - ".join(errors)
        raise AssertionError(
            f"Payload failed strict session context schema validation:{error_summary}"
        )


ALLOWED_SESSION_INTENTS = {
    "initial_search",
    "exploring_domain",
    "refining_options",
    "comparing_items",
    "finalizing_choice",
}

ALLOWED_CONSTRAINT_OPERATORS = {
    "include",
    "exclude",
    "greater_than",
    "less_than",
    "equal",
}

ALLOWED_SYSTEM_ACTIONS = {
    "ask_clarification",
    "present_results",
    "change_topic",
}
