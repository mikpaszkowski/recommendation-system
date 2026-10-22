"""
Input verification, catalogue I/O, lineage assembly and lineage invariants (FR-003, FR-005, FR-015, §5.3).

Before any data is read, the raw JSONL files are checked against `SHA256SUMS` (looked up by file
basename), and the split CSVs and the uncompressed catalogue content are hashed. Any mismatch or
missing file raises `InputVerificationError` (exit 2, no bypass flag).

Before `lineage.json` is written two invariants are checked, or `LineageInvariantError` is raised:
    (1) per source, lines = sum(drop reasons) + kept;
    (2) every relationship endpoint exists in a node file (tracked by `IntegrityTracker`).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from pydantic import ValidationError

from src.knowledge_graph.graph_v2.models import (
    CatalogueInfo,
    ColumnSpec,
    Columns,
    LineageCounts,
    Lineage,
    LineageParameters,
    SourceFile,
    SplitFile,
    SplitsInfo,
)

logger = logging.getLogger(__name__)
_HASH_CHUNK = 8 * 1024 * 1024

SPLIT_NAMES: Tuple[str, ...] = ("train", "valid", "test")
SPLIT_FILE_TEMPLATE: str = "Electronics.{split}.csv"
META_DROP_REASONS: Tuple[str, ...] = ("json_errors", "not_in_catalogue", "duplicate_parent_asin")
META_KEPT_KEY: str = "products_written"
REVIEW_DROP_REASONS: Tuple[str, ...] = (
    "json_errors", "missing_ids", "not_in_catalogue", "product_missing", "valid_test_pair",
    "duplicate_review_id", "beyond_cap",
)
REVIEW_KEPT_KEY: str = "kept"
DUPLICATE_LIST_CAP: int = 200
INTEGRITY_ERROR_CAP: int = 50

META_COLUMNS_READ: Tuple[str, ...] = (
    "parent_asin", "title", "price", "average_rating", "rating_number", "description", "features", "details",
    "categories", "main_category", "store",
)
META_COLUMNS_DROPPED: Tuple[str, ...] = ("images", "videos", "bought_together", "subtitle", "author")
REVIEW_COLUMNS_READ: Tuple[str, ...] = (
    "user_id", "parent_asin", "asin", "timestamp", "helpful_vote", "verified_purchase", "rating", "title", "text",
)
REVIEW_COLUMNS_DROPPED: Tuple[str, ...] = ("images",)


class BuildPaths(NamedTuple):
    """Default artefact locations of one build flavour (full or pilot), relative to the repository root."""

    out_dir: Path            # transform --out-dir (CSVs go to <out_dir>/import)
    import_dir: Path
    report_dir: Path
    lineage: Path
    embedding_report: Path
    import_record: Path
    validation_report: Path


SHARED_INPUTS: Dict[str, Path] = {
    "meta": Path("datasets/raw/meta_Electronics.jsonl"),
    "reviews": Path("datasets/raw/Electronics.jsonl"),
    "sha256sums": Path("datasets/raw/SHA256SUMS"),
    "splits_dir": Path("datasets"),
    "catalogue": Path("graph_versions/v2/catalogue_asins.txt.gz"),
    "build_params": Path("graph_versions/v2/build_params.json"),
    "benchmark": Path("live_eval_dataset.json"),
}
FULL_PATHS = BuildPaths(
    out_dir=Path("datasets/graph_build/v2"), import_dir=Path("datasets/graph_build/v2/import"),
    report_dir=Path("datasets/graph_build/v2/reports"), lineage=Path("graph_versions/v2/lineage.json"),
    embedding_report=Path("graph_versions/v2/embedding_report.json"), import_record=Path("graph_versions/v2/import_run.json"),
    validation_report=Path("graph_versions/v2/validation_report.json"),
)
PILOT_PATHS = BuildPaths(
    out_dir=Path("datasets/graph_build/v2_pilot"), import_dir=Path("datasets/graph_build/v2_pilot/import"),
    report_dir=Path("datasets/graph_build/v2_pilot/reports"), lineage=Path("graph_versions/v2/pilot/lineage.json"),
    embedding_report=Path("graph_versions/v2/pilot/embedding_report.json"),
    import_record=Path("graph_versions/v2/pilot/import_run.json"),
    validation_report=Path("graph_versions/v2/pilot/validation_report.json"),
)


def build_paths(repo_root: Path, pilot: bool) -> BuildPaths:
    """Absolute default artefact paths for the pilot (sample mode) or the full build; shared by all graph v2 CLIs."""
    base = PILOT_PATHS if pilot else FULL_PATHS
    return BuildPaths(*(Path(repo_root) / path for path in base))


def shared_input(repo_root: Path, name: str) -> Path:
    """Absolute default path of an input shared by the pilot and the full build (SHARED_INPUTS key)."""
    return Path(repo_root) / SHARED_INPUTS[name]


class GraphBuildError(Exception):
    """Base class of every error that makes a graph v2 CLI exit 2."""


class InputVerificationError(GraphBuildError):
    """A source hash mismatches SHA256SUMS, or a required input (raw file, split CSV, catalogue) is missing."""


class LineageInvariantError(GraphBuildError):
    """A lineage invariant (source balance or referential integrity) does not hold."""


def sha256_file(path: Path) -> str:
    """Streaming SHA-256 hex digest; raises InputVerificationError if the file cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
                digest.update(chunk)
    except OSError as e:
        raise InputVerificationError(f"cannot read {path}: {e}") from e
    return digest.hexdigest()


