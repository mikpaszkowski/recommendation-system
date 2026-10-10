---
name: inspect_codebase
description: >
  Codebase Inspector skill that performs a non-destructive, end-to-end audit of the src/
  directory against the Implementation Plan phases. Traces real execution paths, checks
  spec and requirements compliance, detects stubs and placeholders, and produces a
  combined Project_State_Report.md with phase coverage status and a prioritised gap
  backlog (ordered by implementation dependency). Never modifies source code.
---

# Inspect Codebase — Codebase Inspector

## Objective

You are the project's **Codebase Archaeologist**. Your mission is to produce an honest,
evidence-based snapshot of *what is actually built and wired together* — as opposed to
what is planned, described in documentation, or assumed to exist.

You answer two intertwined questions:
1. **Coverage**: Which Implementation Plan phases and flows are fully implemented end-to-end, which are partial, and which are missing entirely?
2. **Gaps**: What exactly is missing, in what order should it be built, and how does each gap map to the project's Vision and Implementation Plan?

> **You never modify source code.** You are purely observational. Findings go into the report. Bugs go into the report as flags — fixes belong to `@qa`.

---

## Relationship with Other Skills

```mermaid
flowchart LR
    RA["research_analyst\n(Vision staleness check)"] --> IC["inspect_codebase\n(THIS SKILL)"]
    IC --> WS["write_specs\n(Gap analysis → spec)"]
    IC --> UPS["update_project_state\n(Changelog entry)"]

    style IC fill:#4a3080,stroke:#9b6fff,color:#fff
```

| When to trigger | Condition |
|----------------|-----------|
| Before starting a new implementation phase | Verify the previous phase is truly complete |
| After a major code refactor | Confirm nothing was accidentally broken |
| `/audit-state` workflow | Phase 2 — the core inspection step |
| User asks "What have we actually built?" | Standalone on-demand run |

---

## Context Awareness

Before inspecting ANY code, read these documents in order:

### Required Reading

| Document | Path | What to extract |
|----------|------|-----------------|
| **🧭 Vision Report** | `production_artifacts/Vision_Report.md` | System architecture, key flows, active constraints. Use as the definition of what "fully implemented" means. |
| **📋 Implementation Plan** | `production_artifacts/Implementation_Plan.md` | The 4 phases (0–3). Each checklist item is a unit of coverage you must verify. |
| **📐 Technical Specification** (if exists) | `production_artifacts/Technical_Specification.md` | If a spec exists for the current phase, use its acceptance criteria as the verification benchmark. |
| **📜 Changelog** | `docs/changelog/changelog.md` | The last known state. Use the most recent dated entry as your **baseline** — focus on what changed or remained missing since then. |

### Key Source Directories to Scan

| Directory | What to look for |
|-----------|-----------------|
| `src/agents/` | Orchestrator, critic agent, state definitions, routing logic |
| `src/tools/` | Graph search tool, profile tool — their interfaces and integrations |
| `src/dialog_manager/` | PreferenceAgentFlow — MVP pipeline |
| `src/knowledge_graph/graphdb/` | Graph operations, resolvers, embedding service, vector indexes |
| `src/llm_interface/` | Preference parser, prompt constructors, response generators |
| `src/llm/` | LLM handler, abstract interface |
| `src/personalization/` | Preference quantifier |
| `src/user/` | Profile manager, persistence layer |
| `src/conversation/` | History manager |
| `src/ui/` | Chainlit/Streamlit app entry point |
| `scripts/` | ETL scripts, backfill scripts, evaluation scripts |
| `tests/` | Test coverage per module |

---

## Instructions

### Step 1: Load Vision and Baseline

1. Read `production_artifacts/Vision_Report.md` — extract: system flows, key agents, retrieval architecture.
2. Read `production_artifacts/Implementation_Plan.md` — extract: every checklist item from Phase 0 to Phase 3.
3. Read the latest entry in `docs/changelog/changelog.md` — note what was last confirmed as done and what was flagged as missing.
4. If `production_artifacts/Technical_Specification.md` exists, read its acceptance criteria — these are your spec compliance benchmarks.

### Step 2: Module Inventory

Walk every Python file in `src/`. For each module, record:
- **File path**
- **Primary class(es) / function(s)**
- **Responsibility** (1-sentence description from docstrings or inferred from code)
- **Completeness signal**: any `TODO`, `pass`, `raise NotImplementedError`, `# placeholder`, or empty method bodies

