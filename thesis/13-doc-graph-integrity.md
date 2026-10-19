# Thesis Contribution 13: Integrity of the Grounding Knowledge Graph — Construction Defects, a Leakage-Safe Validated Rebuild, and Version-Bound Citability

**Document ID**: `13-doc-graph-integrity`  
**Date**: 2026-10-19  
**Status**: Confirmed Master's Thesis Contribution (Methodological Artifact; the method is built and unit-tested, but the graph is not built yet)  
**Git Scope**: Uncommitted working tree on branch `feature/afp-002-vector-aggregation` (HEAD `0791e35`). The graph v2 files are untracked or modified and are not yet committed.  
**Relevant Modules**: `src/knowledge_graph/graph_v2/` (`transform.py`, `product_mapping.py`, `review_selection.py`, `taxonomy.py`, `lineage.py`, `validation.py`, `csv_io.py`, `import_command.py`, `models.py`, `graph_queries.py`), `src/knowledge_graph/graphdb/embedding_templates.py`, `src/evaluation/provenance.py` (FR-028, FR-029), `scripts/graph_ingestion/{preflight_v2.py, export_v1_snapshot.py, build_graph_v2.py, import_graph_v2.py, post_import_v2.py, validate_graph.py, check_baseline_diff.py}`. Legacy guards are in `scripts/graph_ingestion/batch_ingest.py`, `src/knowledge_graph/graphdb/backfill_embeddings.py` and `src/utils/AmazonDataProcessor.py`.  
**Tests**: `tests/graph_v2/` (12 test modules, fixtures in `tests/fixtures/graph_v2/`), `tests/test_legacy_ingest_guards.py`, `tests/test_graph_cypher_prompt.py`, `tests/test_provenance.py`, `tests/test_archive_eval_run.py`  
**Design Sources**: `_bmad-output/brainstorming/brainstorm-kg-attribute-problems-2026-10-18/brainstorm-intent.md` (finding, K-1 … K-12), `production_artifacts/Research_Report_Graph_Rebuild.md` (N-1 … N-9, Q1 … Q8), `production_artifacts/Technical_Specification_Graph_Rebuild.md` (FR-001 … FR-039, H-01 … H-18), Vision decisions 2026-10-19-018 … 021  
**Audit**: `production_artifacts/Audit_Report_Graph_Rebuild.md`: **PASS WITH FIXES**. Two High findings (import guard, wrong-graph guard) were fixed. 155/155 targeted tests and 767 tests in the full suite pass, with no Neo4j and no Docker.  
**Evidence status**: There is **no v2 graph and no v2 run**. Every v2 figure in this document is either a guarantee of the construction rule (checked on fixtures) or a read-only projection from the raw files.  
**Relation to earlier contributions**: Supplies the data-validity layer that the citable-run predicate of `11-doc-evaluation-protocol.md` lacked. Invalidates or qualifies claims in `3-doc-robust-retrieval.md`, `4-doc-hybrid-scoring.md`, `6-doc-orthogonal-gating.md`, `7-doc-evaluation-framework.md`, `8-doc-catalog-stratification.md`, `10-doc-fusion-ablation.md` and `11-doc-evaluation-protocol.md`; each now has a dated correction note. Prepares the official-split comparison of Meta-Phase C.

---

## 0. Scope of the Claim

This document keeps three kinds of statement apart. Each paragraph in §4 is labelled with one of them.

* **(a) Measured facts about graph v1 and the raw data.** These are read-only measurements from the brainstorm (2026-10-18), the research report and this evaluation. They are results.
* **(b) The method.** It is a catalogue-first, leakage-safe, deterministic and gate-validated KG construction whose version is bound to run citability. It is implemented, audited and unit-tested on fixtures. It has **not** been executed against Neo4j or the full raw files.
* **(c) Expected effects.** These are hypotheses to be tested once v2 is built and the v1 baseline is re-run at a fixed code commit. **No v2 retrieval, coverage or quality result is claimed.**

The contribution is methodological. It shows that a GraphRAG recommender's grounding graph can be silently corrupted in ways that count-based provenance does not detect. It also gives a construction and validation protocol under which those defects cannot recur unnoticed. It is not a claim that v2 improves recommendation quality.

---

## 1. Formal Research Context

### 1.1 Academic Problem Statement
A GraphRAG conversational recommender treats its Knowledge Graph as the grounding layer. Vision §4 states: "the system cannot invent a product or its features." That guarantee covers only what the graph contains. If the graph holds product nodes with no data, the retriever can rank them and the explainer cannot explain them. If the graph holds the interactions an evaluation later uses as ground truth, comparisons with collaborative baselines leak. If the ingest silently zeroes fields, mechanisms that depend on them (temporal decay, helpfulness ordering) do nothing, and no test fails.

