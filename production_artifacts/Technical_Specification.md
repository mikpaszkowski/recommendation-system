# Technical Specification: Dynamic Domain Schema Extraction

**Date**: 2026-09-29
**Author**: Product Manager Agent (@pm-specs)
**Status**: Draft — Pending Approval
**Related Research**: [Research_Report.md](file:///Users/mikolajpaszkowski/recommendation-system/production_artifacts/Research_Report.md)

## 1. Executive Summary

This specification outlines the technical approach to replace the hardcoded `domain_schemas.json` (which limits the conversational agent to only 3 categories) with a dynamic, graph-derived schema cache. A new offline script will traverse the Neo4j Knowledge Graph to extract the actual product categories and their corresponding features, saving them to `dynamic_domain_schemas.json`. The `preference_parser.py` will be updated to selectively inject these schemas during prompt construction, ensuring the LLM is accurately grounded in the specific Amazon dataset without overwhelming the context window or introducing chat-time database latency.

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority | Description |
|----|-------------|----------|-------------|
| FR-001 | Offline Schema Extraction | Must | A standalone Python script must query the Neo4j Knowledge Graph to extract all unique `Category` nodes and their associated `Feature` attributes. |
| FR-002 | Schema Caching | Must | The extracted schema must be serialized to a JSON file (`src/knowledge_graph/dynamic_domain_schemas.json`). |
| FR-003 | Selective Prompt Injection | Must | `preference_parser.py` must load the dynamic JSON and inject a flat list of categories into the prompt. Detailed attributes should only be injected if a specific category is already present in the session context. |
| FR-004 | Removal of Hardcoded JSON | Must | The existing `src/llm_interface/domain_schemas.json` must be deleted. |

### 2.2 Non-Functional Requirements

| ID | Requirement | Target | Description |
|----|-------------|--------|-------------|
| NFR-001 | Performance | <50ms | Reading the cached JSON and injecting the schema into the prompt must not add perceptible latency to the dialogue turn. |
| NFR-002 | Scalability | Hundreds of Categories | The selective injection strategy must ensure that context limits are not exceeded even if the graph contains 500+ categories. |
| NFR-003 | Data Provenance | Strict Alignment | The injected schema must perfectly match the actual data in the Neo4j graph, preventing LLM property hallucination. |

## 3. Architecture & Tech Stack

### 3.1 Technology Choices

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Extraction Script | Python + Neo4j driver | Reuses existing `Neo4jConnector` for graph traversal. |
| Schema Storage | JSON (File System) | O(1) read latency, easily inspectable, integrates natively with existing `preference_parser.py` logic. |
| Prompt Construction | String Interpolation | Reuses the existing logic in `preference_parser.py` with modifications for selective injection. |

### 3.2 Integration with Existing System

- **Knowledge Graph**: The extraction script (`scripts/extract_domain_schemas.py`) will import and instantiate `Neo4jConnector` from `src/knowledge_graph/graphdb/neo4j_connector.py`.
- **LLM Interface**: `src/llm_interface/preference_parser.py` will be modified to point to the new `dynamic_domain_schemas.json` file. It will receive the current `SessionContext` (or at least the identified category) to determine which detailed attributes to inject.

## 4. API / Interface Design

### 4.1 New Interfaces

**`scripts/extract_domain_schemas.py`**
- Connects to Neo4j.
- Executes Cypher query:
  ```cypher
  MATCH (p:Product)-[:HAS_CATEGORY]->(c:Category)
  MATCH (p)-[:HAS_FEATURE]->(f:Feature)
  RETURN c.name AS category, collect(DISTINCT f.name) AS features
  ```
- Formats the output matching the old JSON structure (global attributes + domains) and writes to `src/knowledge_graph/dynamic_domain_schemas.json`.

### 4.2 Modified Interfaces

**`src/llm_interface/preference_parser.py`**
- `extract_preferences(user_input: str, session_context: Optional[SessionContext] = None)`
  - Currently loads `domain_schemas.json`.
  - **Change**: Load `src/knowledge_graph/dynamic_domain_schemas.json`.
  - **Change**: Implement logic to extract the `category` from `session_context.extracted_parameters.hard_constraints` (if available).
  - **Change**: Modify prompt construction:
    - ALWAYS inject global attributes.
    - ALWAYS inject a flat list of available categories.
    - ONLY inject domain-specific attributes for the category identified in the context (if any). If no category is identified, do not inject detailed attributes to save tokens.

## 5. Data Model / State Management

### 5.1 New Data Structures

The output JSON structure will remain similar to the existing one for backward compatibility:
```json
{
  "global_attributes": [
    "price",
    "brand",
    "category",
    "model"
  ],
  "domains": {
    "monitors": ["refresh_rate", "resolution", ...],
    "fashion": ["size", "color", "material", ...],
    ...
  }
}
```

### 5.2 Data Flow

1. **Offline**: Developer/Pipeline runs `python scripts/extract_domain_schemas.py`.
2. Script queries Neo4j -> Builds JSON -> Saves to disk.
3. **Runtime**: User says "I want a blue dress".
4. `preference_parser.py` reads JSON.
5. If context category is "fashion", it injects fashion features ("size", "color", "material") into the prompt.
6. LLM parses constraints cleanly.

## 6. Implementation Phases

| Phase | Scope | Dependencies | Estimated Effort |
|-------|-------|-------------|-----------------|
| 1 | Create `extract_domain_schemas.py` and generate the JSON file. | Neo4j Connection | Low |
| 2 | Update `preference_parser.py` for selective injection. | Phase 1 | Low |
| 3 | Delete `domain_schemas.json` and run tests. | Phase 2 | Low |

## 7. File Structure

### New Files
- `scripts/extract_domain_schemas.py` — Script to query Neo4j and generate the schema JSON.

### Modified Files
- `src/llm_interface/preference_parser.py` — Update schema loading path and implement selective injection logic.
- `src/llm_interface/domain_schemas.json` — **DELETE** (superseded by dynamic version).

## 8. Acceptance Criteria

| ID | Criterion | Verification Method |
|----|-----------|-------------------|
| AC-001 | Schema extraction script successfully generates JSON containing all categories from the KG. | Manual execution & JSON inspection |
| AC-002 | `preference_parser.py` successfully loads the dynamic JSON without errors. | Unit test execution |
| AC-003 | Prompt correctly contains detailed attributes ONLY for the active category in the context. | Unit test / Print prompt |
| AC-004 | Existing dialogue parsing tests (e.g. `test_preference_parser.py`) pass without modification to their assertions. | Unit test execution (`pytest tests/test_preference_parser.py`) |

## 9. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|-----------|
| Broken Tests | Medium | Medium | The previous static JSON only had 3 domains. Some tests might assume specific attributes are always present in the prompt. We will need to run the full test suite and ensure test fixtures are updated if necessary. |
| Cypher Query Performance | Low | Low | The extraction runs offline. It will not impact runtime latency. |

## 10. Open Questions

- Should we run this script automatically as part of the Neo4j ingestion pipeline (e.g. in `backfill_embeddings.py` or similar), or just document it as a manual prerequisite step for now?
