"""
Pydantic v2 models for the graph v2 JSON artefacts (Technical Specification Graph Rebuild §5.3 – §5.6).

Every artefact written under `graph_versions/` is validated against one of these models before it
is written and after it is read, so a schema drift fails loudly (NFR-008). Models are strict
(`extra="forbid"`) unless a section is documented as free-form.

    Lineage           graph_versions/v2/lineage.json (§5.3)
    BuildParams       graph_versions/v2/build_params.json (§5.4, FR-002)
    PreflightReport   graph_versions/v2/preflight_report.json (§5.4, FR-001)
    EmbeddingReport   graph_versions/v2/embedding_report.json (§5.4, FR-023)
    ImportRun         graph_versions/v2/import_run.json (§5.4, FR-019)
    DumpRecord        graph_versions/v1/DUMP.json (§5.4, FR-004, FR-004a)
    GateResult        one hard-gate outcome (§5.5)
    ValidationReport  graph_versions/v2/validation_report.json (§5.5, FR-026)
    GraphVersionProps properties of the (:GraphVersion) node (§5.6, FR-027)
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: int = 1
GRAPH_VERSION: str = "v2"
REVIEW_EMBEDDING_SCOPE: str = "top5_nonblank_by_cap_rank"
EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_VALIDATION_SEED: int = 20261019


class _Strict(BaseModel):
    """Base model that rejects unknown keys."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------------- lineage


class FileStats(_Strict):
    """Row count, byte size and SHA-256 of one written import CSV (sha256 is None in a dry run)."""

    rows: int = 0
    bytes: int = 0
    sha256: Optional[str] = None


class CodeInfo(_Strict):
    """Code state that produced the build (FR-015, FR-018)."""

    git_commit: Optional[str]
    git_dirty: Optional[bool]
    script: str = "scripts/graph_ingestion/build_graph_v2.py"


class SourceFile(_Strict):
    """One raw JSONL source with its verified SHA-256 and line count."""

    path: str
    sha256: str
    verified_against: Optional[str]
    lines: Optional[int] = None


class SplitFile(_Strict):
    """One official split CSV with its SHA-256 and data-row count."""

    path: str
    sha256: str
    rows: Optional[int] = None


class SplitsInfo(_Strict):
    """The three split files plus the SHA-256 of the canonical JSON {"train": …, "valid": …, "test": …}."""

    train: SplitFile
    valid: SplitFile
    test: SplitFile
    combined_sha256: str


class CatalogueInfo(_Strict):
    """Frozen catalogue: SHA-256 of the uncompressed content, full count and (pilot only) sampled count."""

    path: str
    sha256_content: str
    count: int
    sampled_count: Optional[int] = None


class Sources(_Strict):
    """All hashed inputs of the transform."""

    meta: SourceFile
    reviews: SourceFile
    splits: SplitsInfo
    catalogue: CatalogueInfo


class LineageParameters(_Strict):
    """Every rule parameter of the build, recorded verbatim (§5.3 `parameters`)."""

    review_cap: int
    rank_key: List[str]
    duplicate_rule: str
    review_id: str
    exclusion_rule: str
    embed_top_n: int
    embed_rule: str
    attribute_keys: List[str]
    brand_rule: str
    taxon_separator: str
    array_delimiter: str
    text_normalization: List[str]
    sample_mod: Optional[int] = None


class ColumnSpec(_Strict):
    """Source columns read and dropped for one input file."""

    read: List[str]
    dropped: List[str]


class Columns(_Strict):
    """Columns read and dropped per raw source."""

    meta: ColumnSpec
    reviews: ColumnSpec


class MetaCounts(_Strict):
    """
    Metadata pass counters. Balance (FR-015 invariant 1):
    lines = json_errors + not_in_catalogue + duplicate_parent_asin + products_written.
    `features_only_content` (title and description blank, features present) feeds OQ-1.
    """

    lines: int = 0
    json_errors: int = 0
    not_in_catalogue: int = 0
    duplicate_parent_asin: int = 0
    products_written: int = 0
    catalogue_missing_in_meta: int = 0
    title_empty: int = 0
    description_empty: int = 0
    features_empty: int = 0
    content_empty: int = 0
    features_only_content: int = 0
    categories_empty: int = 0
    main_category_empty: int = 0
    price_null: int = 0
    price_unparseable: int = 0
    price_non_positive: int = 0
    brand_missing: int = 0
    attribute_non_string: int = 0


