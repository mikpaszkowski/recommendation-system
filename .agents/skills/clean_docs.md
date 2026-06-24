---
name: clean_docs
description: >
  Documentation Auditor skill that systematically reviews all project documentation
  (markdown, diagrams, READMEs) against the Vision Report, Technical Specifications,
  and actual codebase to identify outdated, duplicated, conflicting, and missing content.
  Produces a Documentation Audit Report and applies fixes directly. Ensures the project's
  written documentation accurately reflects the system as it actually exists.
---

# Clean Docs — Documentation Auditor

## Objective

Your goal as the **Documentation Auditor** is to ensure every piece of documentation in this project **accurately reflects reality**. You cross-reference all docs against the Vision Report, the actual codebase, and each other — then classify, clean, and consolidate.

## Why This Matters

Documentation debt is insidious. Over time:
- READMEs describe modules that no longer exist
- Diagrams show architectures that have been superseded
- Multiple documents explain the same thing with subtle contradictions
- Foundational docs describe plans that were implemented differently (or abandoned)

When agents read stale documentation, they make stale decisions. This skill prevents that.

## Context Awareness

Before auditing, you MUST read the project's source of truth documents in this order:

### Primary References (What the project IS)

| Document | Path | Role in audit |
|----------|------|---------------|
| **🧭 Vision Report** | `production_artifacts/Vision_Report.md` | The canonical strategic direction. Documentation must not contradict this. |
| **📋 Project State Report** | `docs/project_state_report.md` | What was actually built. Documentation claims must match this. |
| **The actual codebase** | `src/`, `scripts/`, `tests/` | The ultimate truth. If code and docs disagree, the code is right. |

### Secondary References (What the project PLANNED)

| Document | Path | Role in audit |
|----------|------|---------------|
| **Technical Specification** (if exists) | `production_artifacts/Technical_Specification.md` | Latest approved spec — check if docs reflect recent spec changes. |
| **Research Report** (if exists) | `production_artifacts/Research_Report.md` | Latest research findings — check if docs reflect approved direction. |

## Audit Scope

The skill audits ALL documentation in the project. Here is the full inventory of documentation locations:

| Location | Content Type | Expected State |
|----------|-------------|----------------|
| `README.md` (root) | Project overview, setup instructions | Should reflect the current system, not Phase I |
| `src/README.md` | Source code architecture overview | Should match current module structure |
| `docs/project_state_report.md` | Living changelog | Managed by `update_project_state` — do NOT modify entries, only flag issues |
| `docs/kg_pipeline/` | KG pipeline documentation (schema, architecture, extensibility) | Should match current Neo4j schema and pipeline |
| `prompts_and_req/` | Foundational design documents | Static references — flag if they contradict Vision Report but do NOT modify |
| `diagrams/` | Mermaid diagrams (ASTE flow, KG state-of-art, node/edge schema) | Should match current architecture |
| `production_artifacts/Vision_Report.md` | Strategic ledger | Managed by `research_analyst` — flag issues but do NOT modify |
| `chainlit.md` | Chainlit UI welcome message | Should reflect current capabilities |
| `.agents/` | Agent skill definitions, agents.md | Should match current skill inventory |

## Rules of Engagement

### Classification System

Classify every documentation artifact using these categories:

| Status | Symbol | Meaning | Action |
|--------|--------|---------|--------|
| **Valid** | ✅ | Content accurately reflects current state | No action needed |
| **Outdated** | ⏰ | Content describes something that has changed or no longer exists | Fix or flag for removal |
| **Duplicated** | 📋 | Same information exists in multiple places | Consolidate — keep the canonical version, remove or link from others |
| **Conflicting** | ⚠️ | Two documents disagree about the same thing | Resolve — the codebase is the tiebreaker |
| **Missing** | 🕳️ | Something important exists in code but has no documentation | Flag for creation |
| **Stale Reference** | 🔗 | Links to files, classes, or paths that no longer exist | Fix the reference |

### Fix Rules

1. **DO fix**: Outdated file paths, broken references, incorrect class/method names, stale directory structures in READMEs, outdated Mermaid diagrams.
2. **DO consolidate**: When the same information exists in 3+ places, keep the canonical version and replace duplicates with links.
3. **DO NOT modify**: Foundational documents in `prompts_and_req/` — these are historical records. Flag contradictions but preserve them as-is.
4. **DO NOT modify**: Existing entries in `docs/project_state_report.md` — this is an append-only log.
5. **DO NOT modify**: `production_artifacts/Vision_Report.md` — this is managed by `research_analyst`.
6. **ASK before deleting**: Never delete a file without explicit user approval. Propose deletions in the audit report.

## Instructions

### Step 1: Build the Documentation Inventory

Scan every directory for documentation files (`.md`, `.txt`, `.html`, Mermaid diagrams). For each file, record:
- File path
- Last known purpose
- Approximate size / scope
- Which phase of the project it belongs to (Phase I, Phase II, or general)

### Step 2: Cross-Reference Against Reality

For each documentation file, perform three checks:

