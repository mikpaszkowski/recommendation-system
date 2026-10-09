# Source Code Architecture

This directory contains the primary components for the Explainable Hybrid GraphRAG Recommendation System.

## Architecture Layout

- `agents/`: Contains the `AgentOrchestrator` and `CriticAgent` driving the multi-agent conversational loop.
- `dialog_manager/`: Contains `SessionContext` models (`session_schema.py`) and translation layers (`session_adapter.py`).
- `evaluation/`: The Two-Tiered Evaluation framework computing NDCG@K, HitRate, and semantic metrics.
- `knowledge_graph/`: Neo4j connection management (`neo4j_connector.py`) and the exact-match `resolver_service.py`.
- `llm_interface/`: LLM abstraction layer for intent extraction, prompt construction, and preference parsing.
- `tools/`: Concrete tool implementations including `GraphSearchTool` (hybrid vector+cypher) and `KECRTool` (graph reasoning).

Please refer to the [root README.md](../README.md) for startup instructions and `production_artifacts/Vision_Report.md` for the core strategic architecture.
