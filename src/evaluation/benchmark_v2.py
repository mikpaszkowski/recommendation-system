"""
Stratified Benchmark v2 (Release R2b, RS-21 / G-9):
- Deterministic hashed grouped tuning/test split (`assign_split`);
- Automatic leakage and lexical-triviality detector (`check_query_leakage`, pure-Python TF-IDF);
- Title-blind conversational utterance and gold-constraint synthesis (`synthesize_title_blind_utterance`);
- Ambiguous stratum A queries (`AMBIGUOUS_QUERIES_V2`);
- Split filtering and test-split access logging (`filter_benchmark_by_split`, `log_test_split_access`).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

BENCHMARK_V2_SALT = "crs_r2b_20261020"
BENCHMARK_V2_SEED = 20261020
STRATA_RETRIEVAL = ("S0", "S1", "S2", "S3", "S4")
ALL_STRATA = ("S0", "S1", "S2", "S3", "S4", "A", "legacy")

STOP_WORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "compatible",
    "de", "do", "for", "from", "get", "good", "great", "has", "have", "high", "i",
    "in", "into", "is", "it", "its", "looking", "me", "my", "need", "new", "no",
    "not", "of", "on", "one", "or", "out", "over", "pack", "pc", "pcs", "per",
    "please", "pro", "quality", "recommend", "search", "set", "some", "something",
    "that", "the", "their", "them", "these", "this", "to", "under", "up", "use",
    "using", "very", "want", "with", "without", "work", "works", "would", "you",
    "your",
}

# Standard generic technical tokens that contain digits+letters but are NOT product model codes
GENERIC_TECH_TOKENS: Set[str] = {
    "1080p", "720p", "1440p", "2160p", "4k", "8k", "2k", "5k", "3d", "2d",
    "5g", "4g", "3g", "lte", "2g", "24ghz", "5ghz", "6ghz", "60ghz",
    "usb", "usb2", "usb3", "usb4", "usbc", "usba", "typec", "microusb",
    "wifi", "wifi5", "wifi6", "wifi6e", "wifi7", "bt", "bt5", "bluetooth5",
    "mp3", "mp4", "mp5", "cat5", "cat5e", "cat6", "cat6a", "cat7", "cat8",
    "ddr3", "ddr4", "ddr5", "lpddr4", "lpddr5", "sata", "sata3", "nvme", "m2",
    "pcie", "pcie3", "pcie4", "pcie5", "rj45", "rj11", "hdmi", "hdmi2",
    "dp1", "vesa", "ipx4", "ipx5", "ipx6", "ipx7", "ipx8", "ip65", "ip66",
    "ip67", "ip68", "cr2032", "lr44", "18650", "aa", "aaa", "rgb", "led",
    "lcd", "oled", "amoled", "ips", "va", "tn", "qled", "uhd", "fhd", "hd",
    "qhd", "wqhd", "sd", "microsd", "tf", "cf", "ssd", "hdd", "ram", "rom",
    "cpu", "gpu", "ac", "dc", "poe", "ups", "pd", "qc", "qc3", "gan", "nfc",
    "anc", "tws", "eq", "hi-res", "hifi", "aux", "rca", "xlr", "trs", "trrs",
    "ios", "macos", "win10", "win11", "ps4", "ps5", "xbox", "cctv", "ptz",
    "dslr", "slr", "mirrorless",
}

UNIT_TOKEN_RE = re.compile(
    r"^\d+(?:\.\d+)?(?:gb|tb|mb|kb|w|kw|wh|mah|ah|hz|khz|mhz|ghz|mm|cm|m|in|inch|inches|"
    r"ft|feet|yd|lbs|lb|oz|kg|g|v|kv|mv|a|ma|amp|amps|fps|mp|db|dba|ms|s|hr|hrs|min|mins|"
    r"pack|pk|pcs|pc|ft|pin|pins|port|ports|ch|channel|channels|bit|bits|watt|watts|volt|volts|"
    r"ohm|ohms|lumen|lumens|lm|lux|k|deg|x|way|tier|tiers|cell|cells|slot|slots|bay|bays|key|keys)$",
    re.IGNORECASE,
)

BOILERPLATE_DETAIL_KEYS: Set[str] = {
    "asin", "parent_asin", "best sellers rank", "customer reviews", "date first available",
    "is discontinued by manufacturer", "item model number", "model number", "part number",
    "manufacturer", "brand", "brand name", "department", "country of origin", "upc", "ean",
    "gtin", "unspsc code", "domestic shipping", "international shipping", "warranty",
}


def assign_split(key: str, salt: str = BENCHMARK_V2_SALT, test_ratio: int = 60) -> str:
    """
    Deterministic hashed split assignment (Vision 2026-10-18-015 §1).
    Maps `sha256(salt + ":" + key) % 100 < test_ratio` to 'test', else 'tuning'.
    """
    if not key:
        raise ValueError("Split key must be non-empty.")
    digest = hashlib.sha256(f"{salt}:{key}".encode("utf-8")).hexdigest()
    bucket = int(digest, 16) % 100
    return "test" if bucket < test_ratio else "tuning"


def tokenize_words(text: str) -> List[str]:
    """Lowercases and extracts alphanumeric word tokens."""
    if not text:
        return []
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower())


def is_model_code_token(token: str, brand_tokens: Optional[Set[str]] = None) -> bool:
    """
    True when `token` is an alphanumeric product model identifier (contains both letters
    and digits, length >= 3, not a standard unit or generic tech term).
    """
    tok = token.lower().strip("-_")
    if len(tok) < 3:
        return False
    if brand_tokens and tok in brand_tokens:
        return False
    clean = tok.replace("-", "")
    if clean in GENERIC_TECH_TOKENS or tok in GENERIC_TECH_TOKENS:
        return False
    if UNIT_TOKEN_RE.match(clean) or UNIT_TOKEN_RE.match(tok):
        return False
    # Check resolution patterns like 1920x1080 or 802.11ac
    if re.match(r"^\d+x\d+$", clean) or re.match(r"^80211[a-z]*$", clean):
        return False
    has_alpha = any(ch.isalpha() for ch in clean)
    has_digit = any(ch.isdigit() for ch in clean)
    return has_alpha and has_digit


def extract_model_codes(title: str, brand: Optional[str] = None) -> List[str]:
    """Extracts distinct alphanumeric model-code tokens from a product title."""
    brand_tokens = set(tokenize_words(brand or ""))
    codes: List[str] = []
    for tok in tokenize_words(title):
        if is_model_code_token(tok, brand_tokens=brand_tokens):
            if tok not in codes:
                codes.append(tok)
        # Also check hyphen-split parts
        if "-" in tok:
            for part in tok.split("-"):
                if is_model_code_token(part, brand_tokens=brand_tokens) and part not in codes:
                    codes.append(part)
    return codes


def extract_content_tokens(text: str, exclude_tokens: Optional[Set[str]] = None) -> List[str]:
    """
    Returns ordered unique content tokens from `text`, excluding stop words,
    pure numbers, single-char tokens, and any token in `exclude_tokens`.
    """
    excl = {t.lower() for t in (exclude_tokens or set())}
    out: List[str] = []
    for raw in tokenize_words(text):
        for tok in raw.split("-"):
            if len(tok) <= 1 or tok.isdigit() or tok in STOP_WORDS or tok in excl:
                continue
            if tok not in out:
                out.append(tok)
    return out


def compute_tfidf_target_rank(
    utterance: str,
    target_asin: str,
    pool_titles: Mapping[str, str],
) -> int:
    """
    Ranks `pool_titles` ({asin: title}) against `utterance` by pure-Python TF-IDF cosine
    similarity and returns the 1-based rank of `target_asin`.
    Ties are broken by placing `target_asin` first so a tied rank-1 still counts as trivial.
    """
    if not pool_titles or target_asin not in pool_titles:
        return len(pool_titles) + 1

    q_tokens = extract_content_tokens(utterance)
    if not q_tokens:
        return len(pool_titles)

    doc_tokens: Dict[str, List[str]] = {
        asin: extract_content_tokens(title) for asin, title in pool_titles.items()
    }
    n_docs = len(doc_tokens)
    df: Dict[str, int] = {}
    for tokens in doc_tokens.values():
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1

    def _tfidf_vec(tokens: Sequence[str]) -> Dict[str, float]:
        if not tokens:
            return {}
        tf: Dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        vec: Dict[str, float] = {}
        for t, count in tf.items():
            idf = math.log((1.0 + n_docs) / (1.0 + df.get(t, 0))) + 1.0
            vec[t] = (count / len(tokens)) * idf
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm > 0:
            vec = {t: v / norm for t, v in vec.items()}
        return vec

    q_vec = _tfidf_vec(q_tokens)
    scores: List[Tuple[float, int, str]] = []
    for asin, tokens in doc_tokens.items():
        d_vec = _tfidf_vec(tokens)
        sim = sum(q_vec[t] * d_vec.get(t, 0.0) for t in q_vec)
        # Put target_asin first on exact tie (0 vs 1) so rank 1 is conservative
        tie_priority = 0 if asin == target_asin else 1
        scores.append((-sim, tie_priority, asin))

    scores.sort()
    for idx, (_, _, asin) in enumerate(scores, start=1):
        if asin == target_asin:
            return idx
    return len(pool_titles) + 1


def check_query_leakage(
    utterance: str,
    target_asin: str,
    target_title: str,
    target_brand: Optional[str],
    product_type: str,
    pool_titles: Mapping[str, str],
    brand_anchored: bool = False,
    max_overlap: float = 0.30,
    require_non_trivial_tfidf: bool = True,
) -> Dict[str, Any]:
    """
    Automatic leakage & lexical-triviality verification (FR-R2B-004):
    - model_code_leak: any alphanumeric model code from target_title appears in utterance
    - unflagged_brand_leak: target_brand appears in utterance when brand_anchored is False
    - title_token_overlap: share of target_title content tokens (excluding brand, model codes,
      and product_type words) that appear in utterance
    - tfidf_target_rank: 1-based TF-IDF rank of target_asin in pool_titles
    """
    u_tokens_all = set(tokenize_words(utterance))
    for tok in list(u_tokens_all):
        if "-" in tok:
            u_tokens_all.update(tok.split("-"))

    model_codes = extract_model_codes(target_title, brand=target_brand)
    leaked_codes = [c for c in model_codes if c in u_tokens_all or c.replace("-", "") in u_tokens_all]
    model_code_leak = len(leaked_codes) > 0

    brand_tokens = {
        t for t in tokenize_words(target_brand or "")
        if len(t) >= 2 and t not in STOP_WORDS and t not in {"inc", "llc", "ltd", "corp", "co", "store", "amazon", "generic"}
    }
    unflagged_brand_leak = False
    if not brand_anchored and brand_tokens:
        if any(bt in u_tokens_all for bt in brand_tokens):
            unflagged_brand_leak = True

    type_tokens = set(extract_content_tokens(product_type))
    # Also include singular/plural forms of type tokens so head noun never counts as title leak
    for tt in list(type_tokens):
        if tt.endswith("s") and len(tt) > 3:
            type_tokens.add(tt[:-1])
        else:
            type_tokens.add(tt + "s")

    exclude_from_title = brand_tokens | set(model_codes) | type_tokens
    title_content = extract_content_tokens(target_title, exclude_tokens=exclude_from_title)
    utterance_content = set(extract_content_tokens(utterance, exclude_tokens=brand_tokens | type_tokens))

    if title_content:
        shared = [t for t in title_content if t in utterance_content]
        overlap = len(shared) / len(title_content)
    else:
        shared = []
        overlap = 0.0

    tfidf_rank = compute_tfidf_target_rank(utterance, target_asin, pool_titles) if pool_titles else 999
    lexically_trivial = tfidf_rank == 1

    passed = (
        not model_code_leak
        and not unflagged_brand_leak
        and overlap <= max_overlap
        and (not require_non_trivial_tfidf or not lexically_trivial)
    )
    return {
        "passed": passed,
        "model_code_leak": model_code_leak,
        "leaked_model_codes": leaked_codes,
        "unflagged_brand_leak": unflagged_brand_leak,
        "title_token_overlap": round(float(overlap), 4),
        "shared_title_tokens": shared,
        "title_content_token_count": len(title_content),
        "tfidf_target_rank": int(tfidf_rank),
        "lexically_trivial": lexically_trivial,
    }


def round_nice_budget(price: float, multiplier: float = 1.25) -> float:
    """Rounds `price * multiplier` up to a natural consumer budget ceiling > price."""
    raw = max(price + 2.0, price * multiplier)
    if raw <= 50:
        step = 5.0
    elif raw <= 200:
        step = 10.0
    elif raw <= 600:
        step = 25.0
    else:
        step = 50.0
    rounded = math.ceil(raw / step) * step
    if rounded <= price:
        rounded += step
    return float(int(rounded))


# Paraphrase map used by title-blind synthesis to express structured specs in natural user words
# without copying listing title vocabulary verbatim.
SPEC_PARAPHRASE_MAP: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bbluetooth\b", re.I), "cordless wireless pairing"),
    (re.compile(r"\bwireless\b", re.I), "cable-free connectivity"),
    (re.compile(r"\bwired\b", re.I), "direct cabled connection"),
    (re.compile(r"\bnoise cancell?ing\b|\banc\b", re.I), "ambient sound isolation"),
    (re.compile(r"\bwaterproof\b|\bwater resistant\b|\bipx\d\b", re.I), "moisture and splash protection"),
    (re.compile(r"\blightweight\b", re.I), "low-weight portable build"),
    (re.compile(r"\bergonomic\b", re.I), "comfortable hand-friendly shape"),
    (re.compile(r"\brechargeable\b", re.I), "built-in battery power"),
    (re.compile(r"\bportable\b|\bcompact\b", re.I), "easy-to-pack travel form factor"),
    (re.compile(r"\bfast charg(?:ing|e)\b|\bquick charge\b|\bpd\b", re.I), "rapid power delivery"),
    (re.compile(r"\bbacklit\b|\brgb\b", re.I), "illuminated keys for dim rooms"),
    (re.compile(r"\b1080p\b|\bfull hd\b", re.I), "crisp full-HD video clarity"),
    (re.compile(r"\b4k\b|\buhd\b", re.I), "ultra-high-definition visuals"),
    (re.compile(r"\bfoldable\b|\bfolding\b", re.I), "collapsible design for storage"),
    (re.compile(r"\badjustable\b", re.I), "customizable angle and fit"),
    (re.compile(r"\bmagnetic\b", re.I), "snap-on attachment"),
    (re.compile(r"\baluminum\b|\bmetal\b|\bstainless\b", re.I), "solid metallic housing"),
    (re.compile(r"\bsilicone\b|\brubber\b", re.I), "soft non-slip exterior"),
    (re.compile(r"\bheavy duty\b|\bdurable\b|\brugged\b", re.I), "reinforced everyday durability"),
    (re.compile(r"\bgaming\b", re.I), "low-latency interactive responsiveness"),
    (re.compile(r"\boffice\b|\bwork\b", re.I), "daily desk productivity"),
]

USE_CASE_HOOKS: Tuple[str, ...] = (
    "for my home office setup",
    "for daily commuting and travel",
    "for remote work and study sessions",
    "for my apartment workstation",
    "for everyday household use",
    "for a clean desk upgrade",
    "for weekend trips and daily carry",
    "for my studio and media corner",
)


def _paraphrase_spec_clues(
    features: Sequence[str],
    details_json: Optional[str],
    attributes: Sequence[Mapping[str, Any]],
    rng: random.Random,
) -> List[str]:
    """
    Extracts 2–3 natural-language requirement phrases from features, details_json and
    graph attributes without reading the product title.
    """
    corpus_parts: List[str] = list(features or [])
    if details_json:
        try:
            d_obj = json.loads(details_json) if isinstance(details_json, str) else details_json
            if isinstance(d_obj, dict):
                for k, v in d_obj.items():
                    if str(k).lower().strip() not in BOILERPLATE_DETAIL_KEYS:
                        corpus_parts.append(f"{k}: {v}")
        except Exception:
            pass
    for attr in attributes or []:
        if isinstance(attr, Mapping):
            corpus_parts.append(f"{attr.get('name', '')}: {attr.get('value', '')}")

    joined = " | ".join(corpus_parts)
    matched_phrases: List[str] = []
    for pat, phrase in SPEC_PARAPHRASE_MAP:
        if pat.search(joined) and phrase not in matched_phrases:
            matched_phrases.append(phrase)

    rng.shuffle(matched_phrases)

    fallback_descriptors = [
        "reliable everyday performance",
        "practical build for regular use",
        "dependable construction and clean design",
        "hassle-free setup and solid quality",
        "consistent operation and straightforward controls",
        "sturdy materials that hold up over time",
        "convenient form factor for daily routines",
        "well-balanced specifications for the price",
    ]
    rng.shuffle(fallback_descriptors)
    for fd in fallback_descriptors:
        if len(matched_phrases) >= 3:
            break
        if fd not in matched_phrases:
            matched_phrases.append(fd)

    return matched_phrases[:3]


def synthesize_title_blind_utterance(
    candidate: Mapping[str, Any],
    stratum: str,
    rng: random.Random,
    brand_anchored: bool = False,
    budget_stated: bool = True,
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Synthesizes a conversational user utterance, its `gold_constraints` list, and
    `structured_filters` strictly title-blind (never reading `candidate['title']`).
    """
    product_type = str(candidate.get("product_type") or candidate.get("taxon_leaf") or candidate.get("category") or "device").strip()
    # Clean plural taxonomy labels into natural singular/plural request nouns
    product_type_lower = product_type.lower()
    price = float(candidate.get("price") or 50.0)
    brand = str(candidate.get("brand") or "").strip()
    features = candidate.get("features") or []
    details_json = candidate.get("details_json")
    attributes = candidate.get("attributes") or []

    clues = _paraphrase_spec_clues(features, details_json, attributes, rng)
    use_case = rng.choice(USE_CASE_HOOKS)

    gold_constraints: List[Dict[str, Any]] = []
    structured_filters: Dict[str, Any] = {"category": product_type}

    multiplier = rng.uniform(1.15, 1.45)
    budget = round_nice_budget(price, multiplier)
    if budget_stated:
        gold_constraints.append({
            "kind": "price",
            "attribute": "price",
            "operator": "less_than",
            "value": budget,
            "unit": "USD",
            "evidence": f"under ${int(budget)}",
        })
        structured_filters["price_max"] = budget

    if brand_anchored and brand and brand.lower() not in {"unknown", "generic", "none", "n/a"}:
        gold_constraints.append({
            "kind": "brand",
            "attribute": "brand",
            "operator": "include",
            "value": brand,
            "evidence": brand,
        })
        structured_filters["brand"] = brand

    # For S4 (Many-Feature Trade-off), add an extra stretch constraint or multi-requirement phrasing
    brand_phrase = f" from {brand}" if (brand_anchored and brand and structured_filters.get("brand")) else ""
    budget_phrase = f" while staying under ${int(budget)}" if budget_stated else ""

    templates = [
        f"I'm looking for a {product_type_lower}{brand_phrase} {use_case} that offers {clues[0]} and {clues[1]}{budget_phrase}.",
        f"Can you recommend a {product_type_lower}{brand_phrase} with {clues[0]} and {clues[1]} {use_case}{budget_phrase}?",
        f"I need a dependable {product_type_lower}{brand_phrase} {use_case} featuring {clues[0]} plus {clues[1]}{budget_phrase}.",
        f"Looking to buy a {product_type_lower}{brand_phrase} {use_case}—ideally something with {clues[0]} and {clues[1]}{budget_phrase}.",
    ]
    if stratum == "S4":
        extra_clue = clues[2] if len(clues) > 2 else "compact dimensions and long service life"
        templates = [
            f"I want a {product_type_lower}{brand_phrase} {use_case} that combines four things: {clues[0]}, {clues[1]}, {extra_clue}, and ultra-premium studio-grade components{budget_phrase}.",
            f"Could you find me a {product_type_lower}{brand_phrase} {use_case} with {clues[0]}, {clues[1]}, {extra_clue}, and zero-compromise flagship specs{budget_phrase}?",
        ]

    utterance = rng.choice(templates)
    return utterance, gold_constraints, structured_filters


