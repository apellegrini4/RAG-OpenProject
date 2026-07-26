""" Test of the first phase, determinism check with temperature=0.

For each phase-1 model in config.yaml each question is repeated N times (default 30).
Checks if the json is identical to the real one and verifies also that the output is a
valid schema (json_correct).

Usage example:
    python benchmark/scripts/run_phase1.py
    python benchmark/scripts/run_phase1.py --repetitions 30 --label demo
    python benchmark/scripts/run_phase1.py --models qwen2.5-coder:1.5b
"""
from datetime import datetime
from pathlib import Path
import argparse
import csv
import json
import sys
import time
import yaml

CWD = Path(__file__).resolve().parent
PROJECT_ROOT = CWD.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CWD))

from metrics_phase1 import evaluate_question, summarize_stats

def parse_args():
    ap = argparse.ArgumentParser(description="Phase-1 determinism check at temperature 0")
    ap.add_argument("--config", default=str(PROJECT_ROOT / "benchmark" / "config.yaml"))
    ap.add_argument("--repetitions", type=int, default=None,
                    help="repetitions per question (default: config.repetitions_latency or 30)")
    ap.add_argument("--models", nargs="*", default=None,
                    help="override the model list from config (space separated)")
    ap.add_argument("--label", default="determinism-check")
    return ap.parse_args()

# experiment loop for one model
def run_model(chain, questions, format_instructions, reps, model, raw_file) -> tuple:
    results, latencies = [], []

    for q in questions:
        repetitions = []

        for _ in range(reps):
            start = time.time()
            error = None

            try:
                raw = chain.invoke({
                    "format_instructions": format_instructions,
                    "user_query": q["text"],
                }).content
            except Exception as e:
                raw, error = "", str(e)

            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            # raw is the text which is later parsed as dict (contains None if invalid)
            repetitions.append({"raw": raw, "parsed": parsed,
                                "latency": round(time.time() - start, 3), "error": error})

        latencies.extend(rep["latency"] for rep in repetitions)
        metrics = evaluate_question([rep["parsed"] for rep in repetitions], q)

        raw_file.write(json.dumps({
            "model": model,
            "question_id": q["id"],
            "difficulty": q["difficulty"],
            "real_macro": q["macro_section"],
            "real_filters": q["filters"],
            **metrics,
            "repetitions": repetitions,
        }, ensure_ascii=False) + "\n")

        status = "identical" if metrics["deterministic"] else f"{metrics['n_distinct_outputs']} variants"
        print(f"  {q['id']:<4} {q['difficulty']:<7}"
              f" determinism: {status:<12}"
              f" json_correct: {'yes' if metrics['json_correct'] else 'no':<3}"
              f" exact_match: {'yes' if metrics['exact_filter_match'] else 'no'}")
        results.append(metrics)

    return results, latencies


def main():
    args = parse_args()
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    models = args.models or cfg["models_phase1"]
    temperature = cfg.get("temperature_phase1", 0.0)
    reps = args.repetitions or cfg.get("repetitions_latency", 30)

    with open(PROJECT_ROOT / cfg["paths"]["questions"], encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"]

    from langchain_community.chat_models import ChatOllama
    from structured_URL_generator import prompt, parser
    format_instructions = parser.get_format_instructions()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = runs_dir / f"{timestamp}__phase1__{args.label}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # useful for reproducibility
    manifest = {"phase": "phase1", "label": args.label,
                "timestamp": timestamp, "models": models,
                "temperature": temperature, "repetitions": reps,
                "n_questions": len(questions), "seed": cfg.get("seed")}

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Models: {models}")
    print(f"Questions: {len(questions)} | repetitions: {reps} | temperature: {temperature}\n")

    summary_rows = []
    with open(run_dir / "raw_runs.jsonl", "w", encoding="utf-8") as raw_file:
        for model in models:
            print(f"=== MODEL: {model} ===")
            chain = prompt | ChatOllama(model=model, temperature=temperature, format="json")
            results, latencies = run_model(chain, questions, format_instructions, reps, model, raw_file)
            summary_rows.append(summarize_stats(model, results, latencies))
            print()

    with open(run_dir / "summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    print(" SUMMARY ")
    for row in summary_rows:
        print(f"  {row['model']:<26}"
              f" determinism: {row['determinism_rate'] * 100:5.1f}% "
              f" json_correct: {row['json_correct_rate'] * 100:5.1f}% "
              f" exact match: {row['exact_filter_match_rate'] * 100:5.1f}% "
              f" median latency: {row['median_latency']}s")
    print(f"\nResults written to --> {run_dir}")


if __name__ == "__main__":
    main()
