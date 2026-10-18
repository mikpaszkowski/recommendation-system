"""
tests/test_category_recovery.py

RS-23 option C (R2a): category recovery before the CLARIFY guardrail, search-param reuse and
clarify attribution (Technical Specification AC-004 … AC-010, NFR-001). Reuses the test doubles
of tests/test_agent_orchestrator.py.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.agents.orchestrator import (
    CATEGORY_FILTER_KEYS,
    CLARIFY_REASONS,
    SEARCH_GENERATION_PROMPT,
    AgentOrchestrator,
)
from src.dialog_manager.dialogue_manager import DialogueManager
from tests.test_agent_orchestrator import (
    MockCriticAgent,
    MockGraphSearchTool,
    MockLLMHandler,
    MockPreferenceParser,
)

SEARCH_PROMPT_MARKER = "YOUR GOAL: Help the user find the perfect product"
CHARGER_MSG = "I need a compact 65W GaN wall charger with 4 ports under $60."


def _extraction(hard: List[Dict[str, Any]], ready: bool = False, missing: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "User wants a compact wall charger",
            "extracted_parameters": {"hard_constraints": hard, "soft_preferences": []},
            "dialogue_state": {
                "ready_for_recommendation": ready,
                "missing_critical_attributes": missing if missing is not None else ["category"],
                "suggested_system_action": "present_results" if ready else "ask_clarification",
            },
        }
    }


PRICE_ONLY = [{"attribute": "price", "operator": "less_than", "value": 60}]


def _search_param_calls(llm: MockLLMHandler) -> int:
    return sum(1 for q in llm.recorded_queries if SEARCH_PROMPT_MARKER in q)


def _build(llm: MockLLMHandler, parser: MockPreferenceParser, graph: Optional[MockGraphSearchTool] = None,
           **kwargs: Any) -> AgentOrchestrator:
    return AgentOrchestrator(
        graph_tool=graph or MockGraphSearchTool(),
        llm_handler=llm,
        critic_agent=MockCriticAgent(),
        dialogue_manager=DialogueManager(critical_attributes=["category"]),
        preference_parser=parser,
        kecr_tool=MagicMock(),
        **kwargs,
    )


def _run(orch: AgentOrchestrator, message: str, user_id: str = "u_recovery") -> Dict[str, Any]:
    return asyncio.run(orch.run(user_id=user_id, user_message=message))


class TestRecoveryFound:
    """AC-004 and NFR-001."""

    def test_recovered_category_reaches_search_with_one_param_call(self):
        llm = MockLLMHandler()
        llm.search_param_responses = [json.dumps({
            "thought": "wall charger under 60",
            "product_type_decided": True,
            "structured_filters": {"category": "wall charger", "price_max": 60},
            "semantic_query": "compact 65W GaN wall charger",
        })]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        graph = MockGraphSearchTool()
        result = _run(_build(llm, parser, graph), CHARGER_MSG)

        assert result["action"] == "SEARCH"
        assert len(graph.search_calls) == 1
        assert graph.search_calls[0]["structured_filters"]["category"] == "wall charger"
        assert graph.search_calls[0]["semantic_query"] == "compact 65W GaN wall charger"
        assert _search_param_calls(llm) == 1
        trace = result["eval_trace"]
        assert trace["clarify_reason"] is None
        assert trace["search_params_source"] == "recovery"
        assert trace["search_params_fallback"] is False
        assert trace["relaxed_constraints"] == []
        assert trace["category_resolution"] == {
            "parser_category": None, "category": "wall charger", "source": "search_params",
            "guardrail_triggered": True, "recovery_attempted": True, "recovery_outcome": "found",
            "recovery_product_type_decided": True, "recovery_discarded_category": None,
        }

    def test_recovered_turn_costs_the_same_llm_calls_as_a_normal_search(self):
        def _calls(extraction: Dict[str, Any]) -> int:
            llm = MockLLMHandler()
            llm.search_param_responses = [json.dumps({"product_type_decided": True,
                "structured_filters": {"category": "wall charger"}, "semantic_query": "wall charger"})]
            parser = MockPreferenceParser()
            parser.set_extraction(CHARGER_MSG, extraction)
            result = _run(_build(llm, parser), CHARGER_MSG)
            assert result["action"] == "SEARCH"
            return len(llm.recorded_queries)

        recovered = _calls(_extraction(PRICE_ONLY))
        normal = _calls(_extraction(PRICE_ONLY + [{"attribute": "category", "operator": "include", "value": "wall charger"}],
                                    ready=True, missing=[]))
        assert recovered == normal == 3  # router + search params + final answer

    def test_normal_search_records_parser_source(self):
        llm = MockLLMHandler()
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(
            PRICE_ONLY + [{"attribute": "category", "operator": "include", "value": "wall charger"}], ready=True, missing=[]))
        result = _run(_build(llm, parser), CHARGER_MSG)
        trace = result["eval_trace"]
        assert trace["search_params_source"] == "search_branch"
        assert trace["category_resolution"]["source"] == "parser"
        assert trace["category_resolution"]["category"] == "wall charger"
        assert trace["category_resolution"]["guardrail_triggered"] is False
        assert trace["category_resolution"]["recovery_attempted"] is False


class TestRecoveryClarifies:
    """AC-005 and AC-006."""

    def test_null_category_clarifies_without_search(self):
        llm = MockLLMHandler()
        llm.search_param_responses = [json.dumps({"product_type_decided": True, "structured_filters": {"category": None}, "semantic_query": "gift"})]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        graph = MockGraphSearchTool()
        result = _run(_build(llm, parser, graph), CHARGER_MSG)

        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "recovery_failed"
        assert result["eval_trace"]["category_resolution"]["recovery_outcome"] == "null_category"
        assert result["eval_trace"]["category_resolution"]["category"] is None
        assert _search_param_calls(llm) == 1
        assert graph.search_calls == []

    @pytest.mark.parametrize("value", ["none", "N/A", "  ", "unknown", "any"])
    def test_null_like_category_values_do_not_count(self, value):
        llm = MockLLMHandler()
        llm.search_param_responses = [json.dumps({"structured_filters": {"category": value}})]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        result = _run(_build(llm, parser), CHARGER_MSG)
        assert result["eval_trace"]["clarify_reason"] == "recovery_failed"

    @pytest.mark.parametrize("response", ["this is not JSON", "Error: Rate limit reached", "[1, 2, 3]"])
    def test_recovery_llm_failure_fails_closed(self, response):
        llm = MockLLMHandler()
        llm.search_param_responses = [response]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        graph = MockGraphSearchTool()
        result = _run(_build(llm, parser, graph), CHARGER_MSG)

        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "recovery_error"
        assert result["eval_trace"]["category_resolution"]["recovery_outcome"] == "error"
        assert graph.search_calls == []


class TestExistingCategorySources:
    """AC-007."""

    def test_active_filter_category_skips_recovery(self):
        llm = MockLLMHandler()
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        profile_tool = MagicMock()
        profile_tool.get_profile.return_value = {"preferences": {"category": "wall charger"}, "history": []}
        graph = MockGraphSearchTool()
        orch = _build(llm, parser, graph, profile_tool=profile_tool)
        result = _run(orch, CHARGER_MSG)

        assert result["action"] == "SEARCH"
        assert _search_param_calls(llm) == 1
        trace = result["eval_trace"]
        assert trace["search_params_source"] == "search_branch"
        assert trace["category_resolution"]["source"] == "active_filters"
        assert trace["category_resolution"]["guardrail_triggered"] is True
        assert trace["category_resolution"]["recovery_attempted"] is False
        assert graph.search_calls[0]["structured_filters"]["category"] == "wall charger"


class TestClarifyReasons:
    """AC-008 and AC-009."""

    def test_router_clarify(self):
        llm = MockLLMHandler()
        llm.router_responses = [json.dumps({"action": "CLARIFY", "reasoning": "vague"})]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        result = _run(_build(llm, parser), CHARGER_MSG)
        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "router"
        assert result["eval_trace"]["category_resolution"]["recovery_attempted"] is False
        assert _search_param_calls(llm) == 0

    def test_router_fallback(self):
        llm = MockLLMHandler()
        llm.router_responses = ["NOT JSON"]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        result = _run(_build(llm, parser), CHARGER_MSG)
        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "router_fallback"
        assert _search_param_calls(llm) == 0

    def test_recovery_disabled_by_argument(self):
        llm = MockLLMHandler()
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        orch = _build(llm, parser, category_recovery=False)
        result = _run(orch, CHARGER_MSG)
        assert orch.category_recovery is False
        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "parser_missing_category"
        assert result["eval_trace"]["category_resolution"]["guardrail_triggered"] is True
        assert _search_param_calls(llm) == 0

    @pytest.mark.parametrize("raw,expected", [("0", False), ("false", False), ("No", False), ("1", True), ("yes", True)])
    def test_recovery_switch_from_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("ORCH_CATEGORY_RECOVERY", raw)
        llm = MockLLMHandler()
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        orch = _build(llm, parser)
        assert orch.category_recovery is expected
        result = _run(orch, CHARGER_MSG)
        if not expected:
            assert result["eval_trace"]["clarify_reason"] == "parser_missing_category"
            assert _search_param_calls(llm) == 0

    def test_recovery_on_by_default(self, monkeypatch):
        monkeypatch.delenv("ORCH_CATEGORY_RECOVERY", raising=False)
        assert _build(MockLLMHandler(), MockPreferenceParser()).category_recovery is True

    def test_brand_immunisation_still_overrides_clarify(self):
        llm = MockLLMHandler()
        llm.router_responses = [json.dumps({"action": "CLARIFY", "reasoning": "unsure"})]
        parser = MockPreferenceParser()
        parser.set_extraction("Apple wall charger", _extraction([
            {"attribute": "category", "operator": "include", "value": "wall charger"},
            {"attribute": "brand", "operator": "include", "value": "Apple"},
        ], ready=True, missing=[]))
        result = _run(_build(llm, parser), "Apple wall charger")
        assert result["action"] == "SEARCH"
        assert result["eval_trace"]["clarify_reason"] is None
        assert result["eval_trace"]["category_resolution"]["source"] == "parser"

    def test_all_reasons_are_declared(self):
        assert CLARIFY_REASONS == {"router", "router_fallback", "parser_missing_category", "recovery_failed", "recovery_error"}


class TestSearchPromptAndHelpers:
    """AC-010 and helper behaviour."""

    def test_search_prompt_rules(self):
        assert "UPDATE `price_max` to 1500." in SEARCH_GENERATION_PROMPT
        assert "to 150." not in SEARCH_GENERATION_PROMPT
        assert "Copy numbers exactly as the user states them; never rescale, round or convert units." in SEARCH_GENERATION_PROMPT
        assert "set `category` to null" in SEARCH_GENERATION_PROMPT
        assert "Never guess a category." in SEARCH_GENERATION_PROMPT
        assert SEARCH_GENERATION_PROMPT.strip().splitlines()[0] == (
            "YOUR GOAL: Help the user find the perfect product by translating their request into search arguments."
        )

    def test_param_source_markers(self):
        orch = _build(MockLLMHandler(), MockPreferenceParser())
        ok = asyncio.run(orch._generate_search_params("a jacket", {}, ""))
        assert ok["param_source"] == "llm"
        orch.llm_handler.search_param_responses = ["Error: boom"]
        bad = asyncio.run(orch._generate_search_params("a jacket", {}, ""))
        assert bad == {"semantic_query": "a jacket", "structured_filters": {}, "param_source": "fallback"}

    @pytest.mark.parametrize("filters,expected", [
        ({"category": "dress"}, "dress"),
        ({"category": " Dress "}, "Dress"),
        ({"categories": ["jacket", "coat"]}, "jacket"),
        ({"product_type": "kettle"}, "kettle"),
        ({"category": None, "type": "lamp"}, "lamp"),
        ({"category": "null"}, None),
        ({"category": 5}, None),
        ({"categories": []}, None),
        ({}, None),
        (None, None),
    ])
    def test_category_from_filters(self, filters, expected):
        assert AgentOrchestrator._category_from_filters(filters) == expected

    def test_category_keys(self):
        assert CATEGORY_FILTER_KEYS == ("category", "product_category", "product_type", "type", "categories")

    def test_search_history_text_uses_last_six_messages(self):
        from langchain_core.messages import AIMessage, HumanMessage
        messages = [HumanMessage(content=f"m{i}") if i % 2 == 0 else AIMessage(content=f"m{i}") for i in range(9)]
        text = AgentOrchestrator._search_history_text({"messages": messages})
        assert text.splitlines() == [f"{'HumanMessage' if i % 2 == 0 else 'AIMessage'}: m{i}" for i in range(2, 8)]


# ---------------------------------------------------------------------------
# Audit H-1 / FR-007a (spec §13 A-11): recovery gated on `product_type_decided` (AC-034 … AC-038).
# Every search-params double below states the flag explicitly (or omits it on purpose).
# ---------------------------------------------------------------------------

from langchain_core.messages import HumanMessage  # noqa: E402

from src.agents.orchestrator import PRODUCT_TYPE_DECIDED_RULE  # noqa: E402

_MISSING = object()

FULL_RESOLUTION_KEYS = {
    "parser_category", "category", "source", "guardrail_triggered", "recovery_attempted",
    "recovery_outcome", "recovery_product_type_decided", "recovery_discarded_category",
}

# FR-002 legacy-21 product types and the AC-034 smoke-set / morphology tokens
LEGACY_PRODUCT_TYPES = ("webcam", "camera", "bundle", "smartphone", "phone", "iphone", "charger", "adapter",
                        "mouse", "headphones", "earbuds", "laptop", "chromebook", "keyboard")
FORBIDDEN_RULE_TOKENS = ("plural", "singular", "lemma", "gift", "dad", "gadget", "holiday", "photo", "camera",
                         "phone", "twitch", "stream", "living room", "tv", "home office", "clutter")


def _decided_params(category: Optional[str], decided: Any = _MISSING) -> str:
    payload: Dict[str, Any] = {
        "thought": "test",
        "structured_filters": {"category": category, "price_max": 60},
        "semantic_query": "compact 65W GaN wall charger",
    }
    if decided is not _MISSING:
        payload["product_type_decided"] = decided
    return json.dumps(payload)


def _recovery_run(response: str):
    llm = MockLLMHandler()
    llm.search_param_responses = [response]
    parser = MockPreferenceParser()
    parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
    graph = MockGraphSearchTool()
    result = _run(_build(llm, parser, graph), CHARGER_MSG)
    return result, llm, graph


class TestDecidedPrompt:
    """AC-034."""

    def test_prompt_contains_rule_and_output_line(self):
        assert PRODUCT_TYPE_DECIDED_RULE in SEARCH_GENERATION_PROMPT
        assert ('  "product_type_decided": true,  // false if the user has not committed to one specific kind of product'
                in SEARCH_GENERATION_PROMPT)
        assert SEARCH_GENERATION_PROMPT.strip().splitlines()[0] == (
            "YOUR GOAL: Help the user find the perfect product by translating their request into search arguments."
        )

    def test_flag_line_sits_between_thought_and_structured_filters(self):
        thought = SEARCH_GENERATION_PROMPT.index('"thought":')
        flag = SEARCH_GENERATION_PROMPT.index('"product_type_decided":')
        filters = SEARCH_GENERATION_PROMPT.index('"structured_filters":')
        assert thought < flag < filters

    def test_rule_follows_category_rule(self):
        assert SEARCH_GENERATION_PROMPT.index("Never guess a category.") < SEARCH_GENERATION_PROMPT.index(PRODUCT_TYPE_DECIDED_RULE)

    def test_rule_has_no_vocabulary_morphology_or_smoke_tokens(self):
        import re
        lowered = PRODUCT_TYPE_DECIDED_RULE.lower()
        for token in LEGACY_PRODUCT_TYPES + FORBIDDEN_RULE_TOKENS:
            assert not re.search(rf"(?<![a-z]){re.escape(token)}", lowered), token
        assert "example" not in lowered and "e.g." not in lowered

    def test_existing_example_line_unchanged(self):
        assert '"category": "laptop"  // the product type the user asked for, or null if undecided' in SEARCH_GENERATION_PROMPT


class TestDecidedGate:
    """AC-035 … AC-037."""

    def test_found(self):
        result, llm, graph = _recovery_run(_decided_params("wall charger", True))
        assert result["action"] == "SEARCH"
        assert len(graph.search_calls) == 1
        assert graph.search_calls[0]["structured_filters"]["category"] == "wall charger"
        assert _search_param_calls(llm) == 1
        trace = result["eval_trace"]
        assert trace["clarify_reason"] is None
        assert trace["search_params_source"] == "recovery"
        assert trace["category_resolution"] == {
            "parser_category": None, "category": "wall charger", "source": "search_params",
            "guardrail_triggered": True, "recovery_attempted": True, "recovery_outcome": "found",
            "recovery_product_type_decided": True, "recovery_discarded_category": None,
        }

    @pytest.mark.parametrize("flag,expected_flag", [
        (False, False), (_MISSING, None), (None, None), ("true", None), (1, None),
    ])
    def test_undecided(self, flag, expected_flag):
        result, llm, graph = _recovery_run(_decided_params("wall charger", flag))
        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "recovery_failed"
        resolution = result["eval_trace"]["category_resolution"]
        assert resolution["recovery_outcome"] == "undecided"
        assert resolution["recovery_discarded_category"] == "wall charger"
        assert resolution["recovery_product_type_decided"] is expected_flag
        assert resolution["category"] is None and resolution["source"] is None
        assert _search_param_calls(llm) == 1
        assert graph.search_calls == []

    def test_undecided_without_category_discards_nothing(self):
        result, _, _ = _recovery_run(_decided_params(None, False))
        resolution = result["eval_trace"]["category_resolution"]
        assert resolution["recovery_outcome"] == "undecided"
        assert resolution["recovery_discarded_category"] is None

    @pytest.mark.parametrize("category", [None, "none", "  "])
    def test_null_category(self, category):
        result, llm, graph = _recovery_run(_decided_params(category, True))
        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "recovery_failed"
        resolution = result["eval_trace"]["category_resolution"]
        assert resolution["recovery_outcome"] == "null_category"
        assert resolution["recovery_product_type_decided"] is True
        assert resolution["recovery_discarded_category"] is None
        assert _search_param_calls(llm) == 1
        assert graph.search_calls == []

    @pytest.mark.parametrize("response", [
        "this is not JSON",
        "Error: Rate limit reached",
        "[1, 2, 3]",
        '{"product_type_decided": true, "structured_filters": {"category": "wall charger"',
        'Error: {"product_type_decided": true}',
    ])
    def test_error(self, response):
        result, _, graph = _recovery_run(response)
        assert result["action"] == "CLARIFY"
        assert result["eval_trace"]["clarify_reason"] == "recovery_error"
        resolution = result["eval_trace"]["category_resolution"]
        assert resolution["recovery_outcome"] == "error"
        assert resolution["recovery_product_type_decided"] is None
        assert resolution["recovery_discarded_category"] is None
        assert graph.search_calls == []

    def test_clarify_reasons_unchanged(self):
        assert CLARIFY_REASONS == {"router", "router_fallback", "parser_missing_category", "recovery_failed", "recovery_error"}


class TestRecoverCategoryDirect:
    """FR-007a return shape and precedence."""

    @staticmethod
    def _recover(response: str):
        orch = _build(MockLLMHandler(), MockPreferenceParser())
        orch.llm_handler.search_param_responses = [response]
        state: Dict[str, Any] = {"messages": [HumanMessage(content="msg")], "active_filters": {}}
        return asyncio.run(orch._recover_category(state)), state

    def test_found_shape_and_params_stored_for_reuse(self):
        rec, state = self._recover(_decided_params("dress", True))
        assert rec == {"category": "dress", "outcome": "found", "product_type_decided": True, "discarded_category": None}
        assert state["search_params"]["product_type_decided"] is True
        assert state["search_params"]["param_source"] == "llm"

    def test_undecided_shape(self):
        rec, state = self._recover(_decided_params("outfit", False))
        assert rec == {"category": None, "outcome": "undecided", "product_type_decided": False, "discarded_category": "outfit"}
        assert state["search_params"]["structured_filters"]["category"] == "outfit"

    def test_exception_is_error(self):
        orch = _build(MockLLMHandler(), MockPreferenceParser())

        async def _boom(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("boom")

        orch._generate_search_params = _boom  # type: ignore[assignment]
        state: Dict[str, Any] = {"messages": [HumanMessage(content="msg")], "active_filters": {}}
        rec = asyncio.run(orch._recover_category(state))
        assert rec == {"category": None, "outcome": "error", "product_type_decided": None, "discarded_category": None}

    def test_parsed_params_carry_flag_as_returned(self):
        orch = _build(MockLLMHandler(), MockPreferenceParser())
        orch.llm_handler.search_param_responses = [_decided_params("kettle", "true"), _decided_params("kettle")]
        assert asyncio.run(orch._generate_search_params("a kettle", {}, ""))["product_type_decided"] == "true"
        missing = asyncio.run(orch._generate_search_params("a kettle", {}, ""))
        assert "product_type_decided" in missing and missing["product_type_decided"] is None


class TestDecidedScope:
    """AC-038."""

    @pytest.mark.parametrize("flag", [False, _MISSING])
    def test_parser_category_search_ignores_flag(self, flag):
        llm = MockLLMHandler()
        llm.search_param_responses = [_decided_params("wall charger", flag)]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(
            PRICE_ONLY + [{"attribute": "category", "operator": "include", "value": "wall charger"}], ready=True, missing=[]))
        graph = MockGraphSearchTool()
        result = _run(_build(llm, parser, graph), CHARGER_MSG)

        assert result["action"] == "SEARCH"
        assert graph.search_calls[0]["structured_filters"]["category"] == "wall charger"
        assert _search_param_calls(llm) == 1
        trace = result["eval_trace"]
        assert trace["search_params_source"] == "search_branch"
        assert trace["category_resolution"]["source"] == "parser"
        assert trace["category_resolution"]["recovery_attempted"] is False
        assert trace["category_resolution"]["recovery_product_type_decided"] is None
        assert trace["category_resolution"]["recovery_discarded_category"] is None

    def test_flag_never_reaches_filters(self):
        llm = MockLLMHandler()
        llm.search_param_responses = [_decided_params("wall charger", True)]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        graph = MockGraphSearchTool()
        orch = _build(llm, parser, graph)
        seen_states: List[Dict[str, Any]] = []
        original_execute = orch._execute_step

        async def _capturing_execute(user_id: str, state: Any, session_context: Any = None) -> Dict[str, Any]:
            out = await original_execute(user_id, state, session_context)
            seen_states.append(state)
            return out

        orch._execute_step = _capturing_execute  # type: ignore[assignment]
        result = _run(orch, CHARGER_MSG)
        assert result["action"] == "SEARCH"
        assert "product_type_decided" not in graph.search_calls[0]["structured_filters"]
        assert len(seen_states) == 1
        assert seen_states[0]["active_filters"].get("category") == "wall charger"
        assert "product_type_decided" not in seen_states[0]["active_filters"]

    def test_recovered_turn_makes_the_same_llm_calls(self):
        result, llm, _ = _recovery_run(_decided_params("wall charger", True))
        assert result["action"] == "SEARCH"
        assert _search_param_calls(llm) == 1
        assert len(llm.recorded_queries) == 3  # router + search params + final answer

    def test_recovery_disabled_never_reads_flag(self):
        llm = MockLLMHandler()
        llm.search_param_responses = [_decided_params("wall charger", True)]
        parser = MockPreferenceParser()
        parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
        result = _run(_build(llm, parser, category_recovery=False), CHARGER_MSG)
        assert result["eval_trace"]["clarify_reason"] == "parser_missing_category"
        assert _search_param_calls(llm) == 0
        assert result["eval_trace"]["category_resolution"]["recovery_product_type_decided"] is None

    def test_full_key_set_on_every_trace(self):
        assert set(AgentOrchestrator._resolution_for_trace({})) == FULL_RESOLUTION_KEYS
        for router, response in ((json.dumps({"action": "CLARIFY", "reasoning": "vague"}), None),
                                 (None, _decided_params("wall charger", True)),
                                 (None, _decided_params("gadget", False))):
            llm = MockLLMHandler()
            if router:
                llm.router_responses = [router]
            if response:
                llm.search_param_responses = [response]
            parser = MockPreferenceParser()
            parser.set_extraction(CHARGER_MSG, _extraction(PRICE_ONLY))
            result = _run(_build(llm, parser), CHARGER_MSG)
            assert set(result["eval_trace"]["category_resolution"]) == FULL_RESOLUTION_KEYS