def read_sha256sums(path: Path) -> Dict[str, str]:
    """Parses `<hex>  <name>` lines (sha256sum format) into name -> hex digest."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise InputVerificationError(f"cannot read {path}: {e}") from e
    sums: Dict[str, str] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise InputVerificationError(f"{path}:{line_no}: not a sha256sum line: {line!r}")
        sums[parts[1].strip().lstrip("*")] = parts[0].lower()
    return sums


def _verified_source(path: Path, sums: Mapping[str, str], sums_path: Path) -> SourceFile:
    """Hashes one raw file and compares it with its SHA256SUMS entry."""
    path = Path(path)
    if not path.is_file():
        raise InputVerificationError(f"raw input missing: {path}")
    expected = sums.get(path.name)
    if expected is None:
        raise InputVerificationError(f"{path.name} has no entry in {sums_path}")
    actual = sha256_file(path)
    if actual != expected:
        raise InputVerificationError(f"SHA-256 mismatch for {path}: expected {expected}, got {actual}")
    return SourceFile(path=str(path), sha256=actual, verified_against=str(sums_path))


def verify_raw_inputs(meta_path: Path, reviews_path: Path, sha256sums_path: Path) -> Tuple[SourceFile, SourceFile]:
    """FR-005: hashes both raw files and compares with SHA256SUMS by basename; line counts are filled in later."""
    sums = read_sha256sums(sha256sums_path)
    meta = _verified_source(meta_path, sums, sha256sums_path)
    reviews = _verified_source(reviews_path, sums, sha256sums_path)
    logger.info(f"[Lineage] Raw inputs verified against {sha256sums_path}")
    return meta, reviews


def split_paths(splits_dir: Path) -> Dict[str, Path]:
    """split name -> `<splits_dir>/Electronics.<split>.csv` for train, valid, test."""
    return {split: Path(splits_dir) / SPLIT_FILE_TEMPLATE.format(split=split) for split in SPLIT_NAMES}


def _count_data_rows(path: Path) -> int:
    """Data rows of a split CSV (lines minus the header)."""
    with open(path, "rb") as handle:
        lines = sum(1 for _ in handle)
    return max(lines - 1, 0)


def hash_splits(splits_dir: Path) -> SplitsInfo:
    """Hashes the three split CSVs and their canonical-JSON combination; raises InputVerificationError if one is missing."""
    files: Dict[str, SplitFile] = {}
    for split, path in split_paths(splits_dir).items():
        if not path.is_file():
            raise InputVerificationError(f"split file missing: {path}")
        files[split] = SplitFile(path=str(path), sha256=sha256_file(path), rows=_count_data_rows(path))
    canonical = json.dumps({k: v.sha256 for k, v in files.items()}, sort_keys=True, separators=(",", ":"))
    return SplitsInfo(
        train=files["train"], valid=files["valid"], test=files["test"],
        combined_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def encode_catalogue(asins: Iterable[str]) -> bytes:
    """Canonical uncompressed catalogue content: sorted ascending, one per line, each `\\n`-terminated (FR-003)."""
    return "".join(f"{asin}\n" for asin in sorted(asins)).encode("utf-8")


def write_catalogue(asins: Iterable[str], path: Path) -> str:
    """Writes the catalogue as gzip with mtime=0 and no file name (byte-reproducible); returns the content SHA-256."""
    content = encode_catalogue(asins)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(content)
    return hashlib.sha256(content).hexdigest()


def read_catalogue(path: Path) -> Tuple[List[str], str]:
    """Reads a `.gz` or plain catalogue; returns (sorted ASINs, SHA-256 of the uncompressed content).
    Raises InputVerificationError if missing, unsorted, duplicated or not `\\n`-terminated."""
    path = Path(path)
    if not path.is_file():
        raise InputVerificationError(f"catalogue missing: {path}")
    try:
        content = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    except (OSError, gzip.BadGzipFile, EOFError) as e:
        raise InputVerificationError(f"cannot read catalogue {path}: {e}") from e
    text = content.decode("utf-8")
    if text and not text.endswith("\n"):
        raise InputVerificationError(f"catalogue {path} is not newline-terminated")
    asins = text.split("\n")[:-1] if text else []
    if any(not asin for asin in asins):
        raise InputVerificationError(f"catalogue {path} contains an empty line")
    if asins != sorted(set(asins)):
        raise InputVerificationError(f"catalogue {path} is not sorted ascending without duplicates")
    return asins, hashlib.sha256(content).hexdigest()


def catalogue_info(path: Path, content_sha256: str, count: int, sampled_count: Optional[int]) -> CatalogueInfo:
    """The `sources.catalogue` section."""
    return CatalogueInfo(path=str(path), sha256_content=content_sha256, count=count, sampled_count=sampled_count)


def default_parameters(review_cap: int, embed_top_n: int, sample_mod: Optional[int]) -> LineageParameters:
    """The `parameters` section with the fixed rule strings of §5.3."""
    return LineageParameters(
        review_cap=review_cap,
        rank_key=["helpful_vote DESC", "verified_purchase DESC", "timestamp DESC", "review_id ASC"],
        duplicate_rule="same review_id: better rank_key, then lower byte offset",
        review_id="md5(f'{user_id}-{asin}-{timestamp}')",
        exclusion_rule="(user_id, parent_asin) in Electronics.valid.csv ∪ Electronics.test.csv",
        embed_top_n=embed_top_n,
        embed_rule=f"first {embed_top_n} non-blank reviews in cap_rank order",
        attribute_keys=["Material", "Color", "Style", "Size"],
        brand_rule="store if non-blank else details['Brand'] if non-blank; exact name",
        taxon_separator=" > ",
        array_delimiter="U+001F",
        text_normalization=["U+0000->space", "U+001F->space", "\\r\\n|\\r->\\n", "blank->null"],
        sample_mod=sample_mod,
    )


def default_columns() -> Columns:
    """The `columns` section (read and dropped source columns)."""
    return Columns(
        meta=ColumnSpec(read=list(META_COLUMNS_READ), dropped=list(META_COLUMNS_DROPPED)),
        reviews=ColumnSpec(read=list(REVIEW_COLUMNS_READ), dropped=list(REVIEW_COLUMNS_DROPPED)),
    )


def cap_list(items: Sequence[Any], cap: int = DUPLICATE_LIST_CAP) -> List[Any]:
    """First `cap` items (long duplicate lists are capped; full counts stay in `counts`)."""
    return list(items[:cap])


def check_source_balance(counts: LineageCounts) -> List[str]:
    """Invariant (1): one message per source whose `lines` differs from sum(drop reasons) + kept."""
    problems: List[str] = []
    for source, section, reasons, kept_key in (
        ("meta", counts.meta, META_DROP_REASONS, META_KEPT_KEY),
        ("reviews", counts.reviews, REVIEW_DROP_REASONS, REVIEW_KEPT_KEY),
    ):
        values = section.model_dump()
        total = sum(values[r] for r in reasons) + values[kept_key]
        if total != values["lines"]:
            detail = ", ".join(f"{r}={values[r]}" for r in reasons)
            problems.append(f"{source}: lines={values['lines']} but drops + {kept_key} = {total} ({detail}, {kept_key}={values[kept_key]})")
    return problems


class IntegrityTracker:
    """Collects node IDs per label and checks relationship endpoints against them (invariant 2)."""

    def __init__(self) -> None:
        """Creates empty ID sets."""
        self._ids: Dict[str, Set[str]] = defaultdict(set)
        self._errors: List[str] = []
        self._error_count = 0

    def add_node(self, label: str, node_id: str) -> None:
        """Registers one written node ID."""
        self._ids[label].add(node_id)

    def check_edge(self, rel_type: str, start_label: str, start_id: str, end_label: str, end_id: str) -> None:
        """Records an error (capped at INTEGRITY_ERROR_CAP messages, all counted) if an endpoint is unknown."""
        for label, node_id in ((start_label, start_id), (end_label, end_id)):
            if node_id not in self._ids.get(label, ()):
                self._error_count += 1
                if len(self._errors) < INTEGRITY_ERROR_CAP:
                    self._errors.append(f"{rel_type}: {label} {node_id!r} has no node row")

    @property
    def error_count(self) -> int:
        """Number of dangling endpoints seen."""
        return self._error_count

    @property
    def errors(self) -> List[str]:
        """Capped error messages."""
        return list(self._errors)

    def node_ids(self, label: str) -> Set[str]:
        """Registered IDs of one label."""
        return self._ids.get(label, set())


def assert_invariants(lineage: Lineage, integrity: IntegrityTracker) -> None:
    """Raises LineageInvariantError listing every failed invariant; returns None when both hold."""
    problems = check_source_balance(lineage.counts)
    if integrity.error_count:
        problems.append(f"{integrity.error_count} dangling relationship endpoints: {integrity.errors}")
    if problems:
        raise LineageInvariantError("lineage invariants failed: " + "; ".join(problems))


def write_lineage(lineage: Lineage, path: Path) -> str:
    """Writes indented, key-ordered JSON (UTF-8, trailing newline); returns the file SHA-256."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(lineage.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_lineage(path: Path) -> Lineage:
    """Reads and validates a lineage file; raises InputVerificationError if missing or invalid."""
    try:
        return Lineage.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise InputVerificationError(f"cannot read lineage {path}: {e}") from e
    except ValidationError as e:
        raise InputVerificationError(f"invalid lineage {path}: {e}") from e


def comparable_view(lineage: Lineage) -> Mapping[str, Any]:
    """The parts that must be identical across runs (counts, outputs, parameters): created_at and timing_s excluded (NFR-001, AC-016)."""
    data = lineage.model_dump(mode="json")
    return {key: data[key] for key in ("counts", "outputs", "parameters", "duplicates")}
