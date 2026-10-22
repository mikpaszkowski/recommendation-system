# Graph v2 (current)

The Knowledge Graph is built as version v2 from the raw Amazon Reviews 2023 Electronics files
(`production_artifacts/Technical_Specification_Graph_Rebuild.md`, Vision 2026-10-19-018). Every
step marked **CP** needs explicit user approval and is logged in `graph_versions/v2/RUNBOOK_LOG.md`.
Graph operations (stop, dump, volume create/switch, import, stamp) run only after the start gate CP-2.

**Status: built.** Graph v2 was built, validated (18/18 hard gates) and stamped on 2026-10-20; the v2 retrieval baseline was accepted at CP-9 (F4 complete). The live volume is `kg_neo4j_data_v2`. The table below is the record of how it was done and the procedure for rebuilding; the lessons from the real run are in the "Lessons from the 2026-10-20 build" notes after the table. Counts and coverage: `production_artifacts/graph_state_snapshot.md`.

| Step | Command (from the repository root) | Approval |
|---|---|---|
| R-1 pre-flight | `python scripts/graph_ingestion/export_v1_snapshot.py --catalogue-out graph_versions/v2/catalogue_asins.txt.gz --snapshot-out graph_versions/v1/snapshot.json --benchmark live_eval_dataset.json --targets-out graph_versions/v1/benchmark_targets.json`, then `python scripts/graph_ingestion/preflight_v2.py --out graph_versions/v2/preflight_report.json [--embed-device auto|cpu|mps]` (the report is always written; a failed measurement is stored as `{"error": …}` and listed in `failed_sections`; on a 16 GB Mac with MPS out-of-memory errors, rerun P-04 with `--embed-device cpu` or smaller `--throughput-batch-sizes`) | CP-1 (then write and commit `build_params.json`) |
| R-2 start gate | — | CP-2 |
| R-3 re-verify catalogue | `python scripts/graph_ingestion/export_v1_snapshot.py … --verify-only` (exit 0 required) | — |
| R-4 stop v1 | `docker stop neo4j-recommendation` (on the 2026-10-20 build the compose stop command did not match the v1 container, see "Lessons" below; where the container does belong to the current compose project, `docker compose --env-file .env -f src/knowledge_graph/docker-compose.yml stop neo4j` also works) | CP-3 |
| R-5 dump v1 | `python scripts/graph_ingestion/import_graph_v2.py dump --volume <v1> --backup-dir ~/neo4j-backups --record graph_versions/v1/DUMP.json --execute --confirm-volume <v1>`; optional `restore-test --dump ~/neo4j-backups/kg_v1_<ts>/neo4j.dump --execute --confirm-volume kg_v1_restore_test` | CP-4 |
| R-6 transform | `python scripts/graph_ingestion/build_graph_v2.py --sample-mod 20 --require-clean` (pilot: writes `datasets/graph_build/v2_pilot/import/` and `graph_versions/v2/pilot/lineage.json` by default), then `python scripts/graph_ingestion/build_graph_v2.py --require-clean` (full: `datasets/graph_build/v2/import/`, `graph_versions/v2/lineage.json`). A run that writes output exits 2 if the target lineage file already exists or the CSV directory is not empty, so an approved lineage cannot be replaced by accident: add `--force` to the pilot or the full command only to rebuild on purpose (for example `build_graph_v2.py --sample-mod 20 --require-clean --force`). `--dry-run` writes nothing and needs no `--force`. Raw inputs, splits and the catalogue default to `datasets/raw/…`, `datasets` and `graph_versions/v2/catalogue_asins.txt.gz`. | — |
| R-7 pilot | first rename the stopped v1 container (`docker rename neo4j-recommendation neo4j-recommendation-v1`), otherwise compose cannot create its own `neo4j-recommendation`; `docker volume create kg_neo4j_data_v2_pilot`; `python scripts/graph_ingestion/import_graph_v2.py import --volume kg_neo4j_data_v2_pilot --import-dir datasets/graph_build/v2_pilot/import --report-dir datasets/graph_build/v2_pilot/reports --record graph_versions/v2/pilot/import_run.json --execute --confirm-volume kg_neo4j_data_v2_pilot`; start compose on it with the build profile (`NEO4J_DATA_VOLUME=kg_neo4j_data_v2_pilot`); `python scripts/graph_ingestion/post_import_v2.py all --lineage graph_versions/v2/pilot/lineage.json --build-params graph_versions/v2/build_params.json --report graph_versions/v2/pilot/embedding_report.json --embed-device auto --embed-batch-size 32`; `python scripts/graph_ingestion/validate_graph.py --pilot --lineage graph_versions/v2/pilot/lineage.json --build-params graph_versions/v2/build_params.json --embedding-report graph_versions/v2/pilot/embedding_report.json --splits-dir datasets --catalogue graph_versions/v2/catalogue_asins.txt.gz --import-dir datasets/graph_build/v2_pilot/import --benchmark live_eval_dataset.json --out graph_versions/v2/pilot/validation_report.json` (these are also the `--pilot` defaults); record times, sizes, the ×20 extrapolation and the smoke-test outcomes in `graph_versions/v2/pilot/pilot_report.json`; switch compose back and remove the scratch volume. There is no pilot `build_params.json` (amendment A-3): with `--pilot` the expected counts of H-01, H-08 and H-10 come from the pilot lineage (`catalogue_missing_in_meta`, `kept`, `embed_selected`); the H-03 bound `accepted_untitled_count`, `review_cap` and `product_content_rule` come from the full build's `graph_versions/v2/build_params.json`. | CP-5 |
| R-8 full import | `docker volume create kg_neo4j_data_v2`; `python scripts/graph_ingestion/import_graph_v2.py import --volume kg_neo4j_data_v2 --import-dir datasets/graph_build/v2/import --report-dir datasets/graph_build/v2/reports --execute --confirm-volume kg_neo4j_data_v2` | CP-6 |
| R-9 switch, post-import, validate | `NEO4J_DATA_VOLUME=kg_neo4j_data_v2` and the build profile in `.env`; `docker compose … up -d`; **run detached** (the full run took about 2.6 h): `nohup python scripts/graph_ingestion/post_import_v2.py all --lineage graph_versions/v2/lineage.json --build-params graph_versions/v2/build_params.json --embed-device auto --embed-batch-size 32 > post_import.log 2>&1 &` then follow `tail -f post_import.log` (on a device out-of-memory error the encode batch halves down to 8, then that chunk runs on the CPU; written pages are kept, and `embedding_report.json` records the device, the effective batch size, OOM events and CPU fallbacks; re-run `embed` to resume; if a later step such as `fulltext-index` fails, fix the cause and re-run only that step, for example `post_import_v2.py fulltext-index`); `python scripts/graph_ingestion/validate_graph.py --lineage graph_versions/v2/lineage.json --build-params graph_versions/v2/build_params.json --embedding-report graph_versions/v2/embedding_report.json --splits-dir datasets --catalogue graph_versions/v2/catalogue_asins.txt.gz --import-dir datasets/graph_build/v2/import --benchmark live_eval_dataset.json --out graph_versions/v2/validation_report.json` | CP-7 |
| R-10 stamp | `python scripts/graph_ingestion/post_import_v2.py stamp --lineage graph_versions/v2/lineage.json --validation-report graph_versions/v2/validation_report.json --confirm-validation-sha256 <sha256 of the reviewed report>`; commit `graph_versions/v2/*` | CP-8 |
| R-11 runtime profile | remove the build overrides from `.env`; `docker compose … up -d --force-recreate` | — |
| R-12 v2 baseline | three live runs with `--require-clean`; `python scripts/graph_ingestion/check_baseline_diff.py --base 88cdbdf` must exit 0 | CP-9 |

