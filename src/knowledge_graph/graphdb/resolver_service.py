import logging
import os
import sys
import re
from typing import List, Dict, Optional, Set, Tuple, Any

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
except ImportError:
    from neo4j_connector import Neo4jConnector
    from embedding_service import EmbeddingService
from src.knowledge_graph.graphdb.vector_search_helper import build_vector_search_query

logger = logging.getLogger(__name__)

BRAND_CONFIDENCE = 0.85
CATEGORY_CONFIDENCE = 0.70  # Lowered to 0.70 to reliably resolve plurals and inflections
CATEGORY_MARGIN = 0.05      # Minimum margin between top-1 and runner-up candidate

# Principle P-9: Deterministic morphological tables (domain-agnostic English morphology)
INVARIANT_PLURALS: Set[str] = {
    "headphones", "earbuds", "earphones", "glasses", "sunglasses", "eyeglasses",
    "jeans", "scissors", "pants", "shorts", "trousers", "leggings", "goggles",
    "binoculars", "pliers", "tweezers", "clothes", "electronics", "graphics",
    "wireless", "waterproof", "stainless", "cordless", "noiseless", "brushless",
    "seamless", "lossless", "series", "species", "lens", "chassis", "apparatus",
}

IRREGULAR_PLURALS: Dict[str, str] = {
    "mice": "mouse",
    "men": "man",
    "women": "woman",
    "children": "child",
    "teeth": "tooth",
    "feet": "foot",
    "geese": "goose",
    "accessories": "accessory",
    "batteries": "battery",
    "categories": "category",
    "supplies": "supply",
    "memories": "memory",
    "frequencies": "frequency",
    "assemblies": "assembly",
    "knives": "knife",
    "shelves": "shelf",
    "halves": "half",
    "leaves": "leaf",
    "wolves": "wolf",
    "calves": "calf",
    "loaves": "loaf",
    "thieves": "thief",
    "wives": "wife",
    "lives": "life",
    "lenses": "lens",
    "buses": "bus",
    "gases": "gas",
    "quizzes": "quiz",
    "matrices": "matrix",
    "vertices": "vertex",
    "indices": "index",
    "indexes": "index",
    "antennas": "antenna",
    "antennae": "antenna",
    "headphone": "headphones",
    "earbud": "earbuds",
    "earphone": "earphones",
    "eyeglass": "eyeglasses",
    "sunglass": "sunglasses",
    "binocular": "binoculars",
    "goggle": "goggles",
}

# Structural container / accessory head lemmas (used to prevent accessory-modifier taxon hijacking)
ACCESSORY_HEAD_LEMMAS: Set[str] = {
    "accessory", "case", "cover", "mount", "clamp", "bag", "backpack", "pouch",
    "holster", "cable", "cord", "wire", "interconnect", "stand", "holder",
    "cradle", "dock", "protector", "skin", "decal", "sticker", "sleeve",
    "strap", "band", "wristband", "armband", "combo", "bundle", "kit", "set",
    "part", "replacement", "supply", "attachment", "plate", "bracket",
    "cleaner", "cleaning", "repair", "maintenance", "savings", "promotion",
    "event", "tradein", "warranty", "plan", "protection", "housing", "shell",
    "frame", "bumper", "pad", "mat", "wristrest", "cap", "hood", "ring",
}

# Head-lemma semantic equivalence groups for cross-taxonomy alignment
HEAD_EQUIVALENT_GROUPS: List[Set[str]] = [
    {"phone", "smartphone", "cellphone", "iphone", "telephone"},
    {"laptop", "notebook", "chromebook", "macbook", "ultrabook"},
    {"headphones", "headset", "earbuds", "earphones"},
    {"webcam", "camera", "camcorder"},
    {"charger", "adapter", "converter"},
    {"monitor", "display", "screen"},
    {"tv", "television"},
    {"drive", "ssd", "hdd", "storage"},
]

_STOPWORDS_MODIFIERS: Set[str] = {
    "the", "a", "an", "and", "or", "for", "with", "to", "in", "on", "of", "by", "at", "from",
}