#### Check A: Codebase Alignment
- Does the doc reference file paths that still exist?
- Does it reference classes, methods, or modules that still exist?
- Does it describe behavior that matches the actual code?
- Does the directory structure described match reality?

```
Example: src/README.md says "recommendation_engine/" exists.
Reality: src/ has agents/, tools/, knowledge_graph/, etc.
Verdict: ⏰ Outdated — directory structure has completely changed.
```

#### Check B: Vision Report Alignment
- Does the doc's described architecture match the Vision Report's "Current Strategic Direction"?
- Does it reference approaches listed in the Vision Report's "Rejected Approaches"?
- Does it reflect the current phase of the project?

```
Example: A doc says "System uses PreferenceAgentFlow as the main entry point."
Vision Report: "Active entry point: AgentOrchestrator"
Verdict: ⏰ Outdated — entry point changed in Phase II.
```

#### Check C: Cross-Document Consistency
- Does this doc conflict with any other documentation?
- Does it duplicate information that exists elsewhere?
- Is there a "canonical" version of this information?

```
Example: prompts_and_req/ describes the KG schema. docs/kg_pipeline/schema.md also describes it.
Check: Do they agree? Which is more current?
Verdict: 📋 Duplicated or ⚠️ Conflicting — depending on whether they match.
```

### Step 3: Identify Documentation Gaps

Scan the codebase for important components that have NO documentation:
- New modules added since the last documentation update
- Public APIs or interfaces with no docstrings or README coverage
- Configuration requirements (`.env` variables) that aren't documented
- Setup/installation steps that are missing or outdated

### Step 4: Apply Fixes

For each finding:

| Finding Type | Action |
|-------------|--------|
| ⏰ Outdated README | Rewrite to match current state |
| ⏰ Outdated diagram | Update Mermaid code to match current architecture |
| 🔗 Stale reference | Fix the path/class/method name |
| 📋 Duplicated content | Keep canonical version, replace duplicate with a link |
| ⚠️ Conflicting docs | Resolve in favor of the codebase; add a note explaining the correction |
| 🕳️ Missing docs | Flag in the report — do not generate new documentation without user approval |

### Step 5: Produce Documentation Audit Report

Save the report to `production_artifacts/Documentation_Audit_Report.md`:

```markdown
# Documentation Audit Report

**Date**: YYYY-MM-DD
**Auditor**: Documentation Auditor Agent
**Scope**: Full project documentation review

## Executive Summary

[2-3 sentences: overall documentation health, number of issues found, fixes applied]

## Documentation Inventory

| File | Status | Category | Notes |
|------|--------|----------|-------|
| `README.md` | ⏰/✅/⚠️ | [outdated/valid/etc.] | [brief note] |
| `src/README.md` | ⏰/✅/⚠️ | | |
| ... | | | |

## Findings by Severity

### ⚠️ Conflicting Documentation
[Documents that disagree with each other or with the codebase]
- **File A** vs **File B**: [what conflicts, how resolved]

### ⏰ Outdated Documentation
[Documents that describe a state that no longer exists]
- **File**: [what's outdated, what was fixed]

### 📋 Duplicated Content
[Information that exists in multiple places]
- **Topic**: [where it appears, which is canonical, what was consolidated]

### 🔗 Stale References
[Broken links, wrong file paths, non-existent classes]
- **File**: [what reference is broken, how fixed]

### 🕳️ Missing Documentation
[Important components with no documentation]
- **Component**: [what exists in code but has no docs]

### ✅ Valid Documentation
[Documents confirmed as accurate — brief list]

## Fixes Applied

| File | Change | Reason |
|------|--------|--------|
| | | |

## Proposed Actions (Require User Approval)

| Action | File | Reason |
|--------|------|--------|
| Delete | `path/to/file` | [why it should be removed] |
| Create | `path/to/new/doc` | [what important thing is undocumented] |
| Major rewrite | `path/to/file` | [why a simple fix isn't enough] |
```

### Step 6: Present Results

> "Documentation audit complete. Report saved to `production_artifacts/Documentation_Audit_Report.md`.
>
> **Health summary**:
> - [N] documents audited
> - ✅ [N] valid | ⏰ [N] outdated | ⚠️ [N] conflicting | 📋 [N] duplicated | 🕳️ [N] missing
>
> **Fixes applied**: [N] files updated directly
> **Proposed actions**: [N] items need your approval (deletions, major rewrites, new docs)
>
> Would you like to review the proposed actions?"

## When to Trigger

Activate this skill when:
- The user asks "Clean up the documentation" or "Are our docs up to date?"
- After a major implementation milestone (post-audit, post-code-generation)
- The user notices contradictions between different documents
- Before starting a new major feature (ensure the team has accurate context)
- Periodically as maintenance (e.g., monthly documentation health check)

## Example Trigger Prompts

When the user says something like:
- "Audit the documentation"
- "Is the README still accurate?"
- "Clean up the docs — some of them seem outdated"
- "Check if our diagrams still match the architecture"
- "Are there any conflicts between our documents?"
- "What documentation is missing?"
