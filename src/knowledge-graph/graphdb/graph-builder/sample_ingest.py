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
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

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
    adjust_chunk: Optional[Callable[[DataFrame], DataFrame]] = None
    chunk_idx = 0
    for chunk in _read_jsonl_chunks(path, chunksize=50_000):
        chunk_idx += 1
        if adjust_chunk is None:
            column_set = set(chunk.columns)
            has_asin = "asin" in column_set
            has_parent_asin = "parent_asin" in column_set
            if not has_asin and not has_parent_asin:
                raise KeyError(
                    "Metadata payload must include either 'asin' or 'parent_asin' columns."
                )

            def _adjust(df: DataFrame) -> DataFrame:
                if has_asin:
                    if has_parent_asin:
                        df["asin"] = df["asin"].fillna(df["parent_asin"])
                    return df
                return df.assign(asin=df["parent_asin"])

            adjust_chunk = _adjust
        frames.append(adjust_chunk(chunk))
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
                        "asin": product["asin"],
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
        asin = row.get("asin") or row.get("parent_asin")
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
                        "asin": asin,
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
        asin = row.get("asin") or row.get("parent_asin")
        if not asin:
            continue

        # Brand as attribute
        brand = row.get("brand")
        if isinstance(brand, str) and brand:
            key, norm_value = _normalise_attribute("brand", brand)
            attribute_id = hashlib.sha1(f"{key}|{norm_value}".encode("utf-8")).hexdigest()
            attribute_nodes.setdefault(
                attribute_id,
                {
                    "attribute_id": attribute_id,
                    "attribute_name": key,
                    "attribute_value": brand,
                    "normalized_value": norm_value.lower(),
                    "value_type": "categorical",
                    "source": "metadata",
                    "ingested_at": datetime.utcnow().isoformat(),
                },
            )
            product_attribute_edges.append(
                {
                    "asin": asin,
                    "attribute_id": attribute_id,
                    "value_origin": "brand",
                    "raw_value": brand,
                    "confidence": 0.95,
                }
            )

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
                        "asin": asin,
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
                    "asin": asin,
                    "attribute_id": attribute_id,
                    "value_origin": "feature_bullet",
                    "raw_value": value.strip(),
                    "confidence": 0.6,
                }
            )

    return list(attribute_nodes.values()), product_attribute_edges


def derive_copurchase(metadata: DataFrame) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    sets: Dict[str, Dict] = {}
    members: List[Dict] = []
    pair_edges: List[Dict] = []

    for _, row in metadata.iterrows():
        asin = row.get("asin") or row.get("parent_asin")
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
                    "asin": member_asin,
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

    roots = [{"set_id": set_id, "asin": data["source_asin"]} for set_id, data in sets.items()]
    return list(sets.values()), members, pair_edges + roots


def derive_rated_edges(reviews: DataFrame) -> List[Dict]:
    edges = []
    for _, row in reviews.iterrows():
        edges.append(
            {
                "user_id": row["user_id"],
                "asin": row["asin"],
                "rating": float(row["rating"]),
                "timestamp_iso": row["event_time"].tz_convert(None).isoformat(),
                "review_id": _hash_review_id(row),
                "verified": bool(row["verified_purchase"]),
            }
        )
    return edges


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
    metadata_df = metadata_df[metadata_df["asin"].isin(reviews_df["asin"].unique())].reset_index(drop=True)
    LOGGER.info("Metadata filtered to %d products referenced in the review window.", len(metadata_df))

    users = derive_users(reviews_df)
    review_nodes = derive_reviews(reviews_df, ingest_batch_id)
    products = derive_products(metadata_df, reviews_df.groupby("asin").agg(review_count=("rating", "count")).reset_index(), ingest_batch_id)

    buckets = define_price_buckets()
    price_range_nodes = derive_price_ranges(buckets)
    price_range_edges = assign_price_ranges(products, buckets)

    category_nodes, subcategory_edges = derive_categories(metadata_df)
    category_memberships = derive_category_memberships(metadata_df)

    attribute_nodes, has_attribute_edges = derive_attributes(metadata_df)

    copurchase_sets, copurchase_members, copurchase_edges = derive_copurchase(metadata_df)

    rated_edges = derive_rated_edges(reviews_df)
    variant_edges = derive_variant_edges(products)

    wrote_edges = [
        {"user_id": row["user_id"], "review_id": row["review_id"]}
        for row in review_nodes
    ]
    review_relations = [
        {"review_id": row["review_id"], "asin": row["asin"]}
        for row in review_nodes
    ]

    LOGGER.info(
        "Prepared %d users, %d reviews, %d products. Fallback window used: %s",
        len(users),
        len(review_nodes),
        len(products),
        used_fallback,
    )

    if args.dry_run:
        LOGGER.info("Dry run complete; not writing to Neo4j.")
        return

    with Neo4jConnector() as connector:
        load_constraints(connector, args.constraints_path)

        merge_nodes(connector, "User", "user_id", users, args.batch_size)
        merge_nodes(connector, "Review", "review_id", review_nodes, args.batch_size)
        merge_nodes(connector, "Product", "asin", products, args.batch_size)
        merge_nodes(connector, "PriceRange", "range_id", price_range_nodes, args.batch_size)
        merge_nodes(connector, "Category", "category_id", category_nodes, args.batch_size)
        merge_nodes(connector, "Attribute", "attribute_id", attribute_nodes, args.batch_size)
        merge_nodes(connector, "CoPurchaseSet", "set_id", copurchase_sets, args.batch_size)

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

        merge_relationships(
            connector,
            "REVIEWS",
            "Review",
            "review_id",
            "Product",
            "asin",
            review_relations,
            args.batch_size,
        )

        merge_relationships(
            connector,
            "RATED",
            "User",
            "user_id",
            "Product",
            "asin",
            rated_edges,
            args.batch_size,
            property_fields=["rating", "timestamp_iso", "review_id", "verified"],
        )

        merge_relationships(
            connector,
            "IN_PRICE_RANGE",
            "Product",
            "asin",
            "PriceRange",
            "range_id",
            price_range_edges,
            args.batch_size,
        )

        merge_relationships(
            connector,
            "BELONGS_TO_CATEGORY",
            "Product",
            "asin",
            "Category",
            "category_id",
            category_memberships,
            args.batch_size,
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
            "Product",
            "asin",
            "Attribute",
            "attribute_id",
            has_attribute_edges,
            args.batch_size,
            property_fields=["value_origin", "raw_value", "confidence"],
        )

        merge_relationships(
            connector,
            "MEMBER_OF_SET",
            "Product",
            "asin",
            "CoPurchaseSet",
            "set_id",
            copurchase_members,
            args.batch_size,
            property_fields=["position"],
        )

        # Pairwise co-purchase edges and root associations share structure; filter fields
        pair_edges = [edge for edge in copurchase_edges if "target_asin" in edge]
        if pair_edges:
            merge_relationships(
                connector,
                "BOUGHT_TOGETHER",
                "Product",
                "source_asin",
                "Product",
                "target_asin",
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
                "Product",
                "asin",
                root_edges,
                args.batch_size,
                property_fields=[],
            )

        if variant_edges:
            merge_relationships(
                connector,
                "IS_VARIANT_OF",
                "Product",
                "child_asin",
                "Product",
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

