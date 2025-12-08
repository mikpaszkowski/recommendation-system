"""
Aspect sentiment triplet extraction powered by Hugging Face Transformers.

Reads review JSONL (same schema as `sample_ingest.py` expects), computes
`review_id` identically to the ingestion script, extracts
<aspect, opinion, sentiment> triplets, normalizes aspect surface forms, and
writes JSONL ready for Neo4j ingest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pandas as pd
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline


LOGGER = logging.getLogger("kg.aspect_pipeline")

DEFAULT_MODEL = "google/flan-t5-base"
DEFAULT_MAX_NEW_TOKENS = 128
DEFAULT_BATCH_SIZE = 8
SUPPORTED_SENTIMENTS = {"positive", "negative", "neutral"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract aspect-opinion-sentiment triplets from reviews with Hugging Face models."
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        required=True,
        help="Path to reviews JSONL (fields: user_id, asin, timestamp, title, text).",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("analysis_output/aspect_triplets.jsonl"),
        help="Destination JSONL with extracted triplets.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100_000,
        help="Maximum number of reviews to process.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=25_000,
        help="Chunk size for streaming JSONL via pandas.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Batch size for model inference.",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=DEFAULT_MODEL,
        help="Hugging Face model for text2text generation.",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=DEFAULT_MAX_NEW_TOKENS,
        help="Generation cap per review.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Device for inference (e.g., 'cpu', 'cuda:0').",
    )
    parser.add_argument(
        "--gazetteer-path",
        type=Path,
        default=None,
        help="Optional newline-separated list of canonical aspect names for normalization.",
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


def _slugify(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text)
    slug = "_".join(cleaned.lower().split())
    return slug or "unknown"


def _load_gazetteer(path: Optional[Path]) -> List[str]:
    if not path:
        return []
    if not path.exists():
        LOGGER.warning("Gazetteer path %s not found; continuing without it.", path)
        return []
    terms = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    return sorted(set(terms))


class AspectNormalizer:
    """Normalizes extracted aspect surface forms using a spaCy EntityRuler."""

    def __init__(self, gazetteer: Iterable[str]):
        import spacy

        self.nlp = spacy.blank("en")
        self.ruler = self.nlp.add_pipe("entity_ruler")
        patterns = [{"label": "ASPECT", "pattern": term} for term in gazetteer]
        if patterns:
            self.ruler.add_patterns(patterns)

    def normalize(self, text: str) -> Tuple[str, str]:
        """Return (canonical_name, surface_form)."""
        surface = text.strip()
        doc = self.nlp(surface)
        if doc.ents:
            return doc.ents[0].text.lower(), surface
        return _slugify(surface), surface


@dataclass
class Triplet:
    review_id: str
    aspect: str
    opinion: str
    sentiment: str
    surface_form: str
    confidence: float
    model_version: str

    def to_record(self) -> Dict:
        return {
            "review_id": self.review_id,
            "aspect": self.aspect,
            "surface_form": self.surface_form,
            "opinion": self.opinion,
            "sentiment": self.sentiment,
            "confidence": self.confidence,
            "model_version": self.model_version,
        }


class AspectSentimentTripletExtractor:
    """Wrapper around a text2text model that emits JSON triplets."""

    def __init__(
        self,
        model_name: str,
        device: Optional[str],
        max_new_tokens: int,
        batch_size: int,
    ):
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self.pipeline = pipeline(
            "text2text-generation",
            model=model,
            tokenizer=tokenizer,
            device=device,
        )
        self.max_new_tokens = max_new_tokens
        self.batch_size = batch_size
        self.model_name = model_name

    def _build_prompt(self, text: str) -> str:
        return (
            "Extract aspect-opinion-sentiment triplets from this review. "
            "Return a JSON list of objects with keys aspect, opinion, sentiment "
            "(sentiment must be one of Positive, Negative, Neutral). "
            f"Review: {text}"
        )

    def extract_batch(
        self, rows: Sequence[Dict], normalizer: AspectNormalizer
    ) -> List[Triplet]:
        prompts = [self._build_prompt(row["text"]) for row in rows]
        outputs = self.pipeline(
            prompts,
            batch_size=self.batch_size,
            max_new_tokens=self.max_new_tokens,
            truncation=True,
        )
        triplets: List[Triplet] = []
        for row, output in zip(rows, outputs):
            generated = output["generated_text"]
            for parsed in _safe_parse_triplets(generated):
                sentiment = parsed.get("sentiment", "").lower()
                sentiment = sentiment if sentiment in SUPPORTED_SENTIMENTS else "neutral"
                canonical_aspect, surface = normalizer.normalize(parsed.get("aspect", ""))
                triplets.append(
                    Triplet(
                        review_id=row["review_id"],
                        aspect=canonical_aspect,
                        surface_form=surface,
                        opinion=parsed.get("opinion", "").strip(),
                        sentiment=sentiment.title(),
                        confidence=float(parsed.get("confidence", 1.0)),
                        model_version=self.model_name,
                    )
                )
        return triplets


def _safe_parse_triplets(text: str) -> List[Dict]:
    cleaned = text.strip()
    # Remove potential code fences
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict)]
    except json.JSONDecodeError:
        LOGGER.debug("Failed to parse generated text as JSON: %s", cleaned)
    return []


def _batched(items: Sequence[Dict], size: int) -> Iterator[List[Dict]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _prepare_reviews(chunk: pd.DataFrame) -> pd.DataFrame:
    df = chunk.copy()
    df["event_time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["review_id"] = df.apply(_hash_review_id, axis=1)
    df = df[df["text"].notna() & df["text"].str.len().gt(0)]
    return df


def run_pipeline(args: argparse.Namespace) -> None:
    gazetteer = _load_gazetteer(args.gazetteer_path)
    normalizer = AspectNormalizer(gazetteer)
    extractor = AspectSentimentTripletExtractor(
        model_name=args.model_name,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        batch_size=args.batch_size,
    )

    args.output_path.parent.mkdir(parents=True, exist_ok=True)

    processed_reviews = 0
    written_triplets = 0

    with args.output_path.open("w") as sink:
        for chunk in pd.read_json(
            args.input_path,
            lines=True,
            chunksize=args.chunk_size,
            dtype=False,
        ):
            if processed_reviews >= args.limit:
                break
            prepared = _prepare_reviews(chunk)
            remaining = args.limit - processed_reviews
            prepared = prepared.head(remaining)
            rows = prepared[
                ["review_id", "text", "asin", "user_id", "title", "parent_asin", "timestamp", "event_time"]
            ].to_dict(orient="records")
            for batch in _batched(rows, args.batch_size):
                triplets = extractor.extract_batch(batch, normalizer)
                for triplet in triplets:
                    sink.write(json.dumps(triplet.to_record()) + "\n")
                written_triplets += len(triplets)
                processed_reviews += len(batch)
                if processed_reviews >= args.limit:
                    break

    LOGGER.info(
        "Extraction complete. Reviews processed: %d | Triplets written: %d | Model: %s",
        processed_reviews,
        written_triplets,
        args.model_name,
    )


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    run_pipeline(args)


if __name__ == "__main__":
    main()
