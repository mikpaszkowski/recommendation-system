---
paths:
  - "src/**/*.py"
  - "scripts/**/*.py"
  - "tests/**/*.py"
---

# Python Coding Standards

## Type System
- Use type hints on ALL function signatures and return types
- Use `Optional[T]` for nullable parameters, not bare `None` defaults
- Use `List`, `Dict`, `Set` from `typing` for Python 3.9 compatibility
- Use Pydantic models or TypedDict for structured data, not raw dicts

## Style
- 2-space or 4-space indentation — match the existing file you're editing
- Docstrings for all public classes and methods (match project's existing style)
- Use `logging` module — never `print()` for operational output
- No bare `except:` — always catch specific exceptions

## Error Handling
- All external calls (LLM, Neo4j, API) must have try/except blocks
- Error messages must be informative — include context about what failed
- Never swallow exceptions silently
- Use graceful degradation where possible

## Neo4j Specific
- Use Cypher 25 `VECTOR SEARCH` syntax — not deprecated `CALL db.index.vector.queryNodes`
- Always close sessions and transactions
- Use parameterized queries — never string interpolation for Cypher

## LLM Specific
- Always validate LLM responses before using them
- Include timeout handling on all LLM calls
- Never trust LLM output for security-sensitive operations
- Parse structured LLM outputs with Pydantic validation

## Dependencies
- Never import packages not listed in `requirements.txt`
- Add new packages to `requirements.txt` when introducing them
- Pin versions for reproducibility

## Environment
- Never hardcode secrets, API keys, or environment-specific values
- Use environment variables loaded from `.env`
- Document new env vars in `.env.example`
