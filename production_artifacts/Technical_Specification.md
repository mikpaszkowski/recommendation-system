# Technical Specification: Phase A3 — PromptConstructor & Explainable GraphRAG Injection

**Date**: 2026-10-01
**Author**: Product Manager Agent (@pm-specs)
**Status**: Draft — Pending Approval
**Related Docs**: `Implementation_Plan.md` (Phase A3)

## 1. Executive Summary

This specification defines the implementation of **Phase A3: PromptConstructor — Graph Path Injection Slots**. The goal is to prepare the final LLM response generator to accept explicit, structured graph evidence (reasoning paths) and synthesize this evidence with the user's conversational preferences. Rather than letting the LLM hallucinate reasons for a recommendation, the prompt will strictly mandate that all justifications be grounded in the provided `[GRAPH EVIDENCE]` block, cross-referenced with the user's explicit needs.

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority | Description |
|----|-------------|----------|-------------|
| FR-001 | Modify Constructor Signature | High | Update `construct_recommendation_prompt` in `src/llm_interface/prompt_constructor.py` to accept an optional `graph_reasoning_paths: List[Dict[str, Any]]` parameter. |
| FR-002 | Graph Evidence Injection | High | Implement a `_format_graph_evidence()` helper to parse `graph_reasoning_paths` into a human-readable `[GRAPH EVIDENCE]` section within the prompt. |
| FR-003 | Enforce Grounded Synthesis | High | Update the System Message and `_get_reasoning_process()` to explicitly instruct the LLM to synthesize the **User Preferences** with the **Graph Evidence**. |
| FR-004 | Backwards Compatibility | Medium | If `graph_reasoning_paths` is empty or None, the prompt should gracefully fallback to standard conversational recommendation rules without breaking. |

### 2.2 Non-Functional Requirements

| ID | Requirement | Target | Description |
|----|-------------|--------|-------------|
| NFR-001 | Prompt Token Efficiency | Strict | The injected graph paths must be concisely formatted (e.g., `(User)-[BOUGHT]->(Item)`) to avoid exhausting context windows. |

## 3. Architecture & Tech Stack

### 3.1 Technology Choices

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Prompt Formatting | Python (String interpolation) | Inherits from `AbstractPromptConstructor` using LangChain `SystemMessage` and `HumanMessage`. |

### 3.2 Integration with Existing System

- **Input**: The Orchestrator will eventually pass `graph_reasoning_paths` (extracted in Phase A4) down into the `PromptConstructor`.
- **Target File**: `src/llm_interface/prompt_constructor.py`

## 4. API / Interface Design

### 4.1 Modified Interfaces

**`src/llm_interface/prompt_constructor.py`**
- Modify signature:
  ```python
  def construct_recommendation_prompt(
      self,
      user_input: str,
      user_profile: Optional[Dict[str, Any]] = None,
      retrieved_items: Optional[List[Dict[str, Any]]] = None,
      conversation_history: Optional[List[Dict[str, str]]] = None,
      preferences: Optional[Dict[str, Any]] = None,
      graph_reasoning_paths: Optional[List[Dict[str, Any]]] = None
  ) -> List[BaseMessage]:
  ```

### 4.2 Prompt Engineering (Synthesized Grounding)

The internal system prompt will be updated to include the following strict directive inside `_get_reasoning_process()`:

> **[REASONING PROCESS]**
> Follow these steps to recommend:
> 1. **Identify Needs**: Analyze the user's explicit preferences and constraints.
> 2. **Review Candidates**: Analyze the provided candidate items.
> 3. **Synthesize Evidence (CRITICAL)**: You MUST justify your recommendation by connecting the **User's Explicit Preferences** directly to the **[GRAPH EVIDENCE]**. 
>    - Example: "Since you specifically asked for a durable cable [Preference], I recommend this Anker model because our data shows it is frequently reviewed as 'lasting for years' [Graph Evidence]."
> 4. **Do Not Hallucinate**: Do not invent features or reasons that are not explicitly stated in the graph evidence or item details.

## 5. Data Flow

1. Orchestrator calls `construct_recommendation_prompt` with the final list of items and their associated `graph_reasoning_paths`.
2. `PromptConstructor` formats standard blocks (`[USER PROFILE]`, `[ITEMS]`, etc.).
3. `PromptConstructor` checks if `graph_reasoning_paths` exists. If so, it invokes `_format_graph_evidence()` and appends the `[GRAPH EVIDENCE]` block to the `HumanMessage`.
4. The LLM reads the strict system directives, cross-references the user's chat input with the graph evidence, and generates the final explainable response.

## 6. Implementation Phases

| Phase | Scope | Target File |
|-------|-------|-------------|
| 1 | Add `graph_reasoning_paths` to the method signature and implement the `_format_graph_evidence` helper. | `src/llm_interface/prompt_constructor.py` |
| 2 | Rewrite `_get_reasoning_process()` to enforce the Synthesized Grounding rule. | `src/llm_interface/prompt_constructor.py` |
| 3 | Write unit tests verifying the exact injection of the `[GRAPH EVIDENCE]` block and prompt string. | `tests/test_prompt_constructor.py` |

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| AC-001 | Method signature accepts `graph_reasoning_paths` without breaking existing calls that omit it. | Unit Test |
| AC-002 | Output prompt explicitly contains the `[GRAPH EVIDENCE]` block when paths are provided. | Unit Test / String Assertion |
| AC-003 | Output prompt omits the `[GRAPH EVIDENCE]` block entirely when paths are None/Empty. | Unit Test / String Assertion |
| AC-004 | System instructions clearly mandate synthesized reasoning (preferences + graph). | Unit Test / String Assertion |