def normalize_lemma(token: str) -> str:
    """
    Principle P-9: Deterministic morphological normalizer mapping English singular/plural
    inflections to a canonical lemma without corrupting invariant nouns (e.g. 'glasses', 'jeans').
    """
    if not token:
        return ""
    w = token.lower().strip()
    w = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", w)
    if not w or len(w) <= 2:
        return w

    if w in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[w]
    if w in INVARIANT_PLURALS:
        return w

    # Morphological suffix rules
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ves") and len(w) > 4:
        # Preserve -ve words like sleeves, drives, gloves, stoves, microwaves, receivers
        stem_ve = w[:-1]
        if stem_ve.endswith(("sleeve", "drive", "glove", "stove", "wave", "ceive", "curve", "valve")):
            return stem_ve
        return w[:-3] + "f"
    if w.endswith(("ches", "shes", "xes", "zes")) and len(w) > 4:
        return w[:-2]
    if w.endswith("ses") and len(w) > 4:
        # e.g. cases -> case, bases -> base, lenses -> lens (handled in irregulars)
        return w[:-1]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        if w.endswith("os") and not w.endswith(("radios", "videos", "studios", "stereos", "pianos", "photos", "combos", "pros", "duos", "trios")):
            return w
        return w[:-1]
    return w


def get_equivalent_head_lemmas(lemma: str) -> Set[str]:
    """Returns the set of head lemmas semantically equivalent to `lemma` (including itself)."""
    norm = normalize_lemma(lemma)
    out = {norm}
    for grp in HEAD_EQUIVALENT_GROUPS:
        if norm in grp:
            out.update(grp)
    return out


def decompose_type_phrase(phrase: str) -> Dict[str, Any]:
    """
    Decomposes a category or product-type phrase into:
    - clean_text: normalized lowercase phrase without parentheticals
    - lemmas: tuple of all normalized content lemmas in the main phrase
    - head_lemma: primary grammatical head noun lemma
    - head_lemmas: tuple of coordinated head noun lemmas (e.g. ('charger', 'adapter') for 'Chargers & Adapters')
    - modifier_lemmas: tuple of modifier lemmas preceding the head noun
    - parenthetical_lemmas: tuple of lemmas inside parentheses (e.g. 'MacBook Air' in 'laptop (MacBook Air)')
    - is_compound: True if the phrase coordinates multiple categories via '&', 'and', or ','
    - is_accessory_head: True if the primary head noun is an accessory/container/bundle term
    """
    if not phrase:
        return {
            "clean_text": "",
            "lemmas": (),
            "head_lemma": "",
            "head_lemmas": (),
            "modifier_lemmas": (),
            "parenthetical_lemmas": (),
            "is_compound": False,
            "is_accessory_head": False,
        }

    raw = str(phrase).strip()
    paren_matches = re.findall(r"\(([^)]+)\)", raw)
    paren_lemmas: List[str] = []
    for pm in paren_matches:
        for tok in re.findall(r"[a-zA-Z0-9]+", pm.lower()):
            lem = normalize_lemma(tok)
            if lem and lem not in _STOPWORDS_MODIFIERS:
                paren_lemmas.append(lem)

    # Strip parentheticals from main phrase
    main_str = re.sub(r"\([^)]*\)", " ", raw).strip()
    # Split off prepositional trailing qualifiers ("for iPhone", "with microphone")
    prep_split = re.split(r"\b(?:for|with|to|from|under|by)\b", main_str, maxsplit=1, flags=re.IGNORECASE)
    head_part = prep_split[0].strip() if prep_split else main_str

    # Normalize multi-word compound synonyms before tokenizing
    head_part_norm = re.sub(r"\b(?:cell|mobile|smart)\s+phones?\b", "smartphone", head_part, flags=re.IGNORECASE)
    head_part_norm = re.sub(r"\bweb\s+cameras?\b|\bweb\s+cams?\b", "webcam", head_part_norm, flags=re.IGNORECASE)

    is_compound = bool(re.search(r"&|\band\b|,", head_part_norm, flags=re.IGNORECASE))
    segments = [s.strip() for s in re.split(r"&|\band\b|,", head_part_norm, flags=re.IGNORECASE) if s.strip()]

    all_lemmas: List[str] = []
    seg_heads: List[str] = []
    for seg in segments:
        tokens = [normalize_lemma(t) for t in re.findall(r"[a-zA-Z0-9]+", seg.lower())]
        tokens = [t for t in tokens if t and t not in _STOPWORDS_MODIFIERS]
        if tokens:
            all_lemmas.extend(tokens)
            seg_heads.append(tokens[-1])

    if not all_lemmas:
        tokens = [normalize_lemma(t) for t in re.findall(r"[a-zA-Z0-9]+", main_str.lower())]
        all_lemmas = [t for t in tokens if t and t not in _STOPWORDS_MODIFIERS]
        if all_lemmas:
            seg_heads = [all_lemmas[-1]]

    primary_head = seg_heads[-1] if seg_heads else ""
    is_accessory_head = primary_head in ACCESSORY_HEAD_LEMMAS

    # If the final segment is an accessory/container (e.g., "Phone & Tablet Accessories", "Keyboard & Mouse Combos",
    # "Keyboards, Mice & Accessories"), the entire category is an accessory/combo container and preceding segments
    # are modifiers, NOT primary device heads.
    if is_accessory_head:
        effective_heads = (primary_head,)
        modifier_lemmas = tuple(l for l in all_lemmas[:-1] if l != primary_head)
    else:
        effective_heads = tuple(dict.fromkeys(seg_heads))
        modifier_lemmas = tuple(l for l in all_lemmas if l not in effective_heads)

    clean_text = re.sub(r"\s+", " ", main_str.lower()).strip()
    return {
        "clean_text": clean_text,
        "lemmas": tuple(all_lemmas),
        "head_lemma": primary_head,
        "head_lemmas": effective_heads,
        "modifier_lemmas": modifier_lemmas,
        "parenthetical_lemmas": tuple(paren_lemmas),
        "is_compound": is_compound,
        "is_accessory_head": is_accessory_head,
    }


