"""
Graph v2 build package (Technical Specification Graph Rebuild, Vision 2026-10-19-018 … 021).

Pure-Python transform from the raw Amazon Reviews 2023 Electronics files to `neo4j-admin database
import full` CSVs plus `graph_versions/v2/lineage.json`, and the pure helpers used by the import,
post-import and validation CLIs under `scripts/graph_ingestion/`. Nothing in this package opens a
Neo4j session or runs Docker by itself; callers inject sessions and command runners so every module
is unit-testable on the fixtures in `tests/fixtures/graph_v2/` (NFR-005).

Modules:
    models            Pydantic models for every JSON artefact (§5.3 – §5.6)
    product_mapping   Meta record -> product, brand, category, attributes (FR-006 … FR-009)
    taxonomy          Taxon tree builder (FR-010)
    review_selection  Review ID, rank key, bounded top-K selection, embed ranks, split pairs (FR-011, FR-012)
    csv_io            Text sanitisation, import headers, deterministic CSV writer (FR-014)
    lineage           Input verification, catalogue I/O, lineage assembly and invariants (FR-005, FR-015)
    transform         Two-pass orchestration, dry run and sample mode (FR-011, FR-016, FR-017)
    import_command    Docker / neo4j-admin command builders and volume checks (FR-004, FR-019)
    validation        Hard gates H-01 … H-18 and report-only checks as pure functions (FR-026)
    graph_queries     Read-only Cypher collectors shared by the CLIs (counts, version, snapshot)
"""
