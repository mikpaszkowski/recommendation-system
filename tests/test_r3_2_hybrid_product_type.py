"""
Unit & Integration Tests for Release R3.2 (RS-24):
Domain-Agnostic Hybrid Product-Type Matching & W3C SKOS `alt_labels` Induction

Acceptance Criteria:
- AC-R3.2-00: Full-graph W3C SKOS `alt_labels` induction (1,183 Taxon nodes, zero token-reduplication,
              zero hyphen-compound fragments, Head-Noun Integrity on accessory taxa)
- AC-R3.2-01: Dual-side morphological lemmatization (`normalize_lemma`, `decompose_type_phrase`, P-9)
- AC-R3.2-02: SKOS + Anti-Hijacking Taxon resolution (`Mouse -> Mice`, `Tablet -> Tablets`, `Laptop -> Laptops`,
              `streaming camera -> Webcams`, `notebook -> Laptops`)
- AC-R3.2-03: Multi-Taxon Family expansion (`resolve_category_family`)
- AC-R3.2-04: Guarded Lexical Head-Noun Escape Hatch (admits miscategorized genuine devices, blocks accessory traps)

AC-R3.2-05 (100% target admission on the 105 tuning queries) requires a live Neo4j instance and is verified by
the tuning-split admission run (see production_artifacts/Audit_Report.md); it is not part of this offline suite.

All tests here run offline: the ResolverService Taxon cache is seeded from the exported
`graph_versions/v2/taxon_skos_alt_labels.json` artifact (the same data written to Neo4j).
"""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.knowledge_graph.graphdb.resolver_service import (
    ResolverService,
    decompose_type_phrase,
    get_equivalent_head_lemmas,
    normalize_lemma,
)
from src.tools.graph_search_tool import GraphSearchTool


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKOS_ARTIFACT_PATH = PROJECT_ROOT / "graph_versions" / "v2" / "taxon_skos_alt_labels.json"

requires_skos_artifact = pytest.mark.skipif(
    not SKOS_ARTIFACT_PATH.exists(), reason=f"SKOS artifact missing: {SKOS_ARTIFACT_PATH}"
)


