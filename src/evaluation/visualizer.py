"""
Publication-Grade Visual Analytics Engine for CRS Evaluation.

Enforces headless execution via matplotlib Agg backend before importing pyplot.
Generates publication-ready figures at 300 DPI supporting both PNG and JPG formats:
- Grouped bar chart comparing IR retrieval ranking metrics across strategies
- Multi-dimensional horizontal bar chart or radar chart for LLM-as-a-Judge pillars
- Comparative executive scorecard summary charts
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union
import numpy as np

# Enforce headless Agg backend before importing pyplot
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# Set clean default theme
sns.set_theme(style="whitegrid", palette="muted")


def plot_retrieval_metrics(
    metrics_by_strategy: Dict[str, Dict[str, float]],
    output_path: Union[str, Path],
    format: str = "png",
    dpi: int = 300,
) -> str:
    """
    Renders publication-grade grouped bar chart comparing retrieval metrics across strategies.

    Args:
        metrics_by_strategy: Dict mapping strategy name -> {metric_name: score_float}
        output_path: Target image file path
        format: Image format ('png' or 'jpg'/'jpeg')
        dpi: Dots per inch (default: 300)

    Returns:
        String path of the saved figure.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    strategies = list(metrics_by_strategy.keys())
    if not strategies:
        strategies = ["Default"]
        metrics_by_strategy = {"Default": {"NDCG@10": 0.0, "HR@10": 0.0, "MRR": 0.0}}

    metric_keys = list(next(iter(metrics_by_strategy.values())).keys())
    x = np.arange(len(metric_keys))
    width = 0.8 / max(1, len(strategies))

    fig, ax = plt.subplots(figsize=(10, 6), dpi=dpi)

    # Use accessible color palette
    colors = sns.color_palette("muted", n_colors=len(strategies))

    for i, strat in enumerate(strategies):
        values = [metrics_by_strategy[strat].get(m, 0.0) for m in metric_keys]
        offset = (i - len(strategies) / 2) * width + width / 2
        ax.bar(x + offset, values, width, label=strat, color=colors[i], alpha=0.9, edgecolor="black", linewidth=0.5)

    ax.set_title("Retrieval Quality Across Search Strategies", fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("Metric Score", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(metric_keys, fontsize=11)
    ax.set_ylim(0.0, 1.05)
    ax.legend(title="Strategy", fontsize=10, title_fontsize=11, frameon=True)
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_path, format=format, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def plot_generative_metrics(
    judge_scores: Dict[str, float],
    output_path: Union[str, Path],
    format: str = "png",
    dpi: int = 300,
) -> str:
    """
    Renders publication-grade chart for LLM-as-a-Judge quality dimensions.

    Args:
        judge_scores: Dict mapping dimension name -> score (1.0 - 5.0)
        output_path: Target image file path
        format: Image format ('png' or 'jpg'/'jpeg')
        dpi: Dots per inch (default: 300)

    Returns:
        String path of the saved figure.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dimensions = list(judge_scores.keys())
    scores = [float(judge_scores[k]) for k in dimensions]

    fig, ax = plt.subplots(figsize=(8, 5), dpi=dpi)
    colors = plt.cm.viridis(np.linspace(0.25, 0.85, max(1, len(dimensions))))
    bars = ax.barh(dimensions, scores, color=colors, height=0.5, edgecolor="black", linewidth=0.5)

    ax.set_title("LLM-as-a-Judge Quality Dimensions", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Likert Score (1.0 – 5.0)", fontsize=12)
    ax.set_xlim(0.0, 5.2)
    ax.grid(axis="x", linestyle="--", alpha=0.5)

    for bar in bars:
        width = bar.get_width()
        ax.text(
            width + 0.1,
            bar.get_y() + bar.get_height() / 2,
            f"{width:.2f}",
            va="center",
            ha="left",
            fontsize=10,
            fontweight="bold",
        )

    plt.tight_layout()
    plt.savefig(output_path, format=format, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def plot_comparative_summary(
    summary_data: Dict[str, Any],
    output_path: Union[str, Path],
    format: str = "png",
    dpi: int = 300,
) -> str:
    """
    Renders comparative executive evaluation summary scorecard chart.

    Args:
        summary_data: Dict mapping category/strategy name -> normalized score
        output_path: Target image file path
        format: Image format (default: 'png')
        dpi: Dots per inch (default: 300)

    Returns:
        String path of the saved figure.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9, 5), dpi=dpi)
    categories = list(summary_data.keys())
    values = [float(summary_data[k]) for k in categories]

    ax.bar(categories, values, color="steelblue", alpha=0.85, edgecolor="black", linewidth=0.5)
    ax.set_title("Comparative Executive Evaluation Summary", fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("Normalized Score", fontsize=12)
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_path, format=format, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)
