"""
Review identity, ranking and bounded per-product selection (FR-011, FR-012, K-11, K-12, G-6).

    review_id = md5(f"{user_id}-{asin}-{timestamp}").hexdigest()   (v1 formula, real timestamp)
    rank key  = (helpful_vote DESC, verified_purchase DESC, timestamp DESC, review_id ASC)

Per `parent_asin` at most `cap` reviews are kept (best first). Lines with the same review_id collapse
to one: the better rank key wins, then the lower byte offset. `TopKSelector` does this in bounded
memory while streaming; `select_top_reviews_reference` is the obvious in-memory definition the
selector is tested against (AC-005).

Counting note: a duplicate is detected only while its earlier copy is still inside the product's
top-`cap` buffer. A line whose review_id matches a copy that was already evicted is counted as
`beyond_cap`; the kept list is identical to the reference either way.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import AbstractSet, Any, Dict, Iterable, Iterator, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

DEFAULT_REVIEW_CAP: int = 20
DEFAULT_EMBED_TOP_N: int = 5
SPLIT_USER_COLUMN: str = "user_id"
SPLIT_PRODUCT_COLUMN: str = "parent_asin"

Pair = Tuple[str, str]  # (user_id, parent_asin)


class ReviewCandidate(NamedTuple):
    """Pass-1 view of one review line; `user_id` is carried so the selected-pair set can be built after selection."""

    helpful_vote: int
    verified: bool
    timestamp: int
    review_id: str
    offset: int        # byte offset of the line in Electronics.jsonl
    has_text: bool     # title or text non-blank after stripping
    user_id: str


class SelectedReview(NamedTuple):
    """Selection outcome for one kept review, keyed by byte offset for pass 2."""

    parent_asin: str
    review_id: str
    user_id: str
    cap_rank: int
    embed_rank: Optional[int]


def make_review_id(user_id: str, asin: str, timestamp: int) -> str:
    """md5(f"{user_id}-{asin}-{timestamp}").hexdigest() (v1 formula, real timestamp)."""
    return hashlib.md5(f"{user_id}-{asin}-{timestamp}".encode("utf-8")).hexdigest()


def rank_key(c: ReviewCandidate) -> Tuple[int, int, int, str]:
    """Ascending sort = best first: (-helpful_vote, -int(verified), -timestamp, review_id)."""
    return (-c.helpful_vote, -int(c.verified), -c.timestamp, c.review_id)


def int_field(value: Any) -> int:
    """Integral int/float (not bool) as int; anything else (missing, bool, text, non-finite) -> 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return 0


def _id_field(value: Any) -> Optional[str]:
    """A non-blank string ID, else None."""
    return value if isinstance(value, str) and value.strip() else None


def _visible_text(value: Any) -> bool:
    """A string that stays non-blank after the CSV sanitiser's NUL / U+001F -> space rule (FR-014)."""
    return isinstance(value, str) and bool(value.replace("\u0000", " ").replace("\u001f", " ").strip())


def has_review_text(title: Any, text: Any) -> bool:
    """True if title or text is a string that is non-blank after stripping (and after NUL / U+001F sanitising)."""
    return _visible_text(title) or _visible_text(text)


def candidate_from_record(raw: Mapping[str, Any], offset: int, counters: "Counter[str]") -> Optional[Tuple[str, ReviewCandidate]]:
    """
    (parent_asin, candidate) for one parsed review record, or None (counted as `missing_ids`) when
    user_id, parent_asin or asin is missing or blank. Missing helpful_vote -> 0, missing
    verified_purchase -> False, missing timestamp -> 0. Catalogue and split checks are the caller's.
    """
    user_id = _id_field(raw.get("user_id"))
    parent_asin = _id_field(raw.get("parent_asin"))
    asin = _id_field(raw.get("asin"))
    if user_id is None or parent_asin is None or asin is None:
        counters["missing_ids"] += 1
        return None
    timestamp = int_field(raw.get("timestamp"))
    candidate = ReviewCandidate(
        helpful_vote=int_field(raw.get("helpful_vote")),
        verified=raw.get("verified_purchase") is True,
        timestamp=timestamp,
        review_id=make_review_id(user_id, asin, timestamp),
        offset=offset,
        has_text=has_review_text(raw.get("title"), raw.get("text")),
        user_id=user_id,
    )
    return parent_asin, candidate


_Entry = Tuple[Tuple[int, int, int, str], int, ReviewCandidate]


