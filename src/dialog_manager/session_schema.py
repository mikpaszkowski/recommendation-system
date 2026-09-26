"""
Session Schema Models for Conversational Recommender System.
Strict Pydantic v2 models conforming to current_session_context JSON specification.
"""

from __future__ import annotations

import json
import math
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class SessionIntent(str, Enum):
    """The current phase of the user's conversational journey."""
    INITIAL_SEARCH = "initial_search"
    EXPLORING_DOMAIN = "exploring_domain"
    REFINING_OPTIONS = "refining_options"
    COMPARING_ITEMS = "comparing_items"
    FINALIZING_CHOICE = "finalizing_choice"

    # Lowercase aliases for flexible attribute access
    initial_search = "initial_search"
    exploring_domain = "exploring_domain"
    refining_options = "refining_options"
    comparing_items = "comparing_items"
    finalizing_choice = "finalizing_choice"


class ConstraintOperator(str, Enum):
    """Operators for applying strict hard constraints."""
    INCLUDE = "include"
    EXCLUDE = "exclude"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    EQUAL = "equal"

    # Lowercase aliases for flexible attribute access
    include = "include"
    exclude = "exclude"
    greater_than = "greater_than"
    less_than = "less_than"
    equal = "equal"


# Alias for backward compatibility
HardConstraintOperator = ConstraintOperator


class SuggestedSystemAction(str, Enum):
    """Recommended next action for the dialogue system."""
    ASK_CLARIFICATION = "ask_clarification"
    PRESENT_RESULTS = "present_results"
    CHANGE_TOPIC = "change_topic"

    # Lowercase aliases for flexible attribute access
    ask_clarification = "ask_clarification"
    present_results = "present_results"
    change_topic = "change_topic"


def extract_numeric_robust(val: Any) -> Union[int, float]:
    """
    Robust numeric extractor supporting international currency and European decimal notation.
    Disambiguates thousands separators (commas or dots) from decimal marks (dots or commas).
    """
    if isinstance(val, bool):
        raise ValueError(f"Boolean values are not valid numeric constraints: {val}")
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Constraint value cannot be NaN or Inf, got {val}")
        return val
    if not isinstance(val, str):
        raise ValueError(f"Could not extract numeric value from: '{val}'")

    s = val.strip()
    if not s:
        raise ValueError("Could not extract numeric value from empty string")

    # Strip currency symbols, currency codes, whitespace, and comparison symbols
    s_cleaned = re.sub(r"(?i)[$€£¥₹\s~<>]|zł|zl|PLN|USD|EUR|GBP", "", s)
    match = re.search(r"[-+]?[\d.,]+(?:[eE][-+]?\d+)?", s_cleaned)
    if not match:
        raise ValueError(f"Could not extract numeric value from: '{val}'")

    num_token = match.group(0)
    if not any(c.isdigit() for c in num_token):
        raise ValueError(f"Could not extract numeric value from: '{val}'")

    # Distinguish thousands separators from European decimal commas
    has_dot = "." in num_token
    has_comma = "," in num_token

    if has_dot and has_comma:
        last_dot = num_token.rfind(".")
        last_comma = num_token.rfind(",")
        if last_dot > last_comma:
            # e.g., 1,500.50 -> comma is thousands separator
            num_token = num_token.replace(",", "")
        else:
            # e.g., 1.500,50 -> dot is thousands separator, comma is decimal
            num_token = num_token.replace(".", "").replace(",", ".")
    elif has_comma:
        if num_token.count(",") > 1:
            # e.g., 1,000,000 -> multiple commas are thousands separators
            num_token = num_token.replace(",", "")
        else:
            # Single comma: inspect digits before and after
            parts = num_token.lstrip("+-").split(",")
            before = parts[0]
            after = parts[1]
            e_match = re.search(r"[eE][-+]?\d+$", after)
            e_suffix = e_match.group(0) if e_match else ""
            after_digits = after[:len(after) - len(e_suffix)] if e_suffix else after

            if len(after_digits) in (1, 2):
                # Decimal comma (e.g. 2500,00 or 99,99 or 1500,5)
                num_token = num_token.replace(",", ".")
            elif len(after_digits) == 3 and (1 <= len(before) <= 3):
                # Thousands separator (e.g. 1,000 or 75,000)
                num_token = num_token.replace(",", "")
            else:
                num_token = num_token.replace(",", ".")
    elif has_dot:
        if num_token.count(".") > 1:
            # e.g., 1.000.000 -> multiple dots are European thousands separators
            num_token = num_token.replace(".", "")

    try:
        num = float(num_token)
    except ValueError:
        raise ValueError(f"Could not extract numeric value from: '{val}'")

    if math.isnan(num) or math.isinf(num):
        raise ValueError(f"Constraint value cannot be NaN or Inf, got {num}")

    if "." in num_token or "e" in num_token.lower():
        return num
    return int(num)


