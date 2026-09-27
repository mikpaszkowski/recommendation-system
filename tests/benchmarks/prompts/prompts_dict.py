"""
tests/benchmarks/prompts/prompts_dict.py

Contains all prompt variations for the preference extraction benchmark.
Each prompt is a complete system-level instruction string ready to be
paired with a user message containing the conversation.

Prompt categories:
  - BASELINE (1):  The exact production prompt from preference_extract_prompt.py
  - ZERO_SHOT (4): Full rules, no examples. Each emphasises a different concern.
  - FEW_SHOT (4):  Full rules + curated examples. Varying example count / complexity.
  - COT (4):       Full rules + genuinely different chain-of-thought reasoning strategies.
  - FS_COT (2):    Hybrid Few-Shot + Chain-of-Thought prompts.

Total: 15 prompts.
"""

# ---------------------------------------------------------------------------
# SHARED BUILDING BLOCKS
# ---------------------------------------------------------------------------

OBJECTIVE = """<objective>
You are an expert conversational preference extraction engine for an intelligent Conversational Recommender System (CRS).
Your objective is to analyze a multi-turn conversation between a User and an Assistant, comprehend the user's domain intent, situation, and requirements, and extract structured preferences strictly complying with the canonical `current_session_context` JSON schema.
</objective>"""

FULL_RULES = """<rules>
Analyze the full multi-turn conversation history carefully and extract the current conversational state and preferences following these strict requirements:

1. ROOT WRAPPER ENFORCEMENT:
   - All extracted data MUST be strictly encapsulated under the root key "current_session_context".
   - The top-level output must be a single JSON object: {"current_session_context": { ... }}.
   - Never output markdown formatting or explanatory text outside the JSON object.

2. SESSION INTENT CLASSIFICATION (`session_intent`):
   - You MUST classify the user's current conversational stage into EXACTLY ONE of the following 5 enums:
     * "initial_search": The user is initiating a search or stating their upfront product needs for the first time.
     * "exploring_domain": The user is asking broad, open-ended questions to discover options or understand product categories without committing to specific criteria or filters.
     * "refining_options": The user is adjusting parameters, reacting to previous recommendations, adding new constraints, or narrowing down choices.
     * "comparing_items": The user is directly comparing two or more specific items, models, or brands, weighing trade-offs between them.
     * "finalizing_choice": The user has decided on a specific product and is preparing for a purchase, transaction, or final action.

3. SITUATIONAL CONTEXT (`situational_context`):
   - Provide a concise, human-readable summary (1-2 sentences) of *why* the user is looking for this product, capturing their underlying motivation, operational environment, constraints, or intended use case (e.g., "College student looking for an ultra-portable laptop with long battery life for lectures and campus commute under $1000").
   - If no specific situation is described, briefly state the core goal.

4. EXTRACTED PARAMETERS (`extracted_parameters`):
   Contains two distinct collections: `hard_constraints` and `soft_preferences`.

   A. HARD CONSTRAINTS (`hard_constraints`):
      - Strict, non-negotiable filters that MUST be obeyed. If an item violates any hard constraint, it cannot be recommended.
      - Each hard constraint object MUST contain:
        * "attribute" (String): Canonical lowercase property name being constrained (e.g., "price", "brand", "category", "operating_system", "ram", "screen_size", "storage", "refresh_rate", "model").
        * "operator" (String): EXACTLY ONE of the 5 allowed enums:
          - "include": The attribute must match or include the target value (e.g., brand include "Sony", category include "laptop").
          - "exclude": The attribute must NOT match or include the target value (e.g., operating_system exclude "ChromeOS", brand exclude "Acer").
          - "greater_than": Numeric attribute must be strictly greater than the target value (e.g., ram greater_than 16, price greater_than 200).
          - "less_than": Numeric attribute must be strictly less than the target value (e.g., price less_than 1000, weight less_than 3).
          - "equal": Attribute must match the exact value.
        * "value" (Number, String, or Boolean):
          - For "greater_than" and "less_than", "value" MUST be a numeric float or integer (e.g., 1000, 16, 2.5), NEVER a string with currency symbols.
          - For "include", "exclude", and "equal", "value" is typically a string or canonical name (e.g., "Dell", "ChromeOS").

   B. SOFT PREFERENCES (`soft_preferences`):
      - Flexible desires, aesthetic leanings, brand affinities, or subjective qualities used to rank and score candidates, but not strictly required.
      - Each soft preference object MUST contain:
        * "category" (String): Domain/dimension of preference (e.g., "weight", "battery", "display", "design", "performance", "noise_cancellation", "brand", "use_case").
        * "value" (String): The specific quality or feature desired/disliked (e.g., "lightweight", "OLED", "long battery life", "sleek aluminum body", "mechanical keys").
        * "polarity" (Float): Sentiment score between -1.0 and 1.0:
          - +1.0: Strongly desires, loves, or insists as high priority.
          - +0.5 to +0.8: Positively interested, prefers, or likes.
          - -0.5 to -0.8: Dislikes, prefers to avoid if possible.
          - -1.0: Strongly dislikes or hates.
        * "confidence" (Float): Extraction certainty between 0.0 and 1.0:
          - 1.0: Explicitly declared by the user.
          - 0.7 to 0.9: Strongly implied by user description or context.
          - 0.4 to 0.6: Inferred or deduced with moderate certainty.
        * "evidence" (String): Exact quote or clear logical deduction from the conversation justifying this preference.

5. DIALOGUE STATE TRACKING (`dialogue_state`):
   - You MUST assess the system's dialogue state and readiness:
     * "ready_for_recommendation" (Boolean):
       - Set to `true` IF sufficient information exists to query the database and present meaningful recommendations (at minimum, the product category is identified and either basic constraints or clear soft preferences are provided).
       - Set to `false` IF the query is too ambiguous, vague, or missing critical domain parameters needed for search.
     * "missing_critical_attributes" (Array of Strings):
       - List mandatory attributes required to run a meaningful database query that the user has not yet specified (e.g., ["category"], ["screen_size"]).
       - If "ready_for_recommendation" is `true`, this list MUST be empty `[]`.
     * "suggested_system_action" (String):
       - EXACTLY ONE of the 3 allowed enums:
         * "ask_clarification": When "ready_for_recommendation" is `false`, prompt the user for missing critical details.
         * "present_results": When "ready_for_recommendation" is `true`, proceed to retrieve and show recommendations.
         * "change_topic": When the user changes subjects, asks general non-recommendation questions, or indicates completion.

6. MULTI-TURN ACCUMULATION:
   - When given a multi-turn conversation, combine preferences established across previous turns while respecting modifications, refinements, or corrections made in later turns.
</rules>"""

