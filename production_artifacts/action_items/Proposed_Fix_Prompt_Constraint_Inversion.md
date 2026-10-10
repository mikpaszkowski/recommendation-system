# Architectural Fix Proposal: Prompt Schema Realignment & Intent Inversion Elimination

**Document Identifier**: `AFP-004`  
**Target Milestone**: Milestone 3 — Architectural Fix Proposals  
**Component**: Conversational Preference Extractor, Prompt Schema & Dialogue Router  
**Affected Files**:  
- `src/llm_interface/prompts/preference_extract_prompt.py` (Constraint taxonomy instructions)  
- `src/llm_interface/preference_parser.py` (Schema validation for hard constraints)  
- `src/agents/orchestrator.py` (`_decide_next_step:221-231` router guardrails)  
- `src/tools/graph_search_tool.py` (`_build_filters:423-431` affirmative brand filtering)  
**Author**: Principal Solutions Architect (`worker_architectural_fixes_m3`)  
**Status**: APPROVED BY CONSENSUS (Milestone 2 Debate Adjudication)  

---

## 1. Executive Summary & Failure Mapping

### 1.1 The Brand Inversion & Dialogue Abort Pathology
In conversational recommendation systems, users frequently state explicit brand allegiances or preferences alongside their functional requirements (e.g., *"I want an Apple laptop"*, *"from LG"*, *"Sony noise-canceling headphones"*).

In evaluation run `eval_2026-10-07_0222`, the system exhibited a catastrophic intent-inversion failure:
1. **The Negative-Only Brand Rule**: The extraction prompt (`preference_extract_prompt.py:44-48`) strictly forbade the LLM from placing included brands in `hard_constraints`, permitting `brand` *only* when the operator was `"exclude"`.
2. **Hallucinated Inversion**: When faced with an explicit user constraint like *"from LG"*, the extractor attempted to satisfy the user's hard constraint by inverting the brand into `"exclude"`: `{"attribute": "brand", "operator": "exclude", "value": "LG"}`.
3. **Dialogue Router Abort**: The Dialogue Router observed the severe contradiction between the user utterance ("from LG") and the active filter ("exclude LG"). Instead of executing search, the router aborted to `action = "CLARIFY"`.
4. **Zero-Yield Retrieval**: Retrieval was never executed! Zero Cypher queries and zero vector searches were performed, resulting in an immediate **0% Hit Rate** and an unnecessary conversational delay.

### 1.2 Quantitative Evidence from `execution_trace.log` (Query 16 — `ret_016`)
Forensic analysis of Query 16 in `execution_trace.log` reveals the complete chain of causality:
- **User Utterance**: *"I want a 32-inch 4K 144Hz monitor for under $150 from LG"*
- **Extracted Hard Constraints**:
  ```json
  [
    {"attribute": "price", "operator": "less_than", "value": 150},
    {"attribute": "category", "operator": "include", "value": "monitor"},
    {"attribute": "brand", "operator": "exclude", "value": "LG"}
  ]
  ```
- **Active Filters Generated**:
  ```json
  {
    "category": "monitor",
    "price_max": 150.0,
    "exclude_brand": "LG",
    "brand_exclude": "LG"
  }
  ```
- **Router Output (`AgentOrchestrator._decide_next_step`)**:
  ```json
  {
    "action": "CLARIFY",
    "reasoning": "Contradiction detected: User requested 'from LG' but filters specify exclude LG. Clarification required."
  }
  ```
- **Telemetry Outcome**:
  - `Total candidates retrieved: 0`
  - `Search executed: False`
  - `Hit@1: 0 | Hit@5: 0 | Hit@10: 0 | Hit@20: 0`

Query 16 provides empirical proof of **Tier 1 (Conversational & Prompt Intent Routing) failure**: when the prompt schema corrupts user intent, symbolic graph filtering and vector ranking are never even reached.

---

## 2. Current Implementation Defect

### 2.1 The Restrictive Prompt Rule in `preference_extract_prompt.py`
The root cause is located in `src/llm_interface/prompts/preference_extract_prompt.py` lines 44–48:

