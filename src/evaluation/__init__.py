"""
Two-Tiered Evaluation Framework for Explainable Hybrid GraphRAG Conversational Recommender System.

Exposes:
- Information Retrieval (IR) Ranking Metrics: compute_ndcg_at_k, compute_hit_rate_at_k, compute_mrr_at_k,
  compute_precision_at_k, compute_recall_at_k, compute_average_precision_at_k, evaluate_retrieval_batch
- LLM-as-a-Judge Generative Evaluators: evaluate_groundedness, evaluate_explainability, evaluate_coherence,
  evaluate_recoverability, evaluate_generative_batch
- Versioned Run Tracking: create_evaluation_run_dir, save_run_artifacts
- Publication Plotting: plot_retrieval_metrics, plot_generative_metrics, plot_comparative_summary
"""

from src.evaluation.metrics import (
    compute_ndcg_at_k,
    compute_hit_rate_at_k,
    compute_mrr_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
    compute_average_precision_at_k,
    evaluate_retrieval_batch,
)
from src.evaluation.judge import (
    evaluate_groundedness,
    evaluate_explainability,
    evaluate_coherence,
    evaluate_recoverability,
    evaluate_generative_batch,
)
from src.evaluation.tracker import (
    create_evaluation_run_dir,
    save_run_artifacts,
)
from src.evaluation.visualizer import (
    plot_retrieval_metrics,
    plot_generative_metrics,
    plot_comparative_summary,
)

__all__ = [
    "compute_ndcg_at_k",
    "compute_hit_rate_at_k",
    "compute_mrr_at_k",
    "compute_precision_at_k",
    "compute_recall_at_k",
    "compute_average_precision_at_k",
    "evaluate_retrieval_batch",
    "evaluate_groundedness",
    "evaluate_explainability",
    "evaluate_coherence",
    "evaluate_recoverability",
    "evaluate_generative_batch",
    "create_evaluation_run_dir",
    "save_run_artifacts",
    "plot_retrieval_metrics",
    "plot_generative_metrics",
    "plot_comparative_summary",
]
