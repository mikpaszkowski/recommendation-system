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