# Full 6-example block from the production prompt
FULL_EXAMPLES = """<examples>

<example_1>
INPUT:
User: I am looking for a lightweight laptop for college with good battery life.
Assistant: I would be happy to help! Do you have a specific budget or operating system preference in mind?
User: My budget is strictly under $1000, and I definitely do not want ChromeOS. I need it to last all day on campus.
OUTPUT:
{
  "current_session_context": {
    "session_intent": "refining_options",
    "situational_context": "College student looking for an ultra-portable laptop with all-day battery life for campus commute and classes, under $1000 without ChromeOS.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "laptop"},
        {"attribute": "price", "operator": "less_than", "value": 1000},
        {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}
      ],
      "soft_preferences": [
        {"category": "weight", "value": "lightweight", "polarity": 0.8, "confidence": 0.95, "evidence": "User mentioned wanting a lightweight laptop for college"},
        {"category": "battery", "value": "long battery life", "polarity": 0.9, "confidence": 0.9, "evidence": "needs to last all day on campus"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_1>

<example_2>
INPUT:
User: I want to upgrade the audio setup on my desk, but I do not know whether I should get headphones or desktop speakers.
OUTPUT:
{
  "current_session_context": {
    "session_intent": "exploring_domain",
    "situational_context": "User is looking to upgrade desk audio setup and exploring whether headphones or desktop speakers would be more suitable.",
    "extracted_parameters": {
      "hard_constraints": [],
      "soft_preferences": [
        {"category": "use_case", "value": "desk setup", "polarity": 0.6, "confidence": 0.8, "evidence": "upgrade the audio setup on my desk"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": false,
      "missing_critical_attributes": ["category", "budget"],
      "suggested_system_action": "ask_clarification"
    }
  }
}
</example_2>

<example_3>
INPUT:
User: I travel on airplanes frequently for business and need new headphones. Should I buy the Sony WH-1000XM5 or Bose QuietComfort Ultra?
Assistant: Both are class-leading ANC headphones! The Sony has slightly better battery life and EQ customization, while the Bose offers superior passive seal and slightly more compact folding.
User: Active noise cancellation is my absolute top priority on flights. I hate bulky carrying cases because my backpack is always packed. Price is not an issue.
OUTPUT:
{
  "current_session_context": {
    "session_intent": "comparing_items",
    "situational_context": "Frequent business flyer comparing Sony WH-1000XM5 and Bose QuietComfort Ultra, prioritizing best-in-class active noise cancellation and compact travel footprint.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "headphones"}
      ],
      "soft_preferences": [
        {"category": "noise_cancellation", "value": "active noise cancellation", "polarity": 1.0, "confidence": 1.0, "evidence": "Active noise cancellation is my absolute top priority on flights"},
        {"category": "portability", "value": "bulky carrying case", "polarity": -0.85, "confidence": 0.9, "evidence": "I hate bulky carrying cases because my backpack is always packed"},
        {"category": "brand", "value": "Sony", "polarity": 0.4, "confidence": 0.6, "evidence": "evaluating Sony WH-1000XM5"},
        {"category": "brand", "value": "Bose", "polarity": 0.4, "confidence": 0.6, "evidence": "evaluating Bose QuietComfort Ultra"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_3>

<example_4>
INPUT:
User: I need a dedicated gaming monitor for competitive esports.
Assistant: Great! What screen size, resolution, and refresh rate are you aiming for? And what is your budget?
User: My budget is strictly between $200 and $400. Refresh rate must be higher than 144Hz. I only play on IPS panels because I hate washed-out TN colors. Also, exclude Acer brands, prefer ASUS or Dell.
OUTPUT:
{
  "current_session_context": {
    "session_intent": "refining_options",
    "situational_context": "Esports gamer looking for a high-refresh gaming monitor between $200 and $400, strictly requiring IPS panels over 144Hz, excluding Acer while favoring ASUS or Dell.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "monitor"},
        {"attribute": "price", "operator": "greater_than", "value": 200},
        {"attribute": "price", "operator": "less_than", "value": 400},
        {"attribute": "refresh_rate", "operator": "greater_than", "value": 144},
        {"attribute": "panel_type", "operator": "exclude", "value": "TN"},
        {"attribute": "brand", "operator": "exclude", "value": "Acer"}
      ],
      "soft_preferences": [
        {"category": "panel_type", "value": "IPS", "polarity": 0.9, "confidence": 0.95, "evidence": "I only play on IPS panels"},
        {"category": "brand", "value": "ASUS", "polarity": 0.7, "confidence": 0.85, "evidence": "prefer ASUS or Dell"},
        {"category": "brand", "value": "Dell", "polarity": 0.7, "confidence": 0.85, "evidence": "prefer ASUS or Dell"},
        {"category": "use_case", "value": "esports", "polarity": 0.8, "confidence": 0.9, "evidence": "gaming monitor for competitive esports"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_4>

<example_5>
INPUT:
User: I have decided on the Dell XPS 15 laptop with 32GB RAM. Where can I buy it at the best price?
OUTPUT:
{
  "current_session_context": {
    "session_intent": "finalizing_choice",
    "situational_context": "User has made their final selection of the Dell XPS 15 with 32GB RAM and is ready to make a purchase, seeking retailer pricing and availability.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "laptop"},
        {"attribute": "brand", "operator": "include", "value": "Dell"},
        {"attribute": "model", "operator": "equal", "value": "XPS 15"},
        {"attribute": "ram", "operator": "equal", "value": "32GB"}
      ],
      "soft_preferences": []
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_5>

<example_6>
INPUT:
User: I am looking for a pair of running shoes under $150, ideally something with great cushioning for marathon training.
OUTPUT:
{
  "current_session_context": {
    "session_intent": "initial_search",
    "situational_context": "Runner initiating search for cushioned running shoes under $150 suitable for marathon training.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "running shoes"},
        {"attribute": "price", "operator": "less_than", "value": 150}
      ],
      "soft_preferences": [
        {"category": "cushioning", "value": "great cushioning", "polarity": 0.9, "confidence": 0.95, "evidence": "ideally something with great cushioning"},
        {"category": "use_case", "value": "marathon training", "polarity": 0.8, "confidence": 0.9, "evidence": "for marathon training"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_6>

</examples>"""