def _load_skos_rows():
    return json.loads(SKOS_ARTIFACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seeded_resolver() -> ResolverService:
    """ResolverService whose in-memory Taxon cache is seeded from the exported SKOS artifact (no Neo4j)."""
    rows = _load_skos_rows()
    rows.sort(key=lambda r: int(r.get("product_count") or 0), reverse=True)
    embedder = MagicMock()
    embedder.embed_documents.return_value = []
    # MagicMock connector: Tier-1 Cypher exact match returns no rows, so resolution exercises
    # the in-memory SKOS + morphological Tier 2 deterministically.
    resolver = ResolverService(connector=MagicMock(), embed_svc=embedder)
    resolver._taxon_cache = rows
    resolver._taxon_embeddings = None
    resolver._ensure_taxon_cache()
    return resolver


def _cypher_regex_match(pattern: str, text: str) -> bool:
    """Emulates Cypher `=~` (Java full-match semantics) in Python."""
    return re.fullmatch(pattern, text, flags=re.DOTALL) is not None


# ---------------------------------------------------------------------------
# AC-R3.2-00: Full-Graph W3C SKOS `alt_labels` Artifact & Quality Guarantees
# ---------------------------------------------------------------------------

@requires_skos_artifact
def test_ac_r3_2_00_skos_artifact_covers_full_graph():
    """AC-R3.2-00: Exported artifact covers all 1,183 Taxon nodes and contains key colloquial synonyms."""
    rows = _load_skos_rows()
    assert len(rows) == 1183
    assert all("alt_labels" in r and isinstance(r["alt_labels"], list) for r in rows)

    by_name = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(r)

    assert {"webcam", "streaming camera", "pc camera", "video conference camera"} <= set(by_name["Webcams"][0]["alt_labels"])
    assert {"laptop", "notebook", "portable computer"} <= set(by_name["Traditional Laptops"][0]["alt_labels"])
    assert {"digicam", "point and shoot camera"} <= set(by_name["Digital Cameras"][0]["alt_labels"])
    assert {"around-ear headphones", "circumaural headphones"} <= set(by_name["Over-Ear Headphones"][0]["alt_labels"])


@requires_skos_artifact
def test_ac_r3_2_00_skos_labels_have_no_reduplication_or_compound_fragments():
    """AC-R3.2-00: Zero token reduplication ('webcam webcam') and zero hyphen/number compound fragments."""
    fragment_modifiers = {"ear", "way", "bay", "via", "port"}
    for r in _load_skos_rows():
        for alt in r["alt_labels"]:
            words = alt.split()
            for i in range(len(words) - 1):
                assert normalize_lemma(words[i]) != normalize_lemma(words[i + 1]), (
                    f"Reduplicated tokens in '{alt}' on Taxon '{r['name']}'"
                )
            assert not (len(words) == 2 and words[0] in fragment_modifiers), (
                f"Compound fragment alt_label '{alt}' on Taxon '{r['name']}'"
            )


@requires_skos_artifact
def test_ac_r3_2_00_accessory_taxa_keep_head_noun_integrity():
    """AC-R3.2-00: Accessory/container taxa never receive bare primary-device alt_labels."""
    bare_devices = {"laptop", "laptops", "tablet", "tablets", "phone", "phones", "smartphone", "camera", "mouse"}
    for r in _load_skos_rows():
        if decompose_type_phrase(r["name"])["is_accessory_head"]:
            leaked = set(r["alt_labels"]) & bare_devices
            assert not leaked, f"Accessory taxon '{r['name']}' has bare device alt_labels: {leaked}"
            for alt in r["alt_labels"]:
                assert decompose_type_phrase(alt)["is_accessory_head"], (
                    f"Accessory taxon '{r['name']}' has non-accessory alt_label '{alt}'"
                )


# ---------------------------------------------------------------------------
# AC-R3.2-01: Dual-Side Morphological Normalization & Head-Noun Decomposition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "token, lemma",
    [
        # Irregular plurals
        ("mice", "mouse"), ("Mice", "mouse"), ("batteries", "battery"), ("accessories", "accessory"),
        ("lenses", "lens"), ("shelves", "shelf"),
        # Suffix morphology
        ("watches", "watch"), ("boxes", "box"), ("cases", "case"), ("laptops", "laptop"),
        ("tablets", "tablet"), ("microphones", "microphone"),
        # -ve stems preserved
        ("sleeves", "sleeve"), ("drives", "drive"), ("receivers", "receiver"),
        # Invariant plurals and -ss / -us words preserved
        ("headphones", "headphones"), ("glasses", "glasses"), ("jeans", "jeans"),
        ("wireless", "wireless"), ("series", "series"), ("bus", "bus"),
        # Singular -> canonical invariant form
        ("headphone", "headphones"), ("earbud", "earbuds"),
    ],
)
def test_ac_r3_2_01_normalize_lemma(token, lemma):
    """AC-R3.2-01: Deterministic P-9 lemmatizer handles irregular, suffix, and invariant plurals."""
    assert normalize_lemma(token) == lemma


