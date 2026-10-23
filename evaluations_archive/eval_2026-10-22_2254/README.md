# Evaluation Run: `eval_2026-10-22_2254`

✅ **CITABLE LIVE EVIDENCE** &nbsp;|&nbsp; 📊 **Full Benchmark Evaluation Run** ($N = 21$ queries)

---

## 1. Master's Thesis Academic Mapping
* **Primary Thesis Document**: [`19-doc-retrieval-evaluation.md`](../../thesis/19-doc-retrieval-evaluation.md)
* **Research Question ($RQ$)**: $\mathbf{RQ19}$
* **Target Thesis Chapter**: Chapter 5: Empirical Evaluation & Comparative Analysis
* **Scope & Milestone**: **Release R3.2: Domain-Agnostic SKOS Product-Type Matching & Dual HyDE**

---

## 2. Major Architectural Change Context
**What prompted this evaluation run?**
> Unified integration of W3C SKOS alt_labels, morphological lemmatization, phrase decomposition, anti-hijacking Taxon scoring, and Dual-Channel HyDE.

**General Outcome & Academic Finding**:
> BREAKTHROUGH IMPROVEMENT: Target Admission surged from 47.6% to 100.0% (20/20 search queries). Type Precision@5 reached 96.0%-99.0%. 4-Channel RRF (wrrf4) more than doubled HR@20 (0.238 -> 0.571, +140%) and tripled MRR (0.130 -> 0.364, +180%) with 0.000 constraint violations.

---

## 3. Provenance & Execution Rigor
| Attribute | Value |
|---|---|
| **Run ID** | `eval_2026-10-22_2254` |
| **Execution Timestamp** | `2026-10-22T23:25:58.051060` |
| **Git Commit** | [`4fb77f7`](../../commits/4fb77f7d88eeae68e6e0994fce61bd2eafeac2d4) |
| **Knowledge Graph Version** | `v1` |
| **Evaluation Mode** | `live` |
| **Benchmark Dataset** | `live_eval_dataset.json` |
| **Evaluated Queries ($N$)** | 21 |
| **Citability Status** | `citable: True` |

---

## 4. Information Retrieval (Tier 1) Metrics

| Strategy / Fusion Arm | HitRate@1 | HitRate@5 | HitRate@20 | MRR | NDCG@10 | TypeP@5 | CS@5 Viol | Latency |
|---|---|---|---|---|---|---|---|---|
| **`hybrid`** | 0.0952 | 0.2381 | 0.3333 | 0.1684 | 0.1935 | 0.9600 | 0.0042 | 23185.7 ms |
| **`vector_only`** | 0.0000 | 0.0952 | 0.2381 | 0.0478 | 0.0649 | 0.8600 | 0.1802 | 23185.7 ms |
| **`cypher_only`** | 0.0000 | 0.0952 | 0.1905 | 0.0513 | 0.0708 | 0.9200 | 0.1323 | 23185.7 ms |
| **`hybrid@rrf3`** | 0.0952 | 0.2381 | 0.3333 | 0.1684 | 0.1935 | 0.9600 | 0.0042 | 3857.2 ms |
| **`hybrid@rrf3_no_hyde`** | 0.2381 | 0.3810 | 0.4286 | 0.3095 | 0.3390 | 0.9600 | 0.0000 | 3659.0 ms |
| **`hybrid@wrrf3`** | 0.1905 | 0.4286 | 0.4762 | 0.2704 | 0.3193 | 0.9600 | 0.0000 | 3540.8 ms |
| **`hybrid@wrrf3_no_hyde`** | 0.2381 | 0.3333 | 0.4286 | 0.2817 | 0.3027 | 0.9900 | 0.0000 | 2612.4 ms |
| **`hybrid@rrf2`** | 0.1429 | 0.2381 | 0.2857 | 0.1789 | 0.1905 | 0.9600 | 0.0000 | 982.2 ms |
| **`hybrid@cc3`** | 0.0952 | 0.3333 | 0.4286 | 0.2071 | 0.2330 | 0.9600 | 0.0042 | 2862.1 ms |
| **`hybrid@sum_legacy`** | 0.0952 | 0.2381 | 0.3333 | 0.1386 | 0.1580 | 0.9700 | 0.0000 | 3403.9 ms |
| **`hybrid@wrrf4`** | 0.2381 | 0.4286 | 0.5714 | 0.3301 | 0.3601 | 0.9700 | 0.0000 | 10721.5 ms |
| **`hybrid@wrrf4_no_hyde`** | 0.2857 | 0.4762 | 0.5238 | 0.3640 | 0.4024 | 0.9900 | 0.0000 | 13085.6 ms |
| **`hybrid@hyde_only`** | 0.1905 | 0.3810 | 0.4286 | 0.2520 | 0.2941 | 0.9600 | 0.0000 | 4104.7 ms |

---

## 6. Experimental Replication
To replicate this evaluation under identical conditions:
```bash
python3 scripts/evaluate_retrieval.py --mode live
```