AMBIGUOUS_QUERIES_V2: List[Dict[str, Any]] = [
    # Subtype 1: Open gift / use-case without product type (10)
    {"query_id": "r2b_amb_001", "subtype": "open_use_case", "utterance": "I'm looking for a useful tech gift for my brother starting college under $80. Any ideas?"},
    {"query_id": "r2b_amb_002", "subtype": "open_use_case", "utterance": "What can I buy under $100 to make long flights and airport layovers more comfortable?"},
    {"query_id": "r2b_amb_003", "subtype": "open_use_case", "utterance": "I want to upgrade my home office desk setup for remote work with a $150 budget."},
    {"query_id": "r2b_amb_004", "subtype": "open_use_case", "utterance": "Can you suggest something electronic for my parents' living room under $120?"},
    {"query_id": "r2b_amb_005", "subtype": "open_use_case", "utterance": "I need gear for recording content in my bedroom studio without spending over $200."},
    {"query_id": "r2b_amb_006", "subtype": "open_use_case", "utterance": "Looking for a practical gadget for camping and outdoor weekend trips under $60."},
    {"query_id": "r2b_amb_007", "subtype": "open_use_case", "utterance": "What's a good electronics anniversary present under $250 for someone who loves music?"},
    {"query_id": "r2b_amb_008", "subtype": "open_use_case", "utterance": "I just moved into a new apartment and want something to improve my home entertainment setup."},
    {"query_id": "r2b_amb_009", "subtype": "open_use_case", "utterance": "I have $50 to spend on something handy for my daily commute on the train."},
    {"query_id": "r2b_amb_010", "subtype": "open_use_case", "utterance": "Can you help me pick out a piece of tech for fitness and morning runs under $90?"},
    # Subtype 2: Undecided between distinct product categories (10)
    {"query_id": "r2b_amb_011", "subtype": "category_indecision", "utterance": "I can't decide whether to buy a tablet or a lightweight laptop for taking notes in class under $400."},
    {"query_id": "r2b_amb_012", "subtype": "category_indecision", "utterance": "Should I get a soundbar or a pair of bookshelf speakers for my small bedroom TV under $150?"},
    {"query_id": "r2b_amb_013", "subtype": "category_indecision", "utterance": "I'm torn between getting a portable projector or a regular monitor for watching movies in my dorm."},
    {"query_id": "r2b_amb_014", "subtype": "category_indecision", "utterance": "Not sure if I should get a dedicated digital camera or just a gimbal stabilizer for my vacation videos."},
    {"query_id": "r2b_amb_015", "subtype": "category_indecision", "utterance": "For late-night gaming, am I better off buying a desktop microphone or a headset under $100?"},
    {"query_id": "r2b_amb_016", "subtype": "category_indecision", "utterance": "I need extra storage under $120—should I look for an external SSD or a NAS drive?"},
    {"query_id": "r2b_amb_017", "subtype": "category_indecision", "utterance": "Debating between a Wi-Fi mesh system and a powerline adapter to fix dead zones Upstairs."},
    {"query_id": "r2b_amb_018", "subtype": "category_indecision", "utterance": "Would you recommend a trackball or a vertical mouse or maybe a drawing pad for wrist pain?"},
    {"query_id": "r2b_amb_019", "subtype": "category_indecision", "utterance": "I don't know whether to get a portable power station or a solar panel charger for tailgating."},
    {"query_id": "r2b_amb_020", "subtype": "category_indecision", "utterance": "Trying to choose between an e-reader and a small tablet for reading PDFs on the couch."},
    # Subtype 3: Generic part / cable / accessory without specifying type or host device (10)
    {"query_id": "r2b_amb_021", "subtype": "underspecified_part", "utterance": "I need a replacement power cord for my device under $25."},
    {"query_id": "r2b_amb_022", "subtype": "underspecified_part", "utterance": "Can you find me a protective case that fits snugly and has a pocket?"},
    {"query_id": "r2b_amb_023", "subtype": "underspecified_part", "utterance": "I'm looking for an adapter to connect my old display to my new computer."},
    {"query_id": "r2b_amb_024", "subtype": "underspecified_part", "utterance": "I need a spare battery that lasts a long time and charges quickly under $40."},
    {"query_id": "r2b_amb_025", "subtype": "underspecified_part", "utterance": "Looking for a mounting bracket that holds up to 15 pounds without wobbling."},
    {"query_id": "r2b_amb_026", "subtype": "underspecified_part", "utterance": "I need a high-speed cable around 6 feet long with braided nylon."},
    {"query_id": "r2b_amb_027", "subtype": "underspecified_part", "utterance": "Can you recommend a replacement remote control that works out of the box?"},
    {"query_id": "r2b_amb_028", "subtype": "underspecified_part", "utterance": "I want a screen protector that doesn't leave fingerprints or bubbles."},
    {"query_id": "r2b_amb_029", "subtype": "underspecified_part", "utterance": "I need a docking station or hub with plenty of ports under $70."},
    {"query_id": "r2b_amb_030", "subtype": "underspecified_part", "utterance": "Looking for a replacement charger brick that won't overheat."},
]