Graph v1 of this project had all three defects:

| # | Defect (v1) | Mechanism | Observable symptom |
|---|---|---|---|
| D-1 | **Ghost products**: 104,281 of 265,307 `ParentProduct` nodes (39.3%) carry only `parent_asin` and an embedding | Metadata and reviews were sampled independently (`AmazonDataProcessor.process_and_save_data`); the review step created products by `MERGE` (`batch_ingest.py`); `backfill_embeddings.py` embedded empty texts | All ghosts share one blank-template vector ("Product: . Category: Unknown. Features: . Description: "), with cosine ≈ 0.99999 on a 50-ghost sample |
| D-2 | **Zeroed review fields**: `helpful_votes = 0` and `sort_timestamp = 0` in all 1,630,273 rows of `processed_reviews.csv` | Preprocessing read `helpful_votes` / `sort_timestamp`; the raw fields are `helpful_vote` / `timestamp` | The "20 most helpful" cap sorted by `verified_purchase` only; `review_id = md5(user-asin-0)` can collapse repeat reviews; temporal decay has no input |
| D-3 | **No split hygiene**: v1 review evidence was not filtered against the official Amazon 2023 valid/test splits | None needed for v1's purpose; it becomes a leakage path once Meta-Phase C uses the official splits | Measured in §4.1 (F-8) |

None of these defects was detected by the R2a evaluation protocol. The citable-run predicate (Vision 2026-10-18-015) records a graph snapshot of counts (`products`, `categories`, `reviews`). A count cannot tell a filled product node from a ghost. The three R2a gate runs were therefore `citable: true` on a graph in which 39% of the product nodes were empty.

### 1.2 Formal Research Question (RQ)
$$\mathbf{RQ_{13}}: \text{"To what extent do silent construction defects in the grounding Knowledge Graph of a GraphRAG conversational recommender (data-less product nodes with identical embeddings, zeroed interaction fields, held-out interactions in the review evidence) distort coverage statistics and retrieval conclusions, and which of those conclusions change when the graph is rebuilt by a catalogue-first, split-aware, gate-validated and version-stamped construction while code, benchmark and LLM snapshot are held fixed?"}$$

### 1.3 Hypotheses

| ID | Hypothesis | Kind | Status (2026-10-19) |
|---|---|---|---|
| $H_{13a}$ | Count-based run provenance does not detect property-level KG defects. Runs on a defective graph pass the citable predicate. | (a) | **Supported** (measured). The R2a runs were citable with 104,281 ghosts present (§4.1 F-1, F-7). |
| $H_{13b}$ | The v1 defects distort published coverage figures by large factors, not marginally. | (a) | **Supported** (measured). Titled products with reviews: 12%, not 47%. 85.3% of review-embedded products are ghosts. The base rate differs 4.1× by definition (§4.1). |
| $H_{13c}$ | The construction rule makes ghosts, held-out pairs and over-cap products impossible, and its outputs are a deterministic function of hashed inputs. | (b) | **Supported on fixtures** (unit tests, byte-identical rebuild test AC-016). **Untested at full scale**: gates H-01 … H-18 run at build time. |
| $H_{13d}$ | With code commit, benchmark and model fixed, at least one pre-registered retrieval comparison or per-arm metric on legacy-21 changes between v1 and v2. | (c) | **Open.** The direction is not predicted (spec §6.6). Two-sided paired test. |
| $H_{13d,0}$ | No paired per-query difference between v1 and v2 runs for any arm (RR, NDCG@10, HR@{5,10,20}). | (c) | Open |
| $H_{13e}$ | On v2, review-coverage-bias@K loses its discriminating power, because the review-embedded set covers almost the whole catalogue. The RS-02 comparison (`rrf2` vs `rrf3`) then measures the review channel itself rather than its coverage. | (c) | Open; derived in §4.4 |

---

## 2. State-of-the-Art Gap Analysis

### 2.1 Positioning in the Literature
* **Data validation for ML pipelines.** Breck et al. (2019) argue for schema-based checks before data is used and for treating data like code. Schelter et al. (2018) express completeness, uniqueness and referential checks as declarative "unit tests for data". Sambasivan et al. (2021) document *data cascades*: upstream data defects that surface late, silently, in downstream results. Ghost products are a textbook data cascade. A sampling choice in March 2025 surfaced in October 2026 as a hub-bias and coverage-bias artefact.
* **Leakage and rigour in recommender evaluation.** Ferrari Dacrema et al. (2019), Sun et al. (2020) and Hidasi & Czapp (2023) show how evaluation choices and flaws change conclusions. Ji et al. (2023) show that information beyond the test point leaks into offline recommender evaluation. Kapoor & Narayanan (2023) catalogue leakage as a driver of irreproducible ML results.
* **Knowledge-graph quality.** Paulheim (2017) surveys KG completion and error detection, mostly for large open KGs and mostly after the fact. In this case the KG is built from a dataset, so the construction pipeline is the natural point to enforce validity.
* **GraphRAG.** GraphRAG systems (Edge et al., 2024; Peng et al., 2024 survey) evaluate retrieval and generation over a constructed graph. Construction validity is usually assumed rather than checked.
* **Dataset documentation.** Datasheets for Datasets (Gebru et al., 2021) recommend recording how a dataset was built. The lineage file here is a machine-checkable version of that practice.

