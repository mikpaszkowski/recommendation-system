# Evaluation Run: `eval_2026-10-09_1336`

⚠️ **NON-CITABLE (Context / Dev / Legacy)** &nbsp;|&nbsp; 📊 **Full Benchmark Evaluation Run** ($N = 21$ queries)

---

## 1. Master's Thesis Academic Mapping
* **Primary Thesis Document**: [`4-doc-hybrid-scoring.md`](../../thesis/4-doc-hybrid-scoring.md)
* **Research Question ($RQ$)**: $\mathbf{RQ4}$
* **Target Thesis Chapter**: Chapter 4: Hybrid Semantic-Structural Retrieval & Knowledge Representation
* **Scope & Milestone**: **Architectural Fix Proposals (AFP-001..005) & Additive Scoring Baseline**

---

## 2. Major Architectural Change Context
**What prompted this evaluation run?**
> Implementation of AFP-001 through AFP-005: additive vector scoring (sum(score)), category normalization, review embedding integration, and soft constraint relaxation.

**General Outcome & Academic Finding**:
> Significantly improved retrieval yield over strict Boolean Cypher (HR@20 improved to 20.6%, MRR to 0.0986), but revealed attribute hub bias where high-degree generic attributes dominated top ranks.

---

## 3. Provenance & Execution Rigor
| Attribute | Value |
|---|---|
| **Run ID** | `eval_2026-10-09_1336` |
| **Execution Timestamp** | `2026-10-09T13:44:10.252880` |
| **Git Commit** | [`2fdf251`](../../commits/2fdf251abeefcd0dad20dc9679b48be9a6609f06) |
| **Knowledge Graph Version** | `v1` |
| **Evaluation Mode** | `live` |
| **Benchmark Dataset** | `live_eval_dataset.json` |
| **Evaluated Queries ($N$)** | 21 |
| **Citability Status** | `citable: False` |

---

## 4. Information Retrieval (Tier 1) Metrics

| Strategy / Fusion Arm | HitRate@1 | HitRate@5 | HitRate@20 | MRR | NDCG@10 | TypeP@5 | CS@5 Viol | Latency |
|---|---|---|---|---|---|---|---|---|
| **`hybrid`** | 0.0794 | 0.1270 | 0.2063 | 0.0986 | 0.0732 | - | - | - |

---

## 6. Experimental Replication
To replicate this evaluation under identical conditions:
```bash
python3 scripts/evaluate_retrieval.py --mode live
```
