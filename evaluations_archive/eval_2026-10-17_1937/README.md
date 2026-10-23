# Evaluation Run: `eval_2026-10-17_1937`

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
| **Run ID** | `eval_2026-10-17_1937` |
| **Execution Timestamp** | `2026-10-17T19:43:27.102597` |
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
| **`hybrid`** | 0.2381 | 0.2857 | 0.2857 | 0.2540 | 0.2619 | 0.8625 | - | 13116.2 ms |
| **`vector_only`** | 0.0952 | 0.0952 | 0.2381 | 0.1080 | 0.1103 | 0.6750 | - | 13116.2 ms |
| **`cypher_only`** | 0.1429 | 0.1905 | 0.1905 | 0.1548 | 0.1634 | 0.8667 | - | 13116.2 ms |
| **`hybrid@rrf3`** | 0.2381 | 0.2857 | 0.2857 | 0.2540 | 0.2619 | 0.8625 | - | 757.2 ms |
| **`hybrid@rrf2`** | 0.2381 | 0.2857 | 0.3333 | 0.2565 | 0.2619 | 0.8875 | - | 641.9 ms |
| **`hybrid@wrrf3`** | 0.2381 | 0.2857 | 0.3333 | 0.2651 | 0.2681 | 0.9250 | - | 715.9 ms |
| **`hybrid@cc3`** | 0.2381 | 0.2857 | 0.3333 | 0.2644 | 0.2681 | 0.8875 | - | 706.8 ms |
| **`hybrid@sum_legacy`** | 0.2381 | 0.2857 | 0.2857 | 0.2500 | 0.2586 | 0.8375 | - | 727.4 ms |

---

## 6. Experimental Replication
To replicate this evaluation under identical conditions:
```bash
python3 scripts/evaluate_retrieval.py --mode live
```