### 2.2 Gap
LLM-based CRS and GraphRAG evaluations report metrics over a graph, but they rarely make the graph's validity a precondition for citing a result. Conversely, data-validation frameworks are rarely tied to the provenance of individual evaluation runs. Two practical gaps follow:
1. **Grounding validity.** A graph can satisfy its schema (every node has a key) and still contradict the grounding premise (nodes with nothing to ground).
2. **Interaction leakage into evidence.** A conversational recommender that retrieves over review text can see, as evidence, the very review that constitutes a held-out interaction. A CF baseline trained on the official train split never sees that review. This makes the "same dataset splits" comparison of Vision §4 unfair to the baseline.

### 2.3 Red Flag Defense (Novelty Justification)
* **What fails the red-flag test and is not claimed**: the `neo4j-admin database import` wrapper, Docker volume guards, CSV quoting, gzip determinism, memory settings and the 5.14 vector-index procedure form. These are engineering, and they are documented in the spec and audit, not here.
* **What passes**:
  1. A causal account of a KG-construction defect that propagated into retrieval metrics, with measured magnitudes (§4.1).
  2. A construction rule that removes the defect class *structurally*. Nodes come only from metadata, and a relationship to a missing node aborts the import (`--bad-tolerance=0`), instead of a query-time filter.
  3. A split-aware evidence rule that makes the KG and the Meta-Phase C baselines see the same training interactions.
  4. Validation gates that test domain semantics rather than schema. One is the ghost signature (H-04). Another is an ANN self-query that detects the blank-template vector (H-11c). Others are split exclusion (H-06) and benchmark grounding (H-15).
  5. Binding the validated graph version into the citable-run predicate, so that a result can be cited only if the graph it ran on passed those gates.
* **Core Scientific Contribution**: Grounding validity is made a checkable, versioned precondition of every citable recommendation result. A measured case shows why the precondition is necessary.

---

## 3. Architecture & Formal Specification

### 3.1 Construction and Citability Flow
```mermaid
flowchart TD
    RAW["Raw Amazon Reviews 2023 Electronics<br/>meta (1,610,012 lines), reviews (43,886,944 lines)<br/>SHA-256 verified"] --> T
    SPL["Official splits train / valid / test<br/>(hashed)"] --> T
    CAT["Frozen catalogue C<br/>(265,307 v1 parent_asins, hashed)"] --> T
    T["Transform (pure Python)<br/>products from metadata only<br/>exclude valid/test pairs, cap 20 by key κ<br/>Taxon tree from category lists"] --> CSV["Node / relationship CSVs<br/>+ lineage.json (counts, drop reasons, hashes)"]
    CSV --> IMP["neo4j-admin import full<br/>--bad-tolerance=0 (dangling edge aborts)"]
    IMP --> POST["Constraints → embeddings (v1 templates, skip-empty)<br/>→ vector + full-text indexes"]
    POST --> VAL{"18 hard gates H-01 … H-18"}
    VAL -->|any fails| STOP["No stamp; graph not citable"]
    VAL -->|all pass + user confirms report SHA| GV["(:GraphVersion {version: 'v2', hashes, validation_passed: true})"]
    GV --> PROV["provenance.graph_snapshot.graph_version"]
    PROV --> CIT{"evaluate_citable (live)"}
    CIT -->|missing / not validated| NC["graph_version_unknown / graph_version_not_validated"]
    CIT -->|validated| OK["citable: true"]
```

### 3.2 Formal Specification

**The v1 defect (D-1).** Let $M$ be the products in the sampled metadata and $R$ the products referenced by the sampled reviews. v1 created $P_{v1} = M \cup R$, because reviews `MERGE`d their products. Its ghosts are $G = R \setminus M$. In the v1 input files, $|M| = 161{,}001$, $|R| = 123{,}720$ and $|M \cap R| = 19{,}414$, so $|R \setminus M| = 104{,}306$ and $|P_{v1}| = 265{,}307$. In the graph, 104,281 of these remain untitled. The 25-node difference was not traced. For every query embedding $q$, every ghost scores the same $\cos(q, e_{\text{blank}})$. Which ghost appears among tied candidates is therefore an artefact of index order.