# Minimal examples (2 only) for lighter few-shot variants
MINIMAL_EXAMPLES = """<examples>

<example_1>
INPUT:
User: I am looking for a lightweight laptop for college with good battery life.
Assistant: I would be happy to help! Do you have a specific budget or operating system preference in mind?
User: My budget is strictly under $1000, and I definitely do not want ChromeOS. I need it to last all day on campus.
OUTPUT:
{
  "current_session_context": {
    "session_intent": "refining_options",
    "situational_context": "College student looking for an ultra-portable laptop with all-day battery life for campus commute and classes, under $1000 without ChromeOS.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "laptop"},
        {"attribute": "price", "operator": "less_than", "value": 1000},
        {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}
      ],
      "soft_preferences": [
        {"category": "weight", "value": "lightweight", "polarity": 0.8, "confidence": 0.95, "evidence": "User mentioned wanting a lightweight laptop for college"},
        {"category": "battery", "value": "long battery life", "polarity": 0.9, "confidence": 0.9, "evidence": "needs to last all day on campus"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_1>

<example_2>
INPUT:
User: I want to upgrade the audio setup on my desk, but I do not know whether I should get headphones or desktop speakers.
OUTPUT:
{
  "current_session_context": {
    "session_intent": "exploring_domain",
    "situational_context": "User is looking to upgrade desk audio setup and exploring whether headphones or desktop speakers would be more suitable.",
    "extracted_parameters": {
      "hard_constraints": [],
      "soft_preferences": [
        {"category": "use_case", "value": "desk setup", "polarity": 0.6, "confidence": 0.8, "evidence": "upgrade the audio setup on my desk"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": false,
      "missing_critical_attributes": ["category", "budget"],
      "suggested_system_action": "ask_clarification"
    }
  }
}
</example_2>

</examples>"""

