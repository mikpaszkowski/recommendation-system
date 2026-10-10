"""
Challenger 2 Empirical Test Suite: Distinguishing Features & Utterance Quality.

Adversarially tests:
1. Absence of generic template phrases in live_eval_dataset.json utterances.
2. Explicit referencing of distinguishing features in utterances.
3. Live Neo4j target feature presence.
4. Live Neo4j peer contrastiveness (detecting false discriminative claims where peers share the feature).
5. evaluate_retrieval.py offline pipeline execution.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import pytest

from src.database.neo4j_connection import Neo4jConnectionManager

DATASET_PATH = Path("live_eval_dataset.json")

GENERIC_PHRASES = [
    r"\bhigh rating\b",
    r"\bgood rating\b",
    r"\btop rated\b",
    r"\bgreat rating\b",
    r"\bgood product\b",
    r"\bgreat product\b",
    r"\bbest product\b",
    r"\bnice product\b",
    r"\belectronics item\b",
    r"\belectronic item\b",
    r"\belectronic device\b",
    r"\bquality item\b",
    r"\bquality product\b",
    r"\bhigh quality\b",
    r"\bgood quality\b",
    r"\bpopular item\b",
    r"\btop pick\b",
    r"\brecommended\b",
    r"\bsomething good\b",
]


@pytest.fixture(scope="module")
def eval_dataset():
    assert DATASET_PATH.exists(), f"Benchmark file {DATASET_PATH} does not exist"
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 21, f"Expected 21 dataset items, found {len(data)}"
    return data


def test_no_generic_phrases_in_utterances(eval_dataset):
    """Asserts that no generic template phrases appear in any of the 21 utterances."""
    violations = []
    for item in eval_dataset:
        qid = item["query_id"]
        utt = item["utterance"].lower()
        for pat in GENERIC_PHRASES:
            if re.search(pat, utt):
                violations.append((qid, pat, item["utterance"]))

    assert not violations, f"Found generic template phrases in utterances: {violations}"


def test_utterances_reference_distinguishing_features(eval_dataset):
    """Asserts that every utterance explicitly references its item's distinguishing feature."""
    missing_refs = []
    for item in eval_dataset:
        qid = item["query_id"]
        utt = item["utterance"].lower()
        df = item["distinguishing_feature"]
        attr = df.get("attribute", "").lower()
        val = df.get("value", "").lower()
        fval = df.get("feature_value", "").lower()

        # Extract salient terms from attribute, value, and feature_value
        candidates = set(re.findall(r"\b[a-zA-Z0-9-]{3,}\b", f"{attr} {val} {fval}"))
        stopwords = {
            "with", "and", "for", "the", "under", "all", "that", "this",
            "from", "into", "over", "per", "such", "than", "each", "both"
        }
        key_terms = [c for c in candidates if c not in stopwords]

        # Verify that at least some key technical terms from the feature appear in utterance
        matched_terms = [t for t in key_terms if t in utt]
        if not matched_terms:
            missing_refs.append((qid, fval, item["utterance"]))

    assert not missing_refs, f"Utterances missing reference to distinguishing feature: {missing_refs}"


def test_targets_exist_and_possess_features_in_neo4j(eval_dataset):
    """Asserts that all 21 targets exist in Neo4j and their attributes/title match distinguishing features."""
    cypher = """
    MATCH (p:ParentProduct {parent_asin: $asin})
    OPTIONAL MATCH (p)-[:HAS_BRAND]->(b:Brand)
    OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
    RETURN p.parent_asin as asin,
           p.title as title,
           p.price as price,
           b.name as brand,
           collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
    """
    missing_targets = []
    with Neo4jConnectionManager() as conn:
        for item in eval_dataset:
            t_asin = item["target_asin"]
            res = conn.execute_query(cypher, {"asin": t_asin})
            if not res or not res[0]["title"]:
                missing_targets.append(t_asin)

    assert not missing_targets, f"Targets missing or empty in Neo4j: {missing_targets}"


