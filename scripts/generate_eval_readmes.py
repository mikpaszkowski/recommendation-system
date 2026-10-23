import os, json, glob

COMMIT_META = {
    "4ef1cd6": {
        "title": "Two-Tiered Evaluation Framework Implementation",
        "doc": "thesis/7-doc-evaluation-framework.md",
        "doc_name": "7-doc-evaluation-framework.md",
        "rq": "RQ7",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Initial implementation of the two-tiered evaluation framework decoupling Tier 1 Information Retrieval ranking metrics from Tier 2 LLM-as-a-judge generative evaluation.",
        "impact": "Established foundational empirical instrumentation for the thesis. First live catalog baseline exposed significant zero-shot retrieval yield and ranking challenges (MRR = 0.0142, HR@20 = 2.67%)."
    },
    "dfbda92": {
        "title": "Teamwork Swarm Evaluation & Architectural Fix Proposals (AFP-001..005)",
        "doc": "thesis/4-doc-hybrid-scoring.md",
        "doc_name": "4-doc-hybrid-scoring.md",
        "rq": "RQ4",
        "chapter": "Chapter 4: Hybrid Semantic-Structural Retrieval & Knowledge Representation",
        "change_desc": "Multi-agent autonomous evaluation identifying five structural failure modes (AFP-001 to AFP-005) in early Cypher generation and vector search.",
        "impact": "Identified the recall cliff caused by strict Boolean Cypher filtering and proposed additive multi-channel scoring."
    },
    "2fdf251": {
        "title": "Architectural Fix Proposals (AFP-001..005) & Additive Scoring Baseline",
        "doc": "thesis/4-doc-hybrid-scoring.md",
        "doc_name": "4-doc-hybrid-scoring.md",
        "rq": "RQ4",
        "chapter": "Chapter 4: Hybrid Semantic-Structural Retrieval & Knowledge Representation",
        "change_desc": "Implementation of AFP-001 through AFP-005: additive vector scoring (sum(score)), category normalization, review embedding integration, and soft constraint relaxation.",
        "impact": "Significantly improved retrieval yield over strict Boolean Cypher (HR@20 improved to 20.6%, MRR to 0.0986), but revealed attribute hub bias where high-degree generic attributes dominated top ranks."
    },
    "e6593f7": {
        "title": "PR #6 Merge: Foundation Graph Improvement",
        "doc": "thesis/4-doc-hybrid-scoring.md",
        "doc_name": "4-doc-hybrid-scoring.md",
        "rq": "RQ4",
        "chapter": "Chapter 4: Hybrid Semantic-Structural Retrieval & Knowledge Representation",
        "change_desc": "Merged feature branch with foundational graph improvements and soft preference demotion into main branch.",
        "impact": "Post-merge regression sanity checks confirmed stable baseline behavior across standard scenarios."
    },
    "989c1cd": {
        "title": "Release R1: Rank-Based Multi-Channel Fusion via RRF (AFP-002 Redesign)",
        "doc": "thesis/10-doc-fusion-ablation.md",
        "doc_name": "10-doc-fusion-ablation.md",
        "rq": "RQ10",
        "chapter": "Chapter 4: Hybrid Semantic-Structural Retrieval; Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Replaced unbounded additive vector summation with Reciprocal Rank Fusion (RRF) and per-channel MaxP pooling across product, attribute, and review vectors. Added multi-arm comparative replay.",
        "impact": "Substantially improved top-rank precision over additive scoring (MRR surged from 0.0986 to 0.2540, HR@5 to 28.57%), but revealed that 5 queries triggered spurious CLARIFY turns due to rigid extraction gating."
    },
    "9cbf426": {
        "title": "Release R2a Development: Spurious CLARIFY Investigation & Citability Protocol",
        "doc": "thesis/11-doc-evaluation-protocol.md",
        "doc_name": "11-doc-evaluation-protocol.md",
        "rq": "RQ11",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Investigating spurious CLARIFY causes, testing head-noun extraction heuristics, and designing strict evaluation provenance checks and same-request replay.",
        "impact": "Iterative development runs establishing the statistical testing protocol and testing candidate fixes for dialogue clarification gating."
    },
    "f3ed804": {
        "title": "Release R2a Specification, Audit & Exit Gate Criteria",
        "doc": "thesis/11-doc-evaluation-protocol.md",
        "doc_name": "11-doc-evaluation-protocol.md",
        "rq": "RQ11",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Specification amendments and pre-exit-gate audit verification under Vision decisions 014-017.",
        "impact": "Pre-exit gate validation ensuring reproducible evaluation environments and clean working tree checks."
    },
    "88cdbdf": {
        "title": "Release R2a Exit Gate Verification on Graph v1",
        "doc": "thesis/11-doc-evaluation-protocol.md",
        "doc_name": "11-doc-evaluation-protocol.md",
        "rq": "RQ11",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Formal citable exit gate verification: head-noun recovery rule and product_type_decided flag, paired randomization tests, and 5-arm same-request replay.",
        "impact": "MAJOR IMPROVEMENT: Completely eliminated spurious clarifications (0/21 spurious CLARIFY across 3 consecutive citable runs, down from 5/21 in R1). HR@20 reached 42.86%."
    },
    "7fc2d8b": {
        "title": "Release R2a Thesis Documentation & Contribution Registration",
        "doc": "thesis/11-doc-evaluation-protocol.md",
        "doc_name": "11-doc-evaluation-protocol.md",
        "rq": "RQ11",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Post-exit gate sanity runs verifying registered thesis contributions 11 and 12.",
        "impact": "Confirmed deterministic repeatability of R2a exit gate metrics."
    },
    "6333101": {
        "title": "Release R2a Architecture Diagram Update & Documentation",
        "doc": "thesis/11-doc-evaluation-protocol.md",
        "doc_name": "11-doc-evaluation-protocol.md",
        "rq": "RQ11",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Documentation and diagram sync after completing Release R2a.",
        "impact": "Sanity checks confirming regression-free operation."
    },
    "0791e35": {
        "title": "Release Plan Split: R2a Completion and R2b In-Flight",
        "doc": "thesis/11-doc-evaluation-protocol.md",
        "doc_name": "11-doc-evaluation-protocol.md",
        "rq": "RQ11",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Splitting Release R2 into R2a (evaluation foundation) and R2b (stratified benchmark) in project plan.",
        "impact": "Verified pipeline stability prior to beginning the Graph v2 data rebuild."
    },
    "82a1bb9": {
        "title": "Graph v2 Rebuild: Pipeline Preparation & Pre-Flight",
        "doc": "thesis/13-doc-graph-integrity.md",
        "doc_name": "13-doc-graph-integrity.md",
        "rq": "RQ13",
        "chapter": "Chapter 3/4: Knowledge Graph Construction; Chapter 5: Threats to Validity",
        "change_desc": "Pre-flight checks and memory handling fixes for the Graph v2 rebuild pipeline from raw Amazon 2023 data.",
        "impact": "Ensured data ingestion pipeline survives MPS memory limits and passes schema preconditions."
    },
    "8c35d68": {
        "title": "Graph v2 CP-5 Pilot Run",
        "doc": "thesis/13-doc-graph-integrity.md",
        "doc_name": "13-doc-graph-integrity.md",
        "rq": "RQ13",
        "chapter": "Chapter 3/4: Knowledge Graph Construction; Chapter 5: Threats to Validity",
        "change_desc": "Executed 5% pilot rebuild of Graph v2 and verified 18 validation gates.",
        "impact": "Proved viability of the catalogue-first, split-aware graph construction pipeline."
    },
    "8b10a35": {
        "title": "Graph v2 Full-Text Smoke Test Fix & ElementId Write-Back",
        "doc": "thesis/13-doc-graph-integrity.md",
        "doc_name": "13-doc-graph-integrity.md",
        "rq": "RQ13",
        "chapter": "Chapter 3/4: Knowledge Graph Construction; Chapter 5: Threats to Validity",
        "change_desc": "Fixed full-text smoke test query and elementId write-back scaling during Graph v2 construction.",
        "impact": "Resolved scale bottlenecks before full-graph ingestion."
    },
    "4248d03": {
        "title": "Graph v2 Baseline Verification on Live Catalog (F4)",
        "doc": "thesis/13-doc-graph-integrity.md",
        "doc_name": "13-doc-graph-integrity.md",
        "rq": "RQ13",
        "chapter": "Chapter 3/4: Knowledge Graph Construction; Chapter 5: Threats to Validity",
        "change_desc": "Formal citable baseline evaluation on validated Graph v2 (stamped with GraphVersion node, 0 held-out pairs, 0 ghost products, 1,183 Taxons).",
        "impact": "MAJOR DATA INTEGRITY MILESTONE: Eliminated 104k ghost nodes from retrieval results (0% top-10 infiltration vs 35% in v1). HR@20 reached 47.6%-52.4%, MRR reached 0.286-0.381. Shift exposed upstream category resolution traps for 12/21 queries."
    },
    "2e4b234": {
        "title": "Stage 1: Graph v2 Taxon Traversal & 4-Channel Lexical RRF",
        "doc": "thesis/15-doc-taxonomic-lexical-fusion.md",
        "doc_name": "15-doc-taxonomic-lexical-fusion.md",
        "rq": "RQ15",
        "chapter": "Chapter 4: Hybrid Semantic-Structural Retrieval; Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Intent resolution against 1,183 Taxon nodes with [:BROADER*0..7] traversal and 4th full-text Lucene BM25 index channel.",
        "impact": "Tripled candidate yield on title-blind queries, but live evaluation revealed a critical bottleneck: 52.4% of targets were falsely rejected by category filtering due to accessory hijacking (Target Admission = 47.6%)."
    },
    "4fb77f7": {
        "title": "Release R3.2: Domain-Agnostic SKOS Product-Type Matching & Dual HyDE",
        "doc": "thesis/19-doc-retrieval-evaluation.md",
        "doc_name": "19-doc-retrieval-evaluation.md",
        "rq": "RQ19",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": "Unified integration of W3C SKOS alt_labels, morphological lemmatization, phrase decomposition, anti-hijacking Taxon scoring, and Dual-Channel HyDE.",
        "impact": "BREAKTHROUGH IMPROVEMENT: Target Admission surged from 47.6% to 100.0% (20/20 search queries). Type Precision@5 reached 96.0%-99.0%. 4-Channel RRF (wrrf4) more than doubled HR@20 (0.238 -> 0.571, +140%) and tripled MRR (0.130 -> 0.364, +180%) with 0.000 constraint violations."
    }
}