def test_ac_r3_2_01_decompose_type_phrase():
    """AC-R3.2-01: Head noun / modifier decomposition, parenthetical stripping, accessory-container detection."""
    paren = decompose_type_phrase("laptop (MacBook Air)")
    assert paren["clean_text"] == "laptop"
    assert paren["head_lemma"] == "laptop"
    assert paren["modifier_lemmas"] == ()
    assert paren["parenthetical_lemmas"] == ("macbook", "air")
    assert paren["is_accessory_head"] is False

    device = decompose_type_phrase("Traditional Laptops")
    assert (device["head_lemma"], device["modifier_lemmas"], device["is_accessory_head"]) == ("laptop", ("traditional",), False)

    accessory = decompose_type_phrase("Laptop Accessories")
    assert (accessory["head_lemma"], accessory["modifier_lemmas"], accessory["is_accessory_head"]) == ("accessory", ("laptop",), True)

    compound = decompose_type_phrase("Chargers & Adapters")
    assert compound["is_compound"] is True
    assert set(compound["head_lemmas"]) == {"charger", "adapter"}
    assert compound["is_accessory_head"] is False

    # Trailing accessory segment makes the whole coordinated phrase a container
    combo = decompose_type_phrase("Keyboard & Mouse Combos")
    assert combo["is_accessory_head"] is True
    assert combo["head_lemmas"] == ("combo",)
    assert set(combo["modifier_lemmas"]) == {"keyboard", "mouse"}

    # Multi-word synonym normalization
    assert decompose_type_phrase("Cell Phones")["head_lemma"] == "smartphone"
    assert decompose_type_phrase("web camera")["head_lemma"] == "webcam"


def test_ac_r3_2_01_equivalent_head_lemmas():
    """AC-R3.2-01: Head-lemma equivalence groups align cross-taxonomy device names."""
    assert {"phone", "smartphone", "cellphone"} <= get_equivalent_head_lemmas("phones")
    assert {"laptop", "notebook", "macbook"} <= get_equivalent_head_lemmas("Notebooks")
    assert get_equivalent_head_lemmas("toaster") == {"toaster"}


# ---------------------------------------------------------------------------
# AC-R3.2-02: SKOS + Anti-Hijacking Taxon Resolution
# ---------------------------------------------------------------------------

@requires_skos_artifact
@pytest.mark.parametrize(
    "query, expected_top",
    [
        ("streaming camera", {"Webcams"}),
        ("pc camera", {"Webcams"}),
        ("notebook", {"Laptops", "Traditional Laptops"}),
        ("digicam", {"Digital Cameras"}),
        ("around-ear headphones", {"Over-Ear Headphones"}),
    ],
)
def test_ac_r3_2_02_skos_colloquial_synonyms(seeded_resolver, query, expected_top):
    """AC-R3.2-02: Colloquial synonyms resolve via SKOS alt_labels (score 0.96)."""
    res = seeded_resolver.resolve_category(query, k=3)
    assert res, f"No resolution for '{query}'"
    assert res[0]["name"] in expected_top
    assert res[0]["score"] >= 0.95


@requires_skos_artifact
@pytest.mark.parametrize(
    "query, expected_top, forbidden",
    [
        ("Mouse", "Mice", {"Keyboard & Mouse Combos", "Mouse Pads"}),
        ("Tablet", "Tablets", {"Tablet Accessories"}),
        ("Laptop", "Laptops", {"Laptop Accessories"}),
        ("laptop (MacBook Air)", "Laptops", {"Laptop Accessories"}),
        ("microphone", "Microphones", {"Microphone Accessories"}),
    ],
)
def test_ac_r3_2_02_singular_device_queries_are_not_hijacked(seeded_resolver, query, expected_top, forbidden):
    """AC-R3.2-02: Singular device queries resolve to plural device taxa, never to accessory containers."""
    res = seeded_resolver.resolve_category(query, k=3)
    assert res[0]["name"] == expected_top
    assert res[0]["score"] == pytest.approx(1.0)
    assert not ({r["name"] for r in res} & forbidden)


@requires_skos_artifact
def test_ac_r3_2_02_phone_resolves_to_smartphone_device_taxon(seeded_resolver):
    """AC-R3.2-02: 'Phone' resolves to a smartphone device taxon, not earbuds or monitor accessories."""
    res = seeded_resolver.resolve_category("Phone", k=3)
    assert res[0]["name"] in {"Bestselling Renewed Smartphones", "Cell Phones & Accessories"}
    names = {r["name"] for r in res}
    assert "Earbud & In-Ear Headphones" not in names
    assert "Monitor Accessories" not in names