```markdown
<!-- CURRENT DEFECTIVE PROMPT: src/llm_interface/prompts/preference_extract_prompt.py:44-48 -->
CRITICAL TAXONOMY RULE: The ONLY allowed attributes for hard_constraints are:
1. price (budget constraints, e.g., less_than 1000)
2. category (the domain/type of product, e.g., include "laptop")
3. brand (ONLY when the operator is "exclude")

Do NOT put technical specifications (e.g., RAM, refresh rate, screen size) or included brands (e.g., "I want a Sony") in hard_constraints. These must go to soft_preferences.
```

### 2.2 Why the LLM Inverts Affirmative Brands
1. In conversation, when a user says *"from LG"* or *"I must have an ASUS"*, the user is expressing an unambiguous, non-negotiable hard requirement.
2. The LLM's system prompt instructs: *"Strict, non-negotiable filters that MUST be obeyed... If an item violates any hard constraint, it cannot be recommended"*.
3. However, rule #3 states: *"brand (ONLY when the operator is 'exclude')"*.
4. Because the LLM strongly recognizes the user's intent to bind the brand to `LG`, and because the schema allows the `"brand"` attribute *only* under the `"exclude"` operator, the LLM hallucinates an inversion: it selects `operator: "exclude"`.
5. This transforms an explicit desire into a hard negative ban.

### 2.3 The Downstream Router Contradiction Guardrail
In `src/agents/orchestrator.py` lines 221–231:

```python
# CURRENT CODE: src/agents/orchestrator.py:221-231
# Guardrail: If router chose SEARCH, but dialogue state indicates critical attributes are missing,
# gracefully switch to CLARIFY to ask for missing required attributes
dialogue_state = current_context.get("dialogue_state", {})
ready = dialogue_state.get("ready_for_recommendation", True)
missing = dialogue_state.get("missing_critical_attributes", [])
if action == "SEARCH" and not ready and missing:
    logger.info(f"Guardrail: Critical attributes missing {missing}. Switching SEARCH -> CLARIFY.")
    action = "CLARIFY"
    reasoning = f"Missing critical attributes ({', '.join(missing)}). Clarification required before searching."
```

When the LLM detects the contradiction between the utterance *"from LG"* and the filter `exclude_brand: "LG"`, it flags `ready_for_recommendation: false` and sets `missing_critical_attributes: ["brand_clarification"]`.
The router fires the guardrail and aborts search, locking the conversation in a clarification loop.

---

## 3. Detailed Architectural Redesign

To resolve this defect, we implement a cohesive prompt, parser, and router realignment that fully supports affirmative brand constraints across the entire stack.

```
+-----------------------------------------------------------------------------------+
|               AFFIRMATIVE BRAND EXTRACTION & ROUTING ARCHITECTURE                 |
+-----------------------------------------------------------------------------------+
| 1. PROMPT REALIGNMENT (preference_extract_prompt.py):                             |
|    - Remove negative-only restriction on brand                                    |
|    - Allow operator: "equal" or "include" for positive brands ("from LG")         |
|    - Retain operator: "exclude" for negative brands ("not HP")                    |
|-----------------------------------------------------------------------------------|
| 2. SCHEMA PARSER UPDATE (preference_parser.py):                                   |
|    - Validate attribute "brand" with operators in {"equal", "include", "exclude"} |
|-----------------------------------------------------------------------------------|
| 3. SESSION ADAPTER INTEGRATION:                                                   |
|    - Map positive brand to active_filters["brand"]                                |
|    - Map negative brand to active_filters["exclude_brand"]                        |
|-----------------------------------------------------------------------------------|
| 4. ROUTER GUARDRAIL IMMUNIZATION (orchestrator.py):                               |
|    - Ensure explicit brand + category declares ready_for_recommendation = True   |
|    - Prevent false contradiction triggers; guarantee action = "SEARCH"            |
|-----------------------------------------------------------------------------------|
| 5. CYPHER FILTER ASSEMBLY (graph_search_tool.py):                                 |
|    - Case-insensitive containment match: toLower(b.name) CONTAINS $brand_filter   |
|    - High-confidence Resolver normalization (BRAND_CONFIDENCE = 0.85)             |
+-----------------------------------------------------------------------------------+
```

