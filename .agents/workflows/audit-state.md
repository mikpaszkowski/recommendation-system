---
description: "Perform a backward-looking validation of the project: verify Vision staleness, map end-to-end flow coverage against the Implementation Plan, identify all gaps with implementation order, and feed results into the /implement workflow."
---

# `/audit-state` — Project State Audit Pipeline

When the user types `/audit-state`, orchestrate the full audit pipeline using the agents defined in `.agents/agents.md` and skills in `.agents/skills/`.

> **This is NOT a feature implementation workflow.** This workflow is specifically designed for periodic validation of the project's current state against its agreed vision and implementation plan. It produces a prioritised Gap Backlog embedded in `production_artifacts/Project_State_Report.md`, ready to feed into `/implement`.

---

## Pre-Flight Check

Before starting any phase, perform these checks:

1. **Read `production_artifacts/Vision_Report.md`** — establish the strategic baseline, active constraints, and rejected approaches.
2. **Read `production_artifacts/Implementation_Plan.md`** — understand all phases (0–3) and their checklist items.
3. **Read `docs/changelog/changelog.md`** — identify the latest dated entry. This is your implementation baseline — the last confirmed state of the system.
4. **Check for an existing `production_artifacts/Project_State_Report.md`** — if one exists, display its date and note:
   > "An existing Project State Report was found (dated [DATE]). Running `/audit-state` will overwrite it with a fresh snapshot. Proceeding…"
5. **Validate scope**: This workflow does not implement anything. If the user's intent seems to be feature implementation, redirect:
   > "⚠️ `/audit-state` is a read-only audit workflow. To implement a feature, use `/implement <feature description>` instead."

---

## Execution Sequence

### Phase 1: Vision Staleness Check (`@pm-research`)

**Shift context → Research Analyst & Architectural Guardian**

Execute the `research_analyst` skill with the following fixed research question:

> *"Is the current project vision and implementation plan still valid? Have the core technologies (LangGraph, Neo4j vector indexes, LLM-REDIAL dataset, OpenAI embeddings) evolved in a way that invalidates our current approach? Does the Vision Report's stated 'current phase' match what is documented in docs/changelog/changelog.md?"*

**What this phase does:**
- Reads the Vision Report to establish the strategic baseline.
- Reads `docs/changelog/changelog.md` to verify the stated phase matches documented reality.
- Checks `docs/` for theoretical documents (e.g., `Plan Implementacji Systemu Rekomendacyjnego.md`) to see if they are still aligned with the Vision Report or have been superseded.
- Scans `prompts_and_req/` — note that only `knowledge-graph-pipeline-requirements.md` (specifically the graph pipeline prompt/txt) is considered relevant; other files in this directory are largely historical.
- Performs a targeted staleness check on referenced technologies — not a full feature research, just a "is our direction still sound?" sanity check.
- Produces a **Vision Staleness Assessment** section appended to `production_artifacts/Research_Report.md`.

**Output:** `production_artifacts/Research_Report.md` (Vision Staleness Assessment section)

**🚦 APPROVAL GATE #1 — Direction Validation**

Halt and present findings:
> "Vision staleness check complete. Research Report updated at `production_artifacts/Research_Report.md`.
>
> **Vision assessment**: [CURRENT / PARTIALLY STALE / STALE]
> **Key finding**: [1-sentence summary]
> **Phase alignment**: Does Vision Report phase match changelog? [Yes/No — explain if No]
>
> Do you approve this assessment and want to proceed to codebase inspection?"

- ✅ **User approves** → Proceed to Phase 2.
- 🔄 **User gives feedback** → Rework the assessment. Re-present.
- ❌ **Vision is stale** → Stop. Ask the user: "The Vision Report appears outdated. Would you like to run a full `/implement` research phase to update it before auditing the codebase?"

---

### Phase 2: Codebase Inspection (`@inspector`)

**Shift context → Codebase Inspector**

Execute the `inspect_codebase` skill.

**What this phase does:**
- Reads the Vision Report, Implementation Plan, latest changelog entry, and Technical Specification (if it exists).
- Builds a complete module inventory of all files in `src/`.
- Traces 5 end-to-end system flows through the actual source code, confirming whether each step is implemented and wired.
- Checks spec compliance against accepted criteria (if a Technical Specification exists) OR verifies Implementation Plan checklist items directly.
- Detects all stubs, `TODO`s, `NotImplementedError` raises, and placeholders — classified by severity.
- Calculates phase completion percentages (Phase 0 through Phase 3).
- Produces a gap backlog where each gap includes: what is missing, what blocks it, what it blocks, and a ready-to-use `/implement` prompt.
- Produces an **Implementation Order Summary** — a dependency-ordered sequence table that prevents the team from building features on missing foundations.
- Verifies dependency and integration health (`requirements.txt`, `__init__.py`, `.env` variables).

**Output:** `production_artifacts/Project_State_Report.md` (overwritten — living snapshot)

**🚦 APPROVAL GATE #2 — Snapshot Review**

Halt and present findings:
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
> **Stubs on critical path**: N
>
> Do you approve this snapshot and want to proceed to PM gap analysis?"