# ---------------------------------------------------------------------------
# 0. BASELINE — exact copy of the production prompt (SYSTEM_PROMPT from
#    src/llm_interface/prompts/preference_extract_prompt.py)
# ---------------------------------------------------------------------------

BASELINE = f"""{OBJECTIVE}

{FULL_RULES}

{FULL_EXAMPLES}"""

# ---------------------------------------------------------------------------
# 1. ZERO-SHOT PROMPTS — full rules, NO examples, each variant stresses a
#    different behavioural concern to see which focus area matters most.
# ---------------------------------------------------------------------------

# ZS-1: Vanilla — pure rules, no extra nudges
ZS_1 = f"""{OBJECTIVE}

{FULL_RULES}"""

# ZS-2: Strict JSON — emphasises output discipline
ZS_2 = f"""{OBJECTIVE}

{FULL_RULES}

<output_format>
CRITICAL: Your response MUST consist of a single, valid JSON object and nothing else.
Do NOT wrap it in markdown code fences. Do NOT add any explanatory text before or after the JSON.
Ensure all numeric values for "greater_than" / "less_than" operators are raw numbers (e.g. 1000), never strings with currency symbols (e.g. "$1000").
</output_format>"""

# ZS-3: Correction-aware — emphasises multi-turn override behaviour
ZS_3 = f"""{OBJECTIVE}

{FULL_RULES}

<correction_handling>
PAY SPECIAL ATTENTION to later turns that contradict or modify earlier statements.
When the user says "actually", "no wait", "change that to", or any correction language,
the LATEST value MUST override the previously stated value in your extraction.
Do NOT keep both the old and the new value as separate constraints — the old one is superseded.
</correction_handling>"""

# ZS-4: Off-topic resilient — emphasises graceful handling of non-recommendation inputs
ZS_4 = f"""{OBJECTIVE}

{FULL_RULES}

<off_topic_handling>
If the user's message is completely unrelated to product recommendations (e.g. trivia, greetings,
or questions about store hours), you MUST still return a valid JSON object with:
- "session_intent" set to "exploring_domain" or the closest applicable intent
- "extracted_parameters" with empty "hard_constraints" and "soft_preferences"
- "dialogue_state.ready_for_recommendation" set to false
- "dialogue_state.suggested_system_action" set to "change_topic"
Never refuse to produce JSON. Always return the schema even when there is nothing to extract.
</off_topic_handling>"""

# ---------------------------------------------------------------------------
# 2. FEW-SHOT PROMPTS — full rules + examples. Varying example count and focus.
# ---------------------------------------------------------------------------

# FS-1: Minimal examples (2) — tests whether a small number of high-quality examples suffices
FS_1 = f"""{OBJECTIVE}

{FULL_RULES}

{MINIMAL_EXAMPLES}"""