**Catalogue-first products.** Let $C$ be the frozen catalogue and $\text{meta}$ the raw metadata records. Then
$$V_P = \{\, p \in C : p \in \text{meta} \,\},$$
with the first metadata line winning and conflicting duplicates reported. No other step creates `ParentProduct` nodes. Every `ABOUT_PRODUCT` endpoint is checked against $V_P$ before the lineage is written. The importer then rejects any dangling relationship.

**Split-aware review evidence.** Let $H = \{(u, p)\}$ be the user–product pairs of `Electronics.valid.csv` ∪ `Electronics.test.csv`. A raw review $r$ by user $u(r)$ on product $p(r)$ is eligible iff
$$p(r) \in V_P \;\wedge\; (u(r), p(r)) \notin H.$$
Train-split reviews and reviews by users outside the 5-core splits are kept (K-12). Neither is a held-out interaction.

**Bounded, deterministic selection.** Duplicates are removed by `review_id = md5(user_id-asin-timestamp)`, keeping the better key and then the lower byte offset. Then, per product, the first 20 reviews in ascending order of
$$\kappa(r) = \big(-\text{helpful\_vote},\; -\text{verified},\; -\text{timestamp},\; \text{review\_id}\big)$$
are kept (`cap_rank` 1 … n). The first 5 kept reviews with non-blank text get `embed_rank` and are embedded. Users are created only from kept reviews.

**Taxonomy.** For a raw category list $(\ell_1, \dots, \ell_d)$, every prefix becomes a `Taxon` with `taxon_id` $= \ell_1 \,\text{" > "}\, \cdots \,\text{" > "}\, \ell_k$. `BROADER` links a prefix of length $k$ to its prefix of length $k-1$. The product gets one `IN_TAXON` edge to depth $d$. This is SKOS `broader` semantics. Two different level tuples with the same `taxon_id` abort the build.

**Content rule and ghost signature.** A product is embedded only if title, features or description is non-blank. Template scaffolding does not count. A node has the ghost signature iff
$$\big|\{k \in \text{keys}(p) : k \neq \texttt{embedding}\}\big| \le 1.$$

**Version-bound citability (FR-029).** For a live run with runtime graph snapshot $g$:
$$\text{citable}(run) = \text{citable}_{R2a}(run) \;\wedge\; \exists!\, v = g.\texttt{graph\_version} \;\wedge\; v.\texttt{validation\_passed} = \texttt{true}.$$
Archived runs are never recomputed. Live runs on v1, which has no stamp, are therefore no longer citable. v1 evidence is the archived R2a set.

**v1 semantics kept.** Every label, relationship, property and embedding template that a current reader uses keeps its v1 meaning. Examples: `Category` = `main_category`, the 4 attribute keys, no `numeric_value`, and the `product_v1` template. New structures use new names (`Taxon`, `p.features`, `p.details_json`, `product_fulltext_index`). With the code commit fixed (`check_baseline_diff.py` allow-list against `88cdbdf`), a v1 → v2 difference in a retrieval metric is therefore attributable to the data, not to representation or code.

### 3.3 Validation Gates (hard; any failure blocks the stamp)

| Group | Gates | What they guarantee |
|---|---|---|
| Catalogue and ghosts | H-01 product count = lineage = catalogue − accepted missing; H-02 catalogue membership; H-03 untitled = lineage ≤ accepted pre-flight count; **H-04 ghost signature = 0** | Products come only from metadata and match the frozen catalogue |
| Reviews and leakage | H-05 exactly one `ABOUT_PRODUCT` and one `WROTE` per review; **H-06 no review's (user, product) in valid ∪ test**, plus `in_train_split` checked on a seeded sample; H-07 cap ≤ 20 and `cap_rank` contiguous; H-08 review count = lineage = approved | Split hygiene and the cap hold in the graph, not only in the transform |
| Embeddings and indexes | H-09 constraints; H-10 per-label embedding coverage = report = eligible, dimension 384; **H-11 no blank embeddings (content check plus ANN self-query of each blank-template vector: top-1 < 0.9999)**; H-12 indexes online at 100%; H-13 full-text smoke test | The blank-template vector cannot enter any vector index |
| Fidelity and grounding | H-14 seeded import-fidelity sample (2,000 products, 2,000 reviews, plus hard-quoting cases) equals the CSV values; **H-15 the 21 benchmark targets are grounded**; H-16 no legacy labels or `numeric_value`; H-17 Taxon tree integrity; H-18 all counts = lineage | The graph is the lineage, and the benchmark still resolves |

