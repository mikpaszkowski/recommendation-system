---
name: update_project_state
description: >
  Skill for updating the project changelog (`docs/changelog/changelog.md`) with a new changelog entry
  after each important or major change to the recommendation system codebase. Automatically analyzes
  what has changed, what was modified, and what are the crucial changes introduced.
---

# Update Project State Report

## Purpose

This skill is triggered after **major or important changes** to the recommendation system. It analyzes the codebase, compares it against the latest entry in `docs/changelog/changelog.md`, and appends a **new dated changelog entry** documenting all meaningful differences.

## When to Trigger

Activate this skill when:
- A new module, service, or component has been added to `src/`
- An existing component's behavior has significantly changed (e.g., new strategy, new algorithm)
- Architecture-level changes occurred (new orchestration pattern, new agent, new pipeline step)
- A previously missing feature from the roadmap has been implemented
- A dependency or integration was added or removed (e.g., new DB, new LLM provider)
- The user explicitly requests a project state update

**Do NOT trigger** for:
- Minor bug fixes, typo corrections, or formatting changes
- Test file additions without corresponding feature changes
- Documentation-only changes (unless they reflect architectural decisions)

## Analysis Procedure

Before writing the changelog entry, perform the following analysis:

### Step 1: Read the Current Report
- Read `docs/changelog/changelog.md` in full.
- Identify the **most recent dated entry** (the topmost `## 📅 YYYY-MM-DD` section).
- Understand what was documented as the last known state.

### Step 2: Scan the Codebase for Changes
Systematically scan these directories and compare against the last report:

| Directory | What to look for |
|-----------|-----------------|
| `src/agents/` | New agents, orchestrator changes, new state fields |
| `src/tools/` | New tools, modified tool interfaces |
| `src/dialog_manager/` | Changes to `PreferenceAgentFlow` |
| `src/knowledge_graph/graphdb/` | New graph operations, new indexes, schema changes |
| `src/llm_interface/` | New parsers, prompt changes, response generators |
| `src/llm/` | LLM handler changes, new providers |
| `src/personalization/` | Quantifier logic changes |
| `src/user/` | Profile manager changes, persistence changes |
| `src/conversation/` | History manager changes |
| `src/ui/` | UI framework changes |
| `scripts/` | New operational scripts |

### Step 3: Classify Changes

Categorize every discovered change into one of these groups:

- **🔴 Nowe komponenty** — entirely new files, classes, or modules not present in the previous report
- **🟡 Korekty / Modyfikacje** — existing components whose behavior, interface, or implementation changed
- **✅ Bez zmian** — components confirmed as unchanged since the last report
- **❌ Nadal brakuje** — features from the roadmap that remain unimplemented
- **🗑️ Usunięte** — components that were removed or deprecated

### Step 4: Identify Crucial Changes

For each change, assess its **impact level**:
- **Critical**: Changes the system's main entry point, data flow, or architecture pattern
- **High**: Adds a new agent, tool, or search strategy
- **Medium**: Modifies an existing component's behavior or interface
- **Low**: Internal refactoring without external behavior change

Focus the changelog narrative on Critical and High impact changes.

## Changelog Entry Format

Insert the new entry **at the top of the file**, immediately after the header block and before the previous dated entry. Use this exact structure:

```markdown
## 📅 YYYY-MM-DD

### Changelog (względem stanu z PREVIOUS_DATE)

#### 🔴 Nowe komponenty (nieopisane w poprzednim raporcie)

1.  **ComponentName (`path/to/file.py`):**
    *   What it does.
    *   Why it matters.

#### 🟡 Korekty / Modyfikacje istniejących komponentów

1.  **`ComponentName`** — what changed and why.

#### ✅ Bez zmian (potwierdzone jako zgodne)

*   List of unchanged components.

#### ❌ Nadal brakuje (względem pełnej wizji projektu)

*   Features still missing from the roadmap.

#### 🗑️ Usunięte / Zdeprecjonowane

*   Components removed (if any). Omit this section if nothing was removed.

### Zaktualizowana Architektura (jeśli zmieniła się)

<!-- Include an updated Mermaid diagram ONLY if the architecture changed -->
```

## Vision Report Cross-Reference

Before writing a changelog entry, read `production_artifacts/Vision_Report.md` to understand the current strategic direction. This helps you:

- **Contextualize changes**: Understand whether a new component advances the agreed-upon next priorities or represents a deviation.
- **Flag alignment issues**: If implemented changes contradict the Vision Report's "Current Strategic Direction" or reintroduce a "Rejected Approach," note this explicitly in the changelog entry.
- **Suggest Vision Report updates**: If the changes you're documenting represent a significant architectural shift (e.g., new phase entered, new constraint established), proactively suggest that the user update the Vision Report:
  > "Te zmiany wprowadzają istotne zmiany architektoniczne. Czy chcesz, żebym zaktualizował `production_artifacts/Vision_Report.md` z nowym wpisem w Decision Log?"

## Rules

1. **Preserve all previous entries** — NEVER modify or delete existing dated sections. Only INSERT new ones at the top.
2. **Be specific** — reference exact file paths, class names, and method names.
3. **Use Polish** — the report is written in Polish. All changelog entries must be in Polish.
4. **Include Mermaid diagrams** — if the architecture changed, include an updated flowchart diagram.
5. **Date format** — always use `YYYY-MM-DD` format.
6. **Keep it factual** — describe what IS in the code, not what should be. Verify claims by reading actual source files.
7. **Don't duplicate** — if a component was already described in a previous entry and hasn't changed, list it under "✅ Bez zmian" with a one-liner, not a full description.
8. **Cross-reference Vision Report** — read `production_artifacts/Vision_Report.md` before writing entries. Ensure your changelog contextualizes changes against the agreed strategic direction.

## Example Trigger Prompt

When the user says something like:
- "Zaktualizuj raport stanu projektu"
- "Dodaj changelog do changelog"
- "Co się zmieniło w projekcie? Zaktualizuj docs."
- "Update the project state report"

Or after completing a major implementation task, proactively suggest:
> "Wprowadzono istotne zmiany w architekturze. Czy chcesz, żebym zaktualizował `docs/changelog/changelog.md` z nowym wpisem changelog?"