def test_ac_r3_2_02_disjoint_specific_modifiers_fall_through_to_vector_tier():
    """AC-R3.2-02: 'acoustic speakers' must NOT be forced onto 'Bookshelf Speakers' by head-noun scoring."""
    resolver = ResolverService(connector=MagicMock(), embed_svc=MagicMock())
    resolver._taxon_cache = [{"name": "Bookshelf Speakers", "product_count": 100}]
    resolver._taxon_embeddings = None
    resolver._ensure_taxon_cache()
    q = decompose_type_phrase("acoustic speakers")
    assert resolver._score_taxon_candidate(q, resolver._taxon_cache[0]) == 0.0
    # Generic taxonomy prefixes remain valid containers
    resolver._taxon_cache.append({"name": "Traditional Laptops", "product_count": 100})
    resolver._ensure_taxon_cache()
    assert resolver._score_taxon_candidate(decompose_type_phrase("gaming laptop"), resolver._taxon_cache[1]) > 0.85


# ---------------------------------------------------------------------------
# AC-R3.2-03: Multi-Taxon Family Expansion (`resolve_category_family`)
# ---------------------------------------------------------------------------

@requires_skos_artifact
def test_ac_r3_2_03_charger_family_spans_multiple_branches(seeded_resolver):
    """AC-R3.2-03: 'Charger' expands to a multi-branch family (chargers, adapters, battery chargers)."""
    fam = seeded_resolver.resolve_category_family("Charger", query_text="fast USB-C wall charger")
    names = {m["name"] for m in fam}
    assert {"Chargers", "Chargers & Adapters"} <= names
    assert names & {"Battery Chargers", "Batteries & Chargers"}
    assert len(fam) <= 6
    assert all(m["score"] >= 0.85 for m in fam)


@requires_skos_artifact
def test_ac_r3_2_03_camera_family_includes_webcams(seeded_resolver):
    """AC-R3.2-03: 'Camera' + 'streaming webcam' context yields both Digital Cameras and Webcams."""
    fam = seeded_resolver.resolve_category_family("Camera", query_text="1080p HD streaming webcam with microphone")
    names = {m["name"] for m in fam}
    assert {"Digital Cameras", "Webcams"} <= names


@requires_skos_artifact
def test_ac_r3_2_03_family_never_contains_accessory_containers_for_device_query(seeded_resolver):
    """AC-R3.2-03: Device families never include accessory containers (e.g. 'Laptop Accessories')."""
    for q in ("Laptop", "Tablet", "Mouse", "Phone"):
        for m in seeded_resolver.resolve_category_family(q):
            assert not decompose_type_phrase(m["name"])["is_accessory_head"], (
                f"Family for '{q}' contains accessory container '{m['name']}'"
            )


def test_ac_r3_2_03_normalize_filters_propagates_family_and_paths():
    """AC-R3.2-03: GraphSearchTool._normalize_filters attaches the resolved family names and taxon paths."""
    resolver = MagicMock()
    resolver.resolve_category.return_value = [{"name": "Chargers", "score": 1.0}]
    resolver.validate_category_candidates.return_value = {"name": "Chargers", "score": 1.0}
    resolver.resolve_category_family.return_value = [
        {"name": "Chargers", "path": ["Electronics", "Power", "Chargers"], "score": 1.0},
        {"name": "Chargers & Adapters", "path": ["Electronics", "Cell Phones", "Chargers & Adapters"], "score": 0.96},
    ]
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=resolver)
    out = gst._normalize_filters({"category": "Charger"}, query_text="fast wall charger")
    resolver.resolve_category_family.assert_called_once_with("Charger", query_text="fast wall charger")
    assert out["_resolved_category_family"] == ["Chargers", "Chargers & Adapters"]
    assert out["_resolved_taxon_paths"][1] == ["Electronics", "Cell Phones", "Chargers & Adapters"]


# ---------------------------------------------------------------------------
# AC-R3.2-04: Guarded Lexical Head-Noun Escape Hatch
# ---------------------------------------------------------------------------

