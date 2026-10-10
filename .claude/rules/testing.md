---
paths:
  - "tests/**/*.py"
---

# Testing Conventions

## Test Framework
- Use `pytest` as the test runner
- Use `pytest-asyncio` for async tests
- Run from project root: `python -m pytest tests/ -v --tb=short`

## Test Organization
- Mirror the `src/` directory structure under `tests/`
- Name test files `test_<module>.py`
- Name test functions `test_<behavior_being_tested>`

## Test Types
- Unit tests: test individual functions/methods in isolation
- Integration tests: test component interactions (especially Neo4j queries)
- E2E tests: test complete flows (in `tests/e2e/`)

## Fixtures and Mocking
- Use `conftest.py` for shared fixtures
- Mock external services (Neo4j, OpenAI) in unit tests
- Never rely on live external services in CI tests
- Use deterministic test data — no random/unseeded values

## Neo4j Tests
- Use a separate test database or transaction rollback
- Never run tests against production data

## Assertions
- Use specific assertions (`assert x == y`) not generic (`assert result`)
- Test both happy path and error cases
- Test edge cases: empty inputs, None values, malformed data
