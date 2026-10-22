"""
tests/test_legacy_ingest_guards.py

Legacy v1 pipeline guards (Technical Specification Graph Rebuild FR-031 … FR-035): AC-034 … AC-038.
No Neo4j, no embedding model: connectors, sessions and embedders are fakes.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest

from tests.graph_v2.conftest import FakeEmbedder, FakeSession

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_batch_ingest():
    spec = importlib.util.spec_from_file_location("batch_ingest_under_test", REPO_ROOT / "scripts" / "graph_ingestion" / "batch_ingest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def restore_root_logging():
    """Modules under test call logging.basicConfig at import time; restore the root logger afterwards."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    root.setLevel(level)
    root.handlers[:] = handlers


def test_batch_ingest_review_query_has_no_product_merge() -> None:
    """AC-034: the review query contains no MERGE (p:ParentProduct."""
    module = _load_batch_ingest()
    assert "MERGE (p:ParentProduct" not in module.REVIEW_QUERY
    assert "OPTIONAL MATCH (p:ParentProduct {parent_asin: coalesce(row.parent_asin, row.asin)})" in module.REVIEW_QUERY
    assert "WITH row, p WHERE p IS NOT NULL" in module.REVIEW_QUERY
    assert module.REVIEW_QUERY.strip().endswith("RETURN count(*) AS written")
    assert "LEGACY v1 ingestion pipeline" in module.__doc__ and "build_graph_v2.py" in module.__doc__


def test_batch_ingest_logs_and_sums_unmatched(tmp_path: Path, monkeypatch, caplog) -> None:
    """AC-034: a fake session returning written = 7 for a batch of 10 logs 3 unmatched and sums them."""
    module = _load_batch_ingest()
    session = FakeSession(lambda cypher, params: [{"written": 7}] if cypher == module.REVIEW_QUERY else [])
    with caplog.at_level(logging.WARNING, logger="kg.batch_ingest"):
        assert module.ingest_review_batch(session, [{"review_id": str(i)} for i in range(10)]) == 3
    assert any("3 of 10 reviews" in record.getMessage() for record in caplog.records)

    meta_csv = tmp_path / "meta.csv"
    meta_csv.write_text("parent_asin,title,price,main_category,store\nT1,Cable,1.0,All Electronics,Anker\n", encoding="utf-8")
    reviews_csv = tmp_path / "reviews.csv"
    rows = "".join(f"U{i},T1,T1,5.0,ok,text,True,{i}\n" for i in range(10))
    reviews_csv.write_text("user_id,asin,parent_asin,rating,title,text,verified_purchase,sort_timestamp\n" + rows, encoding="utf-8")
    shared = FakeSession(lambda cypher, params: [{"written": len(params["batch"]) - 1}] if cypher == module.REVIEW_QUERY else [])

    class _Connector:
        def connect(self) -> None:
            return None

        def session(self) -> FakeSession:
            return shared

        def close(self) -> None:
            return None

    monkeypatch.setattr(module, "Neo4jConnector", _Connector)
    monkeypatch.setattr(module, "METADATA_CSV", meta_csv)
    monkeypatch.setattr(module, "REVIEWS_CSV", reviews_csv)
    monkeypatch.setattr(module, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="kg.batch_ingest"):
        module.run_ingest(limit=0, batch_size=5)
    assert any("2 reviews skipped because their ParentProduct does not exist" in r.getMessage() for r in caplog.records)
    assert sum(1 for cypher, _ in shared.calls if cypher == module.REVIEW_QUERY) == 2