# FS-2: Full examples (6) — the production-equivalent approach
FS_2 = f"""{OBJECTIVE}

{FULL_RULES}

{FULL_EXAMPLES}"""

# FS-3: Full examples + strict JSON emphasis
FS_3 = f"""{OBJECTIVE}

{FULL_RULES}

{FULL_EXAMPLES}

<output_format>
CRITICAL: Your response MUST consist of a single, valid JSON object and nothing else.
Do NOT wrap it in markdown code fences. Do NOT add any explanatory text before or after the JSON.
Ensure all numeric values for "greater_than" / "less_than" operators are raw numbers (e.g. 1000), never strings with currency symbols (e.g. "$1000").
</output_format>"""

# FS-4: Full examples + correction-awareness emphasis
FS_4 = f"""{OBJECTIVE}

{FULL_RULES}

{FULL_EXAMPLES}

<correction_handling>
PAY SPECIAL ATTENTION to later turns that contradict or modify earlier statements.
When the user says "actually", "no wait", "change that to", or any correction language,
the LATEST value MUST override the previously stated value in your extraction.
Do NOT keep both the old and the new value as separate constraints — the old one is superseded.
</correction_handling>"""

# ---------------------------------------------------------------------------
# 3. CHAIN-OF-THOUGHT PROMPTS — four genuinely different reasoning strategies.
#    Each one forces the model to think DIFFERENTLY before outputting JSON.
# ---------------------------------------------------------------------------

# CoT-1: SEQUENTIAL FIELD-BY-FIELD — forces the model to reason about each
#         schema field independently in order, like filling out a form.
COT_1 = f"""{OBJECTIVE}

{FULL_RULES}

<reasoning_strategy>
Before outputting the final JSON, you MUST produce a step-by-step analysis inside <thinking> tags.
Walk through the schema fields in order, one at a time:

Step 1 — SESSION INTENT: Read the last user message. What stage of the buying journey is the user in?
  Consider: Is this a fresh search? Are they narrowing options? Comparing items? Ready to buy?
  Write your classification and a one-sentence justification.

Step 2 — SITUATIONAL CONTEXT: What is the user's underlying motivation or use case?
  Summarise in 1-2 sentences why they need this product and in what context.

Step 3 — HARD CONSTRAINTS: Scan every user turn for non-negotiable requirements.
  For each one, write: "[quote from user]" → attribute: X, operator: Y, value: Z.
  Check: Are any values numeric? If so, strip currency symbols and use raw numbers.

Step 4 — SOFT PREFERENCES: Scan every user turn for subjective desires, likes, and dislikes.
  For each one, write: "[quote from user]" → category: X, value: Y, polarity: P, confidence: C.
  Justify the polarity and confidence scores.

Step 5 — DIALOGUE STATE: Is the product category known? Are there enough constraints to query?
  If yes → ready_for_recommendation: true, missing: [], action: present_results.
  If no → ready_for_recommendation: false, list what's missing, action: ask_clarification or change_topic.

After </thinking>, output ONLY the final JSON object with no additional text.
</reasoning_strategy>"""

# CoT-2: EVIDENCE-FIRST — forces the model to first extract all user quotes,
#         then classify them, preventing hallucinated constraints.
COT_2 = f"""{OBJECTIVE}

{FULL_RULES}

<reasoning_strategy>
Before outputting the final JSON, you MUST produce a step-by-step analysis inside <thinking> tags.
Use an EVIDENCE-FIRST approach to prevent hallucination:

Phase 1 — QUOTE EXTRACTION: Read the entire conversation. Copy every user statement that
  contains a preference, requirement, constraint, desire, or opinion. Number each quote.
  If no relevant quotes exist (e.g. off-topic), note "No extractable preferences found."

Phase 2 — QUOTE CLASSIFICATION: For each numbered quote, classify it as:
  - HARD CONSTRAINT (non-negotiable filter): specify attribute, operator, value
  - SOFT PREFERENCE (flexible desire): specify category, value, polarity, confidence
  - CONTEXT ONLY (provides situational info but no extractable parameter)
  - IRRELEVANT (off-topic, greeting, etc.)
  Justify each classification in one sentence.

Phase 3 — CONFLICT RESOLUTION: Check if any later quote contradicts an earlier one.
  If so, mark the earlier quote as SUPERSEDED and keep only the latest value.

Phase 4 — SCHEMA ASSEMBLY: Map the classified quotes to the JSON schema fields.
  Determine session_intent from the overall conversation flow.
  Determine dialogue_state from whether category + constraints are sufficient.

After </thinking>, output ONLY the final JSON object with no additional text.
</reasoning_strategy>"""