class ReviewCounts(_Strict):
    """
    Review pass counters. Balance (FR-015 invariant 1): lines = json_errors + missing_ids +
    not_in_catalogue + product_missing + valid_test_pair + duplicate_review_id + beyond_cap + kept.
    kept_in_train_split, kept_no_split, missing_timestamp, empty_text and embed_selected describe kept reviews.
    """

    lines: int = 0
    json_errors: int = 0
    missing_ids: int = 0
    not_in_catalogue: int = 0
    product_missing: int = 0
    valid_test_pair: int = 0
    duplicate_review_id: int = 0
    beyond_cap: int = 0
    kept: int = 0
    kept_in_train_split: int = 0
    kept_no_split: int = 0
    missing_timestamp: int = 0
    empty_text: int = 0
    embed_selected: int = 0


class TaxonomyCounts(_Strict):
    """Shape of the Taxon tree (FR-010)."""

    roots: int = 0
    max_depth: int = 0
    inner_node_assignments: int = 0
    products_without_taxon_by_main_category: Dict[str, int] = Field(default_factory=dict)


class SanitizedCounts(_Strict):
    """Counts of every text normalisation applied while encoding CSV values (FR-014)."""

    nul: int = 0
    unit_separator: int = 0
    carriage_return: int = 0
    blank_to_null: int = 0
    empty_array_items: int = 0


class LineageCounts(_Strict):
    """All per-step counters of the build."""

    meta: MetaCounts = Field(default_factory=MetaCounts)
    reviews: ReviewCounts = Field(default_factory=ReviewCounts)
    nodes: Dict[str, int] = Field(default_factory=dict)
    relationships: Dict[str, int] = Field(default_factory=dict)
    taxonomy: TaxonomyCounts = Field(default_factory=TaxonomyCounts)
    brand_case_duplicate_groups: int = 0
    sanitized: SanitizedCounts = Field(default_factory=SanitizedCounts)


class Duplicates(_Strict):
    """Lists capped at DUPLICATE_LIST_CAP entries; the full counts live in `counts`."""

    parent_asin_conflicting: List[str] = Field(default_factory=list)
    brand_case_groups: List[List[str]] = Field(default_factory=list)


class Lineage(_Strict):
    """graph_versions/v2/lineage.json (§5.3, FR-015)."""

    schema_version: Literal[1] = 1
    graph_version: str = GRAPH_VERSION
    created_at: str
    code: CodeInfo
    sources: Sources
    parameters: LineageParameters
    columns: Columns
    counts: LineageCounts
    duplicates: Duplicates
    outputs: Dict[str, FileStats] = Field(default_factory=dict)
    timing_s: Dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------------- build parameters


class BuildParams(_Strict):
    """
    User-approved gate parameters written after CP-1 (FR-002). `validate_graph.py` reads its
    thresholds only from this file and the lineage. `product_content_rule` records the OQ-1
    decision (default: the approved G-4 rule).
    """

    accepted_untitled_count: int = Field(ge=0)
    accepted_catalogue_missing: int = Field(ge=0)
    expected_review_count: int = Field(ge=0)
    expected_embed_reviews: int = Field(ge=0)
    review_embedding_scope: Literal["top5_nonblank_by_cap_rank"] = "top5_nonblank_by_cap_rank"
    review_cap: int = 20
    embedding_device: str
    build_profile: Dict[str, str]
    preflight_report_sha256: str
    approved_by: Literal["user"] = "user"
    approved_on: str
    product_content_rule: Literal["title_description_features", "title_description"] = "title_description_features"