def extract_metric_fields(s_dict):
    return {
        "HR@1": s_dict.get("mean_hr@1") or s_dict.get("mean_strict_hr@1"),
        "HR@5": s_dict.get("mean_hr@5") or s_dict.get("mean_strict_hr@5"),
        "HR@20": s_dict.get("mean_hr@20") or s_dict.get("mean_strict_hr@20"),
        "MRR": s_dict.get("mean_mrr"),
        "NDCG@10": s_dict.get("mean_ndcg@10") or s_dict.get("mean_strict_ndcg@10"),
        "TypeP@5": s_dict.get("mean_type_precision@5") or s_dict.get("mean_type_p@5"),
        "CS@5_viol": s_dict.get("mean_cs_viol@5"),
        "Latency": s_dict.get("p50_latency_ms")
    }

def extract_run_data(run_dir):
    rid = os.path.basename(run_dir)
    manifest_p = os.path.join(run_dir, "manifest.json")
    summary_p = os.path.join(run_dir, "summary.json")
    retrieval_p = os.path.join(run_dir, "retrieval_metrics.json")
    generative_p = os.path.join(run_dir, "generative_metrics.json")
    
    # If retrieval_metrics.json is missing in archive dir, check corresponding evaluations/ dir
    if not os.path.exists(retrieval_p):
        eval_counterpart = os.path.join("evaluations", rid, "retrieval_metrics.json")
        if os.path.exists(eval_counterpart):
            retrieval_p = eval_counterpart

    manifest = {}
    if os.path.exists(manifest_p):
        try:
            with open(manifest_p) as f: manifest = json.load(f)
        except: pass
    
    summary = {}
    if os.path.exists(summary_p):
        try:
            with open(summary_p) as f: summary = json.load(f)
        except: pass
        
    retrieval = {}
    if os.path.exists(retrieval_p):
        try:
            with open(retrieval_p) as f: retrieval = json.load(f)
        except: pass

    generative = {}
    if os.path.exists(generative_p):
        try:
            with open(generative_p) as f: generative = json.load(f)
        except: pass

    prov = manifest.get("provenance", {})
    commit = prov.get("git_commit") or manifest.get("git_commit") or "UNKNOWN"
    commit_short = commit[:7] if commit != "UNKNOWN" else "UNKNOWN"
    citable = manifest.get("citable")
    ts = manifest.get("timestamp") or prov.get("timestamp") or summary.get("timestamp") or "N/A"
    mode = manifest.get("mode") or (manifest.get("configuration") or {}).get("mode") or "live"
    sample_size = manifest.get("sample_size") or (manifest.get("configuration") or {}).get("sample_size")
    bench = manifest.get("benchmark_path") or (manifest.get("configuration") or {}).get("benchmark") or "live_eval_dataset.json"
    g_ver = manifest.get("graph_version") or prov.get("graph_version") or "v1"
    
    num_queries = summary.get("num_queries") or summary.get("total_queries") or (manifest.get("configuration") or {}).get("query_count")
    if not num_queries and "aggregates" in retrieval and isinstance(retrieval["aggregates"], dict):
        num_queries = retrieval["aggregates"].get("total_queries")
    if not num_queries and sample_size:
        num_queries = sample_size
        
    spurious = summary.get("spurious_clarify_count")
    if spurious is None:
        spurious = summary.get("spurious_clarify")
    target_adm = summary.get("target_admission_rate")

    strat_metrics = {}
    # Prefer aggregates_by_strategy if populated
    strat_aggs = retrieval.get("aggregates_by_strategy")
    if isinstance(strat_aggs, dict) and strat_aggs:
        for sname, s_data in strat_aggs.items():
            if isinstance(s_data, dict):
                strat_metrics[sname] = extract_metric_fields(s_data)
    elif "aggregates" in retrieval and isinstance(retrieval["aggregates"], dict):
        aggs = retrieval["aggregates"]
        first_val = list(aggs.values())[0] if aggs else None
        if isinstance(first_val, dict):
            for arm, arm_data in aggs.items():
                if isinstance(arm_data, dict):
                    strat_metrics[arm] = extract_metric_fields(arm_data)
        else:
            strat_metrics["hybrid"] = extract_metric_fields(aggs)
    elif "mean_mrr" in summary:
        strat_metrics["hybrid"] = extract_metric_fields(summary)

    return {
        "run_id": rid,
        "commit": commit,
        "commit_short": commit_short,
        "citable": citable,
        "timestamp": ts,
        "mode": mode,
        "sample_size": sample_size,
        "benchmark": bench,
        "graph_version": g_ver,
        "num_queries": num_queries,
        "spurious_clarify": spurious,
        "target_admission": target_adm,
        "strat_metrics": strat_metrics,
        "generative": generative
    }

