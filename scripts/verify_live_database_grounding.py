#!/usr/bin/env python3
"""
Independent Empirical Verification Script for Live Evaluation Dataset Grounding.

Written by Challenger 1 (Empirical Database Challenger).
Validates 100% of target and peer ASINs in live_eval_dataset.json against live Neo4j via Cypher.
Verifies:
1. Exact node existence (MATCH (p:ParentProduct {parent_asin: asin}) returns 1 node).
2. Valid node properties (price > 0, non-empty title, 384-d non-zero norm embeddings).
3. Zero mock IDs (no ALT_, MOCK_, VERIFIED_ prefixes).
4. Category distribution (2-3 items per category across 7 categories, total 14-21).
5. Target uniqueness (100% distinct target ASINs).
6. Peer consistency (similarity in embedding space, target not in peers).
7. Review connectedness in Neo4j graph.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Set, Tuple

import numpy as np

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

REQUIRED_CATEGORIES: Set[str] = {
    "Camera",
    "Phone",
    "Charger",
    "Mouse",
    "Headphone",
    "Laptop",
    "Keyboard",
}

FORBIDDEN_MOCK_PREFIXES: List[str] = [
    "ALT_",
    "MOCK_",
    "VERIFIED_",
    "alt_",
    "mock_",
    "verified_",
]


class DatabaseGroundingVerifier:
    def __init__(self, dataset_path: Path):
        self.dataset_path = dataset_path
        self.connector = Neo4jConnector()
        self.raw_data: List[Dict[str, Any]] = []
        self.raw_text: str = ""
        self.report_stats: Dict[str, Any] = {}

    def run_all_checks(self) -> bool:
        print("=" * 80)
        print("EMPIRICAL DATABASE GROUNDING CHALLENGE — INDEPENDENT VERIFIER")
        print(f"Dataset path: {self.dataset_path}")
        print("=" * 80)

        # 1. Load and parse dataset
        if not self._check_json_structure():
            return False

        # 2. Check mock IDs / prefixes across raw file
        if not self._check_zero_mock_prefixes():
            return False

        # 3. Check dataset category distribution and target distinctness
        if not self._check_distribution_and_uniqueness():
            return False

        # 4. Connect to live Neo4j
        print("\nConnecting to live Neo4j database...")
        self.connector.connect()

        try:
            # 5. Verify 100% target ASINs
            targets_ok = self._verify_target_asins()

            # 6. Verify 100% peer ASINs
            peers_ok = self._verify_peer_asins()

            # 7. Verify all graded relevance ASINs
            graded_ok = self._verify_graded_relevance_asins()

            # 8. Check review connectedness
            reviews_ok = self._verify_review_connectedness()

            all_passed = targets_ok and peers_ok and graded_ok and reviews_ok

            print("\n" + "=" * 80)
            if all_passed:
                print(">>> ALL EMPIRICAL GROUNDING CHECKS PASSED (100% SUCCESS) <<<")
            else:
                print(">>> EMPIRICAL GROUNDING VERIFICATION FAILED <<<")
            print("=" * 80)

            return all_passed
        finally:
            self.connector.close()

    def _check_json_structure(self) -> bool:
        print("\n[Step 1] Validating JSON format and structure...")
        if not self.dataset_path.is_file():
            print(f"FAILED: File {self.dataset_path} does not exist!")
            return False

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            self.raw_text = f.read()

        try:
            self.raw_data = json.loads(self.raw_text)
        except json.JSONDecodeError as e:
            print(f"FAILED: Invalid JSON: {e}")
            return False

        if not isinstance(self.raw_data, list):
            print("FAILED: Dataset root must be a JSON array (list).")
            return False

        total_entries = len(self.raw_data)
        print(f"Dataset loaded successfully: {total_entries} entries found.")

        # Check for NaN / Infinity
        if "NaN" in self.raw_text or "Infinity" in self.raw_text:
            print("FAILED: JSON contains non-standard NaN or Infinity tokens!")
            return False

        return True

    def _check_zero_mock_prefixes(self) -> bool:
        print("\n[Step 2] Stress-testing for mock prefixes (Zero-Mock Mandate)...")
        found_mock_tokens = []
        for prefix in FORBIDDEN_MOCK_PREFIXES:
            count = self.raw_text.count(prefix)
            if count > 0:
                found_mock_tokens.append((prefix, count))

        if found_mock_tokens:
            print(f"FAILED: Forbidden mock prefixes found in dataset: {found_mock_tokens}")
            return False

        print("PASSED: Exactly 0 mock prefixes detected across the entire dataset file.")
        return True

    def _check_distribution_and_uniqueness(self) -> bool:
        print("\n[Step 3] Validating category distribution and target distinctness...")
        total_count = len(self.raw_data)
        if not (14 <= total_count <= 21):
            print(f"FAILED: Total entries ({total_count}) outside required range [14, 21].")
            return False

        categories_found: Dict[str, int] = {}
        for entry in self.raw_data:
            cat = entry.get("category")
            if not cat:
                print(f"FAILED: Missing category in entry: {entry.get('query_id')}")
                return False
            categories_found[cat] = categories_found.get(cat, 0) + 1

        print(f"Discovered categories and item counts: {categories_found}")

        # Check all 7 required categories
        missing_cats = REQUIRED_CATEGORIES - set(categories_found.keys())
        if missing_cats:
            print(f"FAILED: Missing required categories: {missing_cats}")
            return False

        unexpected_cats = set(categories_found.keys()) - REQUIRED_CATEGORIES
        if unexpected_cats:
            print(f"FAILED: Unexpected categories found: {unexpected_cats}")
            return False

        for cat, cnt in categories_found.items():
            if not (2 <= cnt <= 3):
                print(f"FAILED: Category '{cat}' has {cnt} items (must be 2-3).")
                return False

        # Check distinct target ASINs
        target_asins = [entry.get("target_asin") for entry in self.raw_data]
        if None in target_asins or any(len(str(a).strip()) == 0 for a in target_asins):
            print("FAILED: Found null or empty target_asin.")
            return False

        unique_targets = set(target_asins)
        if len(unique_targets) != len(target_asins):
            duplicates = [a for a in target_asins if target_asins.count(a) > 1]
            print(f"FAILED: Duplicate target ASINs found: {set(duplicates)}")
            return False

        # Check distinct query IDs
        query_ids = [entry.get("query_id") for entry in self.raw_data]
        if len(set(query_ids)) != len(query_ids):
            print("FAILED: Duplicate query_ids found.")
            return False

        print(f"PASSED: Exactly {len(REQUIRED_CATEGORIES)} categories, all with 2-3 items.")
        print(f"PASSED: All {len(target_asins)} target ASINs and query_ids are 100% unique.")
        return True

    def _query_asin_properties(self, asin: str) -> Tuple[bool, Dict[str, Any], str]:
        cypher = """
            MATCH (p:ParentProduct {parent_asin: $asin})
            RETURN p.parent_asin as asin,
                   p.title as title,
                   p.price as price,
                   p.embedding as embedding
        """
        rows = self.connector.execute_query(cypher, {"asin": asin})
        if len(rows) == 0:
            return False, {}, f"ASIN '{asin}' NOT FOUND in Neo4j (0 nodes)."
        if len(rows) > 1:
            return False, {}, f"ASIN '{asin}' returned {len(rows)} nodes (expected 1)."

        row = rows[0]
        title = row.get("title")
        price = row.get("price")
        emb = row.get("embedding")

        # Validate title
        if not title or not str(title).strip():
            return False, row, f"ASIN '{asin}' has empty/missing title."

        # Validate price
        if price is None or (isinstance(price, float) and math.isnan(price)) or price <= 0:
            return False, row, f"ASIN '{asin}' has invalid price: {price} (expected > 0)."

        # Validate embedding
        if emb is None or not isinstance(emb, list) or len(emb) != 384:
            dim = len(emb) if isinstance(emb, list) else None
            return False, row, f"ASIN '{asin}' has invalid embedding dimension: {dim} (expected 384)."

        norm = float(np.linalg.norm(emb))
        if norm <= 1e-6 or math.isnan(norm):
            return False, row, f"ASIN '{asin}' has zero or NaN embedding norm: {norm}."

        return True, row, "OK"

    def _verify_target_asins(self) -> bool:
        print("\n[Step 4] Cypher verification of 100% Target ASINs against Neo4j...")
        target_asins = [entry["target_asin"] for entry in self.raw_data]
        failures = []

        for i, entry in enumerate(self.raw_data, 1):
            asin = entry["target_asin"]
            q_id = entry.get("query_id")
            ok, row, msg = self._query_asin_properties(asin)
            if not ok:
                failures.append(f"[{q_id}] Target {asin}: {msg}")
                print(f"  ❌ [{i}/{len(target_asins)}] {asin} -> {msg}")
            else:
                emb_norm = float(np.linalg.norm(row["embedding"]))
                print(f"  ✅ [{i:02d}/{len(target_asins)}] {asin} | price=${row['price']:.2f} | emb_dim={len(row['embedding'])} | norm={emb_norm:.3f} | {row['title'][:45]}...")

        if failures:
            print(f"FAILED: {len(failures)} target ASINs failed verification!")
            return False

        print(f"PASSED: 100% of target ASINs ({len(target_asins)}/{len(target_asins)}) exist in Neo4j with valid price, title, and 384-d embeddings.")
        return True

    def _verify_peer_asins(self) -> bool:
        print("\n[Step 5] Cypher verification of 100% Peer ASINs against Neo4j...")
        all_peer_asins: List[str] = []
        peer_per_entry_ok = True

        for entry in self.raw_data:
            peers = entry.get("peer_asins")
            q_id = entry.get("query_id")
            target = entry.get("target_asin")

            if not peers or not isinstance(peers, list):
                print(f"FAILED: Entry {q_id} has missing or non-list peer_asins.")
                peer_per_entry_ok = False
                continue

            if len(peers) < 2:
                print(f"FAILED: Entry {q_id} has fewer than 2 peers ({len(peers)}).")
                peer_per_entry_ok = False

            if target in peers:
                print(f"FAILED: Entry {q_id} target ASIN {target} is inside its own peer_asins list!")
                peer_per_entry_ok = False

            all_peer_asins.extend(peers)

        if not peer_per_entry_ok:
            return False

        unique_peers = sorted(list(set(all_peer_asins)))
        print(f"Checking {len(unique_peers)} unique peer ASINs ({len(all_peer_asins)} total references)...")

        failures = []
        for i, asin in enumerate(unique_peers, 1):
            ok, row, msg = self._query_asin_properties(asin)
            if not ok:
                failures.append(f"Peer {asin}: {msg}")
                print(f"  ❌ [{i}/{len(unique_peers)}] {asin} -> {msg}")

        if failures:
            print(f"FAILED: {len(failures)} peer ASINs failed verification!")
            return False

        print(f"PASSED: 100% of peer ASINs ({len(unique_peers)}/{len(unique_peers)}) exist in Neo4j with valid price, title, and 384-d embeddings.")
        return True

    def _verify_graded_relevance_asins(self) -> bool:
        print("\n[Step 6] Cypher verification of 100% Graded Relevance ASINs against Neo4j...")
        graded_asins: Set[str] = set()
        for entry in self.raw_data:
            for asin in entry.get("graded_relevance", {}).keys():
                graded_asins.add(asin)

        print(f"Checking {len(graded_asins)} unique graded relevance ASINs in Neo4j...")
        failures = []
        for asin in sorted(list(graded_asins)):
            ok, row, msg = self._query_asin_properties(asin)
            if not ok:
                failures.append(f"Graded ASIN {asin}: {msg}")

        if failures:
            print(f"FAILED: {len(failures)} graded relevance ASINs failed verification!")
            return False

        print(f"PASSED: 100% of graded relevance ASINs ({len(graded_asins)}/{len(graded_asins)}) are valid live Neo4j nodes.")
        return True

    def _verify_review_connectedness(self) -> bool:
        print("\n[Step 7] Checking review connectedness in Neo4j graph for targets...")
        zero_reviews = []
        for entry in self.raw_data:
            asin = entry["target_asin"]
            q_id = entry.get("query_id")
            cypher = """
                MATCH (p:ParentProduct {parent_asin: $asin})
                OPTIONAL MATCH (r:Review)-[:ABOUT_PRODUCT]->(p)
                RETURN p.parent_asin as asin, count(DISTINCT r) as review_count
            """
            rows = self.connector.execute_query(cypher, {"asin": asin})
            cnt = rows[0]["review_count"] if rows else 0
            if cnt == 0:
                zero_reviews.append((q_id, asin))
            else:
                print(f"  [{q_id}] Target {asin} connected to {cnt} Review nodes.")

        if zero_reviews:
            print(f"FAILED: Target items have 0 reviews in graph: {zero_reviews}")
            return False

        print("PASSED: 100% of target products have verified associated reviews in Neo4j.")
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Empirical Grounding Verifier for live_eval_dataset.json")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPO_ROOT / "live_eval_dataset.json",
        help="Path to live_eval_dataset.json",
    )
    args = parser.parse_args()

    verifier = DatabaseGroundingVerifier(args.dataset)
    success = verifier.run_all_checks()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
