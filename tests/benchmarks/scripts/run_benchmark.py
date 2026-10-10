"""
tests/benchmarks/scripts/run_benchmark.py

Benchmark runner for preference extraction prompts.
Runs 15 prompt variants × 5 scenarios × 3 models = 225 API calls.
Produces results CSV, per-prompt detail JSON, and publication-quality charts.
"""
import os
import json
import time
import csv
import re
import sys

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from benchmarks.prompts.prompts_dict import PROMPTS
from benchmarks.conversations.scenarios import SCENARIOS

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODELS = ["gpt-6-sol", "gpt-4o", "o4-mini"]

# Load .env from project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'), override=True)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_thinking_tags(text: str) -> str:
    """Remove <thinking>...</thinking> blocks from CoT responses before JSON parsing."""
    return re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL).strip()


def extract_json(text: str) -> str:
    """Extract JSON from model output, handling markdown fences and CoT preambles."""
    # First strip any <thinking> blocks
    text = strip_thinking_tags(text)

    # Try markdown fenced block
    match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try raw JSON object (greedy outermost braces)
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return match.group(0).strip()

    return text.strip()


def classify_prompt(name: str) -> str:
    """Map a prompt key to its strategy category for charting."""
    if name.startswith("baseline"):
        return "baseline"
    if name.startswith("fs_cot"):
        return "fs+cot"
    if name.startswith("few_shot"):
        return "few-shot"
    if name.startswith("zero_shot"):
        return "zero-shot"
    if name.startswith("cot"):
        return "cot"
    return "other"


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_response(response_text: str, expected: dict) -> tuple[float, bool, dict]:
    """
    Evaluate model output against ground truth.

    Returns:
        (score, valid_json, detail_dict)
        score: float 0.0-1.0 composite of intent match + constraint recall + readiness match
        valid_json: whether the output parsed to valid schema JSON
        detail_dict: granular metrics for the detail report
    """
    detail = {
        "intent_match": False,
        "constraint_recall": 0.0,
        "constraint_precision": 0.0,
        "readiness_match": False,
        "parse_error": None,
    }

    try:
        json_str = extract_json(response_text)
        data = json.loads(json_str)

        if "current_session_context" not in data:
            detail["parse_error"] = "Missing root key 'current_session_context'"
            return 0.0, False, detail

        ctx = data["current_session_context"]

        # --- Intent ---
        intent_match = ctx.get("session_intent") == expected["expected_intent"]
        detail["intent_match"] = intent_match

        # --- Hard constraints recall & precision ---
        extracted_constraints = ctx.get("extracted_parameters", {}).get("hard_constraints", [])
        expected_c = expected["expected_constraints"]

        if not expected_c and not extracted_constraints:
            recall = 1.0
            precision = 1.0
        elif not expected_c and extracted_constraints:
            recall = 1.0  # nothing expected, so recall is trivially perfect
            precision = 0.0  # but model hallucinated constraints
        elif expected_c and not extracted_constraints:
            recall = 0.0
            precision = 1.0  # nothing extracted, no false positives
        else:
            matches = 0
            for ec in expected_c:
                for ac in extracted_constraints:
                    attr_match = ac.get("attribute", "").lower() == ec["attribute"].lower()
                    val_match = str(ac.get("value", "")).lower() == str(ec["value"]).lower()
                    if attr_match and val_match:
                        matches += 1
                        break
            recall = matches / len(expected_c) if expected_c else 1.0
            precision = matches / len(extracted_constraints) if extracted_constraints else 0.0

        detail["constraint_recall"] = round(recall, 4)
        detail["constraint_precision"] = round(precision, 4)

        # --- Readiness ---
        ds = ctx.get("dialogue_state", {})
        readiness_match = ds.get("ready_for_recommendation") == expected["expected_ready"]
        detail["readiness_match"] = readiness_match

        # --- Composite score: 40% intent + 40% constraint recall + 20% readiness ---
        score = 0.4 * float(intent_match) + 0.4 * recall + 0.2 * float(readiness_match)
        return round(score, 4), True, detail

    except json.JSONDecodeError as e:
        detail["parse_error"] = f"JSON decode error: {e}"
        return 0.0, False, detail
    except Exception as e:
        detail["parse_error"] = f"Unexpected error: {e}"
        return 0.0, False, detail