class PreflightReport(_Strict):
    """graph_versions/v2/preflight_report.json (FR-001). Each pNN section is free-form (documented in preflight_v2.py).
    A section whose measurement failed holds {"error": "<type>: <message>"} and is listed in `failed_sections`."""

    created_at: str
    git_commit: Optional[str]
    p01_meta_coverage: Dict[str, Any]
    p02_review_funnel: Dict[str, Any]
    p03_embed_scope: Dict[str, Any]
    p04_throughput: Dict[str, Any]
    p05_taxonomy: Dict[str, Any]
    p06_brand_isbn: Dict[str, Any]
    p07_environment: Dict[str, Any]
    p08_v1_snapshot: Dict[str, Any]
    p09_template_conformance: Dict[str, Any]
    p10_timing: Dict[str, Any]
    failed_sections: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------- embeddings


class LabelEmbeddingStats(_Strict):
    """Embedding outcome for one label (FR-023)."""

    template_id: str
    eligible: int = 0
    embedded: int = 0
    skipped_empty: int = 0
    skipped_keys_sample: List[str] = Field(default_factory=list)
    batches: int = 0
    seconds: float = 0.0
    texts_per_s: Optional[float] = None


class EmbeddingReport(_Strict):
    """graph_versions/v2/embedding_report.json (FR-023)."""

    created_at: str
    model: str = EMBEDDING_MODEL
    sentence_transformers_version: Optional[str]
    torch_version: Optional[str]
    device: Optional[str]
    batch_size: int                                   # Neo4j page size (--batch-size)
    labels: Dict[str, LabelEmbeddingStats]
    embed_batch_size: Optional[int] = None            # requested encode batch (--embed-batch-size)
    effective_embed_batch_size: Optional[int] = None  # after out-of-memory halving
    oom_events: int = 0
    cpu_fallback_batches: int = 0


# ------------------------------------------------------------------------------------ import / dump


class ImportRun(_Strict):
    """graph_versions/v2/import_run.json (and pilot/import_run.json), FR-019."""

    volume: str
    image: str
    command: List[str]
    started_at: str
    ended_at: str
    exit_code: int
    report_file_sha256: Optional[str]
    report_file_lines: Optional[int]
    store_kb: Optional[int]


class RestoreTestResult(_Strict):
    """Outcome of `import_graph_v2.py restore-test` (FR-004a)."""

    passed: bool
    counts_match: bool
    at: str
    observed_counts: Dict[str, Dict[str, int]] = Field(default_factory=dict)


class DumpRecord(_Strict):
    """graph_versions/v1/DUMP.json (FR-004). The dump file itself stays outside git."""

    volume: str
    dump_path: str
    sha256: str
    bytes: int
    created_at: str
    neo4j_version: Optional[str]
    restore_test: Optional[RestoreTestResult] = None


# ------------------------------------------------------------------------------------- validation


class GateResult(_Strict):
    """One hard gate H-01 … H-18 (§5.5)."""

    id: str
    name: str
    expected: Any = None
    observed: Any = None
    passed: bool
    detail: Optional[Any] = None


class ValidationReport(_Strict):
    """graph_versions/v2/validation_report.json (§5.5, FR-026). `passed` depends on hard gates only."""

    schema_version: Literal[1] = 1
    graph_version: str = GRAPH_VERSION
    created_at: str
    pilot: bool = False
    seed: int = DEFAULT_VALIDATION_SEED
    lineage_sha256: str
    build_params_sha256: str
    embedding_report_sha256: str
    graph_counts: Dict[str, int]
    passed: bool
    hard_gates: List[GateResult]
    report_only: Dict[str, Dict[str, Any]]


# ---------------------------------------------------------------------------------- GraphVersion


class GraphVersionProps(_Strict):
    """Exactly the properties of the (:GraphVersion) node (§5.6); all values are Neo4j-storable scalars or string lists."""

    version: str
    built_at: str
    lineage_sha256: str
    validation_report_sha256: str
    embedding_report_sha256: str
    build_params_sha256: str
    source_meta_sha256: str
    source_reviews_sha256: str
    splits_sha256: str
    catalogue_sha256: str
    code_commit: str
    stamp_commit: str
    embedding_model: str = EMBEDDING_MODEL
    template_ids: List[str]
    review_embedding_scope: str = REVIEW_EMBEDDING_SCOPE
    review_cap: int
    fulltext_fields: List[str]
    neo4j_version: str
    product_count: int
    review_count: int
    user_count: int
    taxon_count: int
    validation_passed: Literal[True] = True
