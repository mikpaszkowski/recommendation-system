# Implementation Plan: Explainable Hybrid GraphRAG for Conversational Recommendation

## 1. Solution Architecture (State-of-the-Art)
The system represents a definitive shift from legacy pipelines to a Multi-Agent System (MAS) architecture, utilizing a Neo4j database as both a structured Knowledge Graph (KG) and a vector database.

**Technology Stack:**
* **Database**: Neo4j (for relational graphs and graph traversal) + Neo4j Vector Index (for embeddings).
* **Logic / Agents**: LangChain / LangGraph for state-machine orchestration and multi-agent routing.
* **LLM API**: OpenAI (GPT-4o) / Anthropic for reasoning, planning, extraction, and evaluation (LLM-as-a-judge).
* **Embeddings**: High-quality pre-trained models (e.g., OpenAI `text-embedding-3-small` or `Sentence-Transformers`).
* **Interface**: Chainlit or Streamlit for natural chat UX.

---

## 2. Implementation Phases

### PHASE 0: Minimum Viable Product (Completed)
*Objective: The following points need to be checked and audited to ensure we actually have the MVP implementation fully in place before proceeding to the next phases.*
* [x] Basic knowledge graph schema creation and initial ingestion.
* [x] Implementation of `LLMPreferenceParser` for natural language intent extraction.
* [x] Deterministic query mapping to Cypher expressions (Text-to-Cypher).
* [x] Basic session history and profile management setup.

### PHASE 1: Data Infrastructure and Graph Foundation (Current Focus)
*Objective: Establish a robust Knowledge Graph equipped with advanced vector search capabilities, using the targeted dual-dataset approach.*
* [ ] **Dataset Migration & Schema Mapping**: Transition the system to utilize the **LLM-REDIAL** conversational dataset. Construct a strict Neo4j schema (Users, Items, Categories, Brands, Features) by fetching rich metadata for these specific items from the Amazon Reviews 2023 dataset.
* [ ] **Lexical Graph Construction (GraphRAG)**: Parse unstructured item descriptions and historical reviews into overlapping semantic chunks. Create discrete `(:Chunk)` nodes linked to their parent `(:Item)` nodes.
* [ ] **Semantic Embedding Generation**: Develop a pipeline to generate dense vector embeddings for all structural and lexical nodes. Ensure nodes use a "Rich Context String" (concatenating title, hierarchy, and primary features) before embedding.
* [ ] **Vector Index Configuration**: Configure Neo4j Vector Indexes across the generated embedding properties to enable rapid, cosine-similarity-based Approximate Nearest Neighbor (ANN) searches natively.

### PHASE 2: Agentic Tooling and Multi-Agent Orchestration (MAS)
*Objective: Replace the linear processing script of the MVP with an autonomous, intent-driven agent architecture.*
* [ ] **Hybrid Search Tool (`GraphSearchTool`)**: Refactor the existing retrieval manager into a unified tool that accepts both a `semantic_query` (for vector search) and a `structured_filters` JSON object (for hard Cypher constraints).
* [ ] **Orchestrator (Router) Agent**: Construct the central state-machine using LangGraph. Engineer a strict system prompt forcing the LLM to output a deterministic routing decision: `SEARCH`, `CLARIFY`, `UPDATE_PROFILE`, or `DIRECT_ANSWER`.
* [ ] **Critic Agent**: Introduce a secondary verification loop. Following a retrieval, the Critic evaluates candidate items against the conversational context, flagging and removing items that violate implicit user constraints (e.g., negative review sentiment despite technical match).
* [ ] **Entity-Based Memory (MemoCRS)**: Upgrade the session manager to extract and store discrete user attitudes toward specific entities in a persistent database. Configure the system to fetch only semantically relevant historical preferences at the start of new sessions.

### PHASE 3: Explainability Integration and System Evaluation (Thesis Finalization)
*Objective: Ground the LLM's generative output in verifiable data and rigorously evaluate performance against academic benchmarks.*
* [ ] **Reasoning Path Extraction (KECR Framework)**: Augment the retrieval pipeline to execute Knowledge Enhanced Conversational Reasoning. Graph queries must return both candidate items and the shortest topological paths connecting the item to the user's known preferences.
* [ ] **Explainable Response Generation**: Engineer the final generation prompt to explicitly force the LLM to synthesize its conversational response using *only* the extracted graph reasoning paths as justification.
* [ ] **Quantitative Retrieval Testing**: Execute evaluation scripts over the LLM-REDIAL test split. Calculate **Hit@5, Hit@10, Mean Reciprocal Rank (MRR), and Normalized Discounted Cumulative Gain (NDCG)** to mathematically validate the Hybrid GraphRAG retrieval module.
* [ ] **Qualitative Generative Testing**: Employ an **LLM-as-a-Judge** evaluation framework to process a statistically significant sample of conversational outputs. Score outputs on strict rubrics for **Groundedness** (factual alignment with the graph), **Explainability**, and **Grammatical Correctness**.

---

## 3. Work Methodology
* **Iterative Approach**: Force the system to correctly handle 1 scenario end-to-end (e.g., a multi-turn conversation about a specific book or electronic device), perform manual testing, and then expand to full dataset evaluation.
* **KISS Principle (Keep It Simple, Stupid)**: Avoid custom model training (GNNs/LoRA). Rely on the power of robust system instructions, structured tool calls (Function Calling), and explicit path-finding within the Neo4j graph.