### 3.1 Step 1: Prompt Taxonomy Rule Realignment
In `src/llm_interface/prompts/preference_extract_prompt.py`, delete the negative-only brand restriction and replace it with explicit rules for both affirmative and negative brands:

```markdown
<!-- PROPOSED PROMPT: src/llm_interface/prompts/preference_extract_prompt.py -->
CRITICAL TAXONOMY RULE: The ONLY allowed attributes for `hard_constraints` are:
1. `price` (budget constraints, e.g., less_than 1000, greater_than 50)
2. `category` (the domain/type of product, e.g., include "laptop")
3. `brand` (EITHER affirmative inclusion OR negative exclusion):
   - Use operator "equal" or "include" when the user specifies a required brand (e.g., "from LG", "by Sony", "Apple laptop").
   - Use operator "exclude" when the user explicitly rejects a brand (e.g., "no HP", "except Dell", "anything but Apple").

Do NOT put technical specifications (e.g., RAM, refresh rate, screen size) in `hard_constraints`. These must go to `soft_preferences`.

Each hard constraint object MUST contain:
- "attribute" (String): Restricted to "price", "category", or "brand".
- "operator" (String): EXACTLY ONE of the allowed enums:
  * "include": For category (e.g. include "laptop") or brand (e.g. include "LG").
  * "equal": For strict brand or category matching (e.g. brand equal "Sony").
  * "exclude": For brand exclusion only (e.g. exclude "HP").
  * "greater_than": For price minimums.
  * "less_than": For price maximums/ceilings.
- "value" (Number or String): The target constraint value.
```

### 3.2 Step 2: Schema Parser Validation in `preference_parser.py`
In `src/llm_interface/preference_parser.py`, update schema validation to accept affirmative brand operators:

```python
# PROPOSED CODE: src/llm_interface/preference_parser.py
VALID_OPERATORS = {
    "price": {"less_than", "greater_than", "equal"},
    "category": {"include", "equal"},
    "brand": {"equal", "include", "exclude"},
}

def validate_hard_constraint(constraint: Dict[str, Any]) -> bool:
    attr = constraint.get("attribute")
    op = constraint.get("operator")
    val = constraint.get("value")
    
    if attr not in VALID_OPERATORS:
        return False
    if op not in VALID_OPERATORS[attr]:
        return False
    if val is None or str(val).strip() == "":
        return False
    return True
```

### 3.3 Step 3: Session Adapter & Active Filter Mapping
In `src/dialog_manager/session_adapter.py`, map extracted brand constraints to clean structured filter keys:

```python
# Mapping extracted hard constraints into active search filters
for hc in extracted_parameters.get("hard_constraints", []):
    attr = hc.get("attribute")
    op = hc.get("operator")
    val = hc.get("value")
    
    if attr == "brand":
        if op in ["equal", "include"]:
            active_filters["brand"] = str(val).strip()
            # Clear any stale contradictory exclusion
            active_filters.pop("exclude_brand", None)
            active_filters.pop("brand_exclude", None)
        elif op == "exclude":
            active_filters["exclude_brand"] = str(val).strip()
            active_filters["brand_exclude"] = str(val).strip()
            # Clear any stale contradictory positive brand
            active_filters.pop("brand", None)
```

### 3.4 Step 4: Dialogue Router Guardrail Immunization
In `src/agents/orchestrator.py`, update `_decide_next_step`:
When a user provides both a valid category and a preferred brand, the dialogue state must be recognized as fully ready for search, preventing spurious `CLARIFY` actions:

```python
# PROPOSED CODE: src/agents/orchestrator.py:221-235
dialogue_state = current_context.get("dialogue_state", {})
missing = dialogue_state.get("missing_critical_attributes", [])

# Affirmative Brand Immunization: If user provided both category and brand, proceed directly to SEARCH
has_category = bool(active_filters.get("category") or current_context.get("category"))
has_brand = bool(active_filters.get("brand"))

if action == "CLARIFY" and has_category and has_brand:
    logger.info("Immunization: User has specified category and brand. Overriding CLARIFY -> SEARCH.")
    action = "SEARCH"
    reasoning = "Category and preferred brand provided; initiating targeted graph search."
elif action == "SEARCH" and not ready and missing:
    # Only clarify if truly critical attributes (e.g. completely missing category) are absent
    if "category" in missing:
        logger.info(f"Guardrail: Critical category missing. Switching SEARCH -> CLARIFY.")
        action = "CLARIFY"
```