# ---------------------------------------------------------------------------
# Main benchmark loop
# ---------------------------------------------------------------------------

def run_benchmark():
    results = []
    details = []

    total = len(MODELS) * len(PROMPTS) * len(SCENARIOS)
    counter = 0

    for model in MODELS:
        print(f"\n{'='*60}")
        print(f"MODEL: {model}")
        print(f"{'='*60}")

        for p_name, p_text in PROMPTS.items():
            for scen in SCENARIOS:
                counter += 1
                print(f"  [{counter}/{total}] {p_name} × {scen['id']} ... ", end="", flush=True)

                # Build messages: system prompt + user input
                messages = [
                    {"role": "system", "content": p_text},
                    {"role": "user", "content": f"<input>\n{scen['conversation']}\n</input>"},
                ]

                start = time.time()
                try:
                    # Reasoning models (o-series, gpt-6-sol) don't support temperature
                    api_kwargs = dict(model=model, messages=messages)
                    if not (model.startswith("o") or "sol" in model or "astra" in model):
                        api_kwargs["temperature"] = 0.0
                    response = client.chat.completions.create(**api_kwargs)
                    out_text = response.choices[0].message.content or ""
                    prompt_tokens = response.usage.prompt_tokens
                    completion_tokens = response.usage.completion_tokens
                    total_tokens = response.usage.total_tokens
                except Exception as e:
                    print(f"ERROR: {e}")
                    out_text = ""
                    prompt_tokens = completion_tokens = total_tokens = 0

                latency = round(time.time() - start, 3)
                score, valid_json, detail = evaluate_response(out_text, scen)
                print(f"score={score:.2f}  valid={valid_json}  latency={latency}s")

                row = {
                    "model": model,
                    "prompt": p_name,
                    "prompt_type": classify_prompt(p_name),
                    "scenario": scen["id"],
                    "scenario_name": scen["name"],
                    "score": score,
                    "valid_json": valid_json,
                    "intent_match": detail["intent_match"],
                    "constraint_recall": detail["constraint_recall"],
                    "constraint_precision": detail["constraint_precision"],
                    "readiness_match": detail["readiness_match"],
                    "latency_s": latency,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
                results.append(row)

                details.append({
                    **row,
                    "raw_output": out_text[:2000],  # truncate for storage
                    "parse_error": detail.get("parse_error"),
                })

    # --- Save CSV ---
    csv_path = os.path.join(RESULTS_DIR, 'results.csv')
    fieldnames = list(results[0].keys())
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults CSV saved to {csv_path}")

    # --- Save detail JSON ---
    detail_path = os.path.join(RESULTS_DIR, 'results_detail.json')
    with open(detail_path, 'w') as f:
        json.dump(details, f, indent=2, default=str)
    print(f"Detail JSON saved to {detail_path}")

    # --- Generate charts ---
    generate_charts(results)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def generate_charts(results: list[dict]):
    df = pd.DataFrame(results)
    sns.set_theme(style="whitegrid", font_scale=1.1)

    strategy_order = ["baseline", "zero-shot", "few-shot", "cot", "fs+cot"]
    palette = sns.color_palette("viridis", n_colors=len(MODELS))

    # ── Chart 1: Composite Score by Strategy × Model ──
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(data=df, x="prompt_type", y="score", hue="model",
                order=strategy_order, palette=palette, ax=ax, ci="sd")
    ax.set_title("Composite Extraction Score by Prompt Strategy", fontsize=14, fontweight="bold")
    ax.set_xlabel("Prompt Strategy")
    ax.set_ylabel("Score (0-1)")
    ax.set_ylim(0, 1.05)
    ax.legend(title="Model")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'score_by_strategy.png'), dpi=150)
    plt.close(fig)

    # ── Chart 2: JSON Compliance Rate by Strategy ──
    compliance = df.groupby(["prompt_type", "model"])["valid_json"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(data=compliance, x="prompt_type", y="valid_json", hue="model",
                order=strategy_order, palette=palette, ax=ax)
    ax.set_title("JSON Schema Compliance Rate by Strategy", fontsize=14, fontweight="bold")
    ax.set_xlabel("Prompt Strategy")
    ax.set_ylabel("Compliance Rate (0-1)")
    ax.set_ylim(0, 1.05)
    ax.legend(title="Model")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'json_compliance.png'), dpi=150)
    plt.close(fig)

    # ── Chart 3: Per-Prompt Heatmap (Score) ──
    pivot = df.pivot_table(index="prompt", columns="model", values="score", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(8, 10))
    sns.heatmap(pivot, annot=True, fmt=".2f", cmap="YlGnBu", vmin=0, vmax=1,
                linewidths=0.5, ax=ax)
    ax.set_title("Per-Prompt Average Score Heatmap", fontsize=14, fontweight="bold")
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'prompt_heatmap.png'), dpi=150)
    plt.close(fig)

    # ── Chart 4: Intent Accuracy by Strategy × Model ──
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(data=df, x="prompt_type", y="intent_match", hue="model",
                order=strategy_order, palette=palette, ax=ax, ci="sd")
    ax.set_title("Intent Classification Accuracy by Strategy", fontsize=14, fontweight="bold")
    ax.set_xlabel("Prompt Strategy")
    ax.set_ylabel("Intent Match Rate (0-1)")
    ax.set_ylim(0, 1.05)
    ax.legend(title="Model")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'intent_accuracy.png'), dpi=150)
    plt.close(fig)

    # ── Chart 5: Constraint Recall by Strategy × Model ──
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(data=df, x="prompt_type", y="constraint_recall", hue="model",
                order=strategy_order, palette=palette, ax=ax, ci="sd")
    ax.set_title("Hard Constraint Recall by Strategy", fontsize=14, fontweight="bold")
    ax.set_xlabel("Prompt Strategy")
    ax.set_ylabel("Recall (0-1)")
    ax.set_ylim(0, 1.05)
    ax.legend(title="Model")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'constraint_recall.png'), dpi=150)
    plt.close(fig)

    # ── Chart 6: Latency by Strategy × Model ──
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.boxplot(data=df, x="prompt_type", y="latency_s", hue="model",
                order=strategy_order, palette=palette, ax=ax)
    ax.set_title("Response Latency by Strategy", fontsize=14, fontweight="bold")
    ax.set_xlabel("Prompt Strategy")
    ax.set_ylabel("Latency (seconds)")
    ax.legend(title="Model")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'latency_boxplot.png'), dpi=150)
    plt.close(fig)

    # ── Chart 7: Token Usage by Strategy × Model ──
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(data=df, x="prompt_type", y="total_tokens", hue="model",
                order=strategy_order, palette=palette, ax=ax, ci="sd")
    ax.set_title("Total Token Usage by Strategy", fontsize=14, fontweight="bold")
    ax.set_xlabel("Prompt Strategy")
    ax.set_ylabel("Total Tokens")
    ax.legend(title="Model")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'token_usage.png'), dpi=150)
    plt.close(fig)

    # ── Chart 8: Per-Scenario Score Comparison ──
    fig, ax = plt.subplots(figsize=(14, 6))
    sns.barplot(data=df, x="scenario", y="score", hue="prompt_type",
                palette="Set2", ax=ax, ci=None)
    ax.set_title("Score by Scenario across Strategies", fontsize=14, fontweight="bold")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Score (0-1)")
    ax.set_ylim(0, 1.05)
    ax.legend(title="Strategy", bbox_to_anchor=(1.05, 1), loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, 'score_by_scenario.png'), dpi=150)
    plt.close(fig)

    print(f"\n8 charts saved to {RESULTS_DIR}/")


if __name__ == "__main__":
    run_benchmark()