- ✅ **User approves** → Proceed to Phase 3.
- 🔄 **User gives feedback / disputes a finding** → Re-inspect the specific disputed module. Correct the report. Re-present.
- ❌ **User wants to fix critical stubs first** → Stop the pipeline. Direct the user to `/implement` for the critical stub(s) first, then re-run `/audit-state`.

---

### Phase 3: PM Gap Analysis (`@pm-specs`)

**Shift context → Technical Specification Writer (Gap Analysis Mode)**

Execute the `write_specs` skill in **gap analysis mode** — not to produce a spec for a new feature, but to cross-reference the inspection snapshot against the Vision and produce a validated, PM-reviewed Gap Backlog embedded in the State Report.

**What this phase does:**
- Reads `production_artifacts/Project_State_Report.md` (the snapshot from Phase 2).
- Reads `production_artifacts/Vision_Report.md` to validate each gap against strategic priorities.
- Reviews the Inspector's Recommended Implementation Order and validates or revises it based on architectural dependencies and vision priorities.
- Adds a **PM Validation** section to `production_artifacts/Project_State_Report.md`:
  - Confirms or challenges each gap's priority rating.
  - Identifies any gaps the Inspector missed.
  - Identifies any architectural inconsistencies or contradictions between the current code and the agreed vision.
  - Confirms or revises the Implementation Order Summary.
  - Adds a "Next Sprint" recommendation: the top 1–3 gaps to feed into `/implement` immediately.

**Output:** `production_artifacts/Project_State_Report.md` updated with a `## PM Validation` section

**🚦 APPROVAL GATE #3 — Gap Backlog Sign-off**

Halt and present:
> "PM gap analysis complete. `production_artifacts/Project_State_Report.md` has been updated with the PM Validation section.
>
> **Recommended next actions** (top gaps for `/implement`):
> 1. `[GAP-XXX]` — [title] → Suggested prompt: "[/implement prompt]"
> 2. `[GAP-YYY]` — [title] → Suggested prompt: "[/implement prompt]"
>
> **Implementation order**: [N phases in the dependency sequence]
>
> Do you approve this gap backlog? You can open `Project_State_Report.md` and comment on any gap priority or ordering you disagree with."

- ✅ **User approves** → Proceed to Phase 4.
- 🔄 **User gives feedback** → Revise priorities or ordering. Re-present.
- ❌ **User rejects** → Stop. Ask if they want to re-inspect a specific area or reframe the gap analysis.

---

### Phase 4: Project Chronicle (`@historian`)

**Shift context → Project Historian**

Execute the `update_project_state` skill.

**What this phase does:**
- Reads the approved `production_artifacts/Project_State_Report.md` as the source of truth for what this audit found.
- Appends a new dated entry to `docs/changelog/changelog.md` that captures:
  - Phase coverage percentages as of today.
  - End-to-end flows confirmed as working.
  - Key gaps identified and their priorities.
  - The approved implementation order for next steps.
- Written in **Polish** (as per project convention).

**Output:** New dated entry in `docs/changelog/changelog.md`

---

## Pipeline Summary

At the end of the full pipeline, present a consolidated summary:

> "✅ **`/audit-state` pipeline complete**
>
> | Phase | Status | Output |
> |-------|--------|--------|
> | 1. Vision Check | ✅ Approved | `Research_Report.md` (Staleness Assessment) |
> | 2. Codebase Inspection | ✅ Approved | `Project_State_Report.md` (snapshot + gaps) |
> | 3. PM Gap Analysis | ✅ Approved | `Project_State_Report.md` (PM Validation added) |
> | 4. Changelog | ✅ Updated | `docs/changelog/changelog.md` |
>
> **Ready for `/implement`**: Copy any 'Suggested `/implement` prompt' from `Project_State_Report.md` → Section 7 (Recommended Implementation Order) to start building."

---

## Feeding `/implement` After This Workflow

The output of `/audit-state` is designed to feed directly into `/implement`. After the audit:

1. Open `production_artifacts/Project_State_Report.md` → Section 7 "Recommended Implementation Order".
2. Take the **Order 1** gap's "Suggested `/implement` prompt".
3. Run: `/implement <that prompt>`.
4. After completing it, re-run `/audit-state` to update the snapshot and move to the next gap.

---

## Error Handling & Recovery

| Scenario | Action |
|----------|--------|
| Vision Report is significantly stale | Stop at Phase 1. Ask user to update Vision Report first via `@pm-research`. |
| Inspector cannot trace a flow (code too complex) | Inspect the entry point and as many hops as possible. Mark the flow as 🟡 Partial with a note on where the trace stopped. |
| Existing Project_State_Report.md conflicts with what inspector finds | Trust the inspector's fresh read of the source code. Document the discrepancy in the report. |
| User disputes a gap priority | Revise and re-present Phase 3. Do not proceed to Phase 4 until approved. |
| Pipeline abandoned mid-way | All artifacts produced so far are preserved. Resume from the last completed phase by re-triggering the relevant skill. |
