# Explainable Hybrid GraphRAG for Conversational Recommendation

This repository contains the implementation of a modern Multi-Agent System (MAS) that combines a Neo4j Knowledge Graph, Hybrid GraphRAG retrieval, and LLM-driven orchestration into a conversational recommender.

## Strategic Vision

The system addresses the fundamental limitations of pure LLM implementations (hallucinations, lack of deterministic grounding) and traditional engines (cold-start problem) by synthesizing:
1. **Multi-Agent Orchestration**: `AgentOrchestrator` handles dialogue policy and `CriticAgent` evaluates semantic constraints.
2. **Hybrid GraphRAG Retrieval**: Combines Neo4j dense vector ANN search with hard structural Cypher filtering.
3. **Knowledge-Enhanced Conversational Reasoning (KECR)**: Injects explicit graph reasoning pathways into the LLM context window to guarantee data provenance.

## Directory Structure

* `src/` - Primary source code
  * `agents/` - Multi-agent implementations (`orchestrator.py`, `critic_agent.py`)
  * `dialog_manager/` - Dialogue state modeling and session adapters
  * `knowledge_graph/` - Neo4j database connectors and resolver services; `graph_v2/` holds the graph v2 transform, taxonomy, lineage and validation code
  * `tools/` - GraphSearchTool and KECRTool for retrieval
  * `llm_interface/` - Prompt parsers and LLM extraction utilities
  * `evaluation/` - Two-Tiered evaluation metrics and harnesses
* `scripts/` - Execution scripts for Graph Ingestion and Retrieval Evaluation
* `tests/` - Comprehensive unit, integration, and Tier 1-4 End-to-End tests
* `production_artifacts/` - Canonical architecture specs, Vision Report, and Academic documentation
* `thesis/` - Master Thesis research contributions and evaluation methodologies
* `docs/` - Project changelog and historical documentation
* `evaluations/` - Local evaluation run output (git-ignored working data, not thesis evidence)
* `evaluations_archive/` - Git-tracked archive of evaluation runs the thesis may cite (policy in `evaluations_archive/README.md`)

## Getting Started

1. Set up your `.env` based on `.env.example`. `NEO4J_DATA_VOLUME` is required: the compose file uses an external Docker volume, which must exist before the first start (`docker volume create <name>`).
2. Start the Neo4j container from the repository root:
   ```bash
   docker compose --env-file .env -f src/knowledge_graph/docker-compose.yml up -d
   ```
3. Build the Knowledge Graph. The live graph is **v2**, built, validated (18/18 gates) and stamped on 2026-10-20 (265,307 products, 3,382,248 reviews; counts in `production_artifacts/graph_state_snapshot.md`). It is built from the raw Amazon Reviews 2023 files by `scripts/graph_ingestion/build_graph_v2.py`, `import_graph_v2.py`, `post_import_v2.py` and `validate_graph.py`, under a step-by-step runbook with user approval checkpoints (see `scripts/graph_ingestion/README.md`, including the rollback path, and `production_artifacts/Technical_Specification_Graph_Rebuild.md`). Do not use `batch_ingest.py` for the KG: it produced the retired **v1** graph with 104,281 ghost products (Vision 2026-10-19-021). On a machine without the v2 volume, follow the runbook; the raw files and splits are not in git.
4. Run the Retrieval Evaluation suite:
   ```bash
   python scripts/evaluate_retrieval.py
   # compare fusion arms on the same requests (live mode)
   python scripts/evaluate_retrieval.py --fusion-arms rrf3 rrf2 wrrf3 cc3 sum_legacy
   ```
5. Produce a citable run, check the exit gate and archive (R2a). A run is `citable: true` only in `--mode live` on the full benchmark with no uncommitted or untracked changes under `src/` or `scripts/` and a tracked, unmodified benchmark file. `--require-clean` refuses to start (exit code 2) when the tree is not clean. `--stats-seed` and `--stats-resamples` control the paired comparison statistics.
   ```bash
   python scripts/evaluate_retrieval.py --fusion-arms rrf3 rrf2 wrrf3 cc3 sum_legacy --require-clean
   # R2a exit gate on three runs at one commit (exit code 0 = PASS)
   python scripts/check_eval_gate.py --runs <run_a> <run_b> <run_c> --max-spurious-clarify 0
   # copy a citable run into the git-tracked archive (takes a run ID, not a path)
   python scripts/archive_eval_run.py <run_id>
   ```
   The thesis cites only runs under `evaluations_archive/`. Runs in `evaluations/` are local working data.
6. Optional orchestrator switch: `ORCH_CATEGORY_RECOVERY=0` disables the category recovery step before the CLARIFY guardrail (default on; see `.env.example`).
