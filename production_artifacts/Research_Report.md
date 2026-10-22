# Research Report: Graph-Grounded Multi-Agent Ensemble for Recommendation

**Date**: 2026-10-22
**Requested by**: Initial analysis of replacing the current fixed-fanout recommendation flow with a Multi-Agent Ensemble / Mixture-of-Agents architecture for product extraction, preselection, analysis, discussion, and consensus.
**Status**: Pending Approval

## Executive Summary

The proposed direction is compatible with the project's vision: the current system already combines an orchestrator, hybrid GraphRAG retrieval, a Critic agent, Graph Evidence Paths (template metapaths inspired by KECR/PGPR), and grounded response generation. The recommended change is not an unconstrained swarm, but a bounded, graph-grounded ensemble. Several specialized workers should independently produce search hypotheses and candidates; a typed shared state should merge them; deterministic Knowledge Graph constraints should remain authoritative; and verifier/advocate agents should reason only over retrieved catalog evidence. The first implementation should preserve the existing `AgentOrchestrator` and `GraphSearchTool` contracts, activate the existing batched Critic path, and introduce bounded parallel exploration before considering a larger orchestration refactor.

## Problem Statement

The current recommendation path has a fixed candidate fanout (`candidate_limit`, currently defaulting to 20) and a largely linear execution shape:

`router → search-parameter generation → GraphSearchTool → CriticAgent → Graph Evidence Paths → final generator`.

This design is already grounded and measurable, but it has three limitations relevant to the proposed research direction:

1. A single search hypothesis can miss products when category resolution, lexical wording, or the selected retrieval channel is wrong.
2. Hierarchical constraint relaxation is deterministic, but the system does not yet make the reason for a new search strategy explicit to a separate search worker.
3. The current orchestrator calls the legacy per-item `CriticAgent.evaluate_candidates()` method. The batched `evaluate_candidate_tradeoffs()` method exists and supports structured trade-off disclosure, but it is not wired into the live path.

The research question is therefore not simply “can more agents generate better text?” It is: **can bounded diversity in graph exploration and independent verification increase candidate recall, constraint adherence, groundedness, and explanation quality without making latency, cost, and evaluation irreproducible?**

## Research Findings

### Literature & Documentation Review

#### Mixture-of-Agents