def _admitted(escape_rx: str, excl_rx: str, title: str) -> bool:
    t = title.lower()
    return _cypher_regex_match(escape_rx, t) and not _cypher_regex_match(excl_rx, t)


@pytest.mark.parametrize(
    "title, admitted",
    [
        # Genuine miscategorized device (B08GNRGB67 in 'samsung_tradein')
        ("Samsung Galaxy S20+ Plus 5G Factory Unlocked Android Cell Phone 128GB US Version", True),
        ("Unlocked Android Smartphone 6.5 Inch Dual SIM", True),
        # Accessory traps
        ("Silicone Case Compatible with iPhone 14 Pro Cell Phone", False),
        ("Tempered Glass Screen Protector for Samsung Galaxy Phone", False),
        ("Magnetic Car Mount Holder for Cell Phone", False),
        # Unrelated product
        ("Bluetooth Over-Ear Headphones with Microphone", False),
    ],
)
def test_ac_r3_2_04_escape_hatch_phone(title, admitted):
    """AC-R3.2-04: Phone escape hatch admits genuine devices and blocks 'X for phone' accessory traps."""
    escape_rx, excl_rx = GraphSearchTool._build_head_noun_escape_patterns("Phone")
    assert _admitted(escape_rx, excl_rx, title) is admitted


@pytest.mark.parametrize(
    "title, admitted",
    [
        # B0BRZ6VK9N: MacBook Air with empty taxa
        ("Apple 2023 MacBook Air Laptop with M2 chip: 15.3-inch Liquid Retina Display, 8GB RAM", True),
        ("Waterproof Laptop Sleeve Case Bag for 13 inch MacBook Air", False),
        ("Adjustable Aluminum Stand Designed for Laptop and Notebook", False),
    ],
)
def test_ac_r3_2_04_escape_hatch_laptop_with_parenthetical(title, admitted):
    """AC-R3.2-04: 'laptop (MacBook Air)' escape hatch includes the parenthetical lemma and blocks sleeves/stands."""
    escape_rx, excl_rx = GraphSearchTool._build_head_noun_escape_patterns("laptop (MacBook Air)")
    assert "macbook" in escape_rx
    assert _admitted(escape_rx, excl_rx, title) is admitted


def test_ac_r3_2_04_escape_hatch_does_not_block_accessory_queries():
    """AC-R3.2-04: When the user explicitly asks for an accessory, the exclusion regex is disabled."""
    escape_rx, excl_rx = GraphSearchTool._build_head_noun_escape_patterns("Laptop Accessories")
    assert excl_rx == "^$"
    assert _admitted(escape_rx, excl_rx, "Laptop Accessories Kit for MacBook") is True


def test_ac_r3_2_04_build_filters_emits_hybrid_structural_and_escape_clause():
    """AC-R3.2-04: _build_filters combines IN_TAXON/BROADER*, SKOS alt_labels, family filter, and escape hatch."""
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=MagicMock())
    where_clauses, params = gst._build_filters(
        {"category": "Laptops", "_resolved_category_family": ["Laptops", "Traditional Laptops"]},
        raw_filters={"category": "laptop (MacBook Air)"},
    )
    clause = " ".join(where_clauses)
    assert "[:IN_TAXON]->(leaf:Taxon)-[:BROADER*0..7]->(ancestor:Taxon)" in clause
    assert "coalesce(ancestor.alt_labels, [])" in clause
    assert "$category_family_filter" in clause
    assert "toLower(node.title) =~ $head_noun_escape_regex" in clause
    assert "NOT toLower(node.title) =~ $accessory_exclusion_regex" in clause

    assert params["category_filter"] == "Laptops"
    assert params["raw_category_filter"] == "laptop (MacBook Air)"
    assert set(params["category_family_filter"]) == {"laptops", "traditional laptops"}
    assert "macbook" in params["head_noun_escape_regex"]
