#!/usr/bin/env python3
"""
scripts/enrich_taxons_skos.py — SKOS-Compliant Automated Taxonomic Synonym Induction

RS-24 Implementation (Release R3.2): Domain-Agnostic Vocabulary as Data (Neo4j Taxon.alt_labels).

Instead of maintaining hardcoded regexes in Python, this script inducts alternate lexical labels
(skos:altLabel) for all 1,183 Taxon nodes directly from graph structure, morphological inflections,
and catalogue titles, saving them into Neo4j and exporting a deterministic JSON artifact:

    (:Taxon {name: "Webcams", alt_labels: ["webcam", "streaming camera", "pc camera", "video conference camera", ...]})

Architecture:
1. Extract Taxon context: name, taxonomic path/breadcrumbs, depth, product count, and sample product titles.
2. Enforce Head-Noun Integrity:
   - Pure device categories (e.g. "Traditional Laptops", "Tablets", "Mice", "Microphones") receive
     singular/plural head-noun forms ("laptop", "tablet", "mouse", "microphone") and buyer synonyms.
   - Accessory/bundle containers (e.g. "Laptop Accessories", "Tablet Accessories", "Keyboard & Mouse Combos")
     never emit bare device nouns; every alt_label preserves the accessory/container head noun.
3. Filter out brand names (cross-checked against :Brand nodes in Neo4j), token reduplications ('webcam webcam'),
   and plural-noun modifier noise ('batteries camera', 'toys cameras').
4. Persist alt_labels onto all 1,183 :Taxon nodes in Neo4j and export graph_versions/v2/taxon_skos_alt_labels.json.
"""