Report-only checks R-01 … R-08 record coverage per `main_category` and per taxon, the taxon depth distribution, identical-embedding groups, brand case duplicates, the 90 ISBN-like IDs, and v1 → v2 deltas for benchmark targets and counts.

### 3.4 Key Implemented Classes & Interfaces
* `graph_v2.transform.run_transform`: meta pass, two review passes in byte-offset order, train mark, lineage. A dry-run mode shares the code path with the pre-flight.
* `graph_v2.review_selection.TopKSelector`, `rank_key`, `assign_embed_ranks`, `load_pair_set`: bounded per-product selection with de-duplication. The tests check it against a reference implementation on 50 seeded cases.
* `graph_v2.taxonomy.TaxonomyBuilder`: the prefix tree with collision detection.
* `graph_v2.lineage.IntegrityTracker`, `assert_invariants`, `verify_raw_inputs`, `hash_splits`: endpoint integrity, source balance and input hashing.
* `graph_v2.validation`: pure gate functions H-01 … H-18 and `pilot_build_params`. `scripts/graph_ingestion/validate_graph.py` holds the Cypher collectors.
* `evaluation.provenance._graph_version`, `evaluate_citable(..., graph=...)`: version-bound citability, plus the `products_untitled` and `reviews_embedded` counts.
* `scripts/graph_ingestion/check_baseline_diff.py`: allow-list check that the baseline commit differs from `88cdbdf` only in graph v2 paths.

---

## 4. Empirical Instrumentation, Facts and Expected Effects

### 4.1 (a) Measured Facts about v1 and the Raw Data

| # | Fact | Value | Source |
|---|---|---|---|
| F-1 | Ghost products in v1 | 104,281 / 265,307 (39.3%); only `parent_asin` + embedding | Brainstorm 2026-10-18; Vision 018 |
| F-2 | Ghost embeddings | Identical blank-template vector; cosine ≈ 0.99999 across a 50-ghost sample | Brainstorm |
| F-3 | Titled products with ≥ 1 review | 19,439 / 161,026 (12%); the roadmap figure of 47% counted ghosts | Brainstorm; Vision 021 |
| F-4 | Review-embedded products that are ghosts | 4,874 / 5,715 (85.3%); titled base rate 841 / 161,026 = 0.52% vs all-node 2.15% | Brainstorm; doc 11 §4.5 |
| F-5 | Zeroed fields | `helpful_votes = 0`, `sort_timestamp = 0` in 1,630,273 / 1,630,273 v1 review rows; 1,629,426 `Review` nodes (847 fewer; collapse of repeat reviews likely, not verified) | Research Report N-1, N-2 |
| F-6 | Schema claims that did not hold | 0 `Attribute` nodes with `numeric_value`; attributes only Material, Color, Style, Size; 33 `SUBCATEGORY_OF` edges | Vision 021 items 3–4 |
| F-7 | Provenance blind spot | The three citable R2a runs record 265,307 products and `citable: true` | `evaluations_archive/eval_2026-10-18_2340/2349/2358` manifests; doc 11 |
| **F-8** | **Held-out interactions in v1 review evidence** | **204,352 of 1,630,273 rows (12.5%) of the v1 review input `processed_reviews.csv` are (user, parent_asin) pairs of the official valid ∪ test splits. They touch 72,337 of the 123,720 reviewed products.** | **Measured for this document** (read-only, pandas over `processed_reviews.csv` and `Electronics.{valid,test}.csv`, 2026-10-19). This is the ingest input, not a graph query. |
| F-9 | Raw review funnel for the frozen catalogue | 35,349,187 in-scope raw reviews; 2,828,276 are valid/test pairs; 32,520,911 remain (10,495,892 train-split, the rest outside the 5-core splits) | Brainstorm K-11 (read-only measurement) |

*Interpretation of F-8.* No reported result of this project used the official splits, so no published number is contaminated by F-8. The fact matters for Meta-Phase C. Any comparison of the KG system with CF baselines on the official test split would have given the KG system the review text of one in eight held-out interactions as retrievable evidence. That is exactly the kind of evaluation leakage described by Ji et al. (2023).

### 4.2 (b) Construction Guarantees and Their Current Verification

