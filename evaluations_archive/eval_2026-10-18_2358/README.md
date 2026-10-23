# Evaluation Run: `eval_2026-10-18_2358`

✅ **CITABLE LIVE EVIDENCE** &nbsp;|&nbsp; 📊 **Full Benchmark Evaluation Run** ($N = 21$ queries)

---

## 1. Master's Thesis Academic Mapping
* **Primary Thesis Document**: [`11-doc-evaluation-protocol.md`](../../thesis/11-doc-evaluation-protocol.md)
* **Research Question ($RQ$)**: $\mathbf{RQ11}$
* **Target Thesis Chapter**: Chapter 5: Empirical Evaluation & Comparative Analysis
* **Scope & Milestone**: **Release R2a Exit Gate Verification on Graph v1**

---

## 2. Major Architectural Change Context
**What prompted this evaluation run?**
> Formal citable exit gate verification: head-noun recovery rule and product_type_decided flag, paired randomization tests, and 5-arm same-request replay.

**General Outcome & Academic Finding**:
> MAJOR IMPROVEMENT: Completely eliminated spurious clarifications (0/21 spurious CLARIFY across 3 consecutive citable runs, down from 5/21 in R1). HR@20 reached 42.86%.

---

## 3. Provenance & Execution Rigor
| Attribute | Value |
|---|---|
| **Run ID** | `eval_2026-10-18_2358` |
| **Execution Timestamp** | `2026-10-19T00:06:11.996388` |
| **Git Commit** | [`88cdbdf`](../../commits/88cdbdfd75c81e9f6dbf55c7ab71e4d08280ae29) |
| **Knowledge Graph Version** | `v1` |
| **Evaluation Mode** | `live` |
| **Benchmark Dataset** | `live_eval_dataset.json` |
| **Evaluated Queries ($N$)** | 21 |
| **Citability Status** | `citable: True` |

---

## 4. Information Retrieval (Tier 1) Metrics

| Strategy / Fusion Arm | HitRate@1 | HitRate@5 | HitRate@20 | MRR | NDCG@10 | TypeP@5 | CS@5 Viol | Latency |
|---|---|---|---|---|---|---|---|---|
| **`hybrid`** | 0.1429 | 0.2857 | 0.4286 | 0.2100 | 0.2469 | 0.8286 | 0.0000 | 17314.4 ms |
| **`vector_only`** | 0.1429 | 0.1429 | 0.3333 | 0.1624 | 0.1738 | 0.7333 | 0.0941 | 17314.4 ms |
| **`cypher_only`** | 0.1429 | 0.1429 | 0.1905 | 0.1481 | 0.1572 | 0.8300 | 0.0824 | 17314.4 ms |
| **`hybrid@rrf3`** | 0.1429 | 0.2857 | 0.4286 | 0.2100 | 0.2469 | 0.8286 | 0.0000 | 610.6 ms |
| **`hybrid@rrf2`** | 0.1905 | 0.2857 | 0.4286 | 0.2365 | 0.2804 | 0.8571 | 0.0000 | 541.2 ms |
| **`hybrid@wrrf3`** | 0.2381 | 0.4762 | 0.5714 | 0.3375 | 0.3806 | 0.8952 | 0.0000 | 642.7 ms |
| **`hybrid@cc3`** | 0.2381 | 0.3810 | 0.4762 | 0.2984 | 0.3399 | 0.8571 | 0.0000 | 630.5 ms |
| **`hybrid@sum_legacy`** | 0.0952 | 0.2857 | 0.4286 | 0.1736 | 0.2057 | 0.8190 | 0.0000 | 611.4 ms |

---

## 6. Experimental Replication
To replicate this evaluation under identical conditions:
```bash
python3 scripts/evaluate_retrieval.py --mode live
```