def _extract_numeric(val: Any, disambiguate_comma: bool = False) -> Union[int, float]:
    """
    Helper to parse numeric values from currency or formatted strings.
    If disambiguate_comma is True, applies robust international and European comma disambiguation.
    Otherwise maintains backward compatibility with baseline format specifications.
    """
    if disambiguate_comma:
        return extract_numeric_robust(val)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    if isinstance(val, str):
        cleaned = re.sub(r"[$,€£zł\s]", "", val)
        match = re.search(r"[-+]?\d*\.?\d+", cleaned)
        if match:
            num_str = match.group(0)
            if num_str and num_str not in ("-", "+", "."):
                return float(num_str) if "." in num_str else int(num_str)
    raise ValueError(f"Could not extract numeric value from: '{val}'")


class HardConstraint(BaseModel):
    """Strict filter that MUST be obeyed in item retrieval."""
    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    attribute: str = Field(
        ...,
        min_length=1,
        description="The feature being constrained (e.g., 'price', 'brand', 'operating_system')."
    )
    operator: ConstraintOperator = Field(
        ...,
        description="How the constraint should be applied (include, exclude, greater_than, less_than, equal)."
    )
    value: Union[str, int, float, bool] = Field(
        ...,
        description="The target value for the constraint."
    )

    @field_validator("attribute")
    @classmethod
    def clean_attribute(cls, v: Any) -> str:
        if not isinstance(v, str):
            v = str(v)
        s = v.strip().lower()
        if not s:
            raise ValueError("attribute cannot be empty or whitespace")
        return s

    @model_validator(mode="after")
    def validate_and_coerce_value(self) -> HardConstraint:
        if self.operator in (ConstraintOperator.GREATER_THAN, ConstraintOperator.LESS_THAN):
            if isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
                pass
            elif isinstance(self.value, str):
                self.value = _extract_numeric(self.value)
            else:
                raise ValueError(
                    f"Constraint with operator '{self.operator.value}' requires a numeric value, "
                    f"got {type(self.value).__name__}"
                )
        elif isinstance(self.value, str):
            self.value = self.value.strip()
        return self


class SoftPreference(BaseModel):
    """Flexible desire used to rank and score recommendations."""
    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    category: str = Field(
        ...,
        min_length=1,
        description="The type/domain of preference (e.g. 'weight', 'brand', 'battery')."
    )
    value: str = Field(
        ...,
        min_length=1,
        description="The specific preference value (e.g. 'lightweight', 'Apple')."
    )
    polarity: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Sentiment toward value: 1.0 (strongly loves/wants) to -1.0 (strongly hates/avoids)."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Certainty about extraction: 1.0 (explicit) to 0.0 (uncertain/guessed)."
    )
    evidence: str = Field(
        default="",
        description="Brief quote or logical reasoning detailing extraction rationale."
    )

    @field_validator("category", "value")
    @classmethod
    def clean_strings(cls, v: Any) -> str:
        if not isinstance(v, str):
            v = str(v)
        s = v.strip()
        if not s:
            raise ValueError("category and value cannot be empty or whitespace")
        return s


class ExtractedParameters(BaseModel):
    """Container for hard constraints and soft preferences."""
    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    hard_constraints: List[HardConstraint] = Field(
        default_factory=list,
        description="Strict filters that MUST be obeyed."
    )
    soft_preferences: List[SoftPreference] = Field(
        default_factory=list,
        description="Flexible desires used to rank and score recommendations."
    )


class DialogueState(BaseModel):
    """State tracking for dialogue management and recommendation readiness."""
    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    ready_for_recommendation: bool = Field(
        default=False,
        description="True if enough context has been gathered to query the database."
    )
    missing_critical_attributes: List[str] = Field(
        default_factory=list,
        description="Mandatory fields required before querying database."
    )
    suggested_system_action: SuggestedSystemAction = Field(
        default=SuggestedSystemAction.ASK_CLARIFICATION,
        description="Recommended next step for the application backend."
    )


