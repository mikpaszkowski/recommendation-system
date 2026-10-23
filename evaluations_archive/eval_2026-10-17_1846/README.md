# Evaluation Run: `eval_2026-10-17_1846`

⚠️ **NON-CITABLE (Context / Dev / Legacy)** &nbsp;|&nbsp; 📊 **Full Benchmark Evaluation Run** ($N = 21$ queries)

---

## 1. Master's Thesis Academic Mapping
* **Primary Thesis Document**: [`10-doc-fusion-ablation.md`](../../thesis/10-doc-fusion-ablation.md)
* **Research Question ($RQ$)**: $\mathbf{RQ10}$
* **Target Thesis Chapter**: Chapter 4: Hybrid Semantic-Structural Retrieval; Chapter 5: Empirical Evaluation & Comparative Analysis
* **Scope & Milestone**: **Release R1: Rank-Based Multi-Channel Fusion via RRF (AFP-002 Redesign)**

---

## 2. Major Architectural Change Context
**What prompted this evaluation run?**
> Replaced unbounded additive vector summation with Reciprocal Rank Fusion (RRF) and per-channel MaxP pooling across product, attribute, and review vectors. Added multi-arm comparative replay.

**General Outcome & Academic Finding**:
> Substantially improved top-rank precision over additive scoring (MRR surged from 0.0986 to 0.2540, HR@5 to 28.57%), but revealed that 5 queries triggered spurious CLARIFY turns due to rigid extraction gating.

---

## 3. Provenance & Execution Rigor
| Attribute | Value |
|---|---|
| **Run ID** | `eval_2026-10-17_1846` |
| **Execution Timestamp** | `2026-10-17T18:54:35.833505` |
| **Git Commit** | [`989c1cd`](../../commits/989c1cd854242408baa1d71df0aa51db4d1ed251) |
| **Knowledge Graph Version** | `v1` |
| **Evaluation Mode** | `live` |
| **Benchmark Dataset** | `live_eval_dataset.json` |
| **Evaluated Queries ($N$)** | 21 |
| **Citability Status** | `citable: False` |

---

## 4. Information Retrieval (Tier 1) Metrics

| Strategy / Fusion Arm | HitRate@1 | HitRate@5 | HitRate@20 | MRR | NDCG@10 | TypeP@5 | CS@5 Viol | Latency |
|---|---|---|---|---|---|---|---|---|
| **`hybrid`** | 0.2381 | 0.2857 | 0.3810 | 0.2604 | 0.2619 | 0.9059 | - | 14505.5 ms |
| **`vector_only`** | 0.0952 | 0.0952 | 0.2857 | 0.1148 | 0.1261 | 0.6941 | - | 14505.5 ms |
| **`cypher_only`** | 0.1429 | 0.1905 | 0.1905 | 0.1548 | 0.1634 | 0.8750 | - | 14505.5 ms |
| **`hybrid@rrf3`** | 0.2381 | 0.2857 | 0.3810 | 0.2604 | 0.2619 | 0.9059 | - | 1106.8 ms |
| **`hybrid@rrf2`** | 0.2381 | 0.2857 | 0.4286 | 0.2629 | 0.2619 | 0.9176 | - | 676.8 ms |
| **`hybrid@wrrf3`** | 0.2381 | 0.2857 | 0.4286 | 0.2735 | 0.2832 | 0.9529 | - | 751.3 ms |
| **`hybrid@cc3`** | 0.2381 | 0.2857 | 0.4286 | 0.2722 | 0.2825 | 0.9176 | - | 723.0 ms |
| **`hybrid@sum_legacy`** | 0.2381 | 0.2857 | 0.3810 | 0.2550 | 0.2586 | 0.8706 | - | 721.7 ms |

---

## 6. Experimental Replication
To replicate this evaluation under identical conditions:
```bash
python3 scripts/evaluate_retrieval.py --mode live
```
