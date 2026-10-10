# Preference Extraction Prompt Benchmark

## Overview
This benchmark evaluates various Large Language Model (LLM) prompting strategies for accurately extracting structured JSON preferences in a Conversational Recommender System (CRS) context. The extraction process is critical for seamlessly bridging natural language conversation with structured database queries (e.g., Neo4j).

## Methodology

### 1. Prompt Strategies Evaluated
We evaluate 15 distinct prompt variations categorized into five strategies:
- **Baseline (1 prompt):** The original production prompt.
- **Zero-Shot (4 prompts):** Direct instructions strictly defining the required JSON schema without any concrete conversational examples. Each emphasizes a different behavioural concern (e.g., correction handling, strict JSON, off-topic resilience).
- **Few-Shot (4 prompts):** Includes between 2 to 6 specific conversational examples.
- **Chain-of-Thought (4 prompts):** Instructs the model to output a step-by-step reasoning process inside `<thinking>` tags (Sequential Field-by-Field, Evidence-First, Contrastive, and Turn-by-Turn Replay) before generating the final JSON payload.
- **Hybrid FS+CoT (2 prompts):** Combines few-shot examples that explicitly demonstrate the desired chain-of-thought process.

### 2. Conversational Scenarios
Each prompt strategy is evaluated against 5 distinct e-commerce dialogue scenarios designed to test edge cases:
1. **Multi-Turn Clarification:** System and user clarify missing product dimensions.
2. **High-Detail Upfront:** User provides all but one constraint, clarified immediately.
3. **Vague User:** Ambiguous request lacking strict constraints.
4. **Out-of-Domain/Off-Topic:** User shifts away from recommendations (e.g., "What is the capital of France?").
5. **Preference Change/Correction:** User modifies a previously stated preference in the same turn.

### 3. Execution & Metrics
The benchmark executed 225 API calls across three models: `gpt-6-sol`, `gpt-4o`, and `o4-mini`.

**Metrics Collected:**
- **Schema Compliance (%):** Percentage of times the model successfully output valid JSON matching the `current_session_context` structure.
- **Extraction Accuracy:** A normalized composite score evaluating how accurately the model captured the expected `session_intent`, `hard_constraints`, and `dialogue_state.ready_for_recommendation` compared to a manual ground truth.
- **Latency (s):** Time taken to generate the response.
- **Token Usage:** Total input and output tokens consumed.

## Results Analysis

Overall, the benchmark achieved a **99.6% valid JSON output rate**, demonstrating that the root instructions are highly effective at forcing correct schema compliance across all strategies.

### Top Performing Prompts
Based on the average composite score across all models, the top 5 prompts were:
1. `few_shot_full_strict_json` (Score: 0.903)
2. `few_shot_minimal_2ex` (Score: 0.900)
3. `baseline_production` (Score: 0.882)
4. `fs_cot_turn_by_turn` (Score: 0.877)
5. `zero_shot_off_topic_resilient` (Score: 0.839)

### Strategy Comparison
- **Few-Shot Dominance:** Few-shot strategies consistently outperformed standalone Chain-of-Thought approaches. The presence of concrete input/output pairings remains the strongest driver of accurate schema extraction, particularly for complex constraints.
- **CoT Struggles:** Pure Chain-of-Thought prompts generally underperformed compared to Few-Shot prompts. Forcing the model to reason without examples often led to overthinking or misaligning the final JSON schema with the reasoning output.
- **Model Disparity:** `gpt-6-sol` significantly outperformed `gpt-4o` and `o4-mini` across almost all prompt strategies, particularly excelling on Zero-Shot prompts where it achieved an average score of 0.888 (compared to `gpt-4o`'s 0.681).

### Scenario Difficulty
The hardest conversational scenario across all models was **High-Detail Upfront** (Score: 0.716), indicating models struggle with dense constraint extraction in a single turn. Interestingly, models handled **Preference Change/Correction** exceptionally well (Score: 0.907).

### Latency and Token Cost
- Zero-Shot prompts are the fastest and cheapest, averaging ~2-9s latency and ~1700-2400 tokens.
- Few-Shot prompts offer the highest accuracy but consume significantly more tokens (~3300-4100).
- CoT strategies increase latency and cost without a commensurate increase in accuracy for this specific extraction task.

## Conclusion
For production usage in the CRS, a robust **Few-Shot** approach with strict JSON formatting instructions (e.g., `few_shot_full_strict_json` or the current `baseline_production`) provides the most reliable and accurate extraction of user preferences. While `gpt-6-sol` demonstrates an impressive ability to extract accurately with just Zero-Shot instructions, Few-Shot remains the safest architectural choice for ensuring schema compliance and accurate intent classification across different LLM providers.