### 3.5 Step 5: Affirmative Brand Matching in `GraphSearchTool`
In `src/tools/graph_search_tool.py` lines 423–431, ensure that affirmative brand filtering executes case-insensitively and supports corporate suffixes via containment and canonical resolution:

```python
# PROPOSED CODE: src/tools/graph_search_tool.py:423-435
elif key == "brand":
    raw_brand = raw_filters.get("brand", value)
    where_clauses.append(
        "(EXISTS { MATCH (node)-[:HAS_BRAND]->(b:Brand) "
        "WHERE toLower(b.name) = toLower($brand_filter) "
        "   OR toLower(b.name) CONTAINS toLower($brand_filter) "
        "   OR toLower($brand_filter) CONTAINS toLower(b.name) } "
        "OR toLower(node.title) CONTAINS toLower($raw_brand_filter))"
    )
    params["brand_filter"] = value
    params["raw_brand_filter"] = raw_brand
```

#### Why Case-Insensitive Containment is Mandatory for Catalog Nodes
In the Neo4j catalog, brand nodes frequently include corporate or trade suffixes:
- In benchmark scenario `live_eval_phone_01` (ASIN `B08GNRGB67`, Samsung Galaxy S20 FE), the product is connected to `:Brand {name: 'Samsung Electronics'}`.
- Under strict equality `toLower(b.name) = 'samsung'`, `'samsung electronics' = 'samsung'` evaluates to **`FALSE`**, rejecting genuine target products.
- Similar patterns occur across the graph (`Apple Computer`, `Anker Direct`, `Sony Electronics`).

By evaluating `toLower(b.name) = toLower($brand_filter) OR toLower(b.name) CONTAINS toLower($brand_filter) OR toLower($brand_filter) CONTAINS toLower(b.name)`, the system reliably matches both canonical root brands (`LG`, `Apple`) and suffixed entities (`Samsung Electronics`), while `ResolverService` (`BRAND_CONFIDENCE = 0.85`) normalizes common aliases.

---

## 4. Query Resolution Walkthrough

### 4.1 Walkthrough of Query 16 (`ret_016`)

#### Before Fix (Execution Trace Failure)
1. **User Utterance**: *"I want a 32-inch 4K 144Hz monitor for under $150 from LG"*
2. **LLM Extraction**: Constrained by rule *"brand (ONLY when operator is exclude)"*, LLM emits:
   `{"attribute": "brand", "operator": "exclude", "value": "LG"}`
3. **Session Filters**: `active_filters = {"category": "monitor", "price_max": 150.0, "exclude_brand": "LG"}`
4. **Router Assessment**: Sees "from LG" vs "exclude LG", detects internal contradiction, switches to `action = "CLARIFY"`.
5. **System Response**:
   `"Could you clarify if you're looking for a specific model from LG, or are you open to any 32-inch 4K 144Hz monitor..."`
6. **Retrieval**: Completely bypassed. Zero candidates retrieved.

#### After Fix (Seamless Search Execution)
1. **User Utterance**: *"I want a 32-inch 4K 144Hz monitor for under $150 from LG"*
2. **LLM Extraction**: Allowed to emit affirmative brand:
   ```json
   {
     "hard_constraints": [
       {"attribute": "category", "operator": "include", "value": "monitor"},
       {"attribute": "price", "operator": "less_than", "value": 150.0},
       {"attribute": "brand", "operator": "equal", "value": "LG"}
     ],
     "soft_preferences": [
       {"category": "screen_size", "value": "32-inch", "polarity": 1.0},
       {"category": "resolution", "value": "4K", "polarity": 1.0},
       {"category": "refresh_rate", "value": "144Hz", "polarity": 1.0}
     ]
   }
   ```
3. **Session Filters**:
   ```json
   {
     "category": "monitor",
     "price_max": 150.0,
     "brand": "LG"
   }
   ```
