# Research Report: Dynamic Schema Extraction vs Hardcoded domain_schemas.json

**Date**: 2026-09-29
**Requested by**: User investigation request via /teamwork-preview
**Status**: Pending Approval

## Executive Summary

The current `domain_schemas.json` is hardcoded with only three domains ("monitor", "laptop", "headphones"), severely limiting the system's ability to support the full breadth of the Amazon Reviews 2023 dataset (which spans fashion, cosmetics, and thousands of other categories). Relying on this static file creates a scaling bottleneck and brittleness when product domains change. The recommended approach is to dynamically extract domain schemas directly from the Neo4j Knowledge Graph via an offline synchronization script (caching to `dynamic_domain_schemas.json`) and selectively injecting only relevant attributes during prompt construction.

## Problem Statement

During the implementation of "Robust GraphRAG Retrieval Architecture" (Decision 2026-09-28-006), Schema Injection was introduced using a static `domain_schemas.json` file to constrain LLM property hallucination. However:
1. **Domain Limitation**: It restricts the conversational agent to only 3 hardcoded product categories. If a user asks for "cosmetics" or "fashion", the LLM lacks attribute guidance, leading to potential hallucinations or zero-yield Cypher queries.
2. **Context Window Bloat**: Injecting all domains into the prompt simultaneously will exceed token limits when scaling to the hundreds of categories present in the Amazon dataset.
3. **Data Drift**: If the underlying graph database is updated with new datasets or features, the static JSON becomes immediately out-of-sync, requiring manual developer intervention.

## Research Findings

### Literature & Documentation Review

- **Source**: Knowledge Graph Schema Extraction Strategies
- **Key Takeaways**: Modern GraphRAG implementations do not hardcode ontologies. They utilize graph traversal queries to periodically summarize the active ontology (e.g., node labels and their most frequent outgoing edge properties) and cache this schema.
- **Applicability**: We can run a Cypher query aggregating the most common `Feature` nodes linked to each `Category` in our Amazon-curated Neo4j database, exporting this to a cache file.

### Technology / Approach Comparison

| Criterion | Option A: Hardcoded JSON (Current) | Option B: Dynamic Offline Extraction (Recommended) | Option C: Real-time Neo4j Schema Querying |
|-----------|------------------------------------|----------------------------------------------------|-------------------------------------------|
| Alignment with project vision | Low (fails on full Amazon dataset) | High (Data Provenance maintained) | High |
| Integration with existing stack | Already exists | Native Neo4j aggregation query + cron/script | High Latency risk |
| Implementation complexity | Zero | Low (Single Python extraction script) | Medium (Requires async db calls during chat) |
| Performance characteristics | O(1) latency, but limits context | O(1) latency at chat-time, scalable | High latency per turn |

### Codebase Impact Assessment

- **Affected Files**: `src/llm_interface/preference_parser.py` (needs to read the new dynamic cache and preferably inject only relevant category schemas rather than all of them).
- **New Components**: A new script `scripts/extract_domain_schemas.py` that queries Neo4j to build the JSON dynamically.
- **Scope of Change**: Small. Replaces a static file with an automatically generated one, plus a minor update to the prompt logic.

## Guardian Assessment

### ✅ Vision Alignment
This approach perfectly aligns with the project's strategy to utilize the **Amazon Reviews 2023 dataset exclusively**. By reading the schema directly from the populated graph, the LLM is accurately grounded in the exact data available, supporting Explainability and Data Provenance.

### ⚖️ Complexity Analysis
Extracting the schema offline and caching it as JSON introduces minimal complexity. It avoids the latency overhead of querying Neo4j for the schema on every user message, preserving the `preference_parser.py`'s fast execution time.

### 🔗 Integration Assessment
This integrates seamlessly with the existing `preference_parser.py` (which already reads a JSON file). The only addition is a utility script to query the `neo4j_connector.py` for categories and features.

### ⚠️ Risks & Trade-offs
- The offline cache might be slightly stale if the DB is updated in real-time, but for the scope of the Master's thesis (a static Amazon dataset), data drift post-ingestion is virtually non-existent.
- Prompt length could still be an issue if we inject *all* categories. The `preference_parser.py` should be updated to only inject a flat list of categories, and then only inject detailed attributes if the user's intent is narrowed down to a specific domain.

## Recommendation

### Recommended Approach
1. **Create an extraction script** (`scripts/extract_domain_schemas.py`) that queries Neo4j to generate the schema mapping automatically (e.g., matching Categories to their most common Features/Attributes).
2. **Modify `preference_parser.py`** to read this generated file, but implement **Selective Injection**: inject the global attributes and a flat list of available categories first. If a category is already known in the session context, only inject the specific attributes for that domain to save prompt tokens.
3. Delete the hardcoded `domain_schemas.json` and replace it with this automated workflow.

### Why This Approach
It solves the domain limitation for fashion/cosmetics (or any category in the Amazon dataset) without adding real-time database latency. It respects the Knowledge Graph as the ultimate source of truth, removing manual hardcoding.

### What NOT to Do
Do not implement real-time schema querying inside the dialogue turns (Option C). Adding a Neo4j round-trip purely to fetch schema during the semantic parsing phase will unacceptably increase conversational latency.