| Guarantee | Mechanism | Verified now | Verified at build |
|---|---|---|---|
| Zero ghosts | Products only from metadata; dangling edges abort import | Unit tests (`test_transform.py`, `test_lineage.py`), audit | H-01, H-02, H-04 |
| Zero held-out pairs | Pair-set exclusion before selection | `test_review_selection.py`, `test_transform.py` | H-06 |
| Cap ≤ 20, deterministic tie-break | `TopKSelector` with key $\kappa$ | Reference-equivalence on 50 seeded cases | H-07 |
| No blank-template vectors | Content rule; skip-empty in `BackfillService` | `test_embedding_templates.py`, `test_legacy_ingest_guards.py` | H-10, H-11 |
| Determinism | Sorted product-side files; byte-offset review order; gzip `mtime=0` | AC-016: byte-identical CSVs and lineage on repeated builds | Lineage SHA in `GraphVersion` |
| Legacy pipeline cannot recreate ghosts | `batch_ingest.py` review step `MATCH`es products; field names fixed | `test_legacy_ingest_guards.py` | n/a |
| Version-bound citability | FR-028/029 | `test_provenance.py` (AC-032, AC-033) | First v2 run manifest |

At this evaluation, `python -m pytest tests/graph_v2 tests/test_legacy_ingest_guards.py tests/test_graph_cypher_prompt.py tests/test_provenance.py tests/test_archive_eval_run.py -q` gives **195 passed**. `graph_versions/` does not exist yet: no catalogue export, lineage, pre-flight or validation report has been produced.

**Projected v2 counts** (read-only projection of the selection rule over the raw files; not a graph measurement):

| Quantity | v1 (measured) | v2 (projected) |
|---|---:|---:|
| `ParentProduct` | 265,307 | 265,307 (if every catalogue ID has raw metadata; checked for all 104,306 ghost IDs and all 161,001 v1 metadata products) |
| Ghost-signature products | 104,281 | 0 by construction (H-04) |
| Products with ≥ 1 review | 19,439 titled | 265,294 |
| Products with ≥ 5 / ≥ 20 reviews | not computed | 185,332 / 138,021 |
| Products with 0 reviews | — | 13 |
| `Review` nodes | 1,629,426 | 3,388,842 |
| Held-out pairs in review evidence | 204,352 input rows (F-8) | 0 (H-06) |
| Review `timestamp`, `helpful_vote` | 0 everywhere | Raw values |

The number of untitled products with raw metadata is unknown until pre-flight P-01. H-03 accepts that measured count, so "untitled = 0" is not guaranteed. "Ghost signature = 0" is guaranteed.

### 4.3 (c) Pre-Registered Re-Baseline Protocol
* **Fixed**: the code at commit B (`check_baseline_diff.py --base 88cdbdf` exits 0), benchmark legacy-21 (SHA-256 recorded), the LLM snapshot, the CLI configuration of `eval_2026-10-18_2340`, `RETRIEVAL_FUSION_ARM=rrf3`, `ORCH_CATEGORY_RECOVERY=1`, the stats seed, and r = 3.
* **Varied**: only the graph (v1 archived runs vs v2 runs).
* **Gate**: H-15 21/21; each v2 manifest has `citable: true` and `graph_version.version == "v2"`.
* **Analysis**: per arm, HR@{5,10,20}, MRR and NDCG@10 over all queries and SEARCH-only, compared on per-query means over r = 3 with the R2a paired statistics (two-sided; no direction predicted).

### 4.4 (c) Expected Effects to Be Tested (not results)
* **E-1 ($H_{13d}$).** 104k former ghosts become real competitors, often in the benchmark's own categories. Per-query ranks of targets can fall (more competitors) or rise (blank-template ties removed). The direction is not predicted.
* **E-2 ($H_{13e}$).** Under the top-5 embedding scope, the review-embedded set $P_{\text{rev}}$ approaches every product with at least one non-blank review, up to 265,294. Its base rate then approaches 1, so `review-coverage-bias@K` stops discriminating between arms. The RS-02 rule in Vision 2026-10-18-015 point 4 was conditional on 4.7% coverage, and that condition no longer applies. The metric needs redefining for v2 before it is reported, for example as the share of top-K reached *only* through the review channel.
* **E-3.** Stratum S1 "cold" (2026-10-18-014) has about 13 candidates on v2. It is redefined as review-sparse, with cold start simulated by masking (Vision 018 point 9).
* **E-4.** Mechanisms that had no valid input on v1 become testable once their readers are updated. These are temporal decay in KECR (AI-03), helpfulness-ordered review evidence (AI-06), and listing-text grounding (RS-12). This release changes no reader, so the v1 → v2 baseline does not test them.

