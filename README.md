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
  * `knowledge_graph/` - Neo4j database connectors and resolver services
  * `tools/` - GraphSearchTool and KECRTool for retrieval
  * `llm_interface/` - Prompt parsers and LLM extraction utilities
  * `evaluation/` - Two-Tiered evaluation metrics and harnesses
* `scripts/` - Execution scripts for Graph Ingestion and Retrieval Evaluation
* `tests/` - Comprehensive unit, integration, and Tier 1-4 End-to-End tests
* `production_artifacts/` - Canonical architecture specs, Vision Report, and Academic documentation
* `thesis/` - Master Thesis research contributions and evaluation methodologies
* `docs/` - Project changelog and historical documentation

## Getting Started

1. Set up your Neo4j container:
   ```bash
   cd src/knowledge_graph
   docker-compose up -d
   ```
2. Set up your `.env` based on `.env.example`.
3. Ingest the dataset (Amazon-curated subset):
   ```bash
   python scripts/graph_ingestion/batch_ingest.py
   ```
4. Run the Retrieval Evaluation suite:
   ```bash
   python scripts/evaluate_retrieval.py
   ```