## Rollback to v1

The v1 volume `knowledge-graph_neo4j_data` is never written by the v2 build. Three ways back, fastest first:

1. **Start the kept v1 container**: `docker stop neo4j-recommendation`, then `docker start neo4j-recommendation-v1`. Both containers use ports 7474 and 7687, so only one can run. (This is the path recorded at R-11 in `graph_versions/v2/RUNBOOK_LOG.md`.)
2. **Compose on the v1 volume**: stop `neo4j-recommendation`, set `NEO4J_DATA_VOLUME=knowledge-graph_neo4j_data` in `.env`, run the compose `up -d --force-recreate` command. The `.env` comment keeps this value.
3. **Restore the dump** (if the volume is lost): `~/neo4j-backups/kg_v1_20261019_2234/neo4j.dump` (2,717,863,893 bytes, SHA-256 `51db81286ef04f4a780a37833ed5d6d47d1ecc9737ea16ca9043c20af6c0026f`, record `graph_versions/v1/DUMP.json`) with `import_graph_v2.py restore-test --dump <path> --execute --confirm-volume <new volume>`, then point `NEO4J_DATA_VOLUME` at that volume. The restore test has not been run on this dump. Check the SHA-256 before restoring.

After a rollback the `GraphVersion` node is absent and new evaluation runs record `graph_version` as not v2; do not cite them as v2 runs. To go forward again, reverse the steps: stop v1, set `NEO4J_DATA_VOLUME=kg_neo4j_data_v2`, start.

## Lessons from the 2026-10-20 build

- **Compose project of the v1 container.** The v1 container `neo4j-recommendation` belonged to compose project `knowledge-graph`, created from the former path `src/knowledge-graph/docker-compose.yml`. The compose file now lives at `src/knowledge_graph/` (project `knowledge_graph`), so the compose `stop` command from the runbook did not find it. R-4 therefore used `docker stop neo4j-recommendation`, and the stopped container was renamed `neo4j-recommendation-v1` (unchanged) at R-7 so compose could create the v2 `neo4j-recommendation`. Alternatives are `-p knowledge-graph` on the compose command or removing the stopped v1 container first. Do not remove it while it is the rollback target.
- **Long post-import runs.** The full `post_import_v2.py all` took about 2.6 h (reviews alone about 110 min at roughly 164 texts/s). Run it detached with `nohup` (see R-9) so a closed terminal does not stop it. The run is resumable: `embed` skips what is written.
- **Apple-silicon memory (MPS).** MPS shares unified memory with the process and the Docker VM. The pre-flight measured batch 32 at 335 texts/s and batch 64 out of memory on a 16 GB Mac. Use `--embed-device auto` (or `mps`) with `--embed-batch-size 32`; `--embed-device cpu` is the fallback. The full run had no out-of-memory event and no CPU fallback.
- **Full-text smoke test.** Use a phrase from the `features` text, not a single token: a single token matched 11,828 products and triggered the `features_text` fallback index (fixed in `8b10a35`; the fallback was dropped and the index rebuilt over title, description, features and details_text).

Notes:
- `import_graph_v2.py import --execute` refuses to run unless `NEO4J_DATA_VOLUME_V1` is set (shell or the repository `.env`).
- Embedding device: `--embed-device auto` picks MPS on Apple silicon. MPS shares the 16 GB of unified memory with the process and the Docker VM, so keep `--embed-batch-size` modest (default 32) or use `--embed-device cpu`.
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
