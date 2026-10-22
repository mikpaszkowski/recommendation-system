# Action Items

Work-driving documents: audits that produce action items, and Architectural Fix Proposals (AFPs). The canonical reports (Vision Report, Technical Specification, Research Report, Evaluation Failure Analysis) stay in `production_artifacts/`. Progress is tracked in `production_artifacts/Implementation_Plan.md`.

| Document | ID | Status |
|---|---|---|
| [Live_Graph_Audit_2026-10-10.md](Live_Graph_Audit_2026-10-10.md) | AI-01 … AI-13 | Open |
| [Proposed_Fix_Benchmark_Alignment.md](Proposed_Fix_Benchmark_Alignment.md) | AFP-001 | Implemented (Vision Report decision 2026-10-07-010) |
| [Proposed_Fix_Vector_Aggregation.md](Proposed_Fix_Vector_Aggregation.md) | AFP-002 | Implemented 2026-10-17 via RRF (release R1, Vision decision 2026-10-17-013). |
| [Retrieval_Score_Redesign_Roadmap.md](Retrieval_Score_Redesign_Roadmap.md) | RS-01 … RS-25, R1 … R5 | **R1 and R2a done** (branch `feature/afp-002-vector-aggregation`; R2a exit gate PASS 2026-10-18, citable runs in `evaluations_archive/`); R2b (RS-21, RS-02 evidence) next. D-1 recorded (Vision decision 2026-10-17-013); R2 evaluation decisions recorded as Vision 2026-10-18-014 … 017; D-2 … D-4 pending. |
| Graph v2 rebuild (documents in `production_artifacts/`: `Research_Report_Graph_Rebuild.md`, `Technical_Specification_Graph_Rebuild.md`, `Audit_Report_Graph_Rebuild.md`) | Vision 2026-10-19-018 … 021; Implementation Plan item F4 | **Built 2026-10-20** (validated 18/18, `GraphVersion` v2 stamped, v2 baseline accepted at CP-9; code audit PASS WITH FIXES 2026-10-19). The live Neo4j is v2. Record: `graph_versions/v2/RUNBOOK_LOG.md`, `production_artifacts/graph_state_snapshot.md`. Unblocks R2b, AI-03, AI-06, RS-12, RS-03. |
| [Proposed_Fix_Category_Resolution.md](Proposed_Fix_Category_Resolution.md) | AFP-003 | Implemented (decision 2026-10-07-009) |
| [Proposed_Fix_Prompt_Constraint_Inversion.md](Proposed_Fix_Prompt_Constraint_Inversion.md) | AFP-004 | Implemented (decision 2026-10-09-011) |
| [Proposed_Fix_Cypher_Ranking_and_Typing.md](Proposed_Fix_Cypher_Ranking_and_Typing.md) | AFP-005 | Implemented (decision 2026-10-09-012) |

> **Graph v1 figures (2026-10-19)**: the live-graph figures quoted in these documents ("47% have reviews", 4.7% / 2.2% review-embedding coverage, "53% cold products", 71 categories, `Variant` / `PriceRange` structures) are v1 facts. Vision 2026-10-19-021 records that 104,281 of the 265,307 v1 products are ghosts, so they are recomputed on graph v2 (built 2026-10-20: 99.995% of products have an embedded review, 8 untitled products; see `production_artifacts/graph_state_snapshot.md`). Each affected document carries a dated note.

> **Moved 2026-10-10**: The `Proposed_Fix_*.md` files previously lived at `production_artifacts/Proposed_Fix_*.md`. Earlier entries in `Vision_Report.md` and `docs/changelog/changelog.md` still cite the old path. Those documents are append-only, so the references were intentionally left unchanged.