### 4.5 Replication Protocol
```bash
# Offline (no Neo4j, no Docker): construction rule, gates, provenance
python -m pytest tests/graph_v2 tests/test_legacy_ingest_guards.py tests/test_graph_cypher_prompt.py \
                 tests/test_provenance.py tests/test_archive_eval_run.py -q

# F-8 (read-only): held-out pairs in the v1 review input
python - <<'EOF'
import pandas as pd
rv = pd.read_csv("datasets/processed_data/processed_reviews.csv", usecols=["user_id", "parent_asin"], dtype=str)
held = set()
for s in ("valid", "test"):
    d = pd.read_csv(f"datasets/Electronics.{s}.csv", usecols=["user_id", "parent_asin"], dtype=str)
    held.update(zip(d.user_id, d.parent_asin))
mask = [p in held for p in zip(rv.user_id, rv.parent_asin)]
print(sum(mask), len(rv), rv[mask].parent_asin.nunique(), rv.parent_asin.nunique())
EOF

# Build, with explicit user checkpoints CP-1 … CP-9 (scripts/graph_ingestion/README.md):
# preflight_v2.py → export_v1_snapshot.py → import_graph_v2.py dump → build_graph_v2.py (pilot, full)
# → import_graph_v2.py import → post_import_v2.py {constraints, embed, vector-indexes, fulltext-index}
# → validate_graph.py → post_import_v2.py stamp → three evaluate_retrieval.py --require-clean runs → archive
```

### 4.6 Threats to Validity and Limitations
* **Not executed.** No guarantee in §4.2 has yet been checked on the full data. The audit estimates peak transform memory at about 3.3 GB against a 3 GB target (NFR-002, M-2), which pre-flight P-10 will measure.
* **The catalogue is inherited, not designed.** $C$ is $M \cup R$ from v1, the union of a metadata sample and the products of an independent review sample, whose March 2025 parameters were not recorded. v2 is reproducible from the hashed list, but its population cannot be re-derived from a rule. It over-represents reviewed products relative to the full Electronics metadata (1.61M items). Results generalise to this catalogue, not to Amazon Electronics.
* **Split hygiene covers official held-out pairs only.** The project's own benchmark targets keep their reviews in the KG. That is a separate leakage question, tracked as the `target_review_embedded` slice of 2026-10-18-014.
* **Selection bias of the cap.** Ordering by helpfulness prefers visible, older and longer reviews. The review channel's evidence on v2 is the most-helpful slice, not a random sample.
* **F-8 is measured on the ingest input**, not on graph nodes (847 rows collapsed in the graph). The order of magnitude is unaffected.
* **v1 semantics by design.** v2 still has no numeric attributes and no features in the product embedding (K-6 deferred). The grounding limits of doc 11 §4.4 (numeric constraints unverifiable) carry over unchanged.
* **Single domain.** The method is domain-agnostic in construction, but it is exercised only on Electronics.

---

## 5. Rubric Audit (Thesis Evaluator, 2026-10-19)

| # | Criterion | Score | Assessment |
|---|---|---:|---|
| 1 | Algorithmic & Architectural Novelty | 3/10 | Catalogue-first construction, pair exclusion and validation gates are established practice. The new elements are the ghost signature, the ANN self-query check for blank vectors, and binding the graph version into run citability. |
| 2 | Unexpected or Original Combination | 6/10 | It joins KG construction validity, official-split leakage control for a review-retrieving CRS, and run-level citability into one predicate. These are usually treated separately. |
| 3 | Problem Significance in Literature | 8/10 | Data cascades (Sambasivan et al., 2021), leakage (Kapoor & Narayanan, 2023; Ji et al., 2023), and rigour in recommender evaluation (Ferrari Dacrema et al., 2019; Sun et al., 2020). It also bears directly on the grounding premise of Vision §4. |
| 4 | Red Flag Check | PASS (scoped) | The import wrapper, Docker guards and CSV handling fail and are excluded (§2.3). The measured defect analysis, the structural construction rule, the semantic gates and the citability binding pass. |
| 5 | SOTA Gap Alignment | 6/10 | GraphRAG and LLM-CRS evaluations rarely validate the graph or exclude held-out interactions from retrievable evidence. This is a practice gap more than a theory gap. |
| 6 | Formal RQ Formulability | 6/10 | $RQ_{13}$ has two measured hypotheses (supported), one construction hypothesis (supported on fixtures) and one pre-registered two-sided re-baseline (open). |
| 7 | Tangible Research Artifact | 8/10 | A reproducible build pipeline, a lineage schema, 18 hard gates plus 8 report-only checks, the `GraphVersion` stamp, the baseline allow-list and 12 test modules. |
| 8 | Empirical Instrumentation | 8/10 | Per-step drop counts with reasons, source and output hashes, a validation report, per-category coverage, v1 → v2 delta reports, and `products_untitled` / `reviews_embedded` in every manifest. |
| 9 | Measurable Metric Improvements | 2/10 | None yet. The v1 corrections (F-1 … F-8) are measured facts, not improvements. The v2 counts are projections. |
| 10 | Scientific Reproducibility | 7/10 | The graph is a pure function of hashed inputs, with a byte-identical rebuild test, `--require-clean` and a v1 dump. Lowered because nothing has run at scale and the catalogue is an unrecorded historical sample. |
| | **Total** | **54/90 + PASS** | **Verdict: QUALIFIES — Methodological Artifact.** It is not a Primary Academic Contribution until $H_{13d}$ is tested. |

