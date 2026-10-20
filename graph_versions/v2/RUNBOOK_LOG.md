# Graph v2 Runbook Log

Checkpoint approvals for the graph v2 rebuild (`scripts/graph_ingestion/README.md`, "Graph v2";
`production_artifacts/Technical_Specification_Graph_Rebuild.md` §6.3). One entry per checkpoint.

## R-1 pre-flight — CP-1 approved (2026-10-20)

- Catalogue frozen from v1 with read-only Cypher (`export_v1_snapshot.py`, 2026-10-19): 265,307 parent_asins,
  `graph_versions/v2/catalogue_asins.txt.gz`, content SHA-256
  `76d882abd470978c97e060ab6b640315b1f3b3d5fa827c2832b307568c34f528`. v1 snapshot in `graph_versions/v1/`.
- Pre-flight report `graph_versions/v2/preflight_report.json`, SHA-256
  `3c2804ff49968f6490a04e300ee0c4ddfbe8c269c053caf0afe442fdfc03f5d1`, no failed sections. Run at commit `82a1bb9`
  with the uncommitted MPS out-of-memory fix (two earlier runs crashed in P-04 and wrote no report).
- Key measurements: 8 untitled products, 0 catalogue products missing in raw metadata, 3,382,248 kept reviews
  (60,521 duplicate review IDs collapsed), 1,081,137 reviews selected for embedding, 2,594,661 users,
  265,294 products with at least one review, 1,183 taxon nodes (max depth 7), 17,254 products without a
  category path, 151,262 products without a price, embedding on MPS at batch 32 (335 texts/s; batch 64
  out of memory), dry-run peak RSS 3.6 GB (target 3 GB, accepted), 72 GB free disk.
- P-09: product embeddings reproduce v1 (19 of 20 identical); category embeddings do not (40% identical),
  because their sample titles change once ghosts are filled. Accepted as part of the v1 → v2 difference.
- User decisions at CP-1: approve `graph_versions/v2/build_params.json` as written, including
  `product_content_rule = "title_description"` (OQ-1: the single features-only product gets no embedding
  instead of a near-blank one) and `embedding_device = "mps"` with encode batch 32.

## R-2 start gate — CP-2 approved (2026-10-20)

- User confirmed that R2a no longer needs the v1 graph. R2a's citable v1 runs are archived
  (`evaluations_archive/eval_2026-10-18_2340`, `_2349`, `_2358`, commit `96874f3`).
- `.env` (git-ignored) gained `NEO4J_DATA_VOLUME=knowledge-graph_neo4j_data` (compose stays on v1 until
  R-9) and `NEO4J_DATA_VOLUME_V1=knowledge-graph_neo4j_data` (import guard). The running database was not changed.

## R-3 re-verify catalogue (2026-10-20)

- `export_v1_snapshot.py … --verify-only`: catalogue (265,307), v1 snapshot and benchmark targets unchanged.

## R-4 stop v1 — CP-3 approved (2026-10-20)

- `docker stop neo4j-recommendation` (status exited, exit code 0). The runbook's compose stop command does not
  match this container: it belongs to compose project `knowledge-graph`, created from the former path
  `src/knowledge-graph/docker-compose.yml`. To be handled at R-9 (`-p knowledge-graph` or remove the stopped
  v1 container first). Rollback: `docker start neo4j-recommendation`.

## R-5 dump v1 — CP-4 approved (2026-10-20)

- `import_graph_v2.py dump --volume knowledge-graph_neo4j_data … --execute`: `~/neo4j-backups/kg_v1_20261019_2234/neo4j.dump`,
  2,717,863,893 bytes, SHA-256 `51db81286ef04f4a780a37833ed5d6d47d1ecc9737ea16ca9043c20af6c0026f`
  (re-checked independently with `shasum`). Record: `graph_versions/v1/DUMP.json`. Optional restore test not run.
- The v1 volume `knowledge-graph_neo4j_data` was mounted only by the dump container and not modified.

## R-6 transform (2026-10-20)

- `build_graph_v2.py --sample-mod 20 --require-clean` and `build_graph_v2.py --require-clean` at clean commit `75c5c0a`.
- Pilot: 13,381 products, 171,212 reviews, 54,668 to embed, 790 taxon nodes; 152 MB CSV; 6 min, peak RSS 1.1 GB.
- Full: 265,307 products, 3,382,248 reviews, 1,081,137 to embed, 2,594,661 users, 49,663 brands, 38 categories,
  36,187 attributes, 1,183 taxon nodes; 2.9 GB CSV; 10.5 min, peak RSS 4.2 GB. Counts equal `build_params.json`.

