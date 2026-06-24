---
description: "Execute the full Research → Spec → Code → Audit → Document pipeline for implementing a new feature or capability in the CRS recommendation system."
---

# `/implement` — Feature Implementation Pipeline

When the user types `/implement <feature description>`, orchestrate the full development pipeline using the agents defined in `.agents/agents.md` and skills in `.agents/skills/`.

> **This is NOT a generic coding assistant.** This workflow is specifically designed for implementing new features, capabilities, or modules in the Knowledge Graph-enhanced Conversational Recommender System. The `<feature description>` should describe a concrete capability the system needs (e.g., "GraphRAG with review chunking and entity linking", "persistent user profiles with Redis", "preference drift detection using PAMU").

---

## Pre-Flight Check

Before starting the pipeline, perform these checks:

1. **Read `production_artifacts/Vision_Report.md`** — understand current strategic direction, active constraints, and rejected approaches.
2. **Read `docs/project_state_report.md`** — understand what's already implemented.
3. **Validate the feature request**: Does this feature align with the Vision Report's current phase and next priorities? If the request contradicts the vision or proposes a rejected approach, **STOP** and inform the user immediately:
   > "⚠️ This feature conflicts with the Vision Report: [explain]. Would you like to proceed anyway, or should we first run `research_analyst` to revisit this decision?"

---

## Execution Sequence

### Phase 1: Research & Direction Validation (@pm-research)

**Shift context → Research Analyst & Architectural Guardian**

Execute the `research_analyst` skill with the user's `<feature description>` as the research question.

**What this phase does:**
- Reads the Vision Report to establish the strategic baseline
- Researches the feature across web articles, academic papers, official documentation, and the project's own `prompts_and_req/` foundational documents
- Validates that the proposed feature is consistent with the project's goals and doesn't introduce unnecessary complexity
- Produces a technology comparison if multiple approaches exist
- Assesses impact on the existing codebase (references actual file paths in `src/`)

**Output:** `production_artifacts/Research_Report.md`

**🚦 APPROVAL GATE #1 — Direction**

Halt and present findings to the user:
> "Research complete. Report saved to `production_artifacts/Research_Report.md`.
> **Recommended approach:** [summary]
> **Guardian assessment:** [aligns/deviates from vision]
> Do you approve this direction?"

- ✅ **User approves** → Update the Vision Report's Decision Log with the approved direction. Proceed to Phase 2.
- 🔄 **User gives feedback** → Rework the Research Report. Re-present for approval.
- ❌ **User rejects** → Stop the pipeline. Document the rejection in the Vision Report's Rejected Approaches table.

---

### Phase 2: Technical Specification (@pm-specs)

**Shift context → Technical Specification Writer**

Execute the `write_specs` skill, using the approved Research Report as input.

**What this phase does:**
- Reads the Vision Report and the approved Research Report
- Translates the approved direction into a rigorous Technical Specification
- Defines functional/non-functional requirements, architecture, API design, data models
- Maps every new component to exact locations in the existing codebase (`src/`, `scripts/`, `tests/`)
- Defines acceptance criteria that the QA Engineer will later verify against

**Output:** `production_artifacts/Technical_Specification.md`

**🚦 APPROVAL GATE #2 — Specification**

Halt and present the spec to the user:
> "Technical Specification drafted and saved to `production_artifacts/Technical_Specification.md`.
> **Key decisions that need your attention:** [list]
> Do you approve? You can open the file and add comments for rework."

- ✅ **User says "Approved"** → Proceed to Phase 3.
- 🔄 **User gives feedback or adds comments in the file** → Re-read the spec, apply changes, re-present. **Loop until the user explicitly says "Approved".**
- ❌ **User rejects** → Stop the pipeline. Ask if they want to return to Phase 1 with a different direction.

---

### Phase 3: Implementation (@engineer)

**Shift context → Full-Stack Engineer**

Execute the `generate_code` skill based on the approved Technical Specification.

