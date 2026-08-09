""" phase-2 runner: this is an isolated mode, meaning that there is no gate. The input is always correct by construction.
It saves the answer and the latency of every cell, the quality metrics are computed by evaluate_phase2.py, reading the same answers.jsonl

Usage example:
    python benchmark/scripts/phase_2/run_phase2.py
    python benchmark/scripts/phase_2/run_phase2.py --repetitions 5 --label demo
    python benchmark/scripts/phase_2/run_phase2.py --models llama3.2:3b
    # then:
    python benchmark/scripts/phase_2/evaluate_phase2.py
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import time
import yaml

CWD = Path(__file__).resolve().parent          # benchmark/scripts/phase_2/
SCRIPTS_DIR = CWD.parent                       # benchmark/scripts/ -- writers.py, embedder.py
PROJECT_ROOT = CWD.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(CWD))

from metrics_phase2 import latency_stats, question_category
from llm_builder import CONFIG_PATH
from response_generator import PROMPT_VERSION_PHASE2, define_response_chain
import writers

#function to customize run parameters from the terminal
def parse_args():
    ap = argparse.ArgumentParser(description="Phase-2, isolated mode")
    ap.add_argument("--repetitions", type=int, default=None,
                    help="repetitions per question (default: config.repetitions)")
    ap.add_argument("--models", nargs="*", default=None,
                    help="override the model list from config (space separated)")
    ap.add_argument("--label", default="demo")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"], default=None,
                    help="filter the dataset to only this difficulty level (default: all)")
    ap.add_argument("--questions", default=None,
                    help="override the questions.jsonl path from config.yaml")
    ap.add_argument("--no-index", action="store_true",
                    help="do not append to results/index.csv: for diagnostic runs")
    return ap.parse_args()

def run_model(chain, questions, answers, mock_dir, reps, m_dir):
    """ invokes the model reps times per question and saves answer + latency. No other metric is computed here """
    cells = []

    for q in questions:
        mock_id = answers[q["answer_id"]]["mock_id"]
        mock = json.loads((mock_dir / f"{mock_id}.json").read_text(encoding="utf-8"))
        json_text = json.dumps(mock, indent=2, ensure_ascii=False) if isinstance(mock, dict) else str(mock)

        rep_rows = []
        for i in range(reps):
            start = time.time()
            error = None

            try:
                #invokes the chain to generate the response
                generated = chain.invoke({"json": json_text, "user_query": q["text"]})
            except Exception as e:
                generated, error = "", str(e)
            latency = round(time.time() - start, 3)

            rep_rows.append({
                "question_id": q["id"], "answer_id": q["answer_id"],
                "repetition": i, "category": question_category(q),
                "generated": generated, "latency": latency, "error": error,
            })

        writers.write_answers(m_dir, rep_rows)
        cells.extend(rep_rows)

        median, _ = latency_stats([r["latency"] for r in rep_rows])
        errors = sum(1 for r in rep_rows if r["error"])
        print(f"  {q['id']:<4} {question_category(q):<12} median {median:6.2f}s"
              + (f"   {errors} error(s)" if errors else ""))

    return cells


def summarize(model, cells):
    """ what a run can report on its own: how long it took, over every cell of the matrix.
    The quality metrics arrive with evaluate_phase2.py """
    median, p90 = latency_stats([r["latency"] for r in cells])
    return {
        "model": model,
        "cells": len(cells),
        "errors": sum(1 for r in cells if r["error"]),
        "median_latency": median,
        "p90_latency": p90,
    }


def main():
    #loads the config and saves the necessary parameters
    args = parse_args()
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    models = args.models or cfg["models_phase2"]
    reps = args.repetitions or cfg["repetitions"]
    seed = cfg.get("seed", 42)

    #it loads all the questions
    questions_path = Path(args.questions) if args.questions else PROJECT_ROOT / cfg["paths"]["questions"]
    with open(questions_path, encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]

    #takes only the questions for the specified difficulty --> !! operational choice, phase 2 doesn't really have a real difficulty level
    if args.difficulty:
        questions = [q for q in questions if q.get("difficulty") == args.difficulty]

    #it loads the gold answers
    answers_path = PROJECT_ROOT / cfg["paths"]["answers"]
    answers = {r["answer_id"]: r for r in
               (json.loads(line) for line in answers_path.read_text(encoding="utf-8").splitlines()
                if line.strip())}
    missing_ref = [q["id"] for q in questions if q.get("answer_id") not in answers]
    if missing_ref:
        raise ValueError(f"questions whose answer_id has no ideal ideal_answer: {missing_ref}")

    mock_dir = PROJECT_ROOT / cfg["paths"]["mock_data"]
    #runs are grouped by phase
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"] / "phase2"

    #creates the new folder
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_name = f"{timestamp}__phase2__{args.label}"
    run_dir = writers.create_run_dir(runs_dir, run_name)

    started_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "phase": "phase2", "label": args.label, "run_name": run_name,
        "timestamp": timestamp, "started_at": started_at, "finished_at": None,
        "models": models, "temperature": cfg.get("temperature_phase2", 0.6), "seed": seed,
        "repetitions": reps, "mode": "isolated",
        "prompt_version": PROMPT_VERSION_PHASE2,
        "difficulty": args.difficulty, "questions_path": str(questions_path),
        "n_questions": len(questions), "scored": False, "config": cfg,
    }
    writers.write_manifest(run_dir, manifest)

    print(f"Models: {models}")
    print(f"Questions: {len(questions)} | repetitions: {reps} | mode: isolated\n")

    summary_rows = []
    for model in models:
        print(f" MODEL: {model} ")
        m_dir = writers.model_dir(run_dir, model)

        #creates a chain
        chain = define_response_chain(model)

        cells = run_model(chain, questions, answers, mock_dir, reps, m_dir)
        summary_rows.append(summarize(model, cells))
        print()

    #saves the performance of the model
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    writers.write_manifest(run_dir, manifest)

    print("\n GENERATION SUMMARY ")
    header = f"  {'model':<22}{'cells':>8}{'errors':>8}{'lat med':>9}{'lat p90':>9}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in summary_rows:
        print(f"  {row['model']:<22}{row['cells']:>8}{row['errors']:>8}"
              f"{row['median_latency']:8.2f}s{row['p90_latency']:8.2f}s")

    print(f"\nAnswers written to --> {run_dir}")
    print("Now compute the metrics with:")
    print(f"  python benchmark/scripts/phase_2/evaluate_phase2.py --run {run_name}")


if __name__ == "__main__":
    main()