# CoT-3: CONTRASTIVE REASONING — forces the model to consider what the user
#         did NOT say and explicitly reason about ambiguity before extracting.
COT_3 = f"""{OBJECTIVE}

{FULL_RULES}

<reasoning_strategy>
Before outputting the final JSON, you MUST produce a step-by-step analysis inside <thinking> tags.
Use a CONTRASTIVE REASONING approach — consider both what the user said AND what they did not say:

Step 1 — WHAT DID THE USER SAY? List every explicit statement about what they want or need.
  Mark each as either a hard constraint or soft preference.

Step 2 — WHAT DID THE USER NOT SAY? Identify critical product dimensions that are typically
  needed for a good recommendation but were NOT mentioned. Examples:
  - Did they specify a product category? If not, this is a missing critical attribute.
  - Did they mention price/budget? Brand? Size? Use case?
  For each missing dimension, decide: Is it critical (blocks recommendation) or optional (can be inferred)?

Step 3 — INTENT DISAMBIGUATION: Consider multiple possible intents and argue for the best one.
  e.g., "This could be initial_search OR exploring_domain because... I choose X because..."

Step 4 — CONFIDENCE CALIBRATION: For each soft preference, reason about confidence:
  - Did the user EXPLICITLY state this? → confidence 0.9-1.0
  - Is it STRONGLY IMPLIED? → confidence 0.7-0.8
  - Am I INFERRING it from context? → confidence 0.4-0.6
  Never assign high confidence to inferred preferences.

Step 5 — READINESS VERDICT: Based on Steps 1-2, is there enough info to recommend?
  Argue for and against, then decide.

After </thinking>, output ONLY the final JSON object with no additional text.
</reasoning_strategy>"""

# CoT-4: TURN-BY-TURN REPLAY — forces the model to process each dialogue
#         turn chronologically, building up a running state that gets updated.
COT_4 = f"""{OBJECTIVE}

{FULL_RULES}

<reasoning_strategy>
Before outputting the final JSON, you MUST produce a step-by-step analysis inside <thinking> tags.
Use a TURN-BY-TURN REPLAY approach — process the conversation chronologically, maintaining a
running state that evolves with each turn:

For each dialogue turn (User or Assistant message), do the following:

  TURN N (Speaker: User/Assistant):
  - Quote the key parts of this message.
  - NEW constraints introduced: list any new hard constraints (attribute, operator, value).
  - NEW preferences introduced: list any new soft preferences (category, value, polarity, confidence).
  - MODIFIED constraints: did this turn change or override anything from a previous turn?
    If yes, state: "Previously [X] → Now [Y]. Reason: [quote]."
  - REMOVED constraints: did the user explicitly retract or cancel a previous requirement?
  - Running state after this turn: briefly summarise the accumulated extraction so far.

After processing ALL turns:
  - FINAL INTENT: Based on the last user message and conversation arc, classify the session intent.
  - FINAL READINESS: Determine if ready_for_recommendation is true or false.
  - Compile the final running state into the JSON schema.

After </thinking>, output ONLY the final JSON object with no additional text.
</reasoning_strategy>"""

# ---------------------------------------------------------------------------
# 4. HYBRID FEW-SHOT + CHAIN-OF-THOUGHT — examples that demonstrate the
#    reasoning process AND the expected output.
# ---------------------------------------------------------------------------