class TopKSelector:
    """Bounded per-product selection with review_id de-duplication (better rank_key, then lower offset)."""

    def __init__(self, cap: int = DEFAULT_REVIEW_CAP) -> None:
        """Creates an empty selector keeping at most `cap` candidates per product."""
        if cap < 1:
            raise ValueError(f"review cap must be >= 1, got {cap}")
        self.cap = cap
        self._buffers: Dict[str, List[_Entry]] = {}
        self._ids: Dict[str, Dict[str, _Entry]] = {}
        self._duplicates = 0
        self._beyond_cap = 0
        self._offered = 0

    def offer(self, parent_asin: str, cand: ReviewCandidate) -> None:
        """Offers one candidate; collapses same-review_id copies in the buffer and evicts the worst beyond `cap`."""
        self._offered += 1
        entry: _Entry = (rank_key(cand), cand.offset, cand)
        buffer = self._buffers.get(parent_asin)
        if buffer is None:
            self._buffers[parent_asin] = [entry]
            self._ids[parent_asin] = {cand.review_id: entry}
            return
        ids = self._ids[parent_asin]
        existing = ids.get(cand.review_id)
        if existing is not None:
            self._duplicates += 1
            if entry[:2] < existing[:2]:
                buffer.remove(existing)
                bisect.insort(buffer, entry, key=lambda e: e[:2])
                ids[cand.review_id] = entry
            return
        if len(buffer) >= self.cap and entry[:2] >= buffer[-1][:2]:
            self._beyond_cap += 1
            return
        bisect.insort(buffer, entry, key=lambda e: e[:2])
        ids[cand.review_id] = entry
        if len(buffer) > self.cap:
            evicted = buffer.pop()
            del ids[evicted[2].review_id]
            self._beyond_cap += 1

    def ranked(self) -> Dict[str, List[ReviewCandidate]]:
        """Per product, best first, length <= cap."""
        return {asin: [entry[2] for entry in buffer] for asin, buffer in self._buffers.items()}

    @property
    def duplicate_count(self) -> int:
        """Number of lines collapsed into an existing candidate with the same review_id."""
        return self._duplicates

    @property
    def beyond_cap_count(self) -> int:
        """Number of lines rejected or evicted by the cap."""
        return self._beyond_cap

    @property
    def offered_count(self) -> int:
        """Number of offer() calls (for the balance check: offered = kept + duplicate + beyond_cap)."""
        return self._offered


def select_top_reviews_reference(cands: Iterable[ReviewCandidate], cap: int) -> List[ReviewCandidate]:
    """Reference: dedupe by review_id (best rank_key, then lowest offset), sort by rank_key, take cap."""
    best: Dict[str, ReviewCandidate] = {}
    for cand in cands:
        current = best.get(cand.review_id)
        if current is None or (rank_key(cand), cand.offset) < (rank_key(current), current.offset):
            best[cand.review_id] = cand
    return sorted(best.values(), key=lambda c: (rank_key(c), c.offset))[:cap]


def assign_embed_ranks(ranked: Sequence[ReviewCandidate], top_n: int = DEFAULT_EMBED_TOP_N) -> List[Optional[int]]:
    """1..top_n for the first top_n candidates with has_text, else None."""
    ranks: List[Optional[int]] = []
    next_rank = 1
    for cand in ranked:
        if cand.has_text and next_rank <= top_n:
            ranks.append(next_rank)
            next_rank += 1
        else:
            ranks.append(None)
    return ranks


def build_selection(ranked: Mapping[str, Sequence[ReviewCandidate]], top_n: int = DEFAULT_EMBED_TOP_N) -> Dict[int, SelectedReview]:
    """Byte offset -> SelectedReview with cap_rank 1..n (rank-key order) and embed_rank, for every kept review."""
    selection: Dict[int, SelectedReview] = {}
    for parent_asin, cands in ranked.items():
        for cap_rank, (cand, embed_rank) in enumerate(zip(cands, assign_embed_ranks(cands, top_n)), start=1):
            selection[cand.offset] = SelectedReview(
                parent_asin=parent_asin, review_id=cand.review_id, user_id=cand.user_id,
                cap_rank=cap_rank, embed_rank=embed_rank,
            )
    return selection


def iter_split_pairs(csv_path: Path) -> Iterator[Pair]:
    """Streams (user_id, parent_asin) from one official split CSV (header user_id,parent_asin,rating,timestamp,history)."""
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None or SPLIT_USER_COLUMN not in header or SPLIT_PRODUCT_COLUMN not in header:
            raise ValueError(f"{csv_path}: header must contain {SPLIT_USER_COLUMN} and {SPLIT_PRODUCT_COLUMN}, got {header}")
        user_idx = header.index(SPLIT_USER_COLUMN)
        product_idx = header.index(SPLIT_PRODUCT_COLUMN)
        for row in reader:
            if len(row) > max(user_idx, product_idx):
                yield row[user_idx], row[product_idx]


def load_pair_set(csv_paths: Sequence[Path]) -> Set[Pair]:
    """Union of (user_id, parent_asin) over the given split CSVs (valid ∪ test for the exclusion rule)."""
    pairs: Set[Pair] = set()
    for path in csv_paths:
        pairs.update(iter_split_pairs(path))
    return pairs


def mark_train_pairs(train_csv: Path, selected_pairs: AbstractSet[Pair]) -> Set[Pair]:
    """Streams the train CSV once and returns the selected pairs that occur in it (in_train_split = membership)."""
    return {pair for pair in iter_split_pairs(train_csv) if pair in selected_pairs}


def review_node_values(raw: Mapping[str, Any], selected: SelectedReview, in_train_split: bool) -> List[Any]:
    """Values of one `nodes_review.csv` row in header order (§5.2): review_id, review_title, review_body, rating,
    verified, timestamp, helpful_vote, asin, in_train_split, cap_rank, embed_rank."""
    rating = raw.get("rating")
    rating_value: Optional[float] = None
    if isinstance(rating, (int, float)) and not isinstance(rating, bool) and math.isfinite(float(rating)):
        rating_value = float(rating)
    return [
        selected.review_id,
        raw.get("title") if isinstance(raw.get("title"), str) else None,
        raw.get("text") if isinstance(raw.get("text"), str) else None,
        rating_value,
        raw.get("verified_purchase") is True,
        int_field(raw.get("timestamp")),
        int_field(raw.get("helpful_vote")),
        raw.get("asin"),
        bool(in_train_split),
        selected.cap_rank,
        selected.embed_rank,
    ]