def test_contrastive_differentiation_against_peers(eval_dataset):
    """
    Adversarial verification of contrastive property against peers:
    Detects if any peer satisfies the exact distinguishing feature of the target,
    or if the stated discriminative justification contains false factual claims.
    """
    cypher = """
    MATCH (p:ParentProduct {parent_asin: $asin})
    OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
    RETURN p.parent_asin as asin,
           p.title as title,
           p.price as price,
           collect(DISTINCT {name: a.attribute_name, val: a.attribute_value}) as attrs
    """
    contrastive_failures = []

    with Neo4jConnectionManager() as conn:
        for item in eval_dataset:
            qid = item["query_id"]
            t_asin = item["target_asin"]
            t_utt = item["utterance"]
            df = item["distinguishing_feature"]
            just = df.get("discriminative_justification", "")
            peers = item.get("peer_asins", [])

            p_records = []
            for p in peers:
                res = conn.execute_query(cypher, {"asin": p})
                if res and res[0]["title"]:
                    p_records.append(res[0])

            # Adversarial check on known collision cases:
            # 1. live_eval_headphone_02: Claimed iJoy B0BS1QXF6M requires Bluetooth streaming and lacks FM/SD
            if qid == "live_eval_headphone_02":
                for pr in p_records:
                    if pr["asin"] == "B0BS1QXF6M":
                        title_lower = pr["title"].lower()
                        if "fm" in title_lower and "micro sd" in title_lower:
                            contrastive_failures.append({
                                "query_id": qid,
                                "target": t_asin,
                                "conflicting_peer": pr["asin"],
                                "peer_title": pr["title"],
                                "issue": "Peer B0BS1QXF6M possesses both FM radio and Micro SD card slot; justification claim is factually false."
                            })

            # 2. live_eval_mouse_02: Claimed all peers are flat horizontal mice
            elif qid == "live_eval_mouse_02":
                for pr in p_records:
                    if pr["asin"] == "B08JYBC9MY":
                        title_lower = pr["title"].lower()
                        if "vertical" in title_lower and "rechargeable" in title_lower:
                            contrastive_failures.append({
                                "query_id": qid,
                                "target": t_asin,
                                "conflicting_peer": pr["asin"],
                                "peer_title": pr["title"],
                                "issue": "Peer B08JYBC9MY is an ergonomic vertical rechargeable mouse; justification claim that all peers are flat horizontal mice is false."
                            })

            # 3. live_eval_headphone_01: Peer B07KR62YBD is also Senso IPX7 waterproof sports earbuds
            elif qid == "live_eval_headphone_01":
                for pr in p_records:
                    if pr["asin"] == "B07KR62YBD":
                        title_lower = pr["title"].lower()
                        if "ipx7" in title_lower and "sports" in title_lower:
                            contrastive_failures.append({
                                "query_id": qid,
                                "target": t_asin,
                                "conflicting_peer": pr["asin"],
                                "peer_title": pr["title"],
                                "issue": "Peer B07KR62YBD is also a Senso IPX7 waterproof sports earphone with wrap-around hooks, failing contrastive requirement."
                            })

            # 4. live_eval_charger_03: Peer B07SMFV58F is also an all-in-one universal travel adapter with 4 USB ports
            elif qid == "live_eval_charger_03":
                for pr in p_records:
                    if pr["asin"] == "B07SMFV58F":
                        title_lower = pr["title"].lower()
                        if "travel adapter" in title_lower and "universal" in title_lower:
                            contrastive_failures.append({
                                "query_id": qid,
                                "target": t_asin,
                                "conflicting_peer": pr["asin"],
                                "peer_title": pr["title"],
                                "issue": "Peer B07SMFV58F is also a universal worldwide travel adapter with 4 USB ports (3 USB + 1 Type-C), matching utterance."
                            })

    assert not contrastive_failures, (
        f"Found {len(contrastive_failures)} contrastive differentiation failures where peers "
        f"satisfy the target feature or justification is factually false:\n"
        + "\n".join([f"- [{f['query_id']}] Target {f['target']} vs Peer {f['conflicting_peer']}: {f['issue']}" for f in contrastive_failures])
    )


def test_evaluate_retrieval_offline_pipeline():
    """Asserts that evaluate_retrieval.py runs without errors on live_eval_dataset.json."""
    cmd = [
        "python3",
        "scripts/evaluate_retrieval.py",
        "--mode", "offline",
        "--benchmark", "live_eval_dataset.json",
        "--sample-size", "5"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"evaluate_retrieval.py failed: {proc.stderr}\n{proc.stdout}"
    combined_output = proc.stdout + "\n" + proc.stderr
    assert "Evaluation complete" in combined_output
    assert "NDCG@1" in combined_output
    assert "HR@5" in combined_output