# FS-CoT-1: Evidence-First CoT with examples showing the thinking process
FS_COT_1 = (
    OBJECTIVE + "\n\n" + FULL_RULES + "\n\n"
    """<reasoning_strategy>
Before outputting the final JSON, produce your reasoning inside <thinking> tags.
Use an EVIDENCE-FIRST approach:
1. Extract all user quotes containing preferences or constraints.
2. Classify each quote as HARD CONSTRAINT, SOFT PREFERENCE, CONTEXT, or IRRELEVANT.
3. Check for conflicts between turns — later statements override earlier ones.
4. Assemble the JSON from classified evidence.
After </thinking>, output ONLY the final JSON.
</reasoning_strategy>

<examples>

<example_1>
INPUT:
User: I am looking for a lightweight laptop for college with good battery life.
Assistant: I would be happy to help! Do you have a specific budget or operating system preference in mind?
User: My budget is strictly under $1000, and I definitely do not want ChromeOS. I need it to last all day on campus.

<thinking>
QUOTE EXTRACTION:
1. "lightweight laptop for college with good battery life"
2. "budget is strictly under $1000"
3. "definitely do not want ChromeOS"
4. "last all day on campus"

CLASSIFICATION:
1. SOFT PREFERENCE — category: weight, value: lightweight, polarity: +0.8, confidence: 0.95. Explicit.
   CONTEXT — college student, campus use.
   SOFT PREFERENCE — category: battery, value: long battery life, polarity: +0.9, confidence: 0.9. Explicit.
2. HARD CONSTRAINT — attribute: price, operator: less_than, value: 1000. "strictly" = non-negotiable.
3. HARD CONSTRAINT — attribute: operating_system, operator: exclude, value: ChromeOS. "definitely do not want" = non-negotiable.
4. Reinforces battery preference (already captured).

IMPLICIT HARD CONSTRAINT: category = laptop (explicitly stated).

CONFLICT CHECK: No conflicts across turns.

READINESS: Category (laptop) is known, price constraint exists, OS exclusion exists. → ready_for_recommendation: true.
</thinking>

OUTPUT:
{
  "current_session_context": {
    "session_intent": "refining_options",
    "situational_context": "College student looking for an ultra-portable laptop with all-day battery life for campus commute and classes, under $1000 without ChromeOS.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "laptop"},
        {"attribute": "price", "operator": "less_than", "value": 1000},
        {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}
      ],
      "soft_preferences": [
        {"category": "weight", "value": "lightweight", "polarity": 0.8, "confidence": 0.95, "evidence": "User mentioned wanting a lightweight laptop for college"},
        {"category": "battery", "value": "long battery life", "polarity": 0.9, "confidence": 0.9, "evidence": "needs to last all day on campus"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_1>

<example_2>
INPUT:
User: I want to upgrade the audio setup on my desk, but I do not know whether I should get headphones or desktop speakers.

<thinking>
QUOTE EXTRACTION:
1. "upgrade the audio setup on my desk"
2. "do not know whether I should get headphones or desktop speakers"

CLASSIFICATION:
1. CONTEXT — user wants a desk audio upgrade. SOFT PREFERENCE — category: use_case, value: desk setup, polarity: +0.6, confidence: 0.8.
2. CONTEXT — user is undecided on product category. This means category is MISSING.

CONFLICT CHECK: No conflicts (single turn).

READINESS: Product category is NOT determined (headphones vs speakers). Budget unknown.
→ ready_for_recommendation: false. Missing: ["category", "budget"].
</thinking>

OUTPUT:
{
  "current_session_context": {
    "session_intent": "exploring_domain",
    "situational_context": "User is looking to upgrade desk audio setup and exploring whether headphones or desktop speakers would be more suitable.",
    "extracted_parameters": {
      "hard_constraints": [],
      "soft_preferences": [
        {"category": "use_case", "value": "desk setup", "polarity": 0.6, "confidence": 0.8, "evidence": "upgrade the audio setup on my desk"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": false,
      "missing_critical_attributes": ["category", "budget"],
      "suggested_system_action": "ask_clarification"
    }
  }
}
</example_2>

</examples>"""
)