class ResolverService:
    BRAND_CONFIDENCE = BRAND_CONFIDENCE
    CATEGORY_CONFIDENCE = CATEGORY_CONFIDENCE
    CATEGORY_MARGIN = CATEGORY_MARGIN

    def __init__(self, connector=None, embed_svc=None, min_score: float = 0.55):
        self.connector = connector or Neo4jConnector()
        if not connector:
            self.connector.connect()
        self.embed_svc = embed_svc or EmbeddingService()
        self.min_score = min_score

    @staticmethod
    def normalize_lemma(token: str) -> str:
        return normalize_lemma(token)

    @staticmethod
    def decompose_type_phrase(phrase: str) -> Dict[str, Any]:
        return decompose_type_phrase(phrase)

    def _execute_waterfall(self, text: str, node_label: str, property_name: str, index_name: str, k: int, return_props: List[str]) -> List[Dict]:
        """
        Executes a 3-tier waterfall resolution strategy.
        Tier 1: Exact Match (case-insensitive, including SKOS alt_labels for Taxon)
        Tier 2: Morphological / Head-Noun / Substring Match
        Tier 3: Vector Semantic Search
        """
        text = text.strip()
        if not text:
            return []

        ret_clause = ", ".join([f"node.{p} AS {p}" for p in return_props])

        with self.connector.session() as session:
            # Tier 1: Exact Match
            order_clause = "ORDER BY COALESCE(node.product_count, 0) DESC" if node_label == "Taxon" else ""
            t1_query = f"""
            MATCH (node:{node_label})
            WHERE toLower(node.{property_name}) = toLower($text)
            RETURN {ret_clause}, 1.0 AS score
            {order_clause}
            LIMIT {k}
            """
            result = session.run(t1_query, {"text": text})
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 1 (Exact) match found for '{text}' as {node_label}")
                return matches

            # For Taxon, use in-memory SKOS + Morphological Head-Noun scoring if cache is available
            if node_label == "Taxon":
                skos_morph_matches = self._resolve_taxon_skos_and_morphology(text, k=k)
                if skos_morph_matches:
                    logger.info(
                        f"[Resolver] Tier 2 (SKOS/Morphological Head-Noun) match found for '{text}': "
                        f"'{skos_morph_matches[0]['name']}' (score={skos_morph_matches[0]['score']:.3f})"
                    )
                    return skos_morph_matches

            # Tier 2: Substring / Word-Boundary Regex Match (fallback when cache is empty/mocked)
            if node_label in ("Category", "Taxon"):
                text_clean = text.lower().strip()
                if text_clean in ("smartphone", "smartphones", "smart phone", "smart phones", "cellphone", "cellphones", "cell phone", "cell phones", "mobile phone", "mobile phones"):
                    pattern = "(?i).*(^|[^a-z])(smart|cell|mobile)?( )?phone(s)?([^a-z]|$).*"
                else:
                    pattern = f"(?i).*(^|[^a-z]){re.escape(text)}(s)?([^a-z]|$).*"
                t2_query = f"""
                MATCH (node:{node_label})
                WHERE node.{property_name} =~ $pattern
                RETURN {ret_clause}, 0.85 AS score
                {order_clause}
                LIMIT {k}
                """
                result = session.run(t2_query, {"pattern": pattern})
            else:
                t2_query = f"""
                MATCH (node:{node_label})
                WHERE toLower(node.{property_name}) CONTAINS toLower($text)
                RETURN {ret_clause}, 0.85 AS score
                {order_clause}
                LIMIT {k}
                """
                result = session.run(t2_query, {"text": text})
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 2 (Substring/Regex) match found for '{text}' as {node_label}")
                return matches

        # Tier 3: Vector Search (Fallback)
        logger.info(f"[Resolver] Tiers 1 & 2 failed for '{text}'. Falling back to Tier 3 (Vector Semantic Search).")
        if node_label == "Taxon":
            matches = self._resolve_taxon_vector(text, k=k)
            if matches:
                logger.info(f"[Resolver] Tier 3 (Taxon Vector) match found for '{text}' with score {matches[0].get('score', 0):.3f}")
            return matches

        try:
            embedding = self.embed_svc.embed_query(text)
        except Exception as e:
            logger.error(f"[Resolver] Failed to generate embedding for '{text}': {e}")
            return []

        t3_query = build_vector_search_query(
            index_name=index_name,
            k=k,
            where_clause="score >= $min_score",
            return_clause=f"RETURN {ret_clause}, score"
        )

        with self.connector.session() as session:
            result = session.run(t3_query, {
                "k": k,
                "vector": embedding,
                "min_score": self.min_score
            })
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 3 (Vector) match found for '{text}' as {node_label} with score {matches[0].get('score', 0):.3f}")
            return matches

    def _ensure_taxon_cache(self):
        """Loads and embeds all Taxon nodes (including SKOS alt_labels and morphological decomposition) into memory."""
        if getattr(self, "_taxon_cache", None) is not None:
            # Ensure precomputed decomposition exists even if _taxon_cache was injected by a test
            for r in self._taxon_cache:
                if "_decomp" not in r:
                    r["_decomp"] = decompose_type_phrase(r.get("name") or "")
                    alt_raw = r.get("alt_labels") or []
                    r["_alt_lower"] = {str(a).lower().strip() for a in alt_raw if a}
                    r["_alt_lemmas"] = {
                        decompose_type_phrase(str(a))["lemmas"]
                        for a in alt_raw
                        if a and decompose_type_phrase(str(a))["lemmas"]
                    }
            return

        self._taxon_cache = []
        self._taxon_embeddings = None
        try:
            with self.connector.session() as session:
                raw_res = session.run(
                    "MATCH (t:Taxon) "
                    "RETURN t.name AS name, t.path AS path, t.product_count AS product_count, "
                    "t.depth AS depth, t.taxon_id AS taxon_id, t.alt_labels AS alt_labels "
                    "ORDER BY COALESCE(t.product_count, 0) DESC"
                )
                records = [dict(r) for r in raw_res] if not hasattr(raw_res, "data") else raw_res.data()
            if not records or not isinstance(records, list):
                return
            for r in records:
                r["_decomp"] = decompose_type_phrase(r.get("name") or "")
                alt_raw = r.get("alt_labels") or []
                r["_alt_lower"] = {str(a).lower().strip() for a in alt_raw if a}
                r["_alt_lemmas"] = {
                    decompose_type_phrase(str(a))["lemmas"]
                    for a in alt_raw
                    if a and decompose_type_phrase(str(a))["lemmas"]
                }
            self._taxon_cache = records
            names = [r.get("name") or "" for r in records]
            if hasattr(self.embed_svc, "embed_documents"):
                import numpy as np
                raw_embs = self.embed_svc.embed_documents(names)
                if raw_embs and len(raw_embs) == len(names):
                    embs = np.array(raw_embs, dtype=np.float32)
                    norms = np.linalg.norm(embs, axis=1, keepdims=True)
                    norms[norms == 0] = 1.0
                    self._taxon_embeddings = embs / norms
        except Exception as e:
            logger.warning(f"[Resolver] Could not initialize Taxon vector cache: {e}")

    def _score_taxon_candidate(self, q_decomp: Dict[str, Any], rec: Dict[str, Any]) -> float:
        """
        Scores a cached Taxon record against decomposed query `q_decomp` using:
        1. Exact lemmatized prefLabel match (1.00)
        2. Exact SKOS alt_labels match on compatible head (0.96)
        3. Primary head-noun match on pure device taxon (0.90 - 0.94)
        4. Compound '&' peer taxon sharing head noun (0.88)
        5. Accessory-modifier hijack demotion (0.45) when query does not request an accessory.
        """
        t_decomp = rec.get("_decomp") or decompose_type_phrase(rec.get("name") or "")
        q_lemmas = q_decomp["lemmas"]
        t_lemmas = t_decomp["lemmas"]
        if not q_lemmas or not t_lemmas:
            return 0.0

        q_head = q_decomp["head_lemma"]
        q_equiv_heads = get_equivalent_head_lemmas(q_head)
        q_is_acc = q_decomp["is_accessory_head"]

        t_head = t_decomp["head_lemma"]
        t_heads = set(t_decomp["head_lemmas"])
        t_is_acc = t_decomp["is_accessory_head"]

        # 1. Exact lemmatized prefLabel match (e.g. "Mouse" == "Mice", "Tablet" == "Tablets")
        if q_lemmas == t_lemmas:
            return 1.00

        # Check if Taxon is an accessory/container when the user asked for a primary device
        if not q_is_acc and t_is_acc:
            # Allow only if the query head itself is 'charger'/'adapter'/'converter' and Taxon is 'Power Accessories'
            if q_head in ("charger", "adapter", "converter") and "power" in t_lemmas:
                return 0.85
            if any(l in t_lemmas for l in q_lemmas):
                return 0.45
            return 0.0

        # 2. Exact SKOS alt_labels match (on non-accessory-hijacked Taxon)
        alt_lower = rec.get("_alt_lower") or set()
        alt_lemmas = rec.get("_alt_lemmas") or set()
        if q_decomp["clean_text"] in alt_lower or q_lemmas in alt_lemmas:
            return 0.96

        # 3. Primary head-noun match on a non-compound Taxon (e.g. "Laptop" -> "Traditional Laptops", "2 in 1 Laptops")
        if not t_decomp["is_compound"] and (t_head == q_head or t_head in q_equiv_heads):
            exact_head_bonus = 0.02 if t_head == q_head else 0.0
            q_mods = set(q_decomp["modifier_lemmas"])
            t_mods = set(t_decomp["modifier_lemmas"])
            if not q_mods:
                # Query is a bare head noun (e.g. "Laptop", "Camera", "Microphone")
                # Prefer cleaner/shorter device taxa (e.g. "Laptops" > "Traditional Laptops")
                if not t_mods:
                    return 0.94 + exact_head_bonus
                return 0.91 + exact_head_bonus
            else:
                # Query has modifiers (e.g. "instant film camera", "gaming laptop", "wall charger", "portable speaker")
                overlap = len(q_mods & t_mods)
                if overlap > 0:
                    return 0.93 + exact_head_bonus + 0.01 * min(overlap, 2)
                # Even if the specific modifier isn't in the Taxon name (e.g. "gaming laptop" -> "Traditional Laptops"),
                # a general device Taxon with the exact head noun is a valid container
                if t_mods <= {"traditional", "general", "standard", "complete", "digital", "video", "audio", "computer", "home", "portable", "bestselling", "renewed"} or not t_mods:
                    return 0.89 + exact_head_bonus
                return 0.0

        # 4. Compound '&' Taxon where one of the coordinated heads matches q_head
        # (e.g. "Charger" -> "Chargers & Adapters", "Batteries & Chargers"; "Phone" -> "Cell Phones & Accessories")
        if t_decomp["is_compound"]:
            if q_head in t_heads or bool(q_equiv_heads & t_heads):
                q_mods = set(q_decomp["modifier_lemmas"])
                t_all = set(t_lemmas)
                overlap = len(q_mods & t_all)
                return 0.88 + 0.01 * min(overlap, 2)
            # Special case: "Cell Phones & Accessories" where "phone" is in the first coordinated segment
            if ("phone" in q_equiv_heads and "phone" in t_lemmas and "cell" in t_lemmas) or (
                q_head == "camera" and t_lemmas == ("camera", "photo")
            ):
                return 0.88

        return 0.0

    def _resolve_taxon_skos_and_morphology(self, text: str, k: int = 5) -> List[Dict]:
        """Scores all cached Taxon nodes using SKOS alt_labels and morphological head-noun rules."""
        self._ensure_taxon_cache()
        if not self._taxon_cache:
            return []

        q_decomp = decompose_type_phrase(text)
        if not q_decomp["lemmas"]:
            return []

        scored: List[Tuple[float, int, Dict[str, Any]]] = []
        for rec in self._taxon_cache:
            sc = self._score_taxon_candidate(q_decomp, rec)
            if sc >= self.min_score:
                pc = int(rec.get("product_count") or 0)
                scored.append((sc, pc, rec))

        # Sort by (score DESC, product_count DESC)
        scored.sort(key=lambda x: (round(x[0], 4), x[1]), reverse=True)

        results: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()
        for sc, _, rec in scored:
            name = rec.get("name")
            if not name or name in seen_names:
                continue
            # Filter out promotional / 1-product event nodes when strong catalog nodes exist
            if (rec.get("product_count") or 0) < 5 and len(results) > 0 and sc < 0.98:
                continue
            seen_names.add(name)
            item = {
                "name": name,
                "path": rec.get("path"),
                "product_count": rec.get("product_count"),
                "depth": rec.get("depth"),
                "taxon_id": rec.get("taxon_id"),
                "score": float(round(sc, 4)),
            }
            if "alt_labels" in rec and rec["alt_labels"] is not None:
                item["alt_labels"] = rec["alt_labels"]
            results.append(item)
            if len(results) >= k:
                break

        # Only return from Tier 2 if best match meets CATEGORY_CONFIDENCE (0.70);
        # otherwise allow Tier 3 vector search to try semantic matching.
        if results and results[0]["score"] >= CATEGORY_CONFIDENCE:
            return results
        return []

    def _resolve_taxon_vector(self, text: str, k: int = 3) -> List[Dict]:
        """In-memory cosine similarity search over cached Taxon embeddings with accessory-hijack guard."""
        self._ensure_taxon_cache()
        if not self._taxon_cache or self._taxon_embeddings is None:
            return []
        try:
            import numpy as np
            q_decomp = decompose_type_phrase(text)
            clean_query = q_decomp["clean_text"] or text
            q_emb = self.embed_svc.embed_query(clean_query)
            if not q_emb:
                return []
            q_vec = np.array(q_emb, dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)
            if q_norm > 0:
                q_vec /= q_norm
            sims = np.dot(self._taxon_embeddings, q_vec)

            # Demote accessory-head taxa when the query is for a primary device
            adjusted_sims = np.copy(sims)
            if not q_decomp["is_accessory_head"] and len(self._taxon_cache) == len(adjusted_sims):
                for idx, rec in enumerate(self._taxon_cache):
                    t_decomp = rec.get("_decomp") or decompose_type_phrase(rec.get("name") or "")
                    if t_decomp["is_accessory_head"]:
                        adjusted_sims[idx] *= 0.65

            top_indices = np.argsort(-adjusted_sims)[:k]
            matches = []
            for idx in top_indices:
                score = float(adjusted_sims[idx])
                if score >= self.min_score:
                    item = {
                        k_name: v_val
                        for k_name, v_val in self._taxon_cache[idx].items()
                        if not str(k_name).startswith("_")
                    }
                    item["score"] = score
                    matches.append(item)
            return matches
        except Exception as e:
            logger.error(f"[Resolver] Taxon vector search failed for '{text}': {e}")
            return []

    def resolve_brand(self, text: str, k: int = 1) -> List[Dict]:
        return self._execute_waterfall(text, "Brand", "name", "brand_embedding_index", k, ["name"])

    def resolve_attribute(self, text: str, k: int = 3) -> List[Dict]:
        return self._execute_waterfall(text, "Attribute", "attribute_name", "attribute_embedding_index", k, ["attribute_name AS name", "attribute_value AS value", "normalized_value AS norm"])

    def resolve_taxon(self, text: str, k: int = 3) -> List[Dict]:
        return self._execute_waterfall(
            text, "Taxon", "name", "", k, ["name", "path", "product_count", "depth", "taxon_id"]
        )

    def resolve_category(self, text: str, k: int = 3) -> List[Dict]:
        return self.resolve_taxon(text, k=k)

    def resolve_category_family(
        self,
        text: str,
        query_text: Optional[str] = None,
        max_taxa: int = 6,
    ) -> List[Dict]:
        """
        RS-24 Pillar B: Resolves a product-type / category string into a cohesive family of
        matching Taxon nodes (up to `max_taxa`), rather than collapsing to a single k=1 node.
        Also checks `query_text` for specific product sub-types (e.g., 'webcam' when filter is 'Camera',
        or 'instant film camera' / 'power converter').
        """
        if not text or not str(text).strip():
            return []

        raw_candidates = self.resolve_category(str(text), k=max_taxa * 2)
        family: List[Dict] = []
        seen: Set[str] = set()

        for cand in raw_candidates:
            sc = cand.get("score", 0.0)
            name = cand.get("name")
            if not name or name in seen:
                continue
            if sc >= 0.85:
                seen.add(name)
                family.append(cand)
            elif not family and sc >= CATEGORY_CONFIDENCE:
                validated = self.validate_category_candidates(raw_candidates)
                if validated and validated.get("name") not in seen:
                    seen.add(validated["name"])
                    family.append(validated)
                break
            if len(family) >= max_taxa:
                break

        # Query-text refinement: if query_text mentions a specific subtype (e.g. "webcam" under "Camera",
        # or "travel adapter" / "converter" under "Charger"), include its primary Taxon in the family.
        if query_text:
            q_lower = query_text.lower()
            refinement_cues = []
            if "webcam" in q_lower or "web camera" in q_lower:
                refinement_cues.append("Webcams")
            if "travel" in q_lower and ("adapter" in q_lower or "charger" in q_lower):
                refinement_cues.extend(["Power Converters", "AC Adapters"])
            if "wall charger" in q_lower or "usb c charger" in q_lower or "power adapter" in q_lower:
                refinement_cues.extend(["Chargers & Adapters", "AC Adapters", "Power Converters"])
            if "instant" in q_lower and "camera" in q_lower:
                refinement_cues.append("Instant Cameras")
            for cue in refinement_cues:
                for sub_cand in self.resolve_category(cue, k=2):
                    s_name = sub_cand.get("name")
                    if s_name and s_name not in seen and sub_cand.get("score", 0.0) >= 0.85:
                        seen.add(s_name)
                        family.append(sub_cand)

        return family[:max_taxa]

    def validate_category_candidates(
        self,
        matches: List[Dict],
        min_confidence: float = CATEGORY_CONFIDENCE,
        min_margin: float = CATEGORY_MARGIN,
    ) -> Optional[Dict]:
        """
        Validates that the top category candidate meets min_confidence (0.70)
        and min_margin (>= 0.05) against cross-domain runner-ups.
        Returns the top candidate if valid, None if ambiguous or below confidence.
        """
        if not matches or matches[0].get("score", 0.0) < min_confidence:
            return None
        if matches[0].get("score", 0.0) < 0.85 and len(matches) > 1:
            top = matches[0]
            top_name = top.get("name", "").lower()
            top_path = [p.lower() for p in (top.get("path") or [])]
            top_decomp = decompose_type_phrase(top_name)
            for runner_up in matches[1:]:
                ru_name = runner_up.get("name", "").lower()
                ru_path = [p.lower() for p in (runner_up.get("path") or [])]
                ru_decomp = decompose_type_phrase(ru_name)
                if (
                    top_name in ru_name
                    or ru_name in top_name
                    or ru_name in top_path
                    or top_name in ru_path
                    or (top_decomp["head_lemma"] and top_decomp["head_lemma"] == ru_decomp["head_lemma"])
                ):
                    continue
                if top.get("score", 0.0) - runner_up.get("score", 0.0) < min_margin:
                    return None
                break
        return matches[0]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    resolver = ResolverService()
    print("Testing Waterfall Resolver...")
    print(f"Brand 'asus': {resolver.resolve_brand('asus')}")
    print(f"Category 'monitor': {resolver.resolve_category('monitor')}")
    print(f"Attribute 'refresh': {resolver.resolve_attribute('refresh')}")