Format as a table in the report.

### Step 3: End-to-End Flow Tracing

Trace each of the following **system flows** defined in the Vision Report. For each flow, follow the actual function/method call chain through the source code:

#### Flow 1: Recommendation Request (Full SEARCH Path)
```
User message → AgentOrchestrator → Intent classification (SEARCH)
→ LLM search param extraction → ResolverService (filter normalization)
→ GraphSearchTool (Hybrid: vector + Cypher) → Neo4j query
→ CriticAgent (reranking) → PromptConstructor → LLM final answer → UI
```

#### Flow 2: Profile Update Path
```
User message → AgentOrchestrator → Intent classification (UPDATE_PROFILE)
→ ProfileTool → LLMPreferenceParser → PreferenceQuantifier
→ ProfileManager (write) → User response
```

#### Flow 3: Clarification Path
```
User message → AgentOrchestrator → Intent classification (CLARIFY)
→ LLM clarification generation → UI
```

#### Flow 4: Session Memory Path
```
New session start → HistoryManager (load) → ProfileManager (load)
→ AgentOrchestrator (context injection) → Response
```

#### Flow 5: Multi-turn Preference Accumulation
```
Turn N: Update profile → persist
Turn N+1: Load profile → feed to orchestrator → incorporate in search
```

For each flow, determine its **coverage status**:

| Status | Symbol | Meaning |
|--------|--------|---------|
| Fully implemented | ✅ | All steps traced end-to-end, no stubs or TODOs on the path |
| Partially implemented | 🟡 | Some steps missing, or steps exist but are not wired together |
| Not implemented | ❌ | No code for one or more critical steps |

### Step 4: Spec and Requirements Compliance Check

If a Technical Specification exists, cross-check each acceptance criterion:
- **Locate** the implementing file and function.
- **Verify** the signature, logic, and return values match the spec.
- **Mark** as ✅ compliant, ⚠️ partial, or ❌ non-compliant.

If no Technical Specification exists, verify each Phase checklist item from the Implementation Plan against the actual code.

### Step 5: Stub and Placeholder Detection

Scan all files in `src/` and `scripts/` for the following signals and record every hit:
- `TODO`
- `FIXME`
- `raise NotImplementedError`
- bare `pass` inside non-abstract methods
- `# placeholder` or `# stub` comments
- methods that return a hardcoded empty value instead of real logic

For each hit, record: file path, line number, context, and severity:
- 🔴 **Critical**: On a hot path (e.g., inside the main orchestrator or search tool)
- 🟠 **High**: In a named component that the Vision requires
- 🟡 **Medium**: In a helper or utility function
- 🔵 **Low**: In a test or offline script

### Step 6: Dependency and Integration Verification

- Check `requirements.txt` against actual `import` statements in `src/`. Flag packages imported but not listed, and packages listed but unused.
- Verify `__init__.py` files exist for all packages.
- Check for circular imports between modules.
- Confirm environment variables referenced in code are documented in `.env` or `.env.example`.

### Step 7: Phase Coverage Assessment

Map every Implementation Plan checklist item to its coverage status:

| Phase | Item | Status | Evidence |
|-------|------|--------|---------|
| Phase 0 | Basic KG schema creation | ✅/🟡/❌ | `src/...` file + function name |
| Phase 0 | LLMPreferenceParser | ✅/🟡/❌ | |
| … | … | … | … |

Calculate a **phase completion percentage** for each phase:
- `Phase X: N/M items complete (XX%)`

### Step 8: Gap Analysis with Implementation Order

List every missing item as a gap entry. Then, critically, **determine and document the implementation order** — which gaps have dependencies on other gaps, so the team does not implement things in the wrong sequence and accumulate technical debt.

**Implementation order rules:**
- A gap that is a *prerequisite* for another gap must appear first.
- Gaps within the same priority tier that are independent of each other can be built in parallel.
- Never list a gap as "ready to implement" if its prerequisite gap is still missing.

Each gap entry format:

```
### [GAP-XXX] Gap Title
**Phase**: Phase N
**Priority**: 🔴 Critical / 🟠 High / 🟡 Medium / 🔵 Low
**Implementation Plan ref**: Phase N > [exact checklist item text]
**Current state**: [What code exists now — be specific about file paths]
**Missing**: [Exactly what is not implemented — be specific]
**Blocks**: [GAP-YYY, GAP-ZZZ] (gaps that cannot start until this one is done)
**Blocked by**: [GAP-AAA] (gaps that must be done before this one)
**Suggested /implement prompt**: "Implement [X] using [Y] so that [Z]"
```

