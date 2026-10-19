"""
neo4j-admin import CSV encoding (FR-014, §5.2).

Format: UTF-8 without BOM, comma delimiter, `"` quote with doubled-quote escaping
(`csv.QUOTE_MINIMAL`, `lineterminator="\\n"`), arrays joined with U+001F. Text rules applied to
every string: U+0000 and U+001F -> space; CRLF and lone CR -> LF; blank after stripping -> empty
field (null on import with `--ignore-empty-strings=true`); empty array items dropped. Every
replacement is counted under the `models.SanitizedCounts` keys. Booleans are `true`/`false`,
floats `repr()`. Rows are sorted by every column (first ID column first) so identical inputs give
byte-identical files.

`ImportCsvWriter(path=None)` is the dry-run writer: it encodes and counts but writes nothing.
`presorted_key` mode streams rows without buffering and asserts a strictly increasing key; it is
used for the review-derived files (see the transform module for the order).
"""
from __future__ import annotations

import csv
import hashlib
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from src.knowledge_graph.graph_v2.models import FileStats

logger = logging.getLogger(__name__)

ARRAY_DELIMITER = "\u001f"
ATTRIBUTE_ID_SEPARATOR = "\u0000"
SANITIZE_KEYS: Tuple[str, ...] = ("nul", "unit_separator", "carriage_return", "blank_to_null", "empty_array_items")

HEADERS: Dict[str, List[str]] = {
    "nodes_product.csv": [
        "parent_asin:ID(ParentProduct)", "title", "price:double", "avg_rating:double", "review_count:long",
        "description", "features:string[]", "details_json", "details_text", "category_path:string[]", "store",
    ],
    "nodes_review.csv": [
        "review_id:ID(Review)", "review_title", "review_body", "rating:double", "verified:boolean",
        "timestamp:long", "helpful_vote:long", "asin", "in_train_split:boolean", "cap_rank:int", "embed_rank:int",
    ],
    "nodes_user.csv": ["user_id:ID(User)"],
    "nodes_brand.csv": ["name:ID(Brand)"],
    "nodes_category.csv": ["name:ID(Category)"],
    "nodes_attribute.csv": [":ID(Attribute)", "attribute_name", "attribute_value"],
    "nodes_taxon.csv": [
        "taxon_id:ID(Taxon)", "name", "path:string[]", "depth:int", "product_count:long", "direct_product_count:long",
    ],
    "rels_has_brand.csv": [":START_ID(ParentProduct)", ":END_ID(Brand)"],
    "rels_belongs_to_category.csv": [":START_ID(ParentProduct)", ":END_ID(Category)"],
    "rels_has_attribute.csv": [":START_ID(ParentProduct)", ":END_ID(Attribute)"],
    "rels_in_taxon.csv": [":START_ID(ParentProduct)", ":END_ID(Taxon)"],
    "rels_broader.csv": [":START_ID(Taxon)", ":END_ID(Taxon)"],
    "rels_about_product.csv": [":START_ID(Review)", ":END_ID(ParentProduct)"],
    "rels_wrote.csv": [":START_ID(User)", ":END_ID(Review)"],
}


_DIALECT_KWARGS: Dict[str, Any] = {
    "delimiter": ",",
    "quotechar": '"',
    "doublequote": True,
    "quoting": csv.QUOTE_MINIMAL,
    "lineterminator": "\n",
}
_HASH_CHUNK = 1024 * 1024


class CsvOrderError(ValueError):
    """A presorted writer received a key that is not strictly greater than the previous one."""


def _clean(value: str, counters: "Counter[str]") -> str:
    """NUL and U+001F -> space, CRLF / lone CR -> LF, counting every replacement."""
    if "\u0000" in value:
        counters["nul"] += value.count("\u0000")
        value = value.replace("\u0000", " ")
    if ARRAY_DELIMITER in value:
        counters["unit_separator"] += value.count(ARRAY_DELIMITER)
        value = value.replace(ARRAY_DELIMITER, " ")
    if "\r" in value:
        counters["carriage_return"] += value.count("\r")
        value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value


def sanitize_text(value: Any, counters: "Counter[str]") -> Optional[str]:
    """Applies the FR-014 text rules to one string; returns None (empty field) when blank after stripping."""
    if value is None:
        return None
    cleaned = _clean(value if isinstance(value, str) else str(value), counters)
    if not cleaned.strip():
        counters["blank_to_null"] += 1
        return None
    return cleaned