---

## 6. Master's Thesis Chapter Mapping

* **Target Thesis Chapters**: Chapter 3 or 4 (Knowledge Graph construction: §3.2, §3.3); Chapter 5 (Experimental Methodology: data validity as a precondition of citability, §1.1, §4.1, §4.3); threats-to-validity sections of every results chapter that reports v1 numbers.
* **Key Claims to Make in Thesis Text**:
  1. In this project, 39% of the grounding graph's product nodes were data-less and shared one embedding. Count-based run provenance did not detect this, and runs on that graph were citable under the R2a predicate.
  2. The defect was a data cascade with three independent causes: independent sampling, product creation from reviews, and embedding of empty text. Each cause is removed at its source, not filtered at query time.
  3. 12.5% of the v1 review input consisted of official valid/test interactions. A split-aware evidence rule is required before the KG system can be compared with CF baselines on the official splits.
  4. After this change, a recommendation result is citable only if the graph it ran on passed 18 hard gates and carries a validated version stamp.
* **Claims NOT to make**: that v2 improves any retrieval, coverage or quality metric; that v2 has zero untitled products; that v1 results are wrong (they are valid as v1 evidence); that v1 results were inflated by leakage (none used the official splits); that the catalogue is a representative sample of Amazon Electronics.
* **Follow-up**: pilot (5%) and full build with the checkpoints; the v2 re-baseline (§4.3) reported against $H_{13d}$; redefinition of review-coverage-bias for v2 (E-2) before R2b; Meta-Phase C on the official splits with the same training interactions.

### References
* Breck, E., Polyzotis, N., Roy, S., Whang, S. E., & Zinkevich, M. (2019). Data Validation for Machine Learning. In *Proceedings of SysML (MLSys) 2019*.
* Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., & Larson, J. (2024). From Local to Global: A Graph RAG Approach to Query-Focused Summarization. arXiv:2404.16130.
* Ferrari Dacrema, M., Cremonesi, P., & Jannach, D. (2019). Are We Really Making Much Progress? A Worrying Analysis of Recent Neural Recommendation Approaches. In *Proceedings of RecSys 2019*, pp. 101–109.
* Gebru, T., Morgenstern, J., Vecchione, B., Vaughan, J. W., Wallach, H., Daumé III, H., & Crawford, K. (2021). Datasheets for Datasets. *Communications of the ACM*, 64(12), 86–92.
* Hidasi, B., & Czapp, Á. T. (2023). Widespread Flaws in Offline Evaluation of Recommender Systems. In *Proceedings of RecSys 2023*.
* Hou, Y., Li, J., He, Z., Yan, A., Chen, X., & McAuley, J. (2024). Bridging Language and Items for Retrieval and Recommendation. arXiv:2403.03952.
* Ji, Y., Sun, A., Zhang, J., & Li, C. (2023). A Critical Study on Data Leakage in Recommender System Offline Evaluation. *ACM Transactions on Information Systems*, 41(3).
* Kapoor, S., & Narayanan, A. (2023). Leakage and the Reproducibility Crisis in Machine-Learning-Based Science. *Patterns*, 4(9), 100804.
* Paulheim, H. (2017). Knowledge Graph Refinement: A Survey of Approaches and Evaluation Methods. *Semantic Web*, 8(3), 489–508.
* Peng, B., Zhu, Y., Liu, Y., Bo, X., Shi, H., Hong, C., Zhang, Y., & Tang, S. (2024). Graph Retrieval-Augmented Generation: A Survey. arXiv:2408.08921.
* Sambasivan, N., Kapania, S., Highfill, H., Akrong, D., Paritosh, P., & Aroyo, L. M. (2021). "Everyone wants to do the model work, not the data work": Data Cascades in High-Stakes AI. In *Proceedings of CHI 2021*.
* Schelter, S., Lange, D., Schmidt, P., Celikel, M., Biessmann, F., & Grafberger, A. (2018). Automating Large-Scale Data Quality Verification. *Proceedings of the VLDB Endowment*, 11(12), 1781–1794.
* Sun, Z., Yu, D., Fang, H., Yang, J., Qu, X., Zhang, J., & Geng, C. (2020). Are We Evaluating Rigorously? Benchmarking Recommendation for Reproducible Evaluation and Fair Comparison. In *Proceedings of RecSys 2020*, pp. 23–32.
* W3C (2009). SKOS Simple Knowledge Organization System Reference. W3C Recommendation.