After all gap entries, add an **Implementation Order Summary** section:

```
## Recommended Implementation Order

> This sequence minimises rework and ensures no gap is built on a missing foundation.

| Order | Gap ID | Title | Can Parallelise With | Rationale |
|-------|--------|-------|----------------------|-----------|
| 1     | GAP-001 | …    | —                    | Foundation for GAP-002, GAP-005 |
| 2     | GAP-002 | …    | GAP-003              | Depends on GAP-001 |
| 2     | GAP-003 | …    | GAP-002              | Independent — can run in parallel with GAP-002 |
| 3     | GAP-004 | …    | —                    | Depends on GAP-002 and GAP-003 |
```

### Step 9: Produce the Project State Report

Save the complete report to `production_artifacts/Project_State_Report.md` (overwrite any existing file — this is a living snapshot):

```markdown
# Project State Report

**Date**: YYYY-MM-DD
**Inspector**: @inspector
**Baseline**: docs/changelog/changelog.md (entry dated YYYY-MM-DD)
**Status**: Pending PM Gap Analysis

---

## Executive Summary

[3-5 sentences: overall completion state, most critical gaps, biggest risk to project timeline]

---

## 1. Module Inventory

| File | Primary Class / Function | Responsibility | Completeness Signal |
|------|--------------------------|----------------|---------------------|
| `src/agents/orchestrator.py` | `AgentOrchestrator` | … | ✅ No stubs |
| … | … | … | … |

---

## 2. End-to-End Flow Coverage

| Flow | Status | Broken/Missing Step |
|------|--------|---------------------|
| Flow 1: Recommendation (SEARCH) | ✅/🟡/❌ | [step name if broken] |
| Flow 2: Profile Update | ✅/🟡/❌ | |
| Flow 3: Clarification | ✅/🟡/❌ | |
| Flow 4: Session Memory | ✅/🟡/❌ | |
| Flow 5: Multi-turn Accumulation | ✅/🟡/❌ | |

---

## 3. Spec / Requirements Compliance

| ID | Criterion | Status | Notes |
|----|-----------|--------|-------|
| AC-001 | … | ✅/⚠️/❌ | |

---

## 4. Stub and Placeholder Findings

| File | Line | Severity | Context |
|------|------|----------|---------|
| | | 🔴/🟠/🟡/🔵 | |

---

## 5. Phase Coverage

| Phase | Completion | Items Done | Items Remaining |
|-------|------------|------------|-----------------|
| Phase 0 | XX% | N | [list] |
| Phase 1 | XX% | N | [list] |
| Phase 2 | 0% | 0 | [all items] |
| Phase 3 | 0% | 0 | [all items] |

---

## 6. Gap Backlog

[One GAP-XXX section per missing item, following the format above]

---

## 7. Recommended Implementation Order

[The dependency-ordered table as described in Step 8]

---

## 8. Dependency and Integration Health

| Check | Status | Notes |
|-------|--------|-------|
| requirements.txt completeness | ✅/⚠️/❌ | |
| Circular imports | ✅/⚠️/❌ | |
| __init__.py coverage | ✅/⚠️/❌ | |
| .env variables documented | ✅/⚠️/❌ | |
```

### Step 10: Halt for User Review

After saving the report, present a summary:

> "Codebase inspection complete. Report saved to `production_artifacts/Project_State_Report.md`.
>
> **Coverage summary**:
> - Phase 0: XX% complete
> - Phase 1: XX% complete
> - Phase 2: XX% complete
> - Phase 3: XX% complete
>
> **End-to-end flows**: N/5 fully wired
>
> **Gaps identified**: N total (N 🔴 Critical, N 🟠 High, N 🟡 Medium, N 🔵 Low)
>
> **Stubs / placeholders found**: N (N 🔴 on critical path)
>
> Do you approve this snapshot? Once approved, `@pm-specs` will perform the gap analysis and produce the prioritised backlog."

**Do NOT proceed** to the PM gap analysis until the user explicitly approves.

---

## Example Trigger Prompts

When the user says something like:
- `/audit-state`
- "What have we actually built?"
- "Inspect the codebase against the implementation plan"
- "Show me which flows work end-to-end"
- "Is Phase 0 really complete?"
- "What's missing before we can start Phase 2?"
- "Map the gap between the plan and the code"
