#!/usr/bin/env python3
"""
Builds and freezes Stratified Benchmark v2 (Release R2b, RS-21 / G-9) against live Neo4j Graph v2.

Outputs:
- evaluations/benchmarks/benchmark_v2.json (251 items: 40x5 S0-S4 + 30 A + 21 legacy)
- evaluations/benchmarks/benchmark_v2_manifest.json (split/stratum counts, SHA-256, leakage audit)
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
from pathlib import Path
import random
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_retrieval import validate_benchmark_graph_grounding
from src.evaluation.benchmark_v2 import (
    BENCHMARK_V2_SALT,
    BENCHMARK_V2_SEED,
    assign_split,
    build_ambiguous_benchmark_items,
    check_query_leakage,
    synthesize_title_blind_utterance,
)
from src.evaluation.constraint_satisfaction import validate_gold_annotations
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_benchmark_v2")

# Empirically verified head nouns on Graph v2 where >50% of whole-word title matches sit outside
# the primary Taxon leaf (Research_Report.md §7.3):
S3_TRAP_SPECS: List[Dict[str, Any]] = [
    {"head_noun": "camera", "primary_leaves": ["Digital Cameras", "Camcorders", "Security Cameras", "Webcams", "Action Cameras"], "out_of_taxon_ratio": 0.938},
    {"head_noun": "laptop", "primary_leaves": ["Laptops", "Traditional Laptops", "2 in 1 Laptops", "Chromebooks", "Notebooks"], "out_of_taxon_ratio": 0.893},
    {"head_noun": "monitor", "primary_leaves": ["Monitors", "Computer Monitors"], "out_of_taxon_ratio": 0.819},
    {"head_noun": "printer", "primary_leaves": ["Printers", "Inkjet Printers", "Laser Printers", "Label Printers", "3D Printers"], "out_of_taxon_ratio": 0.810},
    {"head_noun": "speaker", "primary_leaves": ["Portable Bluetooth Speakers", "Bookshelf Speakers", "Outdoor Speakers", "Computer Speakers", "Soundbar Speakers", "Speakers"], "out_of_taxon_ratio": 0.805},
    {"head_noun": "charger", "primary_leaves": ["Wall Chargers", "Wireless Chargers", "Car Chargers", "Portable Power Banks", "Chargers & Adapters"], "out_of_taxon_ratio": 0.803},
    {"head_noun": "keyboard", "primary_leaves": ["Computer Keyboards", "Gaming Keyboards", "Keyboards"], "out_of_taxon_ratio": 0.791},
    {"head_noun": "tablet", "primary_leaves": ["Tablets", "Graphics Tablets"], "out_of_taxon_ratio": 0.767},
    {"head_noun": "microphone", "primary_leaves": ["Computer Microphones", "Microphones", "Wireless Microphones", "Condenser Microphones"], "out_of_taxon_ratio": 0.738},
    {"head_noun": "tripod", "primary_leaves": ["Tripods", "Complete Tripods", "Tabletop & Travel Tripods"], "out_of_taxon_ratio": 0.718},
    {"head_noun": "projector", "primary_leaves": ["Video Projectors", "Projectors"], "out_of_taxon_ratio": 0.664},
    {"head_noun": "webcam", "primary_leaves": ["Webcams"], "out_of_taxon_ratio": 0.656},
    {"head_noun": "headphones", "primary_leaves": ["Headphones", "Over-Ear Headphones", "On-Ear Headphones", "Earbud Headphones", "Audio Headphones"], "out_of_taxon_ratio": 0.614},
    {"head_noun": "router", "primary_leaves": ["Routers", "Whole Home & Mesh Wi-Fi Systems"], "out_of_taxon_ratio": 0.534},
    {"head_noun": "mouse", "primary_leaves": ["Computer Mice", "Gaming Mice", "Mice"], "out_of_taxon_ratio": 0.519},
]

SECONDARY_ACCESSORY_PAT = re.compile(
    r"\b(?:case|cover|protector|skin|decal|sticker|sleeve|bag|pouch|strap|band|"
    r"replacement|spare|dust plug|keycap|wrist rest|mouse pad|mousepad|cleaning|cloth|wipes)\b",
    re.I,
)


def fetch_candidate_pool(connector: Neo4jConnector, limit: int = 9000) -> List[Dict[str, Any]]:
    """
    Fetches priced, embedded, titled ParentProduct nodes with their category, taxon leaf,
    graph review count, catalogue review_count, features, details_json, and attributes.
    """
    cypher = """
    MATCH (p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category)
    WHERE p.price IS NOT NULL AND p.price >= 8.0 AND p.price <= 1800.0
      AND p.embedding IS NOT NULL
      AND p.title IS NOT NULL AND size(p.title) >= 25
    MATCH (p)-[:HAS_BRAND]->(b:Brand)
    WHERE b.name IS NOT NULL
      AND NOT toLower(trim(b.name)) IN ['unknown', 'generic', 'none', 'n/a', '']
    WITH p, collect(DISTINCT c.name)[0] AS category_name,
         collect(DISTINCT b.name)[0] AS brand_name
    ORDER BY p.parent_asin ASC
    LIMIT $limit
    OPTIONAL MATCH (p)-[:IN_TAXON]->(t:Taxon)
    WITH p, category_name, brand_name,
         collect(DISTINCT t.name)[0] AS taxon_leaf,
         collect(DISTINCT t.path)[0] AS taxon_path
    OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
    WITH p, category_name, brand_name, taxon_leaf, taxon_path,
         collect(DISTINCT {name: a.attribute_name, value: a.attribute_value}) AS attrs
    RETURN p.parent_asin AS parent_asin,
           p.title AS title,
           brand_name AS brand,
           p.price AS price,
           p.avg_rating AS average_rating,
           coalesce(p.review_count, 0) AS catalog_review_count,
           COUNT { (p)<-[:ABOUT_PRODUCT]-(:Review) } AS graph_review_count,
           p.features AS features,
           p.details_json AS details_json,
           category_name AS category,
           coalesce(taxon_leaf, category_name) AS taxon_leaf,
           taxon_path AS taxon_path,
           [x IN attrs WHERE x.name IS NOT NULL AND x.value IS NOT NULL] AS attributes
    """
    rows = connector.execute_query(cypher, {"limit": limit}) or []
    return [dict(r) for r in rows]


def fetch_cold_start_pool(connector: Neo4jConnector, limit: int = 2000) -> List[Dict[str, Any]]:
    """
    Specifically queries priced, embedded ParentProduct nodes with 0..2 graph reviews (Stratum S1).
    """
    cypher = """
    MATCH (p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category)
    WHERE p.price IS NOT NULL AND p.price >= 8.0 AND p.price <= 1800.0
      AND p.embedding IS NOT NULL
      AND p.title IS NOT NULL AND size(p.title) >= 25
    WITH p, collect(DISTINCT c.name)[0] AS category_name
    LIMIT 25000
    WITH p, category_name,
         COUNT { (p)<-[:ABOUT_PRODUCT]-(:Review) } AS graph_rev_cnt
    WHERE graph_rev_cnt <= 2
    MATCH (p)-[:HAS_BRAND]->(b:Brand)
    WHERE b.name IS NOT NULL
      AND NOT toLower(trim(b.name)) IN ['unknown', 'generic', 'none', 'n/a', '']
    WITH p, category_name, graph_rev_cnt, collect(DISTINCT b.name)[0] AS brand_name
    ORDER BY graph_rev_cnt ASC, p.parent_asin ASC
    LIMIT $limit
    OPTIONAL MATCH (p)-[:IN_TAXON]->(t:Taxon)
    WITH p, category_name, brand_name, graph_rev_cnt,
         collect(DISTINCT t.name)[0] AS taxon_leaf,
         collect(DISTINCT t.path)[0] AS taxon_path
    OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
    WITH p, category_name, brand_name, graph_rev_cnt, taxon_leaf, taxon_path,
         collect(DISTINCT {name: a.attribute_name, value: a.attribute_value}) AS attrs
    RETURN p.parent_asin AS parent_asin,
           p.title AS title,
           brand_name AS brand,
           p.price AS price,
           p.avg_rating AS average_rating,
           coalesce(p.review_count, 0) AS catalog_review_count,
           graph_rev_cnt AS graph_review_count,
           p.features AS features,
           p.details_json AS details_json,
           category_name AS category,
           coalesce(taxon_leaf, category_name) AS taxon_leaf,
           taxon_path AS taxon_path,
           [x IN attrs WHERE x.name IS NOT NULL AND x.value IS NOT NULL] AS attributes
    """
    rows = connector.execute_query(cypher, {"limit": limit}) or []
    return [dict(r) for r in rows]


def _leaf_key(cand: Mapping[str, Any]) -> str:
    return str(cand.get("taxon_leaf") or cand.get("category") or "Electronics").strip()


def _select_peers(
    target: Mapping[str, Any],
    leaf_items: Sequence[Mapping[str, Any]],
    budget: float,
    max_peers: int = 4,
) -> Tuple[List[str], Dict[str, int]]:
    target_asin = str(target["parent_asin"])
    graded: Dict[str, int] = {target_asin: 3}
    peers: List[str] = []
    for item in leaf_items:
        asin = str(item["parent_asin"])
        if asin == target_asin:
            continue
        price = float(item.get("price") or 0.0)
        if 0 < price <= budget:
            peers.append(asin)
            graded[asin] = 2 if len(peers) <= 2 else 1
            if len(peers) >= max_peers:
                break
    return peers, graded


def build_stratum_items(
    stratum: str,
    candidates: Sequence[Dict[str, Any]],
    by_leaf: Mapping[str, List[Dict[str, Any]]],
    used_asins: Set[str],
    target_count: int = 40,
    max_per_leaf: int = 3,
    seed: int = BENCHMARK_V2_SEED,
) -> List[Dict[str, Any]]:
    """
    Selects `target_count` diversified items for `stratum`, synthesizing title-blind utterances
    and enforcing `check_query_leakage` (zero model code leak, zero unflagged brand leak,
    title_token_overlap <= 0.30, and non-trivial TF-IDF rank > 1).
    """
    rng = random.Random(f"{seed}:{stratum}")
    pool = [c for c in candidates if str(c["parent_asin"]) not in used_asins]
    rng.shuffle(pool)
    # Sort stable by leaf diversity (round-robin across leaves)
    leaf_buckets: Dict[str, List[Dict[str, Any]]] = {}
    for c in pool:
        lk = _leaf_key(c)
        leaf_buckets.setdefault(lk, []).append(c)

    ordered_candidates: List[Dict[str, Any]] = []
    leaf_keys = sorted(leaf_buckets.keys())
    rng.shuffle(leaf_keys)
    round_idx = 0
    while True:
        added_any = False
        for lk in leaf_keys:
            bucket = leaf_buckets[lk]
            if round_idx < len(bucket):
                ordered_candidates.append(bucket[round_idx])
                added_any = True
        if not added_any:
            break
        round_idx += 1

    selected: List[Dict[str, Any]] = []
    leaf_counts: Dict[str, int] = {}

    for cand in ordered_candidates:
        if len(selected) >= target_count:
            break
        asin = str(cand["parent_asin"])
        if asin in used_asins:
            continue
        lk = _leaf_key(cand)
        if leaf_counts.get(lk, 0) >= max_per_leaf:
            continue

        # Build pool_titles for TF-IDF triviality check (same leaf + broad distractors if leaf is small)
        leaf_peers = by_leaf.get(lk, [])
        pool_titles: Dict[str, str] = {
            str(p["parent_asin"]): str(p.get("title") or "")
            for p in leaf_peers[:80]
            if p.get("title")
        }
        pool_titles[asin] = str(cand.get("title") or "")
        if len(pool_titles) < 25:
            for extra in ordered_candidates[:40]:
                if len(pool_titles) >= 40:
                    break
                pool_titles.setdefault(str(extra["parent_asin"]), str(extra.get("title") or ""))

        idx_in_stratum = len(selected) + 1
        # 25% of items (every 4th item) are brand-anchored so both brand-filtered and brand-open queries are tested
        brand_anchored = (idx_in_stratum % 4 == 0)

        product_type = cand.get("product_type_override") or lk
        cand_for_synth = dict(cand)
        cand_for_synth["product_type"] = product_type
        # Never expose title to synthesize_title_blind_utterance
        cand_for_synth.pop("title", None)

        passed_attempt: Optional[Tuple[str, List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]] = None
        for attempt in range(20):
            attempt_rng = random.Random(f"{seed}:{stratum}:{asin}:{attempt}")
            utterance, gold_constraints, structured_filters = synthesize_title_blind_utterance(
                cand_for_synth,
                stratum=stratum,
                rng=attempt_rng,
                brand_anchored=brand_anchored,
                budget_stated=True,
            )
            leak = check_query_leakage(
                utterance=utterance,
                target_asin=asin,
                target_title=str(cand.get("title") or ""),
                target_brand=cand.get("brand"),
                product_type=str(product_type),
                pool_titles=pool_titles,
                brand_anchored=brand_anchored,
                max_overlap=0.30,
                require_non_trivial_tfidf=True,
            )
            if leak["passed"]:
                passed_attempt = (utterance, gold_constraints, structured_filters, leak)
                break

        if passed_attempt is None:
            continue

        utterance, gold_constraints, structured_filters, leak = passed_attempt
        budget = float(structured_filters.get("price_max") or (float(cand["price"]) * 1.25))
        peers, graded_rel = _select_peers(cand, leaf_peers, budget=budget, max_peers=4)

        qid = f"r2b_{stratum.lower()}_{idx_in_stratum:03d}"
        split = assign_split(asin, salt=BENCHMARK_V2_SALT)

        item: Dict[str, Any] = {
            "query_id": qid,
            "id": qid,
            "stratum": stratum,
            "split": split,
            "category": str(cand.get("category") or lk),
            "taxon_leaf": cand.get("taxon_leaf"),
            "taxon_path": cand.get("taxon_path"),
            "utterance": utterance,
            "target_asin": asin,
            "target_title": str(cand.get("title") or ""),
            "target_brand": cand.get("brand"),
            "target_price": float(cand["price"]),
            "target_rating": float(cand["average_rating"]) if cand.get("average_rating") is not None else None,
            "target_graph_review_count": int(cand.get("graph_review_count") or 0),
            "target_catalog_review_count": int(cand.get("catalog_review_count") or 0),
            "ground_truth_asins": [asin],
            "peer_asins": peers,
            "graded_relevance": graded_rel,
            "structured_filters": structured_filters,
            "soft_preferences": [],
            "type_explicit": True,
            "gold_action": "SEARCH",
            "gold_product_type": str(product_type),
            "gold_constraints": gold_constraints,
            "brand_anchored": brand_anchored,
            "budget_stated": True,
            "mask_target_reviews": (stratum == "S1"),
            "leakage_audit": leak,
            "gold_annotation": {
                "annotator": "benchmark_v2_builder",
                "source": "title_blind_features_details_attributes",
                "version": "r2b_v2",
            },
        }
        if stratum == "S3":
            item["trap_head_noun"] = cand.get("trap_head_noun")
            item["trap_out_of_taxon_ratio"] = cand.get("trap_out_of_taxon_ratio")

        selected.append(item)
        used_asins.add(asin)
        leaf_counts[lk] = leaf_counts.get(lk, 0) + 1

    if len(selected) < target_count:
        raise RuntimeError(
            f"Stratum {stratum}: only built {len(selected)}/{target_count} items passing quality gates."
        )
    return selected


def load_legacy_items(legacy_path: Path) -> List[Dict[str, Any]]:
    with open(legacy_path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    out: List[Dict[str, Any]] = []
    for item in raw_items:
        copied = dict(item)
        qid = str(copied.get("query_id") or copied.get("id"))
        copied["query_id"] = qid
        copied["id"] = qid
        copied["stratum"] = "legacy"
        copied["split"] = "tuning"
        copied["mask_target_reviews"] = False
        out.append(copied)
    return out


def build_benchmark_v2(
    output_path: Path,
    manifest_path: Path,
    legacy_path: Path,
) -> Dict[str, Any]:
    connector = Neo4jConnector()
    connector.connect()
    try:
        logger.info("Loading legacy-21 continuity queries from %s...", legacy_path)
        legacy_items = load_legacy_items(legacy_path)
        used_asins: Set[str] = {
            str(item["target_asin"]) for item in legacy_items if item.get("target_asin")
        }
        logger.info("Reserved %d legacy target ASINs.", len(used_asins))

        logger.info("Fetching candidate pools from live Neo4j Graph v2...")
        general_pool = fetch_candidate_pool(connector, limit=9000)
        cold_pool = fetch_cold_start_pool(connector, limit=2000)
        logger.info(
            "Fetched %d general candidates and %d cold-start (<=2 graph reviews) candidates.",
            len(general_pool),
            len(cold_pool),
        )

        by_leaf: Dict[str, List[Dict[str, Any]]] = {}
        for c in general_pool + cold_pool:
            lk = _leaf_key(c)
            by_leaf.setdefault(lk, []).append(c)

        # S0: Review-Dense Head (graph_review_count == 20 and catalog_review_count >= 362)
        s0_candidates = [
            c for c in general_pool
            if int(c.get("graph_review_count") or 0) >= 20
            and int(c.get("catalog_review_count") or 0) >= 362
            and len(c.get("features") or []) >= 2
        ]
        logger.info("S0 pool size: %d", len(s0_candidates))
        s0_items = build_stratum_items("S0", s0_candidates, by_leaf, used_asins, target_count=40, max_per_leaf=2)

        # S1: Cold-Start / Zero-Review-Reliance (graph_review_count <= 2, query-time review masking enabled)
        s1_candidates = [
            c for c in cold_pool
            if int(c.get("graph_review_count") or 0) <= 2
            and (len(c.get("features") or []) >= 2 or c.get("details_json"))
        ]
        logger.info("S1 pool size: %d", len(s1_candidates))
        s1_items = build_stratum_items("S1", s1_candidates, by_leaf, used_asins, target_count=40, max_per_leaf=2)

        # S2: Multi-Constraint Structured (>= 2 HAS_ATTRIBUTE edges, >= 3 features, details_json)
        s2_candidates = [
            c for c in general_pool
            if len(c.get("attributes") or []) >= 2
            and len(c.get("features") or []) >= 3
            and c.get("details_json")
            and int(c.get("graph_review_count") or 0) >= 3
        ]
        logger.info("S2 pool size: %d", len(s2_candidates))
        s2_items = build_stratum_items("S2", s2_candidates, by_leaf, used_asins, target_count=40, max_per_leaf=2)

        # S3: Accessory Trap (primary devices in verified head-noun categories where >50% of title matches are accessories)
        leaf_to_trap: Dict[str, Dict[str, Any]] = {}
        for spec in S3_TRAP_SPECS:
            for leaf_name in spec["primary_leaves"]:
                leaf_to_trap[leaf_name.lower()] = spec

        s3_candidates: List[Dict[str, Any]] = []
        for c in general_pool:
            leaf_lower = _leaf_key(c).lower()
            cat_lower = str(c.get("category") or "").lower()
            spec = leaf_to_trap.get(leaf_lower) or leaf_to_trap.get(cat_lower)
            if not spec:
                continue
            title_str = str(c.get("title") or "")
            if SECONDARY_ACCESSORY_PAT.search(title_str):
                continue
            c_copy = dict(c)
            c_copy["trap_head_noun"] = spec["head_noun"]
            c_copy["trap_out_of_taxon_ratio"] = spec["out_of_taxon_ratio"]
            c_copy["product_type_override"] = spec["head_noun"]
            s3_candidates.append(c_copy)

        logger.info("S3 pool size: %d", len(s3_candidates))
        s3_items = build_stratum_items("S3", s3_candidates, by_leaf, used_asins, target_count=40, max_per_leaf=4)

        # S4: Many-Feature Trade-off (>= 5 features, >= 2 attributes, details_json)
        s4_candidates = [
            c for c in general_pool
            if len(c.get("features") or []) >= 5
            and len(c.get("attributes") or []) >= 2
            and c.get("details_json")
            and int(c.get("graph_review_count") or 0) >= 5
        ]
        logger.info("S4 pool size: %d", len(s4_candidates))
        s4_items = build_stratum_items("S4", s4_candidates, by_leaf, used_asins, target_count=40, max_per_leaf=2)

        # Stratum A: 30 Ambiguous CLARIFY-gold queries
        a_items = build_ambiguous_benchmark_items(salt=BENCHMARK_V2_SALT)

        all_items: List[Dict[str, Any]] = (
            s0_items + s1_items + s2_items + s3_items + s4_items + a_items + legacy_items
        )

        # Validate gold annotations & live graph grounding
        gold_errors = validate_gold_annotations(all_items)
        if gold_errors:
            raise RuntimeError(f"Gold annotation validation failed: {gold_errors[:5]}")

        grounding = validate_benchmark_graph_grounding(all_items, connector)
        if grounding.get("missing_asins"):
            raise RuntimeError(f"Graph grounding failed: {grounding}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_bytes = (json.dumps(all_items, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        output_path.write_bytes(raw_bytes)
        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()

        # Build summary manifest
        stratum_counts: Dict[str, Dict[str, int]] = {}
        for item in all_items:
            st = str(item.get("stratum") or "legacy")
            sp = str(item.get("split") or "tuning")
            bucket = stratum_counts.setdefault(st, {"total": 0, "tuning": 0, "test": 0})
            bucket["total"] += 1
            bucket[sp] = bucket.get(sp, 0) + 1

        s0_s4_items = s0_items + s1_items + s2_items + s3_items + s4_items
        overlaps = [float(i["leakage_audit"]["title_token_overlap"]) for i in s0_s4_items]
        tfidf_ranks = [int(i["leakage_audit"]["tfidf_target_rank"]) for i in s0_s4_items]

        manifest = {
            "version": "benchmark_v2",
            "release": "R2b",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "salt": BENCHMARK_V2_SALT,
            "seed": BENCHMARK_V2_SEED,
            "benchmark_path": str(output_path.relative_to(PROJECT_ROOT)),
            "sha256": sha256_hex,
            "total_queries": len(all_items),
            "stratum_split_counts": stratum_counts,
            "split_totals": {
                "tuning": sum(1 for i in all_items if i.get("split") == "tuning"),
                "test": sum(1 for i in all_items if i.get("split") == "test"),
            },
            "distinct_categories_s0_s4": len({i["category"] for i in s0_s4_items}),
            "distinct_taxon_leaves_s0_s4": len({i.get("taxon_leaf") or i["category"] for i in s0_s4_items}),
            "unique_target_asins": len({i["target_asin"] for i in all_items if i.get("target_asin")}),
            "leakage_audit_summary": {
                "s0_s4_count": len(s0_s4_items),
                "model_code_leaks": sum(1 for i in s0_s4_items if i["leakage_audit"]["model_code_leak"]),
                "unflagged_brand_leaks": sum(1 for i in s0_s4_items if i["leakage_audit"]["unflagged_brand_leak"]),
                "max_title_token_overlap": round(max(overlaps), 4) if overlaps else 0.0,
                "mean_title_token_overlap": round(sum(overlaps) / len(overlaps), 4) if overlaps else 0.0,
                "min_tfidf_target_rank": min(tfidf_ranks) if tfidf_ranks else 0,
                "tfidf_rank_1_count": sum(1 for r in tfidf_ranks if r == 1),
            },
            "graph_grounding": grounding,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info("Successfully generated %s (SHA-256: %s)", output_path, sha256_hex)
        logger.info("Split totals: %s | Stratum counts: %s", manifest["split_totals"], stratum_counts)
        return manifest
    finally:
        connector.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and freeze Stratified Benchmark v2 (Release R2b).")
    parser.add_argument(
        "--output",
        default="evaluations/benchmarks/benchmark_v2.json",
        help="Output path for benchmark_v2.json",
    )
    parser.add_argument(
        "--manifest",
        default="evaluations/benchmarks/benchmark_v2_manifest.json",
        help="Output path for benchmark_v2_manifest.json",
    )
    parser.add_argument(
        "--legacy",
        default="live_eval_dataset.json",
        help="Path to legacy-21 continuity dataset",
    )
    args = parser.parse_args()
    build_benchmark_v2(
        output_path=PROJECT_ROOT / args.output,
        manifest_path=PROJECT_ROOT / args.manifest,
        legacy_path=PROJECT_ROOT / args.legacy,
    )


if __name__ == "__main__":
    main()