def encode_array(items: Sequence[str], counters: "Counter[str]") -> Optional[str]:
    """Sanitises every item, drops empty ones (counted), joins with ARRAY_DELIMITER; None if nothing remains."""
    kept: List[str] = []
    for item in items:
        cleaned = _clean(item if isinstance(item, str) else str(item), counters) if item is not None else ""
        if cleaned.strip():
            kept.append(cleaned)
        else:
            counters["empty_array_items"] += 1
    return ARRAY_DELIMITER.join(kept) if kept else None


def format_value(value: Any, counters: "Counter[str]") -> str:
    """One CSV field: None -> "", bool -> "true"/"false", int -> str, float -> repr, str -> sanitize_text, tuple/list -> encode_array."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float cannot be imported: {value!r}")
        return repr(value)
    if isinstance(value, (list, tuple)):
        return encode_array(value, counters) or ""
    return sanitize_text(value, counters) or ""


def decode_array(field: str) -> List[str]:
    """Inverse of encode_array for a read-back field ("" -> [])."""
    return field.split(ARRAY_DELIMITER) if field else []


def attribute_node_id(name: str, value: str) -> str:
    """`sha1(name + "\\u0000" + value)` hex: the import ID of an Attribute node (not stored as a property)."""
    return hashlib.sha1(f"{name}{ATTRIBUTE_ID_SEPARATOR}{value}".encode("utf-8")).hexdigest()


def read_import_csv(path: Path) -> Iterator[Dict[str, str]]:
    """Reads an import CSV back with the same dialect, yielding header -> raw field (H-14 fidelity, AC-014 round trip)."""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, **{k: v for k, v in _DIALECT_KWARGS.items() if k != "lineterminator"})
        for row in reader:
            yield dict(row)


def file_stats(path: Path, rows: int) -> FileStats:
    """Rows, byte size and SHA-256 of a written file."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return FileStats(rows=rows, bytes=size, sha256=digest.hexdigest())


class ImportCsvWriter:
    """Buffers rows, sorts them (FR-014), writes CSV, returns FileStats."""

    def __init__(
        self,
        path: Optional[Path],
        header: Sequence[str],
        counters: Optional["Counter[str]"] = None,
        presorted_key: bool = False,
    ) -> None:
        """
        `path=None` encodes and counts without writing (dry run). `counters` receives the
        sanitisation counts. With `presorted_key=True`, rows are written as they arrive and
        `add(values, key=...)` must receive strictly increasing keys.
        """
        self.path = Path(path) if path is not None else None
        self.header = list(header)
        self.counters: "Counter[str]" = counters if counters is not None else Counter()
        self.presorted_key = presorted_key
        self._rows: List[Tuple[str, ...]] = []
        self._count = 0
        self._last_key: Optional[Any] = None
        self._closed = False
        self._handle = None
        self._writer = None
        if self.path is not None and presorted_key:
            self._open()

    def _open(self) -> None:
        """Opens the output file and writes the header."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "w", encoding="utf-8", newline="")
        self._writer = csv.writer(self._handle, **_DIALECT_KWARGS)
        self._writer.writerow(self.header)

    def add(self, values: Sequence[Any], key: Optional[Any] = None) -> None:
        """Encodes one row (len(values) == len(header)); `key` is required in presorted mode."""
        if self._closed:
            raise ValueError(f"writer for {self.path} is closed")
        if len(values) != len(self.header):
            raise ValueError(f"row has {len(values)} values, header {self.header} has {len(self.header)}")
        row = tuple(format_value(value, self.counters) for value in values)
        self._count += 1
        if not self.presorted_key:
            self._rows.append(row)
            return
        if key is None:
            raise CsvOrderError("presorted writer requires a key for every row")
        if self._last_key is not None and not key > self._last_key:
            raise CsvOrderError(f"key {key!r} is not greater than the previous key {self._last_key!r}")
        self._last_key = key
        if self._writer is not None:
            self._writer.writerow(row)

    def close(self) -> FileStats:
        """Sorts (unless presorted), writes header and rows, and returns rows, bytes and sha256 (None in a dry run)."""
        if self._closed:
            raise ValueError(f"writer for {self.path} is already closed")
        self._closed = True
        if self.path is None:
            self._rows = []
            return FileStats(rows=self._count, bytes=0, sha256=None)
        if not self.presorted_key:
            self._open()
            self._rows.sort()
            self._writer.writerows(self._rows)
            self._rows = []
        self._handle.close()
        return file_stats(self.path, self._count)

    def __enter__(self) -> "ImportCsvWriter":
        """Context-manager entry."""
        return self

    def __exit__(self, *exc: Any) -> None:
        """Closes the underlying file without writing buffered rows when an exception is propagating."""
        if exc and exc[0] is not None:
            self._closed = True
            if self._handle is not None and not self._handle.closed:
                self._handle.close()
            return
        if not self._closed:
            self.close()
