"""
Ambiguous smoke check for RS-23 category recovery (Technical Specification FR-037, AC-033, §7.4).

Runs five hand-written utterances that name no product type through the live AgentOrchestrator
(Neo4j + OpenAI), with category recovery on and then off, and records the CLARIFY count and the
clarify_reason per utterance. Diagnostic only: the outcome is non-deterministic, so the test
asserts only that both passes complete. Skipped unless RUN_LIVE_TESTS=1.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="live Neo4j + OpenAI test; set RUN_LIVE_TESTS=1")
logger = logging.getLogger(__name__)

AMBIGUOUS_UTTERANCES = (
    "I need a gift for my dad who likes gadgets, around $50.",
    "What would help me take better holiday photos, a new camera or just a better phone?",
    "I want to start streaming on Twitch, what do I need?",
    "Can you recommend something for my living room TV?",
    "My home office feels cluttered, any ideas?",
)


@pytest.fixture(scope="module")
def orchestrator():
    from src.agents.orchestrator import AgentOrchestrator

    orch = AgentOrchestrator(category_recovery=True)
    if orch.graph_tool.db is None:
        pytest.skip("Neo4j is unavailable")
    yield orch
    orch.graph_tool.db.close()


def _run_pass(orch: Any, recovery: bool) -> List[Dict[str, Any]]:
    orch.category_recovery = recovery
    outcomes: List[Dict[str, Any]] = []
    for i, utterance in enumerate(AMBIGUOUS_UTTERANCES, 1):
        session = f"ambiguous_smoke_{'on' if recovery else 'off'}_{i}"
        orch.reset_session(session)
        result = asyncio.run(orch.run(user_id=session, user_message=utterance, session_id=session))
        trace = result.get("eval_trace") or {}
        resolution = trace.get("category_resolution") or {}
        outcomes.append({
            "utterance": utterance,
            "action": result.get("action"),
            "clarify_reason": trace.get("clarify_reason"),
            "recovery_outcome": resolution.get("recovery_outcome"),
            "category": resolution.get("category"),
            "recovery_discarded_category": resolution.get("recovery_discarded_category"),
        })
    return outcomes


def test_ambiguous_smoke_recovery_on_and_off(orchestrator, record_property):
    report = {}
    for recovery in (True, False):
        outcomes = _run_pass(orchestrator, recovery)
        clarify = sum(1 for o in outcomes if o["action"] == "CLARIFY")
        label = "on" if recovery else "off"
        report[label] = {"clarify": clarify, "outcomes": outcomes}
        record_property(f"clarify_recovery_{label}", f"{clarify}/{len(outcomes)}")
        print(f"\n[FR-037] recovery {label}: CLARIFY {clarify}/{len(outcomes)}")
        for o in outcomes:
            print(f"  - {o['action']:<8} reason={o['clarify_reason']!s:<24} recovery={o['recovery_outcome']!s:<14} "
                  f"category={o['category']!r} discarded={o['recovery_discarded_category']!r} | {o['utterance']}")
        logger.info(f"[FR-037] recovery {label}: CLARIFY {clarify}/{len(outcomes)}")
    assert len(report["on"]["outcomes"]) == len(report["off"]["outcomes"]) == len(AMBIGUOUS_UTTERANCES)


# ---------------------------------------------------------------------------
# AC-039 (spec §13 A-11, FR-007a): live diagnostic of the `product_type_decided` gate.
# `_recover_category` is called directly on a minimal state (the utterance as the only message,
# empty active filters), so every utterance exercises the flag whatever the router would choose.
# Only the LLM is live; the graph and KECR tools are inert doubles. Diagnostic: per-utterance
# results over N_PASSES passes are printed (plus one JSON line per set); the asserts only check
# that every call completed with a known outcome.
# ---------------------------------------------------------------------------

import json  # noqa: E402
from typing import Optional, Tuple  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from langchain_core.messages import HumanMessage  # noqa: E402

N_PASSES = 3
KNOWN_OUTCOMES = ("found", "undecided", "null_category", "error")

# (i) Fresh multi-domain vague set: names only a recipient, occasion, interest or broad class.
# Not from §7.4, not a paraphrase of it, not in any benchmark or prompt. Expected: "undecided" 3/3.
FRESH_VAGUE_UTTERANCES: Tuple[Tuple[str, str], ...] = (
    ("vague_cooking_sister", "I'm looking for a birthday present for my sister, she loves cooking."),
    ("vague_cozy_bedroom", "What could make my bedroom feel cozier this winter?"),
    ("vague_camping_trip", "We're going camping next month, what stuff should I bring?"),
    ("vague_coworker_30", "Need a present for a coworker who is leaving, under $30."),
    ("vague_dry_skin", "My skin has been really dry lately, can you suggest something?"),
    ("vague_sharper_at_work", "I want to look sharper at work, any recommendations?"),
    ("vague_science_kid_40", "Something fun for a ten-year-old who is into science, budget around $40."),
    ("vague_new_puppy", "I just adopted a puppy and I'm not sure where to start shopping."),
)

# (ii) Type-explicit legacy-21 items (the four historical RS-23 failures first) and a lowercase token
# the recovered category is expected to contain (evaluation data, not system logic). Expected: "found" 3/3.
TYPE_EXPLICIT_ITEMS: Tuple[Tuple[str, str], ...] = (
    ("live_eval_charger_01", "charger"),
    ("live_eval_mouse_02", "mouse"),
    ("live_eval_keyboard_01", "keyboard"),
    ("live_eval_keyboard_02", "keyboard"),
    ("live_eval_camera_01", "webcam"),
    ("live_eval_headphone_01", "headphone"),
    ("live_eval_laptop_03", "laptop"),
    ("live_eval_charger_03", "adapter"),
)

LIVE_DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "live_eval_dataset.json")


@pytest.fixture(scope="module")
def recovery_orchestrator():
    from src.agents.orchestrator import AgentOrchestrator

    return AgentOrchestrator(graph_tool=MagicMock(), kecr_tool=MagicMock(), category_recovery=True)


def _recover_once(orch: Any, utterance: str) -> Dict[str, Any]:
    state: Dict[str, Any] = {"messages": [HumanMessage(content=utterance)], "active_filters": {}}
    rec = asyncio.run(orch._recover_category(state))
    params = state.get("search_params") or {}
    return {
        "outcome": rec.get("outcome"),
        "category": rec.get("category"),
        "product_type_decided": rec.get("product_type_decided"),
        "discarded_category": rec.get("discarded_category"),
        "raw_flag": params.get("product_type_decided"),
    }


def _run_decided_set(orch: Any, set_name: str, items: List[Tuple[str, str, Optional[str]]]) -> List[Dict[str, Any]]:
    """Runs N_PASSES passes over (id, utterance, expected_token) items; expected_token None = vague."""
    rows: List[Dict[str, Any]] = []
    for pass_no in range(1, N_PASSES + 1):
        for qid, utterance, token in items:
            row = {"set": set_name, "pass": pass_no, "id": qid, "utterance": utterance, **_recover_once(orch, utterance)}
            if token is None:
                row["as_expected"] = row["outcome"] == "undecided"
            else:
                category = row["category"]
                row["as_expected"] = row["outcome"] == "found" and isinstance(category, str) and token in category.lower()
            rows.append(row)
    print(f"\n[AC-039] set {set_name}: {N_PASSES} passes")
    for qid, utterance, _ in items:
        per = [r for r in rows if r["id"] == qid]
        ok = sum(1 for r in per if r["as_expected"])
        detail = "; ".join(f"p{r['pass']}={r['outcome']}/flag={r['raw_flag']!r}/cat={r['category']!r}/disc={r['discarded_category']!r}"
                           for r in per)
        print(f"  - {ok}/{len(per)} {qid:<24} {detail}")
    print(f"AC039_JSON {set_name} " + json.dumps(rows, default=str))
    return rows


def test_decided_gate_fresh_vague_set(recovery_orchestrator):
    items = [(qid, utterance, None) for qid, utterance in FRESH_VAGUE_UTTERANCES]
    rows = _run_decided_set(recovery_orchestrator, "fresh_vague", items)
    assert len(rows) == N_PASSES * len(items)
    assert all(r["outcome"] in KNOWN_OUTCOMES for r in rows)


def test_decided_gate_type_explicit_legacy(recovery_orchestrator):
    with open(LIVE_DATASET_PATH, encoding="utf-8") as fh:
        legacy = {str(item.get("query_id")): str(item.get("utterance") or item.get("query") or "") for item in json.load(fh)}
    items = [(qid, legacy[qid], token) for qid, token in TYPE_EXPLICIT_ITEMS]
    assert all(utterance for _, utterance, _ in items)
    rows = _run_decided_set(recovery_orchestrator, "type_explicit", items)
    assert len(rows) == N_PASSES * len(items)
    assert all(r["outcome"] in KNOWN_OUTCOMES for r in rows)
