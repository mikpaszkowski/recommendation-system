# Graph v2 (current)

The Knowledge Graph is built as version v2 from the raw Amazon Reviews 2023 Electronics files
(`production_artifacts/Technical_Specification_Graph_Rebuild.md`, Vision 2026-10-19-018). Every
step marked **CP** needs explicit user approval and is logged in `graph_versions/v2/RUNBOOK_LOG.md`.
Graph operations (stop, dump, volume create/switch, import, stamp) run only after the start gate CP-2.

| Step | Command (from the repository root) | Approval |
|---|---|---|
| R-1 pre-flight | `python scripts/graph_ingestion/export_v1_snapshot.py --catalogue-out graph_versions/v2/catalogue_asins.txt.gz --snapshot-out graph_versions/v1/snapshot.json --benchmark live_eval_dataset.json --targets-out graph_versions/v1/benchmark_targets.json`, then `python scripts/graph_ingestion/preflight_v2.py --out graph_versions/v2/preflight_report.json` | CP-1 (then write and commit `build_params.json`) |
| R-2 start gate | — | CP-2 |
| R-3 re-verify catalogue | `python scripts/graph_ingestion/export_v1_snapshot.py … --verify-only` (exit 0 required) | — |
| R-4 stop v1 | `docker compose --env-file .env -f src/knowledge_graph/docker-compose.yml stop neo4j` | CP-3 |
| R-5 dump v1 | `python scripts/graph_ingestion/import_graph_v2.py dump --volume <v1> --backup-dir ~/neo4j-backups --record graph_versions/v1/DUMP.json --execute --confirm-volume <v1>`; optional `restore-test --dump ~/neo4j-backups/kg_v1_<ts>/neo4j.dump --execute --confirm-volume kg_v1_restore_test` | CP-4 |
| R-6 transform | `python scripts/graph_ingestion/build_graph_v2.py --sample-mod 20 --require-clean` (pilot: writes `datasets/graph_build/v2_pilot/import/` and `graph_versions/v2/pilot/lineage.json` by default), then `python scripts/graph_ingestion/build_graph_v2.py --require-clean` (full: `datasets/graph_build/v2/import/`, `graph_versions/v2/lineage.json`). A run that writes output exits 2 if the target lineage file already exists or the CSV directory is not empty, so an approved lineage cannot be replaced by accident: add `--force` to the pilot or the full command only to rebuild on purpose (for example `build_graph_v2.py --sample-mod 20 --require-clean --force`). `--dry-run` writes nothing and needs no `--force`. Raw inputs, splits and the catalogue default to `datasets/raw/…`, `datasets` and `graph_versions/v2/catalogue_asins.txt.gz`. | — |
| R-7 pilot | `docker volume create kg_neo4j_data_v2_pilot`; `python scripts/graph_ingestion/import_graph_v2.py import --volume kg_neo4j_data_v2_pilot --import-dir datasets/graph_build/v2_pilot/import --report-dir datasets/graph_build/v2_pilot/reports --record graph_versions/v2/pilot/import_run.json --execute --confirm-volume kg_neo4j_data_v2_pilot`; start compose on it with the build profile (`NEO4J_DATA_VOLUME=kg_neo4j_data_v2_pilot`); `python scripts/graph_ingestion/post_import_v2.py all --lineage graph_versions/v2/pilot/lineage.json --build-params graph_versions/v2/build_params.json --report graph_versions/v2/pilot/embedding_report.json`; `python scripts/graph_ingestion/validate_graph.py --pilot --lineage graph_versions/v2/pilot/lineage.json --build-params graph_versions/v2/build_params.json --embedding-report graph_versions/v2/pilot/embedding_report.json --splits-dir datasets --catalogue graph_versions/v2/catalogue_asins.txt.gz --import-dir datasets/graph_build/v2_pilot/import --benchmark live_eval_dataset.json --out graph_versions/v2/pilot/validation_report.json` (these are also the `--pilot` defaults); record times, sizes, the ×20 extrapolation and the smoke-test outcomes in `graph_versions/v2/pilot/pilot_report.json`; switch compose back and remove the scratch volume. There is no pilot `build_params.json` (amendment A-3): with `--pilot` the expected counts of H-01, H-08 and H-10 come from the pilot lineage (`catalogue_missing_in_meta`, `kept`, `embed_selected`); the H-03 bound `accepted_untitled_count`, `review_cap` and `product_content_rule` come from the full build's `graph_versions/v2/build_params.json`. | CP-5 |
| R-8 full import | `docker volume create kg_neo4j_data_v2`; `python scripts/graph_ingestion/import_graph_v2.py import --volume kg_neo4j_data_v2 --import-dir datasets/graph_build/v2/import --report-dir datasets/graph_build/v2/reports --execute --confirm-volume kg_neo4j_data_v2` | CP-6 |
| R-9 switch, post-import, validate | `NEO4J_DATA_VOLUME=kg_neo4j_data_v2` and the build profile in `.env`; `docker compose … up -d`; `python scripts/graph_ingestion/post_import_v2.py all --lineage graph_versions/v2/lineage.json --build-params graph_versions/v2/build_params.json`; `python scripts/graph_ingestion/validate_graph.py --lineage graph_versions/v2/lineage.json --build-params graph_versions/v2/build_params.json --embedding-report graph_versions/v2/embedding_report.json --splits-dir datasets --catalogue graph_versions/v2/catalogue_asins.txt.gz --import-dir datasets/graph_build/v2/import --benchmark live_eval_dataset.json --out graph_versions/v2/validation_report.json` | CP-7 |
| R-10 stamp | `python scripts/graph_ingestion/post_import_v2.py stamp --lineage graph_versions/v2/lineage.json --validation-report graph_versions/v2/validation_report.json --confirm-validation-sha256 <sha256 of the reviewed report>`; commit `graph_versions/v2/*` | CP-8 |
| R-11 runtime profile | remove the build overrides from `.env`; `docker compose … up -d --force-recreate` | — |
| R-12 v2 baseline | three live runs with `--require-clean`; `python scripts/graph_ingestion/check_baseline_diff.py --base 88cdbdf` must exit 0 | CP-9 |

