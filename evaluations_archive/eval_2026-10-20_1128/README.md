# Evaluation Run: `eval_2026-10-20_1128`

✅ **CITABLE LIVE EVIDENCE** &nbsp;|&nbsp; 📊 **Full Benchmark Evaluation Run** ($N = 21$ queries)

---

## 1. Master's Thesis Academic Mapping
* **Primary Thesis Document**: [`13-doc-graph-integrity.md`](../../thesis/13-doc-graph-integrity.md)
* **Research Question ($RQ$)**: $\mathbf{RQ13}$
* **Target Thesis Chapter**: Chapter 3/4: Knowledge Graph Construction; Chapter 5: Threats to Validity
* **Scope & Milestone**: **Graph v2 Baseline Verification on Live Catalog (F4)**

---

## 2. Major Architectural Change Context
**What prompted this evaluation run?**
> Formal citable baseline evaluation on validated Graph v2 (stamped with GraphVersion node, 0 held-out pairs, 0 ghost products, 1,183 Taxons).

**General Outcome & Academic Finding**:
> MAJOR DATA INTEGRITY MILESTONE: Eliminated 104k ghost nodes from retrieval results (0% top-10 infiltration vs 35% in v1). HR@20 reached 47.6%-52.4%, MRR reached 0.286-0.381. Shift exposed upstream category resolution traps for 12/21 queries.

---

## 3. Provenance & Execution Rigor
| Attribute | Value |
|---|---|
| **Run ID** | `eval_2026-10-20_1128` |
| **Execution Timestamp** | `2026-10-20T11:41:58.813964` |
| **Git Commit** | [`4248d03`](../../commits/4248d03ee38d5959791ff3c01d3a28768370a7cc) |
| **Knowledge Graph Version** | `v1` |
| **Evaluation Mode** | `live` |
| **Benchmark Dataset** | `live_eval_dataset.json` |
| **Evaluated Queries ($N$)** | 21 |
| **Citability Status** | `citable: True` |

---

## 4. Information Retrieval (Tier 1) Metrics

| Strategy / Fusion Arm | HitRate@1 | HitRate@5 | HitRate@20 | MRR | NDCG@10 | TypeP@5 | CS@5 Viol | Latency |
|---|---|---|---|---|---|---|---|---|
| **`hybrid`** | 0.3333 | 0.4286 | 0.5238 | 0.3810 | 0.4139 | 0.9238 | 0.0000 | 19081.4 ms |
| **`vector_only`** | 0.0000 | 0.0952 | 0.2381 | 0.0473 | 0.0643 | 0.8667 | 0.1814 | 19081.4 ms |
| **`cypher_only`** | 0.0000 | 0.0952 | 0.1429 | 0.0556 | 0.0771 | 0.8762 | 0.1137 | 19081.4 ms |
| **`hybrid@rrf3`** | 0.3333 | 0.4286 | 0.5238 | 0.3810 | 0.4139 | 0.9238 | 0.0000 | 1426.9 ms |
| **`hybrid@rrf2`** | 0.1429 | 0.2381 | 0.3810 | 0.1954 | 0.2374 | 0.8571 | 0.0000 | 371.0 ms |
| **`hybrid@wrrf3`** | 0.2857 | 0.3810 | 0.5238 | 0.3434 | 0.3848 | 0.9238 | 0.0000 | 1761.0 ms |
| **`hybrid@cc3`** | 0.2381 | 0.3810 | 0.5238 | 0.3113 | 0.3468 | 0.8857 | 0.0000 | 1418.0 ms |
| **`hybrid@sum_legacy`** | 0.0952 | 0.2381 | 0.3810 | 0.1695 | 0.1928 | 0.8571 | 0.0000 | 1314.1 ms |

---

## 6. Experimental Replication
To replicate this evaluation under identical conditions:
```bash
python3 scripts/evaluate_retrieval.py --mode live
```