## R-7 pilot — CP-5 approved (2026-10-20)

- v1 container renamed to `neo4j-recommendation-v1` (unchanged, stopped) so compose can create `neo4j-recommendation`.
- `docker volume create kg_neo4j_data_v2_pilot`; import 13 s, store 479 MB, empty import report (0 bad rows).
- Neo4j 5.14 started on the pilot volume with the build profile (heap 4G, page cache 1G, tx timeout 600s).
- `post_import_v2.py all`: 7.8 min; MPS, encode batch 32, 0 out-of-memory events, 0 CPU fallbacks; all eligible
  nodes embedded (13,381 products, 54,668 reviews); 5 vector indexes via procedure; full-text smoke test passed.
- `validate_graph.py --pilot`: **18/18 hard gates passed**. R-07 shows 20 benchmark targets outside the 5% sample;
  the sampled target `live_eval_laptop_02` keeps title, price, brand and category (reviews 33 → 20, cap).
- Full-build estimate (`pilot/pilot_report.json`): import ≈ 4 min; embedding ≈ 2.25 h (reviews ≈ 110 min at
  164 texts/s, products ≈ 22 min); store ≈ 12.5 GB plus ≈ 0.5–1 GB transaction logs.
- Pilot container removed (`compose down`, no `-v`) and scratch volume `kg_neo4j_data_v2_pilot` deleted.

## R-8 full import — CP-6 approved (2026-10-20)

- `docker volume create kg_neo4j_data_v2`; `import_graph_v2.py import --volume kg_neo4j_data_v2 … --execute`: 94 s,
  store 4.0 GB, empty import report (0 bad rows). Record `graph_versions/v2/import_run.json`.

## R-9 switch, post-import, validate — CP-7 approved (2026-10-20)

- Compose started on `kg_neo4j_data_v2` with the build profile (heap 4G, page cache 1G, tx timeout 600s).
- `post_import_v2.py all` (run detached with nohup; ~2.6 h): all labels embedded on MPS at batch 32 with no
  out-of-memory event (reviews 1,081,137; products 265,303, 4 skipped by `title_description`; brands 49,663;
  categories 38). The run stopped at the full-text step; three code bugs were fixed and committed with tests:
  - `8b10a35`: the single-token smoke test did not scale (token matched 11,828 products) and triggered the
    `features_text` fallback; 2 Attribute nodes with unpaired surrogates were not written back (string match).
    Now: phrase smoke test, fallback recovery, elementId write-back with write counts.
  - `0a32604`: the smoke query passed `query=` to `Session.run` (argument clash); now `$search`.
  - Re-ran `embed --labels Attribute` (2 embedded; 36,187/36,187) and `fulltext-index` (fallback index dropped,
    `features_text` removed from 215,032 products, index rebuilt over title, description, features,
    details_text; phrase smoke test found at rank 1).
- `validate_graph.py`: **18/18 hard gates passed**; report SHA-256
  `d8a68b7f2ac1589353fc8d32b6b00646dfe4e2aca98150b1964f8f1e6b1bb8af`.

## R-10 stamp — CP-8 approved (2026-10-20)

- User reviewed and approved the validation report above.
- `post_import_v2.py stamp … --confirm-validation-sha256 d8a68b7f…8af`: `(:GraphVersion {version: 'v2',
  validation_passed: true})` written at 2026-10-20T08:20:05Z (lineage `3f985952…86ec`, code commit `75c5c0a`,
  stamp commit `0a32604`, Neo4j 5.14.0).

## R-11 runtime profile (2026-10-20)

- `.env`: `NEO4J_DATA_VOLUME=kg_neo4j_data_v2` (rollback value `knowledge-graph_neo4j_data` noted in the comment);
  compose recreated without build overrides: heap 2 GiB, page cache 2 GiB, transaction timeout 1 min. `GraphVersion` v2 present.
- Rollback to v1: stop `neo4j-recommendation`, then `docker start neo4j-recommendation-v1` (or compose with the v1 volume).

## R-12 v2 baseline — pre-check (2026-10-20)

- `check_baseline_diff.py --base 88cdbdf` exits 1: 5 paths outside the allow-list, all documentation or infrastructure
  (`src/README.md`, `src/knowledge_graph/DOCKER.md`, deleted `src/knowledge_graph/README.md` and `QUICKSTART.md`,
  `src/knowledge_graph/docker-compose.yml`). Decision pending at CP-9.