- **Source**: Wang et al., *Mixture-of-Agents Enhances Large Language Model Capabilities* — [arXiv](https://arxiv.org/abs/2406.04692)
- **Key takeaways**: The proposed architecture uses multiple agents in layers; each agent receives outputs from a previous layer and a final layer aggregates or synthesizes them. The key transferable idea is structured diversity followed by aggregation, not unrestricted conversation.
- **Applicability**: Useful for parallel query hypotheses and candidate-set synthesis. The paper does not make LLM agreement a substitute for external truth, so in this project the aggregator must be constrained by Neo4j evidence and typed candidate records.

#### Multi-Agent Debate

- **Source**: Du et al., *Improving Factuality and Reasoning in Language Models through Multiagent Debate* — [arXiv](https://arxiv.org/abs/2305.14325)
- **Key takeaways**: Independent model instances propose answers and debate over several rounds. The approach is relevant to adversarial verification, but debate can still produce agreement around a shared error when all participants see the same incomplete evidence.
- **Applicability**: Supports a small verifier/challenger round after retrieval. It does not justify allowing agents to override hard catalog constraints or to invent missing product facts.

#### LLM-powered agents for recommender systems

- **Source**: *A Survey on LLM-powered Agents for Recommender Systems* — [ACL Anthology](https://aclanthology.org/2025.findings-emnlp.620/)
- **Key takeaways**: Agent recommender systems can be grouped into recommendation-oriented, interaction-oriented, and simulation-oriented paradigms. The survey emphasizes that agent roles should map to recommendation tasks rather than merely multiply LLM calls.
- **Applicability**: The proposed Scout, Verifier, User Advocate, and Orchestrator roles are defensible when each has a distinct responsibility and measurable output. A role without a separate decision object or metric would add complexity without research value.

#### Multi-Agent Conversational Recommender System

- **Source**: *A Multi-Agent Conversational Recommender System* — [arXiv](https://arxiv.org/abs/2402.01135)
- **Key takeaways**: Multi-agent decomposition is used to address conversational recommendation challenges beyond simply prompting one LLM. This supports the thesis framing that orchestration and interaction policy are meaningful parts of a CRS contribution.
- **Applicability**: Relevant to the conversational layer and active clarification. The project's Amazon-only dataset and graph-grounding constraints remain stronger than a generic conversational-agent design.

#### Stateful graph orchestration

- **Source**: LangGraph Graph API overview — [LangChain documentation](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- **Key takeaways**: LangGraph models workflows as state graphs with nodes, edges, and looping state transitions. This is a natural fit for bounded fan-out, conditional re-search, checkpoints, and human-in-the-loop transitions.
- **Applicability**: LangGraph is technically suitable for the proposed bounded loop. However, the Vision decision log explicitly accepted procedural Python for the current five-action router and positioned LangGraph initially as a persistence mechanism. A framework migration should therefore follow demonstrated workflow complexity, not precede it.

### Technology / Approach Comparison

| Criterion | Current procedural extension | LangGraph bounded workflow | Open-ended swarm / free debate |
|---|---|---|---|
| Alignment with project vision | High; extends existing MAS + GraphRAG | High if state remains typed and graph-grounded | Medium; risks weakening deterministic grounding |
| Integration with Neo4j KG | Direct reuse of existing tools | Direct reuse through graph nodes | Often indirect; agents may invent intermediate facts |
| Implementation complexity | Low–medium | Medium | High and difficult to control |
| Reproducibility | High with fixed seeds, caps, and traces | High if checkpoints and state schema are explicit | Low unless heavily constrained |
| Latency and cost | Predictable bounded increase | Predictable if fan-out and rounds are capped | Potentially unbounded |
| Research value | Strong incremental ablation | Strong workflow/state contribution | Weak unless a novel consensus protocol is rigorously defined |
| Recommendation | Use first | Introduce when cycles/checkpoints justify it | Reject for the first implementation |

### Codebase Impact Assessment

The existing system already provides most of the required infrastructure:

- `src/agents/orchestrator.py` owns routing, search-parameter generation, candidate preparation, Critic execution, Graph Evidence Paths extraction, response generation, and `eval_trace` assembly.
- `src/agents/state.py` provides a typed dictionary state, but it currently lacks explicit fields for search hypotheses, per-agent candidate contributions, evidence verdicts, consensus status, iteration count, latency, and token/cost telemetry.
- `src/tools/graph_search_tool.py` already exposes hybrid vector/lexical/structural retrieval, RRF metadata, soft scoring, hierarchical constraint relaxation, and product-detail retrieval. It should remain the only component that decides catalog facts and executes Neo4j search.
- `src/agents/critic_agent.py` contains both the legacy per-item evaluator and the batched `evaluate_candidate_tradeoffs()` path. The latter is the better base for a verifier stage because it returns structured rankings, disclosure text, and rationale.
- `src/tools/kecr_tool.py` and `src/llm_interface/prompt_constructor.py` already provide graph evidence extraction and provenance-aware generation.
- `tests/test_agent_orchestrator.py`, `tests/test_critic_agent.py`, `tests/test_graph_search_tool.py`, `tests/test_score_fusion.py`, and the live-evaluation tests provide seams for regression and ablation tests.
- `requirements.txt` already includes `langgraph>=1.0.0`, but the repository's Vision decision log records that procedural orchestration is currently intentional. The dependency alone is not evidence that the whole orchestrator should be rewritten.

Recommended new boundaries, if approved:

```text
src/agents/ensemble_state.py       # typed blackboard / evidence contracts
src/agents/recommendation_ensemble.py  # bounded fan-out, merge, retry budget
src/agents/scout_agents.py         # retrieval strategies, not free-form chat agents
src/agents/consensus_agent.py      # evidence-constrained final selection
tests/test_recommendation_ensemble.py
tests/test_consensus_grounding.py
```

These names are proposals, not an implementation commitment. Existing modules should be extended where the new abstraction is small enough to preserve current contracts.

## Guardian Assessment

### ✅ Vision Alignment

The proposal directly strengthens the existing strategic vision:

- It preserves Multi-Agent orchestration rather than reverting to a single RAG chain.
- It improves Hybrid GraphRAG recall by allowing independent retrieval hypotheses over the existing product, attribute, review, full-text, and Taxon channels.
- It preserves the Knowledge Graph as the grounding layer: an agent may propose a query or candidate, but only Neo4j-returned product records and extracted graph paths may support a recommendation.
- It supports explainability because each candidate can carry agent provenance, retrieval-channel evidence, hard-constraint verdicts, Critic reasoning, and KECR paths.
- It is compatible with the project's active evaluation framework and with the existing thesis claim about multi-agent verification.

It does not require a change to the Amazon-only dataset, graph v2, RRF retrieval, or the current hard/soft constraint taxonomy.

### ⚖️ Complexity Analysis

The proposed “swarm” language is useful as a conceptual metaphor, but an unconstrained swarm would exceed the project's complexity budget. The main risks are duplicated LLM reasoning, correlated errors, uncontrolled recursive search, non-deterministic explanations, and a large cost/latency increase.

The recommended complexity budget is:

- 3 bounded Scout strategies per request: semantic/product, lexical/Taxon, and exploratory relaxation/substitution.
- Each Scout returns a typed `SearchHypothesis`, not a prose conversation.
- At most 8–10 candidates per Scout before deterministic de-duplication, with a global candidate cap such as 30.
- One Verifier pass over the merged candidates.
- At most 2 corrective retrieval rounds, only when evidence shows candidate starvation, hard-constraint failure, or disagreement above a threshold.
- One final Consensus/Advocate decision that cannot override hard constraints and cannot create catalog facts.

This delivers meaningful agent diversity while keeping execution bounded and comparable to the existing `top_k` baseline.

### 🔗 Integration Assessment

The strongest integration pattern is a shared typed blackboard:

1. The existing router and session context produce canonical user intent, hard constraints, soft preferences, and profile context.
2. Scout workers independently translate that state into search hypotheses and call `GraphSearchTool` through a narrow interface.
3. A deterministic merger de-duplicates by ASIN, retains per-Scout and per-channel provenance, and preserves each relaxation decision.
4. A Strict Verifier labels every requested constraint `SATISFIED`, `VIOLATED`, or `UNKNOWN` using retrieved catalog fields, reviews, and graph evidence.
5. A User Advocate ranks acceptable trade-offs using the session profile, but may not downgrade a hard violation to a success.
6. A Consensus node selects the final top 3 and emits an evidence ledger to KECR and `PromptConstructor`.

The proposed roles should be defined by contracts:

| Role | Input | Output | Authority |
|---|---|---|---|
| Graph Scout | SessionContext + strategy | SearchHypothesis + live candidates | May explore, never assert facts not returned by KG |
| Strict Verifier | Candidate records + evidence | Three-valued constraint verdicts | Authoritative for hard constraint violations |
| User Advocate | Verified candidates + profile | Preference-weighted trade-off ranking | May rank soft compromises, not hard violations |
| Orchestrator / Consensus | All typed outputs | Final selection + evidence ledger | Controls budget, termination, and response contract |

The “pheromone” idea should not write mutable inference traces into Neo4j. Use an in-memory or persisted execution state for each request. Neo4j should remain the catalog and provenance source, avoiding cross-request contamination and preserving reproducible evaluation.

### ⚠️ Risks & Trade-offs

1. **Agreement is not truth.** Multiple agents using the same incomplete graph can agree on the same wrong interpretation. Deterministic Neo4j checks and three-valued evidence verdicts are required.
2. **Correlated agents.** Three prompts sent to the same model do not automatically create cognitive diversity. Diversity must come from retrieval strategies, channel restrictions, prompt roles, and measurable disagreement—not only temperature.
3. **Latency and cost.** Parallel Scouts reduce wall-clock growth but increase total tokens and Neo4j calls. Every run must record call count, elapsed time, and token usage where available.
4. **Search-loop instability.** “Search until consensus” is unsafe. Termination must be controlled by a maximum round count, candidate cap, and explicit stop conditions.
5. **Silent compromises.** An Advocate must never silently approve a widened budget or violated hard constraint. Existing `relaxed_constraints` and the final disclosure mechanism should be mandatory outputs.
6. **Architecture drift.** A full LangGraph rewrite before proving the ensemble adds migration risk. The current procedural orchestrator is already stateful and testable; a thin ensemble service can validate the research hypothesis first.
7. **Evaluation leakage and overfitting.** If agents adapt repeatedly to the frozen benchmark, they can overfit retrieval strategies. Keep the existing frozen holdout, archive manifests, and run ablations against the same live graph version.

## Recommendation

### Recommended Approach

Adopt a **Bounded Graph-Grounded Multi-Agent Ensemble (BG-MAE)** as an incremental extension of the current architecture.

The first version should implement this workflow:

```text
SessionContext
    ↓
bounded parallel Scouts
    ↓
deterministic candidate merger + provenance ledger
    ↓
Strict Verifier (three-valued evidence checks)
    ↓
User Advocate / trade-off ranker
    ↓
bounded corrective search, if needed
    ↓
Consensus top-3 + KECR evidence
    ↓
grounded response generation
```

The initial implementation should preserve `AgentOrchestrator.run()` and `GraphSearchTool.search()` as public entry points. It should first:

1. Add typed ensemble state and per-agent trace records.
2. Extract the current search branch into a reusable bounded ensemble coordinator.
3. Implement three retrieval strategies using the existing GraphSearchTool interface.
4. Replace the live per-item Critic call with the existing batched trade-off evaluator, after deciding and testing its fail-closed behavior.
5. Enforce hard constraints outside the LLM and pass only verified evidence to the final generator.
6. Add the ensemble trace to the existing `eval_trace` without changing the benchmark schema.
7. Compare the ensemble against the current RRF + legacy Critic baseline before adding more agent roles or a framework migration.

LangGraph should be introduced only if the bounded workflow needs explicit parallel branches, cyclic retry edges, or checkpointed session execution that becomes cumbersome in procedural Python. If introduced, use it as an execution layer around the typed contracts; do not move Neo4j truth or constraint enforcement into arbitrary agent messages.

### Proposed Agent Contracts

```text
SearchHypothesis:
  strategy, semantic_query, structured_filters, soft_preferences,
  rationale, requested_channels, round_id

CandidateEvidence:
  asin, source_strategies, channel_scores, catalog_snapshot,
  graph_paths, constraint_verdicts, critic_score, critic_reasoning

ConsensusDecision:
  selected_asins, rejected_asins, tradeoffs, unresolved_unknowns,
  termination_reason, rounds_used, grounded_evidence
```

These are conceptual contracts for the specification phase. They should become Pydantic models or equivalent typed structures only after approval.

### Evaluation Plan

Use the current live-data, frozen benchmark and compare at least these arms:

1. **Baseline**: current GraphSearchTool RRF + current Critic path.
2. **Ensemble retrieval**: three Scouts + deterministic merge, no extra debate.
3. **Ensemble verification**: ensemble retrieval + batched Strict Verifier/Trade-off Critic.
4. **Full BG-MAE**: ensemble verification + bounded corrective round + consensus disclosure.

Report:

- HR@K, NDCG@K, MRR, candidate recall before and after verification.
- Hard-constraint violation rate, CVER, FPPA, Critic Acceptance Rate, and ranking gain.
- Catalog Validity Rate and provenance-grounded explanation scores.
- Clarification quality, recoverability, multi-turn coherence, latency, LLM calls, tokens, and estimated cost.
- Consensus stability across repeated runs and the proportion of UNKNOWN evidence.

The central thesis claim should be conditional: **BG-MAE improves recommendation quality or groundedness at an acceptable cost relative to the frozen RRF + Critic baseline.** If it does not, the negative result is still academically useful and prevents attributing gains to agent count alone.

### What NOT to Do

- Do not replace the Knowledge Graph with agent memory, a mutable “pheromone” layer, or a free-form blackboard that stores unverified facts.
- Do not let agents write directly to Neo4j during inference.
- Do not use unrestricted “search until consensus”; cap rounds, candidates, and tool calls.
- Do not treat majority vote or LLM agreement as a factual verifier.
- Do not create multiple agents that all perform the same retrieval with different prose prompts and call that diversity.
- Do not make the Advocate override price ceilings, excluded brands, category validity, or other hard constraints.
- Do not remove the current RRF and deterministic retrieval baseline; it is necessary for ablation and thesis validity.
- Do not perform a full LangGraph migration as the first implementation step. Validate the ensemble hypothesis at the existing module boundaries first.

## Sources

1. Wang et al., *Mixture-of-Agents Enhances Large Language Model Capabilities*, arXiv:2406.04692 — https://arxiv.org/abs/2406.04692
2. Du et al., *Improving Factuality and Reasoning in Language Models through Multiagent Debate*, arXiv:2305.14325 — https://arxiv.org/abs/2305.14325
3. *A Survey on LLM-powered Agents for Recommender Systems*, Findings of EMNLP 2025 — https://aclanthology.org/2025.findings-emnlp.620/
4. *A Multi-Agent Conversational Recommender System*, arXiv:2402.01135 — https://arxiv.org/abs/2402.01135
5. LangGraph Graph API overview, LangChain documentation — https://langchain-ai.github.io/langgraph/concepts/low_level/

