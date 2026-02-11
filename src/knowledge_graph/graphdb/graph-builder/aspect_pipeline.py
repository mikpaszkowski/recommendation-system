"""
Aspect sentiment triplet extraction powered by PyABSA (ASTE).

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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pandas as pd
from pyabsa import AspectSentimentTripletExtraction as ASTE


LOGGER = logging.getLogger("kg.aspect_pipeline")

DEFAULT_MODEL = "english"
DEFAULT_BATCH_SIZE = 8
SUPPORTED_SENTIMENTS = {"positive", "negative", "neutral"}
MAX_TEXT_CHARS = 512
MAX_TEXT_TOKENS = 200


def _patch_pyabsa_length_guard() -> None:
    """Patch PyABSA ASTE Instance to avoid fatal length errors."""
    try:
        import pyabsa.tasks.AspectSentimentTripletExtraction.dataset_utils.aste_utils as aste_utils
    except Exception as err:
        LOGGER.warning("Unable to patch PyABSA ASTE utils: %s", err)
        return

    if getattr(aste_utils.Instance, "_kg_length_safe", False):
        return

    orig_init = aste_utils.Instance.__init__

    def _trim_sentence_pack(sentence_pack, tokenizer, max_seq_len: int):
        tokens = (sentence_pack.get("sentence") or "").split()
        max_slots = max(max_seq_len - 2, 1)
        trimmed_tokens = tokens[:max_slots]
        # shrink until tokenizer would not overflow max_seq_len without truncation
        while trimmed_tokens:
            encoded = tokenizer.encode(
                " ".join(trimmed_tokens),
                padding="do_not_pad",
                truncation=False,
                add_special_tokens=True,
            )
            if len(encoded) <= max_seq_len:
                break
            trimmed_tokens.pop()

        if not trimmed_tokens:
            return None

        updated = dict(sentence_pack)
        updated["sentence"] = " ".join(trimmed_tokens)
        for key in ("postag", "head", "deprel"):
            if key in updated and isinstance(updated[key], list):
                updated[key] = updated[key][: len(trimmed_tokens)]
        return updated

    def safe_init(
        self,
        tokenizer,
        sentence_pack,
        post_vocab,
        deprel_vocab,
        postag_vocab,
        synpost_vocab,
        config,
    ):
        try:
            return orig_init(
                self,
                tokenizer,
                sentence_pack,
                post_vocab,
                deprel_vocab,
                postag_vocab,
                synpost_vocab,
                config,
            )
        except AssertionError as err:
            if "length error" not in str(err):
                raise

            patched_pack = _trim_sentence_pack(
                sentence_pack, tokenizer, config.max_seq_len
            )
            if patched_pack:
                try:
                    return orig_init(
                        self,
                        tokenizer,
                        patched_pack,
                        post_vocab,
                        deprel_vocab,
                        postag_vocab,
                        synpost_vocab,
                        config,
                    )
                except AssertionError:
                    LOGGER.debug("Patched ASTE Instance still hit length error; using empty stub.")

            # Final fallback: initialize an empty instance so the caller can skip it.
            import torch

            self.id = sentence_pack.get("id")
            self.sentence = sentence_pack.get("sentence", "")
            self.tokens = []
            self.postag = []
            self.head = []
            self.deprel = []
            self.sen_length = 0
            self.token_range = []
            self.text_ids = tokenizer.encode(
                "",
                padding="do_not_pad",
                max_length=2,
                truncation=True,
                add_special_tokens=True,
            )
            self.length = len(self.text_ids)
            self.bert_tokens_padding = torch.zeros(config.max_seq_len).long()
            self.aspect_tags = torch.full(
                (config.max_seq_len,), -1, dtype=torch.long
            )
            self.opinion_tags = torch.full(
                (config.max_seq_len,), -1, dtype=torch.long
            )
            self.tags = torch.full(
                (config.max_seq_len, config.max_seq_len), -1, dtype=torch.long
            )
            self.tags_symmetry = torch.full(
                (config.max_seq_len, config.max_seq_len), -1, dtype=torch.long
            )
            self.mask = torch.zeros(config.max_seq_len)
            self.word_pair_position = torch.zeros(
                config.max_seq_len, config.max_seq_len
            ).long()
            self.word_pair_deprel = torch.zeros(
                config.max_seq_len, config.max_seq_len
            ).long()
            self.word_pair_pos = torch.zeros(
                config.max_seq_len, config.max_seq_len
            ).long()
            self.word_pair_synpost = torch.zeros(
                config.max_seq_len, config.max_seq_len
            ).long()
            LOGGER.warning(
                "PyABSA ASTE length mismatch; returning empty instance for id=%s",
                self.id,
            )
            return

    aste_utils.Instance.__init__ = safe_init
    aste_utils.Instance._kg_length_safe = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract aspect-opinion-sentiment triplets from reviews with PyABSA ASTE."
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
        help="PyABSA checkpoint (e.g., english, multilingual, or path to PyABSA ASTE model).",
    )
    parser.add_argument(
        "--debug-first-n",
        type=int,
        default=0,
        help="If >0, log raw model outputs for the first N reviews to inspect parsing issues.",
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


def _sanitize_text(raw_text: str) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(raw_text, str):
        return None, "non-string text"

    normalized = " ".join(raw_text.split())
    if not normalized:
        return None, "empty after strip"

    capped_chars = normalized[:MAX_TEXT_CHARS]
    tokens = capped_chars.split()
    if not tokens:
        return None, "empty after cap"

    if len(tokens) > MAX_TEXT_TOKENS:
        capped_tokens = tokens[:MAX_TEXT_TOKENS]
        capped_chars = " ".join(capped_tokens)

    if not capped_chars.strip():
        return None, "empty after token cap"

    return capped_chars, None


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
        patterns = [{"label": "ASPECT", "pattern": term} for term in gazetteer]
        if patterns:
            # Only add the entity ruler when we actually have patterns to avoid spaCy W036 warnings.
            self.ruler = self.nlp.add_pipe("entity_ruler")
            self.ruler.add_patterns(patterns)
        else:
            self.ruler = None

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
    """Wrapper around PyABSA ASTE extractor."""

    def __init__(
        self,
        model_name: str,
        device: Optional[str],
        batch_size: int,
    ):
        _patch_pyabsa_length_guard()
        # PyABSA auto-downloads when given alias like "english" or a path
        # device handling: PyABSA uses "cuda" or "cpu"
        target_device = device if device else "cpu"
        if target_device.startswith("cuda"):
            target_device = "cuda"
        self.predictor = ASTE.AspectSentimentTripletExtractor(
            checkpoint=model_name, auto_device=target_device
        )
        # Guard against length-related crashes in older checkpoints/tokenizers
        try:
            self.predictor.config.max_seq_len = min(
                getattr(self.predictor.config, "max_seq_len", 256) or 256, 256
            )
            self.predictor.config.overlength_threshold = 512
        except Exception:
            pass
        self.batch_size = batch_size
        self.model_name = model_name

    def extract_batch(
        self, rows: Sequence[Dict], normalizer: AspectNormalizer, debug_limit: int = 0
    ) -> List[Triplet]:
        filtered_rows: List[Dict] = []
        filtered_texts: List[str] = []
        skipped: List[Tuple[str, str]] = []
        for row in rows:
            raw_text = row.get("text", "")
            text, reason = _sanitize_text(raw_text)
            if text:
                filtered_rows.append(row)
                filtered_texts.append(text)
            else:
                review_id = row.get("review_id") or row.get("asin") or "unknown"
                skipped.append((str(review_id), reason or "filtered"))

        if not filtered_rows:
            if skipped:
                LOGGER.info(
                    "Skipped %d texts before predict; first reason: %s",
                    len(skipped),
                    skipped[0][1],
                )
            return []

        if skipped:
            sampled = ", ".join(f"{rid}: {why}" for rid, why in skipped[:3])
            LOGGER.info(
                "Skipped %d texts before predict (sample: %s)",
                len(skipped),
                sampled,
            )

        def _pull_triplets(raw_output) -> List:
            if isinstance(raw_output, dict):
                return raw_output.get("Triplets") or raw_output.get("triplets") or []
            if isinstance(raw_output, list):
                return raw_output
            return []

        def _split_text(text: str) -> Optional[Tuple[str, str]]:
            parts = text.split()
            if len(parts) < 2:
                return None
            midpoint = len(parts) // 2
            left = " ".join(parts[:midpoint]).strip()
            right = " ".join(parts[midpoint:]).strip()
            if not left or not right:
                return None
            return left, right

        def _predict_single(text: str) -> Optional[Dict]:
            try:
                single = self.predictor.predict(
                    [text],
                    print_result=False,
                    eval_batch_size=1,
                    ignore_error=True,
                )
                return single[0] if isinstance(single, list) else single
            except Exception as err:
                LOGGER.warning("Predict failed for len=%d; attempting split. err=%s", len(text), err)
                halves = _split_text(text)
                if not halves:
                    return None
                try:
                    partial = self.predictor.predict(
                        list(halves),
                        print_result=False,
                        eval_batch_size=2,
                        ignore_error=True,
                    )
                    partial_outputs = partial if isinstance(partial, list) else [partial]
                    combined = []
                    for piece in partial_outputs:
                        combined.extend(_pull_triplets(piece))
                    return {"Triplets": combined}
                except Exception as split_err:
                    LOGGER.warning("Split predict failed; skipping text. err=%s", split_err)
                    return None

        def _predict_safely(texts: List[str]) -> List:
            try:
                batch_output = self.predictor.predict(
                    texts,
                    print_result=False,
                    eval_batch_size=self.batch_size,
                    ignore_error=True,
                )
                outputs = batch_output if isinstance(batch_output, list) else [batch_output]
            except Exception as err:
                LOGGER.warning("Batch predict failed (%s); falling back to per-item.", err)
                outputs = []
                for idx, t in enumerate(texts):
                    outputs.append(_predict_single(t))
            else:
                if len(outputs) != len(texts):
                    LOGGER.warning(
                        "Predict returned %d outputs for %d texts; filling mismatches.",
                        len(outputs),
                        len(texts),
                    )

            if len(outputs) < len(texts):
                outputs.extend([None] * (len(texts) - len(outputs)))
            elif len(outputs) > len(texts):
                outputs = outputs[: len(texts)]
            return outputs

        outputs = _predict_safely(filtered_texts)
        triplets: List[Triplet] = []
        for idx, (row, output) in enumerate(zip(filtered_rows, outputs)):
            if debug_limit and idx < debug_limit:
                LOGGER.warning("DEBUG sample #%d raw output: %s", idx, output)

            result_triplets = []
            if isinstance(output, dict):
                # PyABSA usually returns {"text": ..., "Triplets": [...]}
                result_triplets = output.get("Triplets") or output.get("triplets") or []
            elif isinstance(output, list):
                result_triplets = output

            for parsed in result_triplets:
                # parsed can be tuple/list or dict
                if isinstance(parsed, dict):
                    # handle both lowercase and PyABSA's capitalized keys
                    aspect_raw = (
                        parsed.get("aspect")
                        or parsed.get("Aspect")
                        or parsed.get("target")
                        or parsed.get("Target")
                        or ""
                    )
                    opinion_raw = parsed.get("opinion") or parsed.get("Opinion") or ""
                    sentiment_val = (
                        parsed.get("sentiment")
                        or parsed.get("Sentiment")
                        or parsed.get("Polarity")
                        or ""
                    )
                    sentiment = str(sentiment_val).lower()
                    confidence = float(parsed.get("confidence", 1.0))
                elif isinstance(parsed, (list, tuple)) and len(parsed) >= 3:
                    aspect_raw, opinion_raw, sentiment = parsed[:3]
                    confidence = 1.0
                else:
                    continue

                # drop empty aspect+opinion to avoid "unknown" spam
                if not (str(aspect_raw).strip() or str(opinion_raw).strip()):
                    continue

                if not aspect_raw and opinion_raw:
                    aspect_raw = opinion_raw

                sentiment = sentiment if sentiment in SUPPORTED_SENTIMENTS else "neutral"
                canonical_aspect, surface = normalizer.normalize(str(aspect_raw))
                triplets.append(
                    Triplet(
                        review_id=row["review_id"],
                        aspect=canonical_aspect,
                        surface_form=surface,
                        opinion=str(opinion_raw).strip(),
                        sentiment=sentiment.title(),
                        confidence=confidence,
                        model_version=self.model_name,
                    )
                )
        return triplets


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
                triplets = extractor.extract_batch(batch, normalizer, debug_limit=args.debug_first_n)
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

    if written_triplets == 0:
        LOGGER.warning(
            "No triplets produced. The chosen model may not be suitable for ASTE; "
            "try a more constrained model or smaller limit for debugging."
        )


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    run_pipeline(args)


if __name__ == "__main__":
    main()
