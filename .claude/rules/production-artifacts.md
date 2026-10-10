---
paths:
  - "production_artifacts/**/*.md"
---

# Production Artifacts Rules

These files are structured project documents with specific ownership and modification rules.

## Ownership Rules
- `Vision_Report.md` — ONLY the Research Analyst (@pm-research) may modify this file
- `Technical_Specification.md` — ONLY the Spec Writer (@pm-specs) may create/modify this
- `Audit_Report.md` — ONLY the QA Engineer (@qa) may create/modify this
- `Project_State_Report.md` — ONLY the Inspector (@inspector) may create/modify this
- `Research_Report.md` — ONLY the Research Analyst (@pm-research) may create/modify this
- `Documentation_Audit_Report.md` — ONLY the Doc Cleaner (@doc-cleaner) may create/modify this
- `Implementation_Plan.md` — Modified only with explicit user approval

## Vision Report Decision Log
- NEVER modify existing Decision Log entries — only APPEND new ones at the top
- New entries must follow format: `### 📅 YYYY-MM-DD-NNN: [Title]`
- Include: Context, Decision, Rationale, Impact on vision, Approved by

## General Rules
- All production artifacts use English
- Always include dates in `YYYY-MM-DD` format
- Reference actual file paths and class names — never abstract hand-waving