# FS-CoT-2: Turn-by-Turn Replay CoT with examples showing the replay process
FS_COT_2 = (
    OBJECTIVE + "\n\n" + FULL_RULES + "\n\n"
    """<reasoning_strategy>
Before outputting the final JSON, produce your reasoning inside <thinking> tags.
Use a TURN-BY-TURN REPLAY approach:
- Process each dialogue turn chronologically.
- For each turn, note NEW constraints, NEW preferences, MODIFIED values, and the RUNNING STATE.
- After all turns, compile the final state into JSON.
After </thinking>, output ONLY the final JSON.
</reasoning_strategy>

<examples>

<example_1>
INPUT:
User: I need a dedicated gaming monitor for competitive esports.
Assistant: Great! What screen size, resolution, and refresh rate are you aiming for? And what is your budget?
User: My budget is strictly between $200 and $400. Refresh rate must be higher than 144Hz. I only play on IPS panels because I hate washed-out TN colors. Also, exclude Acer brands, prefer ASUS or Dell.

<thinking>
TURN 1 (User): "I need a dedicated gaming monitor for competitive esports."
  NEW constraints: category = monitor (hard, include)
  NEW preferences: use_case = esports (soft, polarity +0.8, confidence 0.9)
  Running state: {category: monitor, use_case: esports}

TURN 2 (Assistant): System asks for screen size, resolution, refresh rate, budget.
  No extraction needed from assistant turns.
  Running state: unchanged.

TURN 3 (User): Budget $200-$400, refresh >144Hz, IPS only, no Acer, prefer ASUS/Dell.
  NEW constraints:
    - price greater_than 200 (hard) — "strictly between"
    - price less_than 400 (hard)
    - refresh_rate greater_than 144 (hard) — "must be higher"
    - panel_type exclude TN (hard) — "hate washed-out TN"
    - brand exclude Acer (hard) — "exclude Acer"
  NEW preferences:
    - panel_type = IPS (soft, polarity +0.9, confidence 0.95) — "I only play on IPS"
    - brand = ASUS (soft, polarity +0.7, confidence 0.85) — "prefer ASUS or Dell"
    - brand = Dell (soft, polarity +0.7, confidence 0.85)
  MODIFIED: none
  Running state: {category: monitor, price: 200-400, refresh: >144, panel: IPS/no TN, brand: no Acer / prefer ASUS|Dell, use: esports}

FINAL INTENT: refining_options — user is narrowing down with specific constraints after system asked.
FINAL READINESS: Category known, multiple constraints → ready_for_recommendation: true.
</thinking>

OUTPUT:
{
  "current_session_context": {
    "session_intent": "refining_options",
    "situational_context": "Esports gamer looking for a high-refresh gaming monitor between $200 and $400, strictly requiring IPS panels over 144Hz, excluding Acer while favoring ASUS or Dell.",
    "extracted_parameters": {
      "hard_constraints": [
        {"attribute": "category", "operator": "include", "value": "monitor"},
        {"attribute": "price", "operator": "greater_than", "value": 200},
        {"attribute": "price", "operator": "less_than", "value": 400},
        {"attribute": "refresh_rate", "operator": "greater_than", "value": 144},
        {"attribute": "panel_type", "operator": "exclude", "value": "TN"},
        {"attribute": "brand", "operator": "exclude", "value": "Acer"}
      ],
      "soft_preferences": [
        {"category": "panel_type", "value": "IPS", "polarity": 0.9, "confidence": 0.95, "evidence": "I only play on IPS panels"},
        {"category": "brand", "value": "ASUS", "polarity": 0.7, "confidence": 0.85, "evidence": "prefer ASUS or Dell"},
        {"category": "brand", "value": "Dell", "polarity": 0.7, "confidence": 0.85, "evidence": "prefer ASUS or Dell"},
        {"category": "use_case", "value": "esports", "polarity": 0.8, "confidence": 0.9, "evidence": "gaming monitor for competitive esports"}
      ]
    },
    "dialogue_state": {
      "ready_for_recommendation": true,
      "missing_critical_attributes": [],
      "suggested_system_action": "present_results"
    }
  }
}
</example_1>

</examples>"""
)

# ---------------------------------------------------------------------------
# PROMPT REGISTRY — all 15 prompts keyed by descriptive name
# ---------------------------------------------------------------------------

PROMPTS = {
    # Baseline
    "baseline_production": BASELINE,

    # Zero-Shot (4)
    "zero_shot_vanilla": ZS_1,
    "zero_shot_strict_json": ZS_2,
    "zero_shot_correction_aware": ZS_3,
    "zero_shot_off_topic_resilient": ZS_4,

    # Few-Shot (4)
    "few_shot_minimal_2ex": FS_1,
    "few_shot_full_6ex": FS_2,
    "few_shot_full_strict_json": FS_3,
    "few_shot_full_correction": FS_4,

    # Chain-of-Thought (4) — each is a genuinely different reasoning strategy
    "cot_field_by_field": COT_1,
    "cot_evidence_first": COT_2,
    "cot_contrastive": COT_3,
    "cot_turn_by_turn_replay": COT_4,

    # Hybrid Few-Shot + CoT (2)
    "fs_cot_evidence_first": FS_COT_1,
    "fs_cot_turn_by_turn": FS_COT_2,
}
