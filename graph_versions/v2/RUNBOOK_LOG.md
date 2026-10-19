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