def format_readme(data):
    rid = data["run_id"]
    c_short = data["commit_short"]
    meta = COMMIT_META.get(c_short, {
        "title": f"Feature / Fix at commit {c_short}",
        "doc": "thesis/19-doc-retrieval-evaluation.md",
        "doc_name": "19-doc-retrieval-evaluation.md",
        "rq": "RQ19",
        "chapter": "Chapter 5: Empirical Evaluation & Comparative Analysis",
        "change_desc": f"Evaluation run associated with commit {c_short}.",
        "impact": "Empirical validation run recording system performance."
    })
    
    if rid == "eval_2026-10-09_1333":
        meta = {
            "title": "CriticAgent & Synthesized Grounding Generative Evaluation",
            "doc": "thesis/5-doc-synthesized-grounding.md",
            "doc_name": "5-doc-synthesized-grounding.md",
            "rq": "RQ5",
            "chapter": "Chapter 4: Explainable Hybrid GraphRAG Generation",
            "change_desc": "Tier 2 Inverted CoT LLM-as-a-judge evaluation measuring Groundedness, Explainability, Coherence, and Recoverability.",
            "impact": "Validated factual KG adherence (Groundedness = 4.80/5.0) and multi-turn context retention (Coherence = 4.60/5.0)."
        }

    citable_badge = "✅ **CITABLE LIVE EVIDENCE**" if data["citable"] is True else ("⚠️ **NON-CITABLE (Context / Dev / Legacy)**" if data["citable"] is False else "ℹ️ **LEGACY / PRE-R2 RUN**")
    is_sample = bool(data["sample_size"] and data["sample_size"] < 21) or (data["num_queries"] and data["num_queries"] < 21)
    run_type_note = f"🧪 **Intermediate Dev / Smoke Test** ($N = {data['num_queries']}$ queries)" if is_sample else f"📊 **Full Benchmark Evaluation Run** ($N = {data['num_queries']}$ queries)"

    md = []
    md.append(f"# Evaluation Run: `{rid}`")
    md.append("")
    md.append(f"{citable_badge} &nbsp;|&nbsp; {run_type_note}")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 1. Master's Thesis Academic Mapping")
    md.append(f"* **Primary Thesis Document**: [`{meta['doc_name']}`](../../{meta['doc']})")
    md.append(f"* **Research Question ($RQ$)**: $\\mathbf{{{meta['rq']}}}$")
    md.append(f"* **Target Thesis Chapter**: {meta['chapter']}")
    md.append(f"* **Scope & Milestone**: **{meta['title']}**")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. Major Architectural Change Context")
    md.append("**What prompted this evaluation run?**")
    md.append(f"> {meta['change_desc']}")
    md.append("")
    md.append("**General Outcome & Academic Finding**:")
    md.append(f"> {meta['impact']}")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. Provenance & Execution Rigor")
    md.append("| Attribute | Value |")
    md.append("|---|---|")
    md.append(f"| **Run ID** | `{rid}` |")
    md.append(f"| **Execution Timestamp** | `{data['timestamp']}` |")
    md.append(f"| **Git Commit** | [`{c_short}`](../../commits/{data['commit']}) |")
    md.append(f"| **Knowledge Graph Version** | `{data['graph_version']}` |")
    md.append(f"| **Evaluation Mode** | `{data['mode']}` |")
    md.append(f"| **Benchmark Dataset** | `{os.path.basename(str(data['benchmark']))}` |")
    md.append(f"| **Evaluated Queries ($N$)** | {data['num_queries']} |")
    md.append(f"| **Citability Status** | `citable: {data['citable']}` |")
    if data["spurious_clarify"] is not None:
        md.append(f"| **Spurious CLARIFY Turns** | {data['spurious_clarify']} |")
    if data["target_admission"] is not None:
        md.append(f"| **Target Product Admission** | {round(data['target_admission'] * 100, 1)}% |")
    md.append("")
    md.append("---")
    md.append("")

    if data["strat_metrics"]:
        md.append("## 4. Information Retrieval (Tier 1) Metrics")
        md.append("")
        md.append("| Strategy / Fusion Arm | HitRate@1 | HitRate@5 | HitRate@20 | MRR | NDCG@10 | TypeP@5 | CS@5 Viol | Latency |")
        md.append("|---|---|---|---|---|---|---|---|---|")
        for sname, m in data["strat_metrics"].items():
            hr1 = f"{m.get('HR@1'):.4f}" if m.get('HR@1') is not None else "-"
            hr5 = f"{m.get('HR@5'):.4f}" if m.get('HR@5') is not None else "-"
            hr20 = f"{m.get('HR@20'):.4f}" if m.get('HR@20') is not None else "-"
            mrr = f"{m.get('MRR'):.4f}" if m.get('MRR') is not None else "-"
            ndcg = f"{m.get('NDCG@10'):.4f}" if m.get('NDCG@10') is not None else "-"
            typep = f"{m.get('TypeP@5'):.4f}" if m.get('TypeP@5') is not None else "-"
            viol = f"{m.get('CS@5_viol'):.4f}" if m.get('CS@5_viol') is not None else "-"
            lat = f"{m.get('Latency'):.1f} ms" if m.get('Latency') is not None else "-"
            md.append(f"| **`{sname}`** | {hr1} | {hr5} | {hr20} | {mrr} | {ndcg} | {typep} | {viol} | {lat} |")
        md.append("")

    if data["generative"]:
        gen_aggs = data["generative"].get("aggregates", data["generative"])
        md.append("## 5. Generative Explanation (Tier 2) Metrics")
        md.append("")
        md.append("| Metric | Dimension | Score (1.0 - 5.0) | Target |")
        md.append("|---|---|---|---|")
        md.append(f"| **Groundedness** | Factual Graph Adherence | `{gen_aggs.get('groundedness_mean', 'N/A')}` | $\\ge 4.50$ |")
        md.append(f"| **Explainability** | Provenance Fidelity | `{gen_aggs.get('explainability_mean', 'N/A')}` | $\\ge 3.50$ |")
        md.append(f"| **Coherence** | Dialogue Context Retention | `{gen_aggs.get('coherence_mean', 'N/A')}` | $\\ge 4.50$ |")
        md.append(f"| **Recoverability** | Negative Preference Handling | `{gen_aggs.get('recoverability_mean', 'N/A')}` | $\\ge 4.00$ |")
        md.append(f"| **Composite Score** | Overall Generation Quality | `{gen_aggs.get('composite_score', 'N/A')}` | $\\ge 4.00$ |")
        md.append("")

    md.append("---")
    md.append("")
    md.append("## 6. Experimental Replication")
    md.append("To replicate this evaluation under identical conditions:")
    md.append("```bash")
    if is_sample:
        md.append(f"python3 scripts/evaluate_retrieval.py --mode {data['mode']} --sample-size {data['num_queries']}")
    else:
        md.append(f"python3 scripts/evaluate_retrieval.py --mode {data['mode']}")
    md.append("```")
    md.append("")
    return "\n".join(md)

# Process all runs
eval_dirs = glob.glob("evaluations/eval_*")
archive_dirs = glob.glob("evaluations_archive/eval_*")

total_written = 0
for d in eval_dirs + archive_dirs:
    if not os.path.isdir(d): continue
    data = extract_run_data(d)
    content = format_readme(data)
    readme_path = os.path.join(d, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)
    total_written += 1

print(f"Successfully generated clean README.md in {total_written} evaluation directories.")