4. **Router Assessment**: Category (`monitor`) and brand (`LG`) are present. Router selects `action = "SEARCH"`.
5. **Graph Search Execution**:
   - `ResolverService` verifies `"LG"` $\to$ `:Brand {name: 'LG'}` (score 1.0).
   - Executed Cypher:
     ```cypher
     MATCH (node:ParentProduct)
     WHERE (node.price IS NULL OR node.price <= 150.0)
       AND (EXISTS { MATCH (node)-[:HAS_BRAND]->(b:Brand) 
                     WHERE toLower(b.name) = 'lg' 
                        OR toLower(b.name) CONTAINS 'lg' 
                        OR 'lg' CONTAINS toLower(b.name) } 
            OR toLower(node.title) CONTAINS 'lg')
       AND (EXISTS { MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category) WHERE toLower(c.name) CONTAINS 'monitor' }
            OR toLower(node.title) CONTAINS 'monitor')
     ...
     ```
6. **Result**: Candidate LG monitors are retrieved immediately. The system recommends LG displays without conversational interruption, successfully satisfying the query.

---

## 5. Verification & Acceptance Test Strategy

### 5.1 Verification Test 1: LLM Preference Extraction Unit Test
Verify that affirmative brand requests are parsed as `hard_constraints` with `operator: "equal"` or `"include"`, never `"exclude"`:

```python
# tests/test_prompt_constraint_inversion.py
import pytest
from src.llm_interface.preference_parser import LLMPreferenceParser

@pytest.mark.asyncio
async def test_affirmative_brand_extraction():
    parser = LLMPreferenceParser()
    utterance = "I want a 32-inch 4K 144Hz monitor for under $150 from LG"
    result = await parser.aparse(utterance)
    
    hard_constraints = result.get("extracted_parameters", {}).get("hard_constraints", [])
    brand_constraints = [c for c in hard_constraints if c.get("attribute") == "brand"]
    
    assert len(brand_constraints) == 1, "Expected exactly 1 brand hard constraint"
    assert brand_constraints[0]["value"].upper() == "LG", "Brand value must be 'LG'"
    assert brand_constraints[0]["operator"] in ["equal", "include"], (
        f"Brand operator must be 'equal' or 'include', got '{brand_constraints[0]['operator']}'"
    )
    assert brand_constraints[0]["operator"] != "exclude", (
        "CRITICAL DEFECT: Affirmative brand 'from LG' was inverted into 'exclude'!"
    )
```

### 5.2 Verification Test 2: Orchestrator Router Action Test
Assert that affirmative brand requests trigger `action == "SEARCH"` and do not divert to `CLARIFY`:

```python
@pytest.mark.asyncio
async def test_orchestrator_routes_affirmative_brand_to_search():
    orchestrator = AgentOrchestrator()
    utterance = "Looking for an Apple MacBook Air under $1000"
    
    # Process turn
    result = await orchestrator.run(user_id="test_user", message=utterance)
    
    assert result["action"] == "SEARCH", (
        f"Expected action 'SEARCH' for well-specified brand request, got '{result['action']}'"
    )
    assert result["eval_trace"]["raw_candidates"] is not None
```

### 5.3 Acceptance Criteria Table
| Criteria ID | Requirement Description | Verification Method | Pass/Fail Condition |
| :--- | :--- | :--- | :--- |
| **AC-004.1** | Prompt rule forbidding affirmative brand is removed from `preference_extract_prompt.py` | Inspect prompt template | No restriction stating "brand (ONLY when operator is exclude)" |
| **AC-004.2** | Preference parser accepts `brand` with operator `equal` and `include` | Unit test execution | `validate_hard_constraint({"attribute": "brand", "operator": "equal", "value": "LG"}) == True` |
| **AC-004.3** | Utterance "from LG" extracts affirmative brand `brand == 'LG'` | Run `test_affirmative_brand_extraction` | `operator in ["equal", "include"]` |
| **AC-004.4** | Dialogue router proceeds to `SEARCH` for well-specified brand queries | Run `test_orchestrator_routes_affirmative_brand_to_search` | `result["action"] == "SEARCH"` |
| **AC-004.5** | Cypher brand filter supports corporate suffixes via case-insensitive containment | Inspect Cypher in `_build_filters` | Uses `toLower(b.name) = $brand OR toLower(b.name) CONTAINS $brand` |
