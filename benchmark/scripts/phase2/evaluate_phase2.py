""" computes the Phase-2 metrics from a run that has already been generated.

    usage:
        python benchmark/scripts/phase_2/evaluate_phase2.py                 # newest run
        python benchmark/scripts/phase_2/evaluate_phase2.py --run 20260807-101500__phase2__full
        python benchmark/scripts/phase_2/evaluate_phase2.py --no-index
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import yaml

CWD = Path(__file__).resolve().parent
SCRIPTS_DIR = CWD.parent
PROJECT_ROOT = CWD.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(CWD))

from embedder import EMBEDDING_MODEL, CachedEmbedder, get_embedder
from metrics_phase2 import (INTENTS, avg_cosine, avg_item_consistency, avg_value_coverage,
                            claims_done, full_coverage_rate, item_consistency,
                            observable_consistency_rate, latency_stats, response_type_accuracy,
                            response_type_check, value_coverage)
from llm_builder import CONFIG_PATH
import writers


def parse_args():
    ap = argparse.ArgumentParser(description="score an existing phase-2 run")
    ap.add_argument("--run", default=None,
                    help="run name or path (default: the most recent phase2 run)")
    ap.add_argument("--no-index", action="store_true",
                    help="do not append to results/phase2/index.csv")
    return ap.parse_args()


def resolve_run(run_arg, runs_dir):
    """ the run to score: the one named, or the most recent one """
    if run_arg:
        path = Path(run_arg)
        return path if path.is_dir() else runs_dir / run_arg

    candidates = sorted(p for p in runs_dir.iterdir() if p.is_dir() and (p / "models").is_dir())
    if not candidates:
        raise FileNotFoundError(f"no run to score in {runs_dir}")
    return candidates[-1]      # run names start with the timestamp, so the last is the newest


def score_cell(row, reference, embedder):
    """ the metrics of one generated answer (one repetition of one question) """
    generated = row.get("generated") or ""
    key_values = reference.get("key_values")
    coverage = value_coverage(generated, key_values)
    consistency_result = item_consistency(generated, key_values)
    response_type = response_type_check(generated, row["category"], coverage["coverage"])

    return {
        "question_id": row["question_id"], "repetition": row["repetition"],
        "category": row["category"], "latency": row["latency"], "error": row.get("error"),
        "cosine_similarity": round(embedder.cosine(generated, reference["ideal_answer"]), 4),
        "value_coverage": coverage["coverage"],
        "missing_values": coverage["missing"],
        "item_consistency": consistency_result["consistency"],
        "mixed_items": consistency_result["mixed"],
        "consistency_applicable": consistency_result["applicable"],
        "response_type_ok": response_type["ok"],
        "response_type_reason": response_type["reason"],
        "claims_done": claims_done(generated),
    }


def quality_metrics(cells):
    return {
        "avg_cosine_similarity": avg_cosine(cells),
        "avg_value_coverage": avg_value_coverage(cells),
        "full_coverage_rate": full_coverage_rate(cells),
        "avg_item_consistency": avg_item_consistency(cells),
        "observable_consistency_rate": observable_consistency_rate(cells), #on how many cells the consistency_result was observable at all
        "response_type_accuracy": response_type_accuracy(cells),
    }


def summarize(model, cells):
    """ global results, over every cell of the matrix """
    median, p90 = latency_stats([r["latency"] for r in cells])
    return {"model": model, "cells": len(cells), **quality_metrics(cells),
            "median_latency": median, "p90_latency": p90}


def summarize_by_intent(model, cells):
    """ same metrics but calculated per intent """
    rows = []
    for intent in INTENTS:
        subset = [r for r in cells if r["category"] == intent]
        if subset:
            rows.append({"model": model, "intent": intent, **quality_metrics(subset)})
    return rows


def score_model(m_dir, answers, embedder):
    """ reads answers.jsonl, writes scores.jsonl, returns the scored cells """
    cells = []
    with open(m_dir / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                #calculates the score for every single response
                cells.append(score_cell(row, answers[row["answer_id"]], embedder))

    (m_dir / "scores.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cells), encoding="utf-8")
    return cells


def main():
    args = parse_args()
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    #runs and results are both grouped by phase
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"] / "phase2"
    results_dir = PROJECT_ROOT / cfg["paths"]["results"] / "phase2"
    run_dir = resolve_run(args.run, runs_dir)

    answers_path = PROJECT_ROOT / cfg["paths"]["answers"]
    answers = {r["answer_id"]: r for r in
               (json.loads(line) for line in answers_path.read_text(encoding="utf-8").splitlines()
                if line.strip())}

    missing_kv = [aid for aid, a in answers.items() if "key_values" not in a]
    if missing_kv:
        raise ValueError(
            f"{len(missing_kv)} reference answers have no 'key_values' field "
            f"(first: {missing_kv[:3]}). Rebuild ideal_answers.jsonl before scoring.")

    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    #loads the embedder
    embedder = CachedEmbedder(get_embedder())
    print(f"Scoring {run_dir.name}")
    print(f"Embedding with {EMBEDDING_MODEL}\n")

    models = manifest.get("models") or sorted(p.name for p in (run_dir / "models").iterdir())

    summary_rows, intent_rows, index_rows = [], [], []
    for model in models:
        m_dir = run_dir / "models" / writers.validate_name(model)
        if not (m_dir / "answers.jsonl").exists():
            continue

        #calculates the metrics for every answer of the model
        cells = score_model(m_dir, answers, embedder)
        performance = summarize(model, cells)
        writers.write_performance(m_dir, performance)

        summary_rows.append(performance)
        intent_rows.extend(summarize_by_intent(model, cells))
        index_rows.append({"run": run_dir.name, "timestamp": manifest.get("timestamp", ""),
                           "difficulty": manifest.get("difficulty") or "all", **performance})
        print(f"  {model:<22} {len(cells)} cells scored")

    if not summary_rows:
        print("nothing to score: no answers.jsonl found")
        return 1

    #writes important data in the summary files
    writers.write_summary_csv(run_dir, summary_rows)
    writers.write_summary_csv(run_dir, intent_rows, filename="summary_by_intent.csv")
    writers.write_report_md(run_dir, run_dir.name, summary_rows)
    if args.no_index:
        print("\n  (--no-index: index.csv untouched)")
    else:
        writers.append_index_csv(results_dir, index_rows)

    if manifest:
        manifest["scored"] = True
        manifest["scored_at"] = datetime.now(timezone.utc).isoformat()
        manifest["embedding_model"] = EMBEDDING_MODEL
        writers.write_manifest(run_dir, manifest)


    print(f"\nResults written to --> {run_dir}")
    if not args.no_index:
        print(f"Appended to        --> {results_dir / 'index.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
