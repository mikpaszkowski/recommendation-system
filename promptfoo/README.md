# Promptfoo evaluation for preference extraction

## Prerequisites

- Install promptfoo (Node): `npm install -g promptfoo`
- Set `OPENAI_API_KEY` in your environment (used by the provider config).

## Run the evaluation

- From repo root: `promptfoo eval -c promptfooconfig.yaml`
- Results are written to `.promptfoo/` (default) with HTML report support.

## Test cases

- Defined in `promptfoo/preference_extract.yaml`, derived from the prompt examples and parser tests.
- Each case sets `conversation_text` and asserts key fields (likes, dislikes, constraints, intent).

## Extending

- Add more scenarios to `promptfoo/preference_extract.yaml` using the same `vars` structure.
- Use additional `assert` blocks per test for field-level checks (e.g., required brands/categories).
- Global assertions (JSON shape, allowed intents, `_thinking` presence) live in `promptfooconfig.yaml`.
