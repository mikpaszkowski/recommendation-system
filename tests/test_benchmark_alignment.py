import json
import os
import subprocess
import pytest
from neo4j import GraphDatabase

from scripts.evaluate_retrieval import validate_benchmark_graph_grounding
from src.evaluation.metrics import evaluate_retrieval_batch

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "recommendation_password")


@pytest.fixture
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception:
        pytest.skip("Neo4j database not reachable")
    yield driver
    driver.close()


def test_cli_default_benchmark_path():
    """AC-001.1: Default benchmark path in evaluate_retrieval.py points to live_eval_dataset.json."""
    from scripts.evaluate_retrieval import main
    import argparse
    from unittest.mock import patch

    test_parser = argparse.ArgumentParser()
    test_parser.add_argument(
        "--benchmark",
        "--dataset",
        dest="benchmark",
        default="live_eval_dataset.json",
    )
    parsed = test_parser.parse_args([])
    assert parsed.benchmark == "live_eval_dataset.json"

    # Also inspect actual evaluate_retrieval CLI via subprocess --help
    res = subprocess.run(
        ["python3", "scripts/evaluate_retrieval.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    normalized_help = " ".join(res.stdout.split())
    assert "default: live_eval_dataset.json" in normalized_help


def test_live_eval_dataset_neo4j_alignment(neo4j_driver):
    """AC-001.2: 100% of target ASINs exist in live Neo4j with valid attributes and degrees."""
    benchmark_path = "live_eval_dataset.json"
    assert os.path.exists(benchmark_path), f"Benchmark file {benchmark_path} does not exist"

    with open(benchmark_path, "r", encoding="utf-8") as f:
        benchmark = json.load(f)

    assert len(benchmark) == 21, f"Expected 21 benchmark scenarios, found {len(benchmark)}"

    with neo4j_driver.session() as session:
        for scenario in benchmark:
            asin = scenario["target_asin"]
            price_max = scenario.get("structured_filters", {}).get("price_max")

            record = session.run("""
                MATCH (p:ParentProduct {parent_asin: $asin})
                RETURN p.title AS title, p.price AS price, size([(p)--() | 1]) AS degree
            """, {"asin": asin}).single()

            assert record is not None, f"Target ASIN {asin} missing from Neo4j in scenario {scenario['query_id']}"
            assert record["title"] is not None and len(record["title"]) > 5, f"ASIN {asin} has empty title"
            assert record["price"] is not None, f"ASIN {asin} has NULL price"
            assert record["degree"] > 0, f"ASIN {asin} is an isolated ghost node"

            if price_max is not None:
                assert float(record["price"]) <= float(price_max), (
                    f"Scenario {scenario['query_id']}: Target price ${record['price']} "
                    f"exceeds filter price_max ${price_max}"
                )


def test_charger_budget_ceiling_alignment():
    """AC-001.3: live_eval_charger_01 budget ceiling aligned with actual catalog price ($55.99)."""
    with open("live_eval_dataset.json", "r", encoding="utf-8") as f:
        benchmark = json.load(f)

    charger_01 = next((item for item in benchmark if item.get("query_id") == "live_eval_charger_01"), None)
    assert charger_01 is not None, "Scenario live_eval_charger_01 not found in live_eval_dataset.json"

    price_max = charger_01.get("structured_filters", {}).get("price_max")
    assert price_max is not None, "price_max missing in structured_filters"
    assert float(price_max) >= 55.99, f"price_max ${price_max} must accommodate catalog price $55.99 (expected 60.0)"
    assert float(price_max) == 60.0, f"Expected price_max to be 60.0, got {price_max}"
    assert "under $60" in charger_01.get("utterance", ""), "Utterance text should reflect budget ceiling under $60"


def test_evaluation_runner_rejects_hallucinated_asin(neo4j_driver):
    """AC-001.4: Pre-flight graph grounding verification gate rejects hallucinated ASINs."""
    corrupted_data = [{
        "query_id": "test_corrupted_01",
        "target_asin": "B000NOTREAL",
        "structured_filters": {"price_max": 100.0}
    }]
    with pytest.raises(ValueError, match="Benchmark contains 1 ungrounded target entities"):
        validate_benchmark_graph_grounding(corrupted_data, neo4j_driver)


def test_multi_ground_truth_and_graded_metrics():
    """AC-001.5: Multi-ground-truth metrics compute strict and graded NDCG / Hit Rate."""
    mock_predictions = [
        {
            "query_id": "live_eval_charger_01",
            "strategy": "hybrid",
            # Peer ASIN at rank 1, primary target at rank 2
            "candidate_asins": ["B08B14VXPL", "B088FHJLR1", "OTHER_ASIN_1"],
            "latency_ms": 15.0,
        }
    ]

    mock_ground_truth = [
        {
            "query_id": "live_eval_charger_01",
            "target_asin": "B088FHJLR1",
            "peer_asins": ["B08B14VXPL", "B0936X8RDR"],
            "graded_relevance": {
                "B088FHJLR1": 1.0,
                "B08B14VXPL": 0.45,
            },
        }
    ]

    results = evaluate_retrieval_batch(mock_predictions, mock_ground_truth, k_values=[1, 2, 5])
    per_query = results["per_query_results"][0]
    aggregates = results["aggregates"]

    # At K=1: Peer B08B14VXPL is returned
    # Strict Hit@1 = 0 (primary target B088FHJLR1 is at rank 2)
    # Soft/Peer Hit@1 = 1 (peer is in top 1)
    assert per_query["strict_hit@1"] == 0
    assert per_query["soft_hit@1"] == 1
    assert per_query["strict_ndcg@1"] == 0.0
    assert per_query["graded_ndcg@1"] > 0.0

    # At K=2: Primary target B088FHJLR1 is returned
    assert per_query["strict_hit@2"] == 1
    assert per_query["soft_hit@2"] == 1
    assert per_query["strict_ndcg@2"] > 0.0
    assert per_query["graded_ndcg@2"] > 0.0

    # Aggregates contain both strict and soft / graded metrics
    assert "mean_strict_hr@1" in aggregates
    assert "mean_soft_hr@1" in aggregates
    assert "mean_graded_ndcg@1" in aggregates
    assert "mean_strict_ndcg@1" in aggregates
    assert aggregates["mean_strict_hr@1"] == 0.0
    assert aggregates["mean_soft_hr@1"] == 1.0