def build_ambiguous_benchmark_items(salt: str = BENCHMARK_V2_SALT) -> List[Dict[str, Any]]:
    """Builds the 30 Stratum A benchmark items with deterministic hashed tuning/test split."""
    items: List[Dict[str, Any]] = []
    for raw in AMBIGUOUS_QUERIES_V2:
        qid = raw["query_id"]
        split = assign_split(qid, salt=salt)
        items.append({
            "query_id": qid,
            "id": qid,
            "stratum": "A",
            "split": split,
            "subtype": raw["subtype"],
            "utterance": raw["utterance"],
            "category": None,
            "target_asin": None,
            "ground_truth_asins": [],
            "peer_asins": [],
            "graded_relevance": {},
            "structured_filters": {},
            "soft_preferences": [],
            "type_explicit": False,
            "gold_action": "CLARIFY",
            "gold_constraints": [],
            "brand_anchored": False,
            "budget_stated": "$" in raw["utterance"],
            "mask_target_reviews": False,
            "gold_annotation": {
                "annotator": "benchmark_v2_builder",
                "source": "utterance_only",
                "version": "r2b_v2",
            },
        })
    return items


def filter_benchmark_by_split(
    items: Sequence[Dict[str, Any]],
    split: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Filters benchmark items by `--split {all,tuning,test,legacy}`.
    Items without an explicit `split` key default to `'tuning'` (legacy compatibility).
    """
    if not split or split == "all":
        return list(items)
    split_norm = split.strip().lower()
    if split_norm == "legacy":
        return [item for item in items if item.get("stratum") == "legacy" or not item.get("stratum")]
    if split_norm in ("tuning", "test"):
        return [item for item in items if (item.get("split") or "tuning") == split_norm]
    raise ValueError(f"Unknown split '{split}'. Expected one of: all, tuning, test, legacy.")


def log_test_split_access(
    log_path: Path,
    benchmark_path: Path,
    split: str,
    query_count: int,
    strategies: Sequence[str],
    git_commit: str,
) -> None:
    """Appends an immutable audit entry whenever `--split test` (or `all` on benchmark_v2) is executed."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_commit": git_commit,
        "benchmark": str(benchmark_path),
        "split": split,
        "query_count": int(query_count),
        "strategies": list(strategies),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