class SessionContext(BaseModel):
    """Payload representing conversational context and dialogue state."""
    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    session_intent: SessionIntent = Field(
        default=SessionIntent.INITIAL_SEARCH,
        description="The current phase of the user journey."
    )
    situational_context: str = Field(
        default="",
        description="Brief, human-readable summary of why the user is making the request."
    )
    extracted_parameters: ExtractedParameters = Field(
        default_factory=ExtractedParameters,
        description="Extracted hard constraints and soft preferences."
    )
    dialogue_state: DialogueState = Field(
        default_factory=DialogueState,
        description="Dialogue state tracking readiness and next actions."
    )

    @classmethod
    def create_empty(cls) -> SessionContext:
        """Create a default empty session context."""
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize model to a JSON-serializable Python dictionary."""
        return self.model_dump(mode="json")

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize model to a JSON string."""
        return self.model_dump_json(indent=indent)

    def __getitem__(self, item: Any) -> Any:
        if item == "current_session_context":
            return self
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: Any, default: Any = None, safe: bool = False) -> Any:
        """
        Retrieve attribute with fallback.
        If safe is True, non-string keys return default without raising TypeError.
        """
        if safe:
            if not isinstance(item, str):
                return default
            try:
                return self[item]
            except (AttributeError, KeyError, TypeError):
                return default
        try:
            return self[item]
        except (AttributeError, KeyError):
            return default

    def safe_get(self, item: Any, default: Any = None) -> Any:
        """Robust dict emulation helper returning default on non-string or missing keys."""
        return self.get(item, default=default, safe=True)

    def __contains__(self, item: Any) -> bool:
        return item in (
            "current_session_context",
            "session_intent",
            "situational_context",
            "extracted_parameters",
            "dialogue_state",
        ) or hasattr(self, item)

    def safe_contains(self, item: Any) -> bool:
        """Robust dict emulation helper returning False on non-string keys."""
        if not isinstance(item, str):
            return False
        return item in self


class CurrentSessionContextWrapper(BaseModel):
    """
    Root wrapper enforcing that all session context data is encapsulated
    under the 'current_session_context' key.
    """
    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    current_session_context: SessionContext = Field(
        ...,
        description="Root wrapper for all session context data."
    )

    @classmethod
    def create_empty(cls) -> CurrentSessionContextWrapper:
        """Create a default empty wrapped session context."""
        return cls(current_session_context=SessionContext.create_empty())

    @classmethod
    def from_dict(cls, data: Dict[str, Any], auto_wrap: bool = False) -> CurrentSessionContextWrapper:
        """
        Validate and construct wrapper from a dictionary.
        If auto_wrap is True and 'current_session_context' key is missing,
        it automatically wraps the data.
        """
        if not isinstance(data, dict):
            raise ValueError("Input data must be a dictionary")
        if "current_session_context" in data:
            return cls.model_validate(data)
        if auto_wrap:
            return cls(current_session_context=SessionContext.model_validate(data))
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str, auto_wrap: bool = False) -> CurrentSessionContextWrapper:
        """Validate and construct wrapper from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data, auto_wrap=auto_wrap)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize wrapped model to a JSON-serializable Python dictionary."""
        return self.model_dump(mode="json")

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize wrapped model to a JSON string."""
        return self.model_dump_json(indent=indent)

    def __getitem__(self, item: Any) -> Any:
        if item == "current_session_context":
            return self.current_session_context
        if hasattr(self.current_session_context, item):
            return getattr(self.current_session_context, item)
        raise KeyError(item)

    def get(self, item: Any, default: Any = None, safe: bool = False) -> Any:
        """
        Retrieve attribute with fallback.
        If safe is True, non-string keys return default without raising TypeError.
        """
        if safe:
            if not isinstance(item, str):
                return default
            try:
                return self[item]
            except (AttributeError, KeyError, TypeError):
                return default
        try:
            return self[item]
        except (AttributeError, KeyError):
            return default

    def safe_get(self, item: Any, default: Any = None) -> Any:
        """Robust dict emulation helper returning default on non-string or missing keys."""
        return self.get(item, default=default, safe=True)

    def __contains__(self, item: Any) -> bool:
        return item == "current_session_context" or item in self.current_session_context

    def safe_contains(self, item: Any) -> bool:
        """Robust dict emulation helper returning False on non-string keys."""
        if not isinstance(item, str):
            return False
        return self.current_session_context.safe_contains(item)

    # Convenience delegating properties
    @property
    def context(self) -> SessionContext:
        return self.current_session_context

    @property
    def session_intent(self) -> SessionIntent:
        return self.current_session_context.session_intent

    @property
    def situational_context(self) -> str:
        return self.current_session_context.situational_context

    @property
    def extracted_parameters(self) -> ExtractedParameters:
        return self.current_session_context.extracted_parameters

    @property
    def dialogue_state(self) -> DialogueState:
        return self.current_session_context.dialogue_state

    @property
    def hard_constraints(self) -> List[HardConstraint]:
        return self.current_session_context.extracted_parameters.hard_constraints

    @property
    def soft_preferences(self) -> List[SoftPreference]:
        return self.current_session_context.extracted_parameters.soft_preferences


# Canonical alias
CurrentSessionContext = CurrentSessionContextWrapper
