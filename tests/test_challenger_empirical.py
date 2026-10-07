"""
Adversarial Stress Tests and Empirical Verification for Milestone 4 Architectural Fixes.
Author: Challenger 2 (teamwork_preview_challenger_m4_2)
"""

import json
import math
import re
import pytest
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "recommendation_password")


def get_neo4j_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)


def test_challenge_bayesian_cypher_ranking_distribution():
    """
    Challenge AFP-005 Part 1:
    Test the Bayesian ranking formula:
      score = ((10 * 4.0 + count * rating) / (10 + count)) * log(1 + count)
    Examines:
    1. What happens to products with 0 reviews/ratings? (Cold-start items)
    2. Does it rank high-volume mediocre products above low-volume excellent products?
    3. Where does Logitech C920 rank in Query 21 under cypher_only?
    """
    driver = get_neo4j_driver()
    cypher = """
    MATCH (node:ParentProduct)
    WHERE (node.price IS NULL OR node.price <= 70.0)
      AND toLower(node.title) CONTAINS 'webcam'
    WITH node,
         coalesce(node.rating, node.avg_rating, 0.0) AS raw_rating,
         coalesce(node.rating_count, node.review_count, 0) AS raw_count,
         coalesce(node.price, 999999.0) AS sort_price
    WITH node, raw_rating, raw_count, sort_price,
         ((10.0 * 4.0 + (toFloat(raw_count) * raw_rating)) / (10.0 + toFloat(raw_count)))
         * log(1.0 + toFloat(raw_count)) AS relevance_score
    RETURN node.parent_asin AS asin, node.title AS title, raw_rating, raw_count, 
           relevance_score AS score, node.price AS price
    ORDER BY score DESC, sort_price ASC
    """
    with driver.session() as session:
        rows = session.run(cypher).data()

    print(f"\nTotal webcam matches: {len(rows)}")
    zero_score_count = sum(1 for r in rows if r["score"] == 0.0)
    print(f"Products with score == 0.0: {zero_score_count} ({zero_score_count / len(rows) * 100:.1f}%)")

    asins = [r["asin"] for r in rows]
    c920_rank = asins.index("B006JH8T3S") + 1 if "B006JH8T3S" in asins else -1
    print(f"Logitech C920 rank under Bayesian ranking: {c920_rank}")
    if c920_rank > 0:
        c920 = rows[c920_rank - 1]
        print(f"C920 details: score={c920['score']:.2f}, rating={c920['raw_rating']}, count={c920['raw_count']}")

    print("\nTop 5 products:")
    for i, r in enumerate(rows[:5], 1):
        print(f"  {i}. [{r['asin']}] score={r['score']:6.2f} (rating={r['raw_rating']}, count={r['raw_count']}) - {r['title'][:40]}")

    print("\nBottom 5 products:")
    for i, r in enumerate(rows[-5:], len(rows) - 4):
        print(f"  {i}. [{r['asin']}] score={r['score']:6.2f} (rating={r['raw_rating']}, count={r['raw_count']}) - {r['title'][:40]}")

    driver.close()
    return rows


def test_challenge_eav_regex_edge_cases():
    """
    Challenge AFP-005 Part 2:
    Stress-test Tier A regex and Tier B Cypher unit stripping against real e-commerce attribute values.
    """
    # Tier A regex from AFP-005:
    NUMERIC_REGEX = re.compile(r"[-+]?\d*\.?\d+")

    def parse_numeric_attribute(raw_val):
        if raw_val is None:
            return None
        val_str = str(raw_val).strip()
        match = NUMERIC_REGEX.search(val_str)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
        return None

    # Test cases:
    cases = [
        ("144 Hz", 144.0, "Standard spaced unit"),
        ("144Hz", 144.0, "Unspaced unit"),
        ("1 ms", 1.0, "Response time"),
        ("0.5 ms", 0.5, "Decimal response time"),
        (".5 ms", 0.5, "Leading dot decimal"),
        ("16 GB", 16.0, "Memory"),
        ("27 Inches", 27.0, "Screen size"),
        ("27\"", 27.0, "Quote mark unit"),
        ("27-inch", 27.0, "Hyphenated unit"),
        ("Model-1234", None, "Model number with hyphen (should NOT be -1234.0!)"),
        ("WiFi-6", None, "WiFi generation (should NOT be -6.0!)"),
        ("Cat-6", None, "Cable category (should NOT be -6.0!)"),
        ("Core i7-12700K", None, "CPU model (should NOT be -12700.0!)"),
        ("-20 dB", -20.0, "Negative gain (true negative)"),
        ("-10 C", -10.0, "Negative temperature (true negative)"),
        ("10-15 hrs", 10.0, "Range (min or max ambiguous)"),
        ("1920x1080", 1920.0, "Resolution compound (only extracts 1920)"),
        ("USB 3.0", 3.0, "USB version"),
        ("4K", 4.0, "Resolution symbol (4K parsed as 4.0, not 3840!)"),
        ("N/A", None, "Not applicable"),
        ("", None, "Empty string"),
    ]

    print("\n--- EAV REGEX STRESS TEST RESULTS ---")
    failures = []
    for raw, expected, desc in cases:
        parsed = parse_numeric_attribute(raw)
        status = "PASS" if parsed == expected else "FAIL"
        if status == "FAIL":
            failures.append((raw, expected, parsed, desc))
        print(f"  {raw:18} -> Parsed: {str(parsed):8} | Expected: {str(expected):8} [{status}] ({desc})")

    # Now test Cypher Tier B fallback:
    driver = get_neo4j_driver()
    cypher_tier_b = """
    WITH $raw AS raw
    RETURN coalesce(
        toFloat(split(raw, ' ')[0]),
        toFloat(replace(replace(replace(replace(raw, 'Hz', ''), 'ms', ''), 'GB', ''), '"', ''))
    ) AS parsed
    """
    print("\n--- CYPHER TIER B FALLBACK TEST RESULTS ---")
    cypher_cases = ["144 Hz", "144Hz", "1 ms", "16 GB", "27\"", "27-inch", "4K", "65W", "3.5 mm"]
    with driver.session() as s:
        for c in cypher_cases:
            rec = s.run(cypher_tier_b, {"raw": c}).single()
            val = rec["parsed"]
            print(f"  Cypher Tier B: '{c:10}' -> {val}")

    driver.close()
    return failures


if __name__ == "__main__":
    test_challenge_bayesian_cypher_ranking_distribution()
    test_challenge_eav_regex_edge_cases()