**What this phase does:**
- Reads the approved Technical Specification and Vision Report
- Scans the existing codebase to understand current patterns and conventions
- Scaffolds the complete file structure (empty files with signatures and docstrings)

**🚦 APPROVAL GATE #3 — File Structure**

Halt after scaffolding and present the structure:
> "File structure scaffolded. Here's what will be created and modified: [list]
> Do you approve this structure before I write the full implementation?"

- ✅ **User approves** → Write full implementation code. Complete all functions — no placeholders.
- 🔄 **User gives feedback** → Adjust the structure. Re-present.

After full implementation:
- Run basic self-verification (syntax, imports, interface compliance)
- Report what was built

**Output:** Production code in `src/`, `scripts/`, etc.

---

### Phase 4: Quality Audit (@qa)

**Shift context → QA Engineer**

Execute the `audit_code` skill against the approved Technical Specification.

**What this phase does:**
- Walks every requirement and acceptance criterion from the spec
- Performs static analysis (dependencies, imports, types, error handling)
- Runs `pytest` on existing and new tests
- Hunts for bugs (logic errors, race conditions, resource leaks, Neo4j/LLM specifics)
- Fixes 🔴 Critical and 🟠 High severity issues directly in source
- Produces a structured audit report with a PASS / FAIL verdict

**Output:** `production_artifacts/Audit_Report.md` + fixes applied in source

**🚦 QUALITY GATE**

- **PASS** → Proceed to Phase 5.
- **PASS WITH FIXES** → Report what was fixed. Proceed to Phase 5.
- **FAIL** → Report critical unfixed issues. Ask user:
  > "The audit found issues that require rework. Should I:
  > (a) Return to Phase 3 (@engineer) to fix implementation issues?
  > (b) Return to Phase 2 (@pm-specs) if the spec itself needs revision?"

---

### Phase 5: Project Chronicle (@historian)

**Shift context → Project Historian**

Execute the `update_project_state` skill.

**What this phase does:**
- Analyzes what was built, modified, and added during this pipeline run
- Appends a new dated changelog entry to `docs/project_state_report.md`
- Cross-references the Vision Report to contextualize the changes
- Written in Polish (as per project convention)

**Output:** New dated entry in `docs/project_state_report.md`

---

### Phase 6: Documentation Cleanup (@doc-cleaner)

**Shift context → Documentation Auditor**

Execute the `clean_docs` skill.

**What this phase does:**
- Audits all project documentation against the newly implemented feature
- Identifies READMEs, diagrams, and docs that are now outdated due to this change
- Fixes stale references, updates architecture diagrams
- Flags deletions and major rewrites for user approval

**Output:** `production_artifacts/Documentation_Audit_Report.md` + fixes applied

---

## Pipeline Summary

At the end of the full pipeline, present a consolidated summary:

> "✅ **Pipeline complete for: `<feature description>`**
>
> | Phase | Status | Output |
> |-------|--------|--------|
> | 1. Research | ✅ Approved | `Research_Report.md` |
> | 2. Specification | ✅ Approved | `Technical_Specification.md` |
> | 3. Implementation | ✅ Complete | [N] files created, [N] modified |
> | 4. Audit | ✅ PASS | `Audit_Report.md` |
> | 5. Changelog | ✅ Updated | `project_state_report.md` |
> | 6. Docs Cleanup | ✅ Complete | `Documentation_Audit_Report.md` |
>
> The Vision Report has been updated with the decision log entry for this feature."

---

## Error Handling & Recovery

| Scenario | Action |
|----------|--------|
| User abandons pipeline mid-way | All artifacts produced so far are preserved. Pipeline can be resumed from any phase. |
| Research reveals the feature shouldn't be built | Stop at Phase 1. Record in Vision Report's Rejected Approaches. |
| Spec approval loop exceeds 3 iterations | Ask user: "We've iterated 3 times. Would you like to step back to research and reconsider the approach?" |
| Audit fails twice on the same issue | Escalate to user: "This issue may require a spec revision, not just a code fix." |
| Feature conflicts with Vision Report constraints | Stop immediately. Do not proceed without explicit user override. |
