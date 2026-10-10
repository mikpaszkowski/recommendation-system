# Knowledge Graph-enhanced Conversational Recommender System (CRS) 2.0

> **Canonical Source of Truth**: `production_artifacts/Vision_Report.md` — read this before making any architectural decisions.

@production_artifacts/Vision_Report.md
@production_artifacts/Implementation_Plan.md

## Project Overview

A Multi-Agent System (MAS) combining a Neo4j Knowledge Graph, Hybrid GraphRAG retrieval, and LLM-driven orchestration into a conversational recommender for the Master's Thesis: *"Explainable Hybrid GraphRAG for Conversational Recommendation"*.

## Tech Stack

- **Language**: Python 3.11+
- **Database**: Neo4j (structured graph + vector index for ANN search)
- **Agents**: LangChain + procedural Python orchestration
- **LLM**: OpenAI GPT-4o
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (384-dim)
- **UI**: Chainlit (async chat UI)

## Build & Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v --tb=short

# Run specific test module
python -m pytest tests/test_<module>.py -v

# Start the Chainlit UI
chainlit run src/ui/app.py

# Run evaluation scripts
python scripts/evaluate_retrieval.py
python scripts/evaluate_generative.py
```

## Project Structure

- `src/agents/` — Orchestrator, critic agent, state definitions, routing logic
- `src/tools/` — Graph search tool, profile tool, KECR tool
- `src/dialog_manager/` — Session adapter, preference agent flow
- `src/knowledge_graph/graphdb/` — Graph operations, resolvers, embedding service
- `src/llm_interface/` — Preference parser, prompt constructors, response generators
- `src/llm/` — LLM handler, abstract interface
- `src/personalization/` — Preference quantifier
- `src/user/` — Profile manager, persistence layer
- `src/conversation/` — History manager
- `src/evaluation/` — Evaluation metrics
- `src/ui/` — Chainlit app
- `scripts/` — ETL, backfill, evaluation, graph ingestion scripts
- `tests/` — Test suite
- `production_artifacts/` — Vision Report, Implementation Plan, specs, audit reports
- `thesis/` — Academic thesis contribution documents
- `docs/changelog/` — Append-only changelog (written in Polish)

## Coding Conventions

- Use Python type hints for all function signatures and return types
- Write docstrings for all public classes and methods
- Use `logging` module for operational logging — match existing patterns
- Never hardcode secrets or API keys — use environment variables
- Never leave `TODO` comments or `pass` in production code
- Match existing code patterns before writing new code
- Preserve all existing comments and docstrings unrelated to your changes

## Key Architectural Constraints

- **No custom model training** — no GNN, LoRA, R-GCN. Use prompt engineering + RAG only.
- **Amazon Reviews 2023 dataset exclusively** — no LLM-REDIAL dependency
- **Knowledge Graph is the grounding layer** — the system cannot invent products or features
- **Never write code into `app_build/`** — write into `src/`, `scripts/`, `tests/` only
- **Changelog is append-only** — never modify existing entries in `docs/changelog/changelog.md`
- **Vision Report is managed by @pm-research only** — other agents must not modify it
- **Foundational docs in `prompts_and_req/` are historical** — never modify them

## Agent Workflow Pipelines

### `/implement` — Feature Implementation Pipeline

Research (@pm-research) → Spec (@pm-specs) → Code (@engineer) → Audit (@qa) → Changelog (@historian) → Doc cleanup (@doc-cleaner)

Each phase has an approval gate. The user must approve before proceeding.

### `/audit-state` — Project State Audit Pipeline

Vision staleness check (@pm-research) → Codebase inspection (@inspector) → Gap analysis (@pm-specs) → Changelog (@historian)

## File References

- Changelog: `docs/changelog/changelog.md`
- Vision Report: `production_artifacts/Vision_Report.md`
- Implementation Plan: `production_artifacts/Implementation_Plan.md`
- Technical Specification: `production_artifacts/Technical_Specification.md`
- Audit Report: `production_artifacts/Audit_Report.md`
- Project State Report: `production_artifacts/Project_State_Report.md`
- Research Report: `production_artifacts/Research_Report.md`
- Action items & fix proposals (AFPs, audits): `production_artifacts/action_items/` (index in its `README.md`)