Rollback at any point: stop the container, set `NEO4J_DATA_VOLUME=<v1 volume>`, start. The v1 volume is never written.

Notes:
- `import_graph_v2.py import --execute` refuses to run unless `NEO4J_DATA_VOLUME_V1` is set (shell or the repository `.env`).
- `validate_graph.py` gate H-15 loads `scripts/evaluate_retrieval.py`, which imports `seaborn` (in `requirements.txt` and the project `.venv`).

---

# Legacy v1 pipeline (do not use for the KG)

The content below documents the v1 pipeline (`batch_ingest.py` over the sampled processed CSVs),
which produced the v1 ghost products. It is kept for reference only. Do not run it against the
live graph: after graph v2 (FR-031 … FR-035) the review query in `batch_ingest.py` only matches existing products
(`OPTIONAL MATCH`, no `MERGE` of `ParentProduct`; the product metadata query still merges), and `backfill_embeddings.py` skips blank texts. Embeddings use
`sentence-transformers/all-MiniLM-L6-v2` locally; no OpenAI key is needed for them.

# Graph Ingestion Pipeline Instructions

This guide outlines the steps required to populate the Neo4j Knowledge Graph with the full catalog of products from the flattened datasets (`datasets/processed_data/processed_metadata.csv and processed_reviews.csv`).

## Prerequisites

1. Ensure the `.env` file is properly configured with your Neo4j credentials:
   ```env
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=password
   OPENAI_API_KEY=your_key_here  # Not needed for embeddings (local sentence-transformers); used by the LLM components
   ```
2. Ensure the Neo4j docker container is running.

## 1. Run the Batch Ingestion Script

We have consolidated the ingestion logic into a dedicated script directory: `scripts/graph_ingestion/`.
Run the new batch ingestion script to load the nodes and edges from the processed CSV.

```bash
python scripts/graph_ingestion/batch_ingest.py
```
*(You can pass `--limit 1000` for a test run).*

## 2. Apply Neo4j Constraints and Setup Vector Indexes

Next, setup the constraints and vector indexes required for search. The live Neo4j is 5.14, which has no Cypher 25 `VECTOR SEARCH` and does not support `CREATE VECTOR INDEX` DDL (Neo4j >= 5.15). The index scripts use the procedure form `db.index.vector.createNodeIndex` (`create_vector_indexes.cypher`, `setup_indexes.py`; the DDL fallback in `setup_indexes.py` is disabled for 5.14 callers). `create_indexes.py` still contains DDL statements and must not be used on 5.14.

```bash
python src/knowledge_graph/graphdb/setup_indexes.py
```

## 3. Backfill Embeddings (Required for GraphSearchTool)

The full product catalog will be missing OpenAI embeddings for vector search upon initial ingestion. You must run the backfill scripts to generate them.

### Generate Product, Attribute, and Review Embeddings
```bash
python src/knowledge_graph/graphdb/backfill_embeddings.py
```

### Generate Category Embeddings
```bash
python src/knowledge_graph/graphdb/backfill_category_embeddings.py
```

## 4. Test the Database

Finally, test the end-to-end graph query:
```bash
python scripts/run_a1_flow.py "small keyboard under 30$ with usb-c"
```
