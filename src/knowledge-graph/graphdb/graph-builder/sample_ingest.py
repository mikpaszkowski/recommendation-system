"""
Prototype ingestion script for the Electronics knowledge graph subset.

Loads Neo4j constraints, filters Amazon review data to a recent temporal window,
derives core entities/relationships, and upserts them into Neo4j for validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

import pandas as pd
from pandas import DataFrame

from dotenv import load_dotenv

# Dynamically import Neo4jConnector to avoid issues with the hyphenated package name
import importlib.util


LOGGER = logging.getLogger("kg.sample_ingest")

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATA_DIR = ROOT_DIR / "datasets"
DEFAULT_CONSTRAINTS_PATH = Path(__file__).resolve().parent / "constraints.cypher"


def _load_connector_class():
    module_path = Path(__file__).resolve().parents[1] / "neo4j_connector.py"
    spec = importlib.util.spec_from_file_location("kg.neo4j_connector", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Neo4jConnector


Neo4jConnector = _load_connector_class()


@dataclass(frozen=True)
class PriceBucket:
    lower: float
    upper: Optional[float]  # None => +inf
    label: str

    @property
    def range_id(self) -> str:
        upper_val = "inf" if self.upper is None else f"{self.upper:.2f}"
        return f"USD_{self.lower:.2f}_{upper_val}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prototype KG ingestion for Electronics subset.")
    parser.add_argument(
        "--reviews-path",
        type=Path,
        default=DEFAULT_DATA_DIR / "Electronics.jsonl",
        help="Path to Amazon reviews JSONL file.",
    )
    parser.add_argument(
        "--metadata-path",
        type=Path,
        default=DEFAULT_DATA_DIR / "meta_Electronics.jsonl",
        help="Path to Amazon metadata JSONL file.",
    )
    parser.add_argument(
        "--constraints-path",
        type=Path,
        default=DEFAULT_CONSTRAINTS_PATH,
        help="Path to Cypher file defining constraints and indexes.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2018-01-01",
        help="Inclusive start date (UTC) for review filtering.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2023-12-31",
        help="Inclusive end date (UTC) for review filtering.",
    )
    parser.add_argument(
        "--fallback-start-date",
        type=str,
        default="2021-01-01",
        help="Fallback start date if the primary window returns too many reviews.",
    )
    parser.add_argument(
        "--max-reviews",
        type=int,
        default=500_000,
        help="Maximum number of reviews to load before falling back to the tighter window.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=150_000,
        help="Cap the number of reviews ingested for rapid prototyping.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5_000,
        help="Number of records per Neo4j transaction.",
    )
    parser.add_argument(
        "--aspects-path",
        type=Path,
        default=None,
        help="JSONL produced by aspect_pipeline.py containing aspect triplets.",
    )
    parser.add_argument(
        "--aggregate-preferences",
        action="store_true",
        help="Aggregate user preference edges (PREFERS/DISLIKES) from aspect sentiments.",
    )
    parser.add_argument(
        "--min-opinions",
        type=int,
        default=3,
        help="Minimum positive+negative mentions before emitting PREFERS/DISLIKES.",
    )
    parser.add_argument(
        "--preference-threshold",
        type=float,
        default=0.70,
        help="Positive ratio threshold for PREFERS edges.",
    )
    parser.add_argument(
        "--dislike-threshold",
        type=float,
        default=0.70,
        help="Negative ratio threshold for DISLIKES edges.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform transformations only; do not write to Neo4j.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def load_constraints(connector: Neo4jConnector, path: Path) -> None:
    if not path.exists():
        LOGGER.warning("Constraints file %s not found; skipping index setup.", path)
        return

    statements = []
    buffer: List[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        buffer.append(stripped)
        if stripped.endswith(";"):
            statements.append(" ".join(buffer))
            buffer.clear()
    if buffer:
        statements.append(" ".join(buffer))

    with connector.session() as session:
        for stmt in statements:
            cleaned = stmt.rstrip(";")
            LOGGER.debug("Executing constraint/index statement: %s", cleaned)
            session.run(cleaned)


def _read_jsonl_chunks(path: Path, chunksize: int = 100_000) -> Iterator[DataFrame]:
    LOGGER.debug("Reading JSONL in chunks from %s", path)
    if not path.exists():
        raise FileNotFoundError(f"JSONL source {path} not found.")
    if path.stat().st_size == 0:
        raise ValueError(f"JSONL source {path} is empty; populate the dataset before running ingestion.")
    try:
        return pd.read_json(
            path,
            lines=True,
            chunksize=chunksize,
            dtype=False,
        )
    except ValueError as exc:
        raise ValueError(f"Failed to parse JSONL file at {path}: {exc}") from exc


def load_reviews(
    path: Path,
    start_date: datetime,
    end_date: datetime,
    limit: int,
    fallback_start: Optional[datetime],
    max_reviews: int,
) -> Tuple[DataFrame, bool]:
    """Load reviews within the given window; fallback if the batch remains large."""

    def _filter_reviews(window_start: datetime) -> DataFrame:
        frames: List[DataFrame] = []
        total = 0
        for chunk in _read_jsonl_chunks(path):
            chunk["event_time"] = pd.to_datetime(chunk["timestamp"], unit="ms", utc=True)
            mask = (chunk["event_time"] >= window_start) & (chunk["event_time"] <= end_date)
            filtered = chunk.loc[mask]
            if filtered.empty:
                continue
            frames.append(filtered)
            total += len(filtered)
            LOGGER.debug("Collected %s reviews so far...", total)
            if limit and total >= limit:
                break
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        if limit:
            df = df.sort_values("event_time", ascending=False).head(limit)
        return df.reset_index(drop=True)

    LOGGER.info("Loading reviews between %s and %s", start_date.date(), end_date.date())
    reviews = _filter_reviews(start_date)
    LOGGER.info("Initial window yielded %d reviews", len(reviews))

    used_fallback = False
    if len(reviews) > max_reviews and fallback_start and fallback_start > start_date:
        LOGGER.warning(
            "Review count %d exceeds max_reviews=%d. Retrying with fallback start date %s.",
            len(reviews),
            max_reviews,
            fallback_start.date(),
        )
        reviews = _filter_reviews(fallback_start)
        used_fallback = True
        LOGGER.info("Fallback window yielded %d reviews", len(reviews))

    return reviews, used_fallback


def load_metadata(path: Path) -> DataFrame:
    LOGGER.info("Loading metadata from %s", path)
    frames = []
    chunk_idx = 0
    for chunk in _read_jsonl_chunks(path, chunksize=50_000):
        chunk_idx += 1
        if "parent_asin" not in chunk.columns:
            raise KeyError("Metadata payload must include 'parent_asin' column.")
        frames.append(chunk)
        LOGGER.debug("Processed metadata chunk %d containing %d rows", chunk_idx, len(chunk))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    LOGGER.info("Metadata records loaded: %d", len(df))
    return df


def _hash_review_id(row: pd.Series) -> str:
    payload = "|".join(
        [
            str(row.get("user_id", "")),
            str(row.get("asin", "")),
            str(int(row["event_time"].timestamp())),
            str(row.get("title", "")),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_users(reviews: DataFrame) -> List[Dict]:
    agg = reviews.groupby("user_id").agg(
        review_count=("asin", "count"),
        verified_purchase_count=("verified_purchase", lambda x: int(x.sum())),
        helpful_votes_total=("helpful_vote", "sum"),
    )
    agg = agg.reset_index()
    agg["ingested_at"] = datetime.utcnow().isoformat()
    return agg.to_dict(orient="records")


def derive_reviews(reviews: DataFrame, ingest_batch_id: str) -> List[Dict]:
    df = reviews.copy()
    df["review_id"] = df.apply(_hash_review_id, axis=1)
    df["timestamp_iso"] = df["event_time"].dt.tz_convert(None).astype("datetime64[ns]")
    df["ingest_batch_id"] = ingest_batch_id
    df.rename(
        columns={
            "title": "review_title",
            "text": "review_body",
            "verified_purchase": "verified",
            "helpful_vote": "helpful_votes",
        },
        inplace=True,
    )
    fields = [
        "review_id",
        "rating",
        "review_title",
        "review_body",
        "verified",
        "helpful_votes",
        "timestamp_iso",
        "user_id",
        "asin",
        "ingest_batch_id",
    ]
    return df[fields].to_dict(orient="records")


def derive_variants_from_reviews(reviews: DataFrame) -> List[Dict]:
    df = reviews[["asin", "parent_asin"]].drop_duplicates().copy()
    df["ingested_at"] = datetime.utcnow().isoformat()
    fields = ["asin", "parent_asin", "ingested_at"]
    return df[fields].to_dict(orient="records")


def _safe_float(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def derive_products(metadata: DataFrame, review_stats: DataFrame, ingest_batch_id: str) -> List[Dict]:
    df = metadata.copy()
    df["asin"] = df.get("asin", df.get("parent_asin"))
    df["price"] = df["price"].apply(_safe_float)
    df["avg_rating"] = df["average_rating"].apply(_safe_float)
    df["review_count"] = df["rating_number"].apply(lambda x: int(x) if pd.notna(x) else None)
    df["ingested_at"] = datetime.utcnow().isoformat()
    df["ingest_batch_id"] = ingest_batch_id

    if not review_stats.empty:
        df = df.merge(
            review_stats[["asin", "review_count"]].rename(columns={"review_count": "recent_review_count"}),
            on="asin",
            how="left",
        )

    fields = [
        "asin",
        "parent_asin",
        "title",
        "brand",
        "price",
        "avg_rating",
        "review_count",
        "recent_review_count",
        "main_category",
        "ingested_at",
        "ingest_batch_id",
    ]
    existing_fields = [f for f in fields if f in df.columns]
    return df[existing_fields].drop_duplicates("asin").to_dict(orient="records")


def derive_parent_products(metadata: DataFrame, ingest_batch_id: str) -> List[Dict]:
    df = metadata[metadata["parent_asin"].notna()].copy()
    if df.empty:
        return []
    df = df.sort_values(["parent_asin"]).drop_duplicates("parent_asin")
    df["price"] = df["price"].apply(_safe_float) if "price" in df.columns else None
    df["avg_rating"] = df["average_rating"].apply(_safe_float) if "average_rating" in df.columns else None
    if "rating_number" in df.columns:
        df["review_count"] = df["rating_number"].apply(lambda x: int(x) if pd.notna(x) else None)
    df["ingested_at"] = datetime.utcnow().isoformat()
    df["ingest_batch_id"] = ingest_batch_id
    fields = ["parent_asin", "title", "price", "avg_rating", "review_count", "ingested_at", "ingest_batch_id"]
    existing = [f for f in fields if f in df.columns]
    return df[existing].to_dict(orient="records")


def define_price_buckets() -> List[PriceBucket]:
    return [
        PriceBucket(0.0, 50.0, "$0-$50"),
        PriceBucket(50.0, 150.0, "$50-$150"),
        PriceBucket(150.0, 400.0, "$150-$400"),
        PriceBucket(400.0, 1000.0, "$400-$1000"),
        PriceBucket(1000.0, 1500.0, "$1000-$1500"),
        PriceBucket(1500.0, None, "$1500+")
    ]


def derive_price_ranges(buckets: Sequence[PriceBucket]) -> List[Dict]:
    now_iso = datetime.utcnow().isoformat()
    return [
        {
            "range_id": bucket.range_id,
            "label": bucket.label,
            "lower_bound": bucket.lower,
            "upper_bound": bucket.upper,
            "currency": "USD",
            "ingested_at": now_iso,
        }
        for bucket in buckets
    ]


def assign_price_ranges(products: List[Dict], buckets: Sequence[PriceBucket]) -> List[Dict]:
    relations = []
    for product in products:
        price = product.get("price")
        if price is None:
            continue
        for bucket in buckets:
            if price >= bucket.lower and (bucket.upper is None or price < bucket.upper):
                relations.append(
                    {
                        "parent_asin": product["parent_asin"],
                        "range_id": bucket.range_id,
                    }
                )
                break
    return relations


def derive_categories(metadata: DataFrame) -> Tuple[List[Dict], List[Dict]]:
    category_nodes = {}
    subcategory_edges = set()

    for _, row in metadata.iterrows():
        categories = row.get("categories")
        if not categories:
            continue
        if isinstance(categories, str):
            try:
                categories = json.loads(categories)
            except json.JSONDecodeError:
                categories = [categories]

        if categories and isinstance(categories[0], list):
            paths = categories
        else:
            paths = [categories]

        for path in paths:
            if not path:
                continue
            for level, name in enumerate(path):
                canonical = " > ".join(path[: level + 1])
                category_id = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
                category_nodes[category_id] = {
                    "category_id": category_id,
                    "name": name,
                    "level": level,
                    "path": path[: level + 1],
                    "ingested_at": datetime.utcnow().isoformat(),
                }
                if level > 0:
                    parent_canonical = " > ".join(path[:level])
                    parent_id = hashlib.sha1(parent_canonical.encode("utf-8")).hexdigest()
                    subcategory_edges.add((category_id, parent_id, level))

    category_list = list(category_nodes.values())
    subcategory_list = [
        {"child_category_id": child, "parent_category_id": parent, "depth": depth}
        for child, parent, depth in subcategory_edges
    ]
    return category_list, subcategory_list


def derive_category_memberships(metadata: DataFrame) -> List[Dict]:
    relations = []
    for _, row in metadata.iterrows():
        asin = row.get("parent_asin")
        categories = row.get("categories")
        if not asin or not categories:
            continue

        if isinstance(categories, str):
            try:
                categories = json.loads(categories)
            except json.JSONDecodeError:
                categories = [categories]

        if categories and isinstance(categories[0], list):
            paths = categories
        else:
            paths = [categories]

        for path in paths:
            for level in range(len(path)):
                canonical = " > ".join(path[: level + 1])
                category_id = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
                relations.append(
                    {
                        "parent_asin": asin,
                        "category_id": category_id,
                        "primary": level == len(path) - 1,
                    }
                )
    return relations


def _normalise_attribute(name: str, value: str) -> Tuple[str, str]:
    key = name.strip().lower().replace(" ", "_")
    norm_value = value.strip() if isinstance(value, str) else str(value)
    return key, norm_value


def derive_attributes(metadata: DataFrame) -> Tuple[List[Dict], List[Dict]]:
    attribute_nodes: Dict[str, Dict] = {}
    product_attribute_edges: List[Dict] = []

    for _, row in metadata.iterrows():
        asin = row.get("parent_asin")
        if not asin:
            continue

        # Details dictionary
        details = row.get("details") or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}

        if isinstance(details, dict):
            for key, value in details.items():
                if value in (None, "", "Not Available"):
                    continue
                attr_key, norm_value = _normalise_attribute(key, str(value))
                attribute_id = hashlib.sha1(f"{attr_key}|{norm_value}".encode("utf-8")).hexdigest()
                attribute_nodes.setdefault(
                    attribute_id,
                    {
                        "attribute_id": attribute_id,
                        "attribute_name": attr_key,
                        "attribute_value": str(value),
                        "normalized_value": norm_value.lower(),
                        "value_type": "categorical",
                        "source": "details",
                        "ingested_at": datetime.utcnow().isoformat(),
                    },
                )
                product_attribute_edges.append(
                    {
                        "parent_asin": asin,
                        "attribute_id": attribute_id,
                        "value_origin": "details",
                        "raw_value": str(value),
                        "confidence": 0.8,
                    }
                )

        # Feature bullets
        features = row.get("features") or []
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                features = [features]

        for feature in features:
            if not feature:
                continue
            if ":" in feature:
                key, value = feature.split(":", 1)
            else:
                key, value = "feature", feature
            attr_key, norm_value = _normalise_attribute(key, value)
            attribute_id = hashlib.sha1(f"{attr_key}|{norm_value}".encode("utf-8")).hexdigest()
            attribute_nodes.setdefault(
                attribute_id,
                {
                    "attribute_id": attribute_id,
                    "attribute_name": attr_key,
                    "attribute_value": value.strip(),
                    "normalized_value": norm_value.lower(),
                    "value_type": "text",
                    "source": "feature_bullet",
                    "ingested_at": datetime.utcnow().isoformat(),
                },
            )
            product_attribute_edges.append(
                {
                    "parent_asin": asin,
                    "attribute_id": attribute_id,
                    "value_origin": "feature_bullet",
                    "raw_value": value.strip(),
                    "confidence": 0.6,
                }
            )

    return list(attribute_nodes.values()), product_attribute_edges


def derive_brands(metadata: DataFrame) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    brand_nodes: Dict[str, Dict] = {}
    product_brand_edges: List[Dict] = []
    parent_brand_edges: List[Dict] = []

    for _, row in metadata.iterrows():
        # Prefer top-level brand, else fallback to details["Brand"] (common in metadata)
        brand_candidates = []
        top_brand = row.get("brand")
        if isinstance(top_brand, str) and top_brand.strip():
            brand_candidates.append(top_brand.strip())

        details = row.get("details") or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}

        if isinstance(details, dict):
            for key in ["Brand", "brand", "Brand Name", "Brand_Name"]:
                val = details.get(key)
                if isinstance(val, str) and val.strip():
                    brand_candidates.append(val.strip())
                    break

        if not brand_candidates:
            continue

        norm = brand_candidates[0]
        brand_id = hashlib.sha1(norm.lower().encode("utf-8")).hexdigest()
        brand_nodes.setdefault(
            brand_id,
            {"brand_id": brand_id, "name": norm, "ingested_at": datetime.utcnow().isoformat()},
        )
        parent_asin = row.get("parent_asin")
        if parent_asin:
            parent_brand_edges.append(
                {
                    "parent_asin": parent_asin,
                    "brand_id": brand_id,
                    "source": "metadata",
                    "confidence": 0.95,
                }
            )

    return list(brand_nodes.values()), product_brand_edges, parent_brand_edges


def derive_copurchase(metadata: DataFrame) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    sets: Dict[str, Dict] = {}
    members: List[Dict] = []
    pair_edges: List[Dict] = []

    for _, row in metadata.iterrows():
        asin = row.get("parent_asin")
        bought_together = row.get("bought_together")
        if not asin or not bought_together:
            continue

        if isinstance(bought_together, str):
            try:
                bought_together = json.loads(bought_together)
            except json.JSONDecodeError:
                bought_together = [bought_together]

        if not isinstance(bought_together, (list, tuple)):
            continue

        cleaned = [item for item in bought_together if item]
        if not cleaned:
            continue
        set_id = hashlib.sha1(f"{asin}|{'|'.join(cleaned)}".encode("utf-8")).hexdigest()
        sets.setdefault(
            set_id,
            {
                "set_id": set_id,
                "source_asin": asin,
                "size": len(cleaned),
                "support": len(cleaned),
                "confidence": 1.0,
                "ingested_at": datetime.utcnow().isoformat(),
            },
        )
        for position, member_asin in enumerate(cleaned):
            members.append(
                {
                    "set_id": set_id,
                    "parent_asin": member_asin,
                    "position": position,
                }
            )
        pair_edges.append(
            {
                    "source_asin": asin,
                    "target_asin": member_asin,
                "support": 1,
                "confidence": 0.5,
            }
        )

    roots = [{"set_id": set_id, "parent_asin": data["source_asin"]} for set_id, data in sets.items()]
    return list(sets.values()), members, pair_edges + roots


def split_rated_edges(reviews: DataFrame) -> Tuple[List[Dict], List[Dict]]:
    variant_edges: List[Dict] = []
    parent_edges: List[Dict] = []
    for _, row in reviews.iterrows():
        edge_base = {
            "user_id": row["user_id"],
            "rating": float(row["rating"]),
            "timestamp_iso": row["event_time"].tz_convert(None).isoformat(),
            "review_id": _hash_review_id(row),
            "verified": bool(row["verified_purchase"]),
        }
        parent_asin = row.get("parent_asin")
        asin = row.get("asin")
        if parent_asin and asin and asin != parent_asin:
            edge = dict(edge_base)
            edge["asin"] = asin
            variant_edges.append(edge)
        else:
            edge = dict(edge_base)
            edge["parent_asin"] = parent_asin or asin
            parent_edges.append(edge)
    return variant_edges, parent_edges


def derive_variant_edges(products: List[Dict]) -> List[Dict]:
    edges = []
    for product in products:
        asin = product.get("asin")
        parent = product.get("parent_asin")
        if parent and asin and parent != asin:
            edges.append(
                {
                    "child_asin": asin,
                    "parent_asin": parent,
                }
            )
    return edges


def load_aspect_triplets(path: Optional[Path], known_review_ids: Set[str]) -> Tuple[List[Dict], List[Dict]]:
    """Load aspect triplets JSONL emitted by aspect_pipeline.py."""
    if not path:
        return [], []
    if not path.exists():
        LOGGER.warning("Aspects path %s not found; skipping aspect ingestion.", path)
        return [], []

    df = pd.read_json(path, lines=True, dtype=False)
    if df.empty:
        return [], []

    df = df[df["review_id"].isin(known_review_ids)]
    if df.empty:
        LOGGER.warning("No aspect rows align with current review window; skipping.")
        return [], []

    df["aspect_name"] = df["aspect"].astype(str).str.strip().str.lower()
    df["sentiment"] = df["sentiment"].astype(str).str.title()
    df["opinion_text"] = df.get("opinion", df.get("opinion_text", "")).fillna("")
    df["confidence"] = df.get("confidence", 1.0).fillna(1.0).astype(float)
    df["surface_form"] = df.get("surface_form", df["aspect_name"])
    df["model_version"] = df.get("model_version", "unknown").fillna("unknown")

    now_iso = datetime.utcnow().isoformat()

    aspect_nodes = (
        df.groupby("aspect_name")
        .agg(
            surface_forms=("surface_form", lambda series: sorted(set([val for val in series if isinstance(val, str)]))),
            mention_count=("review_id", "count"),
        )
        .reset_index()
        .rename(columns={"aspect_name": "name"})
    )
    aspect_nodes["ingested_at"] = now_iso
    aspect_nodes_records = aspect_nodes.to_dict(orient="records")

    relationship_rows = df[
        ["review_id", "aspect_name", "sentiment", "opinion_text", "confidence", "surface_form", "model_version"]
    ].rename(columns={"aspect_name": "name"})
    return aspect_nodes_records, relationship_rows.to_dict(orient="records")


def aggregate_user_preferences(
    aspect_mentions: List[Dict],
    reviews: DataFrame,
    min_opinions: int,
    preference_threshold: float,
    dislike_threshold: float,
) -> Tuple[List[Dict], List[Dict]]:
    """Aggregate aspect sentiments into user-level PREFERS/DISLIKES edges."""
    if not aspect_mentions:
        return [], []

    df = pd.DataFrame(aspect_mentions)
    review_users = reviews[["review_id", "user_id"]].drop_duplicates()
    df = df.merge(review_users, on="review_id", how="left")
    df = df[df["user_id"].notna()]
    if df.empty:
        return [], []

    df["sentiment_norm"] = df["sentiment"].str.lower()
    sentiment_counts = (
        df.groupby(["user_id", "name"])["sentiment_norm"]
        .value_counts()
        .unstack(fill_value=0)
        .reset_index()
    )

    def _series_with_default(frame: DataFrame, column: str) -> pd.Series:
        return frame[column] if column in frame.columns else pd.Series([0] * len(frame), index=frame.index)

    pos = _series_with_default(sentiment_counts, "positive")
    neg = _series_with_default(sentiment_counts, "negative")
    total = pos + neg

    sentiment_counts["positive"] = pos
    sentiment_counts["negative"] = neg
    sentiment_counts["total"] = total
    sentiment_counts["positive_ratio"] = sentiment_counts.apply(
        lambda row: (row["positive"] / row["total"]) if row["total"] else 0.0, axis=1
    )
    sentiment_counts["negative_ratio"] = sentiment_counts.apply(
        lambda row: (row["negative"] / row["total"]) if row["total"] else 0.0, axis=1
    )

    prefers: List[Dict] = []
    dislikes: List[Dict] = []

    for _, row in sentiment_counts.iterrows():
        if row["total"] < min_opinions:
            continue
        base = {
            "user_id": row["user_id"],
            "name": row["name"],
            "positive_count": int(row["positive"]),
            "negative_count": int(row["negative"]),
            "support": int(row["total"]),
        }
        if row["positive_ratio"] >= preference_threshold:
            prefers.append({**base, "preference_score": float(row["positive_ratio"])})
        if row["negative_ratio"] >= dislike_threshold:
            dislikes.append({**base, "preference_score": float(row["negative_ratio"])})

    return prefers, dislikes

def chunk(items: Sequence[Dict], size: int) -> Iterator[List[Dict]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def merge_nodes(
    connector: Neo4jConnector,
    label: str,
    key: str,
    rows: Sequence[Dict],
    batch_size: int,
) -> None:
    if not rows:
        return
    query = f"""
    UNWIND $batch AS row
    MERGE (n:{label} {{{key}: row.{key}}})
    SET n += row
    """
    with connector.session() as session:
        for batch in chunk(list(rows), batch_size):
            session.run(query, batch=batch)


def merge_relationships(
    connector: Neo4jConnector,
    type_: str,
    start_label: str,
    start_key: str,
    end_label: str,
    end_key: str,
    rows: Sequence[Dict],
    batch_size: int,
    *,
    start_field: Optional[str] = None,
    end_field: Optional[str] = None,
    property_fields: Optional[Sequence[str]] = None,
    additional_set: Optional[str] = None,
) -> None:
    if not rows:
        return

    start_field = start_field or start_key
    end_field = end_field or end_key

    set_clauses = []
    if property_fields:
        set_clauses.extend([f"rel.{field} = row.{field}" for field in property_fields])
    if additional_set:
        set_clauses.append(additional_set)
    set_clause = ""
    if set_clauses:
        set_clause = "SET " + ", ".join(set_clauses)

    query = f"""
    UNWIND $batch AS row
    MATCH (start:{start_label} {{{start_key}: row.{start_field}}})
    MATCH (end:{end_label} {{{end_key}: row.{end_field}}})
    MERGE (start)-[rel:{type_}]->(end)
    {set_clause}
    """
    with connector.session() as session:
        for batch in chunk(list(rows), batch_size):
            session.run(query, batch=batch)


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    load_dotenv()

    ingest_batch_id = datetime.utcnow().strftime("electronics_%Y%m%d%H%M%S")

    start_date = datetime.fromisoformat(args.start_date).replace(tzinfo=timezone.utc)
    end_date = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc)
    fallback_start = None
    if args.fallback_start_date:
        fallback_start = datetime.fromisoformat(args.fallback_start_date).replace(tzinfo=timezone.utc)

    reviews_df, used_fallback = load_reviews(
        path=args.reviews_path,
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
        fallback_start=fallback_start,
        max_reviews=args.max_reviews,
    )
    if reviews_df.empty:
        LOGGER.warning("No reviews found for the specified window; nothing to ingest.")
        return

    metadata_df = load_metadata(args.metadata_path)
    metadata_df = metadata_df[
        metadata_df["parent_asin"].notna()
        & metadata_df["parent_asin"].isin(reviews_df["parent_asin"].dropna().unique())
    ].reset_index(drop=True)
    LOGGER.info("Metadata filtered to %d parent products referenced in the review window.", len(metadata_df))

    users = derive_users(reviews_df)
    reviews_enriched = reviews_df.copy()
    reviews_enriched["review_id"] = reviews_enriched.apply(_hash_review_id, axis=1)

    review_nodes = derive_reviews(reviews_df, ingest_batch_id)
    variants = derive_variants_from_reviews(reviews_enriched)
    parent_products = derive_parent_products(metadata_df, ingest_batch_id)

    buckets = define_price_buckets()
    price_range_nodes = derive_price_ranges(buckets)
    price_range_edges = assign_price_ranges(parent_products, buckets)

    category_nodes, subcategory_edges = derive_categories(metadata_df)
    category_memberships = derive_category_memberships(metadata_df)

    attribute_nodes, has_attribute_edges = derive_attributes(metadata_df)
    brand_nodes, product_brand_edges, parent_brand_edges = derive_brands(metadata_df)

    copurchase_sets, copurchase_members, copurchase_edges = derive_copurchase(metadata_df)

    rated_variant_edges, rated_parent_edges = split_rated_edges(reviews_enriched)
    variant_edges = derive_variant_edges(variants)

    aspect_nodes: List[Dict] = []
    aspect_mentions: List[Dict] = []
    user_pref_edges: List[Dict] = []
    user_dislike_edges: List[Dict] = []
    if args.aspects_path:
        aspect_nodes, aspect_mentions = load_aspect_triplets(
            args.aspects_path,
            set(reviews_enriched["review_id"].tolist()),
        )
        if args.aggregate_preferences:
            user_pref_edges, user_dislike_edges = aggregate_user_preferences(
                aspect_mentions,
                reviews_enriched,
                min_opinions=args.min_opinions,
                preference_threshold=args.preference_threshold,
                dislike_threshold=args.dislike_threshold,
            )

    wrote_edges = [
        {"user_id": row["user_id"], "review_id": row["review_id"]}
        for row in review_nodes
    ]
    about_variant_edges = [
        {"review_id": row["review_id"], "asin": row["asin"]}
        for _, row in reviews_enriched.iterrows()
        if row.get("parent_asin") and row["asin"] != row["parent_asin"]
    ]
    about_parent_edges = [
        {"review_id": row["review_id"], "parent_asin": row.get("parent_asin") or row.get("asin")}
        for _, row in reviews_enriched.iterrows()
        if not row.get("parent_asin") or row["asin"] == row.get("parent_asin")
    ]

    LOGGER.info(
        "Prepared %d users, %d reviews, %d variants, %d parents. Fallback window used: %s",
        len(users),
        len(review_nodes),
        len(variants),
        len(parent_products),
        used_fallback,
    )

    if args.dry_run:
        LOGGER.info("Dry run complete; not writing to Neo4j.")
        return

    with Neo4jConnector() as connector:
        load_constraints(connector, args.constraints_path)

        merge_nodes(connector, "User", "user_id", users, args.batch_size)
        merge_nodes(connector, "Review", "review_id", review_nodes, args.batch_size)
        merge_nodes(connector, "Variant", "asin", variants, args.batch_size)
        merge_nodes(connector, "ParentProduct", "parent_asin", parent_products, args.batch_size)
        merge_nodes(connector, "Brand", "brand_id", brand_nodes, args.batch_size)
        merge_nodes(connector, "PriceRange", "range_id", price_range_nodes, args.batch_size)
        merge_nodes(connector, "Category", "category_id", category_nodes, args.batch_size)
        merge_nodes(connector, "Attribute", "attribute_id", attribute_nodes, args.batch_size)
        merge_nodes(connector, "CoPurchaseSet", "set_id", copurchase_sets, args.batch_size)
        if aspect_nodes:
            merge_nodes(connector, "Aspect", "name", aspect_nodes, args.batch_size)

        merge_relationships(
            connector,
            "WROTE",
            "User",
            "user_id",
            "Review",
            "review_id",
            wrote_edges,
            args.batch_size,
        )

        if about_variant_edges:
            merge_relationships(
                connector,
                "ABOUT_PRODUCT",
                "Review",
                "review_id",
                "Variant",
                "asin",
                about_variant_edges,
                args.batch_size,
            )
        if about_parent_edges:
            merge_relationships(
                connector,
                "ABOUT_PRODUCT",
                "Review",
                "review_id",
                "ParentProduct",
                "parent_asin",
                about_parent_edges,
                args.batch_size,
                end_field="parent_asin",
            )

        if rated_variant_edges:
            merge_relationships(
                connector,
                "RATED",
                "User",
                "user_id",
                "Variant",
                "asin",
                rated_variant_edges,
                args.batch_size,
                property_fields=["rating", "timestamp_iso", "review_id", "verified"],
            )
        if rated_parent_edges:
            merge_relationships(
                connector,
                "RATED",
                "User",
                "user_id",
                "ParentProduct",
                "parent_asin",
                rated_parent_edges,
                args.batch_size,
                end_field="parent_asin",
                property_fields=["rating", "timestamp_iso", "review_id", "verified"],
            )

        merge_relationships(
            connector,
            "IN_PRICE_RANGE",
            "ParentProduct",
            "parent_asin",
            "PriceRange",
            "range_id",
            price_range_edges,
            args.batch_size,
            start_field="parent_asin",
        )

        merge_relationships(
            connector,
            "BELONGS_TO_CATEGORY",
            "ParentProduct",
            "parent_asin",
            "Category",
            "category_id",
            category_memberships,
            args.batch_size,
            start_field="parent_asin",
            property_fields=["primary"],
        )

        merge_relationships(
            connector,
            "SUBCATEGORY_OF",
            "Category",
            "category_id",
            "Category",
            "category_id",
            subcategory_edges,
            args.batch_size,
            start_field="child_category_id",
            end_field="parent_category_id",
            property_fields=["depth"],
        )

        merge_relationships(
            connector,
            "HAS_ATTRIBUTE",
            "ParentProduct",
            "parent_asin",
            "Attribute",
            "attribute_id",
            has_attribute_edges,
            args.batch_size,
            start_field="parent_asin",
            property_fields=["value_origin", "raw_value", "confidence"],
        )

        if aspect_mentions:
            merge_relationships(
                connector,
                "MENTIONS_ASPECT",
                "Review",
                "review_id",
                "Aspect",
                "name",
                aspect_mentions,
                args.batch_size,
                end_field="name",
                property_fields=["sentiment", "opinion_text", "confidence", "surface_form", "model_version"],
            )

        if user_pref_edges:
            merge_relationships(
                connector,
                "PREFERS",
                "User",
                "user_id",
                "Aspect",
                "name",
                user_pref_edges,
                args.batch_size,
                start_field="user_id",
                end_field="name",
                property_fields=["positive_count", "negative_count", "support", "preference_score"],
            )

        if user_dislike_edges:
            merge_relationships(
                connector,
                "DISLIKES",
                "User",
                "user_id",
                "Aspect",
                "name",
                user_dislike_edges,
                args.batch_size,
                start_field="user_id",
                end_field="name",
                property_fields=["positive_count", "negative_count", "support", "preference_score"],
            )

        if parent_brand_edges:
            merge_relationships(
                connector,
                "HAS_BRAND",
                "ParentProduct",
                "parent_asin",
                "Brand",
                "brand_id",
                parent_brand_edges,
                args.batch_size,
                start_field="parent_asin",
                property_fields=["source", "confidence"],
            )

        merge_relationships(
            connector,
            "MEMBER_OF_SET",
            "ParentProduct",
            "parent_asin",
            "CoPurchaseSet",
            "set_id",
            copurchase_members,
            args.batch_size,
            start_field="parent_asin",
            property_fields=["position"],
        )

        # Pairwise co-purchase edges and root associations share structure; filter fields
        pair_edges = [edge for edge in copurchase_edges if "target_asin" in edge]
        if pair_edges:
            merge_relationships(
                connector,
                "BOUGHT_TOGETHER",
                "ParentProduct",
                "parent_asin",
                "ParentProduct",
                "parent_asin",
                pair_edges,
                args.batch_size,
                start_field="source_asin",
                end_field="target_asin",
                property_fields=["support", "confidence"],
            )

        root_edges = [edge for edge in copurchase_edges if "target_asin" not in edge]
        if root_edges:
            merge_relationships(
                connector,
                "HAS_ROOT",
                "CoPurchaseSet",
                "set_id",
                "ParentProduct",
                "parent_asin",
                root_edges,
                args.batch_size,
                end_field="parent_asin",
                property_fields=[],
            )

        if variant_edges:
            merge_relationships(
                connector,
                "IS_VARIANT_OF",
                "Variant",
                "child_asin",
                "ParentProduct",
                "parent_asin",
                variant_edges,
                args.batch_size,
                start_field="child_asin",
                end_field="parent_asin",
            )

    LOGGER.info("Ingestion complete.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        LOGGER.warning("Ingestion interrupted by user.")
        sys.exit(1)