class _BackfillConnector:
    """Fake connector whose sessions answer BackfillService queries for products and reviews."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def connect(self) -> None:
        return None

    def session(self) -> FakeSession:
        def respond(cypher: str, params: Mapping[str, Any]):
            self.calls.append(cypher)
            if "RETURN elementId(n) as id" in cypher:
                return [{"id": "1"}, {"id": "2"}]
            if "MATCH (p:ParentProduct)" in cypher:
                return [
                    {"id": "1", "title": "Cable", "description": None, "category": None, "features": ["Color: x"], "listing_features": None},
                    {"id": "2", "title": " ", "description": "", "category": "C", "features": ["Color: y"], "listing_features": [" "]},
                ]
            if "MATCH (r:Review)" in cypher:
                return [{"id": "1", "title": "Good", "body": "Works"}, {"id": "2", "title": "", "body": "  "}]
            return []
        return FakeSession(respond)


def test_backfill_service_skips_blank_texts(monkeypatch, caplog, restore_root_logging) -> None:
    """AC-035: BackfillService sends no blank product or review to the embedder and logs skip counts."""
    import src.knowledge_graph.graphdb.backfill_embeddings as backfill

    embedder = FakeEmbedder()
    monkeypatch.setattr(backfill, "Neo4jConnector", _BackfillConnector)
    monkeypatch.setattr(backfill, "EmbeddingService", lambda: embedder)
    service = backfill.BackfillService()
    with caplog.at_level(logging.INFO, logger=backfill.logger.name):
        service.backfill_products()
        service.backfill_reviews()
    texts = [text for batch in embedder.batches for text in batch]
    assert texts == ["Product: Cable. Category: Unknown. Features: Color: x. Description: ", "Good. Works"]
    messages = [record.getMessage() for record in caplog.records]
    assert any("Skipped 1 ParentProduct" in m for m in messages) and any("Skipped 1 Review" in m for m in messages)


def test_backfill_product_fetch_orders_attributes(monkeypatch, restore_root_logging) -> None:
    """AC-035: the product fetch query orders attributes before collect."""
    import src.knowledge_graph.graphdb.backfill_embeddings as backfill

    connector = _BackfillConnector()
    monkeypatch.setattr(backfill, "Neo4jConnector", lambda: connector)
    monkeypatch.setattr(backfill, "EmbeddingService", lambda: FakeEmbedder())
    backfill.BackfillService().backfill_products()
    fetch = next(cypher for cypher in connector.calls if "MATCH (p:ParentProduct)" in cypher)
    order = fetch.index("WITH p, c, a ORDER BY a.attribute_name, a.attribute_value")
    assert order < fetch.index("collect(a.attribute_name") and "p.features as listing_features" in fetch


def test_category_backfill_query_ordered_titled(restore_root_logging) -> None:
    """AC-036: the category fetch query filters titled products and orders by review_count DESC, parent_asin ASC before collect(...)[..5]."""
    import src.knowledge_graph.graphdb.backfill_category_embeddings as category_backfill

    query = re.sub(r"\s+", " ", category_backfill.CATEGORY_FETCH_QUERY)
    assert "WHERE p.title IS NOT NULL AND trim(p.title) <> ''" in query
    order = query.index("WITH c, p ORDER BY coalesce(p.review_count, 0) DESC, p.parent_asin ASC")
    assert order < query.index("collect(p.title)[..5]")
    source = (REPO_ROOT / "src" / "knowledge_graph" / "graphdb" / "backfill_category_embeddings.py").read_text(encoding="utf-8")
    assert "category_text_v1(" in source


def _raw_reviews(path: Path) -> None:
    lines = [
        {"rating": 5.0, "title": "A", "text": "x", "asin": "A1", "parent_asin": "P1", "user_id": "U1",
         "timestamp": 1600000000001, "helpful_vote": 4, "verified_purchase": True},
        {"rating": 4.0, "title": "B", "text": "y", "asin": "A1", "parent_asin": "P1", "user_id": "U2",
         "timestamp": 1600000000002, "helpful_vote": 0, "verified_purchase": False},
        {"rating": 3.0, "title": "C", "text": "z", "asin": "A1", "parent_asin": "P1", "user_id": "U3",
         "sort_timestamp": 1500000000003, "helpful_votes": 2, "verified_purchase": True},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def test_amazon_processor_reads_raw_field_names(tmp_path: Path, restore_root_logging) -> None:
    """AC-037: process_reviews_file on a 3-line raw fixture fills helpful_votes and sort_timestamp from helpful_vote and timestamp."""
    from src.utils.AmazonDataProcessor import AmazonDataProcessor

    raw = tmp_path / "Electronics.jsonl"
    _raw_reviews(raw)
    processor = AmazonDataProcessor(max_reviews_per_item=20, min_reviews_per_item=1, min_reviews_per_user=1)
    processor.process_reviews_file(str(raw))
    rows: Dict[str, Dict[str, Any]] = {row["user_id"]: row for row in processor.reviews_df.to_dict("records")}
    assert (rows["U1"]["helpful_votes"], rows["U1"]["sort_timestamp"]) == (4, 1600000000001)
    assert (rows["U2"]["helpful_votes"], rows["U2"]["sort_timestamp"]) == (0, 1600000000002)
    assert (rows["U3"]["helpful_votes"], rows["U3"]["sort_timestamp"]) == (2, 1500000000003)
    assert list(processor.reviews_df["user_id"]) == ["U1", "U3", "U2"]


def test_amazon_processor_warns_on_sampling(monkeypatch, caplog, restore_root_logging) -> None:
    """AC-037: process_and_save_data(frac=0.5) logs the KG warning (patched processor)."""
    import src.utils.AmazonDataProcessor as adp

    class _Processor:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def process_metadata_file(self, *args: Any, **kwargs: Any) -> None:
            return None

        def process_reviews_file(self, *args: Any, **kwargs: Any) -> None:
            return None

        def combine_product_data(self) -> None:
            return None

        def save_to_csv(self, output_dir: str) -> None:
            return None

        def get_processed_data(self):
            return {}, [], {}

    monkeypatch.setattr(adp, "AmazonDataProcessor", _Processor)
    with caplog.at_level(logging.WARNING, logger=adp.logger.name):
        assert adp.process_and_save_data("meta.jsonl", "reviews.jsonl", output_dir="unused", frac=0.5) == ({}, [], {})
    assert any("Knowledge Graph" in r.getMessage() and "frac=0.5" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=adp.logger.name):
        adp.process_and_save_data("meta.jsonl", "reviews.jsonl", output_dir="unused", frac=1.0)
    assert not any("Knowledge Graph" in r.getMessage() for r in caplog.records)


def test_create_vector_indexes_cypher_procedure_form() -> None:
    """AC-038: create_vector_indexes.cypher has 5 db.index.vector.createNodeIndex calls and no CREATE VECTOR INDEX."""
    text = (REPO_ROOT / "src" / "knowledge_graph" / "graphdb" / "create_vector_indexes.cypher").read_text(encoding="utf-8")
    statements = re.findall(r"^CALL db\.index\.vector\.createNodeIndex\('(\w+)', '(\w+)', 'embedding', 384, 'cosine'\);$", text, re.M)
    assert statements == [
        ("product_embedding_index", "ParentProduct"), ("brand_embedding_index", "Brand"),
        ("category_embedding_index", "Category"), ("attribute_embedding_index", "Attribute"), ("review_embedding_index", "Review"),
    ]
    assert "CREATE VECTOR INDEX" not in text and "D-4" in text