import argparse
import json
import logging
import os
import re
import sys
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
from src.knowledge_graph.graphdb.resolver_service import (
    ACCESSORY_HEAD_LEMMAS,
    decompose_type_phrase,
    normalize_lemma,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("enrich_taxons_skos")

# High-value buyer colloquial synonyms grounded in catalogue categories
CURATED_COLLOQUIAL_SYNONYMS: Dict[str, List[str]] = {
    "webcams": [
        "webcam", "web camera", "streaming camera", "pc camera",
        "computer camera", "video conference camera", "usb camera", "web cam", "desktop webcam",
    ],
    "traditional laptops": [
        "laptop", "laptops", "notebook", "notebooks", "notebook computer",
        "laptop computer", "portable computer", "pc laptop", "gaming laptop", "chromebook", "macbook",
    ],
    "laptops": [
        "laptop", "notebook", "notebooks", "laptop computer", "portable computer", "gaming laptop", "chromebook",
    ],
    "2 in 1 laptops": [
        "2 in 1 laptop", "convertible laptop", "touchscreen laptop", "hybrid laptop",
    ],
    "tablets": [
        "tablet", "android tablet", "touchscreen tablet", "tablet computer", "ipad",
    ],
    "mice": [
        "mouse", "computer mouse", "wireless mouse", "optical mouse", "ergonomic mouse", "pc mouse",
    ],
    "gaming mice": [
        "gaming mouse", "wired gaming mouse", "wireless gaming mouse",
    ],
    "keyboards": [
        "keyboard", "computer keyboard", "typing keyboard", "pc keyboard",
        "mechanical keyboard", "wireless keyboard",
    ],
    "over-ear headphones": [
        "over-ear headphones", "around-ear headphones", "circumaural headphones",
        "over ear headset", "wireless over-ear headphones", "over the ear headphones",
        "over-ear headphone", "bluetooth headphones", "wireless headphones",
    ],
    "earbud headphones": [
        "earbuds", "earbud", "in-ear headphones", "in-ear monitors",
        "earphones", "wireless earbuds", "true wireless earbuds",
    ],
    "on-ear headphones": [
        "on-ear headphones", "on ear headphones", "supra-aural headphones", "on-ear headset",
    ],
    "headphones": [
        "headphone", "audio headphones", "stereo headphones", "music headphones",
    ],
    "digital cameras": [
        "digital camera", "point and shoot camera", "digicam", "compact camera",
        "vlogging camera", "still camera", "digital photo camera",
    ],
    "instant cameras": [
        "instant camera", "instant film camera", "polaroid camera", "instant print camera",
    ],
    "microphones": [
        "microphone", "mic", "vocal microphone", "recording microphone", "wireless microphone",
    ],
    "computer microphones": [
        "computer microphone", "usb microphone", "pc microphone", "streaming microphone", "desktop microphone",
    ],
    "chargers & adapters": [
        "charger", "wall charger", "power adapter", "usb charger", "usb c charger",
        "charging adapter", "fast charger", "laptop charger",
    ],
    "ac adapters": [
        "ac adapter", "power adapter", "power brick", "wall power adapter", "dc power adapter",
    ],
    "power converters": [
        "power converter", "travel power adapter", "travel adapter", "voltage converter", "universal travel adapter",
    ],
    "battery chargers": [
        "battery charger", "rechargeable battery charger", "wall battery charger",
    ],
    "bestselling renewed smartphones": [
        "smartphone", "smartphones", "phone", "cell phone", "mobile phone", "unlocked smartphone", "iphone", "renewed smartphone",
    ],
    "cell phones & accessories": [
        "cell phone", "smartphone", "mobile phone", "phone", "unlocked phone",
    ],
    "monitors": [
        "monitor", "computer monitor", "desktop monitor", "pc monitor", "display monitor", "gaming monitor",
    ],
    "routers": [
        "router", "wifi router", "wireless router", "internet router", "home router",
    ],
    "video projectors": [
        "projector", "video projector", "home theater projector", "movie projector", "mini projector",
    ],
    "complete tripods": [
        "tripod", "camera tripod", "photography tripod", "travel tripod",
    ],
    "portable bluetooth speakers": [
        "bluetooth speaker", "portable speaker", "wireless speaker", "portable bluetooth speaker",
    ],
    "bookshelf speakers": [
        "bookshelf speaker", "stereo bookshelf speakers", "home bookshelf speakers",
    ],
    "outdoor speakers": [
        "outdoor speaker", "patio speaker", "weatherproof speaker",
    ],
}

SPEC_AND_NOISE_BLACKLIST: Set[str] = {
    "4k", "8k", "1080p", "720p", "hd", "fhd", "uhd", "pro", "mini", "max", "plus", "ultra",
    "best", "new", "old", "black", "white", "silver", "gray", "grey", "blue", "red", "pink",
    "gold", "green", "inch", "inches", "pack", "set", "pair", "piece", "pieces", "version",
    "model", "series", "generation", "gen", "edition", "style", "type", "size", "color",
    "with", "for", "and", "the", "from", "under", "over", "into", "onto", "within", "without",
    "via", "per", "your", "our", "any", "all", "this", "that", "way", "bay", "port", "ear",
    "depstech", "logitech", "nisheng", "saneen", "wikico", "oladance", "sony", "samsung",
    "apple", "dell", "hp", "lenovo", "acer", "asus", "anker", "ugreen", "belkin", "jbl",
    "bose", "sennheiser", "razer", "corsair", "steelseries", "hyperx", "canon", "nikon",
    "fujifilm", "panasonic", "olympus", "gopro", "garmin", "tp-link", "netgear", "d-link",
}

# English locative particles that form compound adjectives with the following token
# ('in ear', 'on ear', 'over ear'); a mined modifier preceded by one is a compound tail, not a type label.
COMPOUND_PARTICLES: Set[str] = {"in", "on", "over", "under", "up", "off", "out", "around", "behind"}


class SKOSTaxonEnricher:
    """Enriches Neo4j Taxon nodes with W3C SKOS altLabels."""

    def __init__(self, connector: Optional[Neo4jConnector] = None):
        load_dotenv()
        self.connector = connector or Neo4jConnector()
        self.connector.connect()
        self.known_brands: Set[str] = self._load_brand_tokens()

    def close(self):
        if self.connector:
            self.connector.close()

    def _load_brand_tokens(self) -> Set[str]:
        """Loads lowercase brand tokens from Neo4j to prevent brand names from leaking into SKOS alt_labels."""
        brands: Set[str] = set(SPEC_AND_NOISE_BLACKLIST)
        try:
            with self.connector.session() as session:
                res = session.run("MATCH (b:Brand) WHERE b.name IS NOT NULL RETURN toLower(b.name) AS name LIMIT 10000")
                for r in res:
                    bname = (r["name"] or "").strip()
                    if bname and len(bname) >= 3:
                        brands.add(bname)
                        for tok in re.findall(r"[a-z0-9]+", bname):
                            if len(tok) >= 4 and tok not in {"audio", "video", "digital", "smart", "power", "wireless", "cable", "sound", "photo", "tech", "home", "mobile", "computer", "gaming"}:
                                brands.add(tok)
        except Exception as e:
            logger.debug(f"Brand token load skipped: {e}")
        return brands

    def fetch_taxons_with_context(
        self,
        taxon_names: Optional[List[str]] = None,
        taxon_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """Fetches Taxon nodes along with breadcrumb paths and sample product titles."""
        query = """
        MATCH (t:Taxon)
        WHERE ($names IS NULL OR t.name IN $names)
          AND ($ids IS NULL OR t.taxon_id IN $ids)
        OPTIONAL MATCH (p:ParentProduct)-[:IN_TAXON]->(t)
        WITH t, collect(p.title)[0..10] AS sample_titles
        RETURN t.taxon_id AS taxon_id,
               t.name AS name,
               t.path AS path,
               t.depth AS depth,
               t.product_count AS product_count,
               t.alt_labels AS existing_alt_labels,
               sample_titles
        ORDER BY COALESCE(t.product_count, 0) DESC
        """
        if limit:
            query += f" LIMIT {int(limit)}"

        params = {
            "names": taxon_names if taxon_names else None,
            "ids": taxon_ids if taxon_ids else None,
        }

        with self.connector.session() as session:
            result = session.run(query, params)
            records = [dict(r) for r in result]

        return records

    def induct_alt_labels(self, taxon_info: Dict, use_llm: bool = False) -> List[str]:
        """
        Induces clean W3C SKOS alt_labels using morphological decomposition,
        head-noun integrity rules, and catalogue-grounded title mining (plus optional LLM).
        """
        name = taxon_info["name"]
        path = taxon_info.get("path") or [name]
        titles = taxon_info.get("sample_titles") or []

        if use_llm and os.getenv("OPENAI_API_KEY"):
            try:
                labels = self._induct_via_llm(name, path, titles)
                if labels:
                    return labels
            except Exception as e:
                logger.warning(f"LLM induction failed for '{name}': {e}. Falling back to deterministic catalogue induction.")

        return self._induct_via_catalogue_heuristics(name, path, titles)

    def _induct_via_llm(self, name: str, path: List[str], titles: List[str]) -> List[str]:
        """Calls OpenAI Chat Completion to generate SKOS altLabels."""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        hierarchy_str = " > ".join(path)
        sample_str = "\n".join([f"- {t}" for t in titles[:5]]) if titles else "None available"

        prompt = f"""You are a taxonomy engineer enriching an e-commerce Knowledge Graph using the W3C SKOS (Simple Knowledge Organization System) standard.

Your task is to generate alternate lexical labels (`skos:altLabel`) for the following category node.
Category Name (prefLabel): "{name}"
Taxonomic Hierarchy: "{hierarchy_str}"

Sample Product Titles currently assigned to this category in the catalog:
{sample_str}

Instructions:
1. Provide 4 to 8 high-relevance search synonyms, lexical variations, and everyday colloquial terms that buyers use to find products in this category.
2. Include common singular and plural variations where natural.
3. CRITICAL HEAD-NOUN RULE: If the category is an accessory, part, case, cable, or mount (e.g. "Laptop Accessories"), every synonym MUST remain an accessory/part/case/cable/mount and MUST NOT be the bare device name ("laptop").
4. Exclude brand names (e.g. Logitech, Sony, Apple, Dell, HP, Oladance).
5. Exclude specific technical specs (e.g. 4K, 1080p, 60fps, 16GB, Bluetooth, USB-C).
6. Output ONLY a valid JSON array of lowercase strings, for example: ["synonym a", "synonym b"].
"""
        response = llm.invoke(prompt)
        content = response.content.strip()
        match = re.search(r"\[.*?\]", content, re.DOTALL)
        if match:
            labels = json.loads(match.group(0))
            return self._clean_labels(name, labels)
        return []

    def _induct_via_catalogue_heuristics(self, name: str, path: List[str], titles: List[str]) -> List[str]:
        """
        Deterministic, domain-agnostic SKOS alt_label generator enforcing Principle P-9
        and Head-Noun Integrity.
        """
        ordered_candidates: List[str] = []
        name_lower = name.lower().strip()
        decomp = decompose_type_phrase(name)
        is_acc = decomp["is_accessory_head"]
        head_lemma = decomp["head_lemma"]
        lemmas = decomp["lemmas"]

        # 1. Curated high-frequency colloquial expansions
        if name_lower in CURATED_COLLOQUIAL_SYNONYMS:
            ordered_candidates.extend(CURATED_COLLOQUIAL_SYNONYMS[name_lower])

        # 2. Lemmatized whole-phrase singular/plural variations
        if lemmas:
            lemmatized_phrase = " ".join(lemmas)
            ordered_candidates.append(lemmatized_phrase)
            # Pluralized form of head lemma if singular
            if head_lemma and not head_lemma.endswith("s"):
                plural_head = (
                    head_lemma[:-1] + "ies"
                    if head_lemma.endswith("y") and len(head_lemma) > 2 and head_lemma[-2] not in "aeiou"
                    else ("mice" if head_lemma == "mouse" else head_lemma + "s")
                )
                if len(lemmas) > 1:
                    ordered_candidates.append(" ".join(list(lemmas[:-1]) + [plural_head]))
                else:
                    ordered_candidates.append(plural_head)

        # 3. Head-Noun Integrity:
        #    - For pure device categories (not accessory heads and not compound '&'),
        #      include the bare head noun when modifiers are generic taxonomy prefixes
        if not is_acc and not decomp["is_compound"] and head_lemma:
            mods = set(decomp["modifier_lemmas"])
            if not mods or mods <= {"traditional", "complete", "general", "standard", "basic", "portable", "digital", "electronic"}:
                ordered_candidates.append(head_lemma)
            # Parent-context qualified form (e.g. path has 'Camera & Photo' -> 'camera <name>')
            if len(path) >= 2 and len(lemmas) == 1:
                parent_decomp = decompose_type_phrase(path[-2])
                if parent_decomp["head_lemma"] and parent_decomp["head_lemma"] != head_lemma and not parent_decomp["is_accessory_head"]:
                    ordered_candidates.append(f"{parent_decomp['head_lemma']} {head_lemma}")

        # 4. Compound category lemmatization (without stealing single-word nouns from pure leaf taxa)
        if decomp["is_compound"] and not is_acc and lemmas:
            ordered_candidates.append(" ".join(lemmas))

        # 5. Mine clean modifier + head_noun bigrams from actual catalogue product titles
        if titles and head_lemma and len(head_lemma) >= 3:
            title_text = " " + " ".join(titles).lower() + " "
            title_text = re.sub(r"[^\w\s-]", " ", title_text)

            # Negative lookbehind (?<![\w-]) rejects fragments of hyphenated / numeric compounds
            # (e.g. 'ear headphones' from 'over-ear headphones', 'bay charger' from '4-bay charger').
            pattern = rf"(?<![\w-])([a-z]{{3,14}})\s+({re.escape(head_lemma)}(?:s|es)?)\b"

            found_pairs = []
            for m in re.finditer(pattern, title_text):
                # Reject tails of space-separated compounds: a preceding digit-bearing token
                # ('4 bay charger', '2 port hub') or an English locative particle forming a compound
                # adjective ('in ear headphones', 'on ear headphones').
                prev_tokens = title_text[: m.start()].split()
                prev = prev_tokens[-1] if prev_tokens else ""
                if re.search(r"\d", prev) or prev in COMPOUND_PARTICLES:
                    continue
                found_pairs.append((m.group(1), m.group(2)))

            for mod_word, head_word in found_pairs:
                mod_lemma = normalize_lemma(mod_word)
                head_norm = normalize_lemma(head_word)
                # Reject token reduplication ('webcam webcam'), stopwords, numbers, and brands
                if (
                    mod_lemma == head_norm
                    or mod_word == head_word
                    or mod_word in self.known_brands
                    or mod_lemma in self.known_brands
                    or mod_word in SPEC_AND_NOISE_BLACKLIST
                    or mod_lemma in SPEC_AND_NOISE_BLACKLIST
                ):
                    continue
                # Reject plural nouns acting as left modifiers (e.g. 'batteries camera', 'toys cameras')
                if mod_word.endswith("s") and not mod_word.endswith(("ss", "ous", "less", "ics", "ireless")):
                    continue
                # If the Taxon is an accessory container, ensure the mined phrase keeps the accessory head
                if is_acc and head_norm not in ACCESSORY_HEAD_LEMMAS:
                    continue
                ordered_candidates.append(f"{mod_word} {head_norm}")

        return self._clean_labels(name, ordered_candidates, is_accessory_taxon=is_acc)

    def _clean_labels(self, original_name: str, labels: List[str], is_accessory_taxon: bool = False) -> List[str]:
        """Cleans, normalizes, deduplicates, enforces head-noun integrity, and removes prefLabel."""
        orig = original_name.lower().strip()
        cleaned: List[str] = []
        seen: Set[str] = set()
        for label in labels:
            norm = label.lower().strip()
            norm = re.sub(r"\s+", " ", norm)
            if not norm or norm == orig or norm in seen:
                continue
            words = norm.split()
            # Reject adjacent duplicate words or duplicate lemmas ('webcam webcam')
            if len(words) >= 2 and any(
                words[i] == words[i + 1] or normalize_lemma(words[i]) == normalize_lemma(words[i + 1])
                for i in range(len(words) - 1)
            ):
                continue
            # Reject compound fragment prefixes (e.g. 'ear headphones', 'bay charger', 'way charger')
            if len(words) == 2 and words[0] in {"ear", "way", "bay", "via", "port"}:
                continue
            # Enforce Head-Noun Integrity on accessory taxa: never emit a bare non-accessory noun
            if is_accessory_taxon:
                l_decomp = decompose_type_phrase(norm)
                if not l_decomp["is_accessory_head"]:
                    continue
            if 2 <= len(norm) <= 45:
                seen.add(norm)
                cleaned.append(norm)
        return cleaned[:12]

    def save_alt_labels_to_neo4j(self, enrichments: List[Dict], batch_size: int = 250) -> int:
        """Updates Taxon nodes in Neo4j with their induced alt_labels in batches."""
        query = """
        UNWIND $batch AS item
        MATCH (t:Taxon {taxon_id: item.taxon_id})
        SET t.alt_labels = item.alt_labels
        RETURN count(t) AS updated_count
        """
        total_updated = 0
        with self.connector.session() as session:
            for i in range(0, len(enrichments), batch_size):
                batch = [
                    {"taxon_id": item["taxon_id"], "alt_labels": item["alt_labels"]}
                    for item in enrichments[i : i + batch_size]
                ]
                result = session.run(query, {"batch": batch})
                rec = result.single()
                if rec:
                    total_updated += int(rec["updated_count"] or 0)
        return total_updated

    def verify_taxons(self, test_queries: List[str]) -> List[Dict]:
        """Executes domain-agnostic Cypher matching against t.name and t.alt_labels."""
        verification_results = []
        cypher = """
        MATCH (t:Taxon)
        WHERE toLower(t.name) = toLower($query)
           OR any(alt IN coalesce(t.alt_labels, []) WHERE toLower(alt) = toLower($query))
        RETURN t.name AS matched_taxon,
               t.taxon_id AS taxon_id,
               t.path AS path,
               t.alt_labels AS alt_labels,
               CASE
                 WHEN toLower(t.name) = toLower($query) THEN "Exact (prefLabel)"
                 ELSE "Synonym (altLabel)"
               END AS match_type
        ORDER BY CASE WHEN toLower(t.name) = toLower($query) THEN 0 ELSE 1 END ASC,
                 COALESCE(t.product_count, 0) DESC
        LIMIT 3
        """

        with self.connector.session() as session:
            for q in test_queries:
                res = session.run(cypher, {"query": q})
                matches = [dict(r) for r in res]
                verification_results.append({
                    "query": q,
                    "matches": matches,
                })

        return verification_results


def main():
    parser = argparse.ArgumentParser(description="SKOS Taxon altLabel Induction & Graph Enrichment")
    parser.add_argument("--names", type=str, default="Webcams,Traditional Laptops,Over-Ear Headphones,Digital Cameras",
                        help="Comma-separated list of Taxon names to process (ignored when --all is set)")
    parser.add_argument("--all", action="store_true", help="Process all 1,183 Taxon nodes in Neo4j")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of taxons to process")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM API in addition to deterministic catalogue mining")
    parser.add_argument("--export-json", type=str, default="graph_versions/v2/taxon_skos_alt_labels.json",
                        help="Path to export deterministic SKOS alt_labels JSON snapshot")
    parser.add_argument("--dry-run", action="store_true", help="Induct labels without writing to Neo4j")
    parser.add_argument("--verify", action="store_true", default=True, help="Run verification queries after enrichment")
    args = parser.parse_args()

    taxon_names = None if args.all else ([n.strip() for n in args.names.split(",") if n.strip()] if args.names else None)

    logger.info("Connecting to Neo4j database...")
    enricher = SKOSTaxonEnricher()

    try:
        logger.info(f"Fetching Taxon nodes with context (all={args.all}, names={taxon_names})...")
        taxons = enricher.fetch_taxons_with_context(taxon_names=taxon_names, limit=args.limit)
        logger.info(f"Found {len(taxons)} matching Taxon nodes.")

        enrichments = []
        for t in taxons:
            alt_labels = enricher.induct_alt_labels(t, use_llm=args.use_llm)
            enrichments.append({
                "taxon_id": t["taxon_id"],
                "name": t["name"],
                "path": t["path"],
                "product_count": t["product_count"],
                "alt_labels": alt_labels,
            })

        # Print sample of up to 8 enriched taxons
        for item in enrichments[:8]:
            print(f"TAXON: {item['name']} (count={item['product_count']}) -> alt_labels={item['alt_labels']}")

        if not args.dry_run and enrichments:
            logger.info(f"Writing induced alt_labels to {len(enrichments)} Taxon nodes in Neo4j...")
            updated = enricher.save_alt_labels_to_neo4j(enrichments)
            logger.info(f"Successfully updated {updated} Taxon nodes in Neo4j!")
            if args.export_json:
                os.makedirs(os.path.dirname(os.path.abspath(args.export_json)), exist_ok=True)
                with open(args.export_json, "w", encoding="utf-8") as f:
                    json.dump(enrichments, f, indent=2, ensure_ascii=False)
                logger.info(f"Exported SKOS alt_labels snapshot to {args.export_json}")
        elif args.dry_run:
            logger.info("[Dry Run] Skipped writing to Neo4j.")

        if args.verify:
            test_queries = [
                "streaming camera",
                "pc camera",
                "notebook",
                "laptop",
                "tablet",
                "mouse",
                "microphone",
                "smartphone",
                "wall charger",
                "travel power adapter",
                "around-ear headphones",
                "digicam",
            ]
            results = enricher.verify_taxons(test_queries)
            print("\n=== SKOS Cypher Verification ===")
            for r in results:
                q = r["query"]
                matches = r["matches"]
                if matches:
                    top = matches[0]
                    print(f"  '{q}' -> {top['matched_taxon']} [{top['match_type']}]")
                else:
                    print(f"  '{q}' -> NO MATCH")

    finally:
        enricher.close()


if __name__ == "__main__":
    main()
