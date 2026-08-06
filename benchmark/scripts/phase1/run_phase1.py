""" Test of the first phase, filters extraction.

For each phase-1 model in config.yaml each question is repeated N times (default 30).
Checks if the json is identical to the real one and verifies also that the output is a
valid schema (json_correct).

Usage example:
    python benchmark/scripts/phase_1/run_phase1.py
    python benchmark/scripts/phase_1/run_phase1.py --repetitions 30 --label demo
    python benchmark/scripts/phase_1/run_phase1.py --models qwen2.5-coder:1.5b
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import time
import yaml

CWD = Path(__file__).resolve().parent          # benchmark/scripts/phase_1/
SCRIPTS_DIR = CWD.parent
PROJECT_ROOT = CWD.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(CWD))

from collections import Counter

from metrics_phase1 import (evaluate_question, summarize_stats, failure_reason, schema_validation,
                            exact_filter_match)
from llm_builder import build_llm, CONFIG_PATH
import writers

#function to customize run parameters from the terminal
def parse_args():
    ap = argparse.ArgumentParser(description="Phase-1")
    ap.add_argument("--repetitions", type=int, default=None,
                    help="repetitions per question (default: config.repetitions)")
    ap.add_argument("--models", nargs="*", default=None,
                    help="override the model list from config (space separated)")
    ap.add_argument("--label", default="demo")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"], default=None,
                    help="filter the dataset to only this difficulty level (default: all)")
    ap.add_argument("--questions", default=None,
                    help="override the questions.jsonl path from config.yaml (useful for trial runs)")
    ap.add_argument("--no-index", action="store_true",
                    help="do not append to results/index.csv: for diagnostic runs")
    return ap.parse_args()

def strip_reasoning(parsed):
    """ removes the reasoning from the answer to obtain a cleaner answers file"""
    if not isinstance(parsed, dict):
        return parsed
    return {k: v for k, v in parsed.items() if k != "reasoning"}


def save_results(repetitions, q, m_dir):
    """ writes the resultes in separated folders"""
    answers_rows, reasoning_rows, failure_rows = [], [], []

    for i, rep in enumerate(repetitions):
        parsed = rep["parsed"]
        parsed_clean = strip_reasoning(parsed)
        json_correct = schema_validation(parsed)

        answers_rows.append({
            "question_id": q["id"], "repetition": i,
            "parsed": parsed_clean,
            "json_correct": json_correct,
            "exact_match": json_correct and exact_filter_match(parsed, q),
            "latency": rep["latency"], "error": rep["error"],
        })
        reasoning_rows.append({
            "question_id": q["id"], "repetition": i,
            "reasoning": parsed.get("reasoning") if isinstance(parsed, dict) else None,
        })

        reason = failure_reason(parsed, q)
        if reason is not None:
            failure_row = {
                "question_id": q["id"], "repetition": i,
                "failure_reason": reason, "error": rep["error"],
            }
            if reason in ("filter_mismatch", "payload_mismatch"):
                failure_row["parsed"] = parsed_clean
            else:
                failure_row["raw"] = rep["raw"]
            failure_rows.append(failure_row)

    #writes the info
    writers.write_answers(m_dir, answers_rows)
    writers.write_reasoning(m_dir, reasoning_rows)
    writers.write_failures(m_dir, failure_rows)


def print_question_line(q, metrics, repetitions):
    """ prints the reason of the query failure """
    total = metrics["total_reps"]
    print(f"  {q['id']:<4} {q['intent']:<6} {q['macro_section']:<14}"
          f" json {metrics['json_correct_count']:>3}/{total}"
          f" | intent {metrics['intent_correct_count']:>3}/{total}"
          f" | macro {metrics['macro_correct_count']:>3}/{total}"
          f" | filters {metrics['filter_correct_count']:>3}/{total}"
          f" | payload {metrics['payload_correct_count']:>3}/{total}"
          f" | {'identical' if metrics['deterministic'] else str(metrics['n_distinct_outputs']) + ' varianti'}"
          f", stab {metrics['stability'] * 100:.0f}%")

    if (metrics["json_correct_count"] == total and metrics["intent_correct_count"] == total
            and metrics["macro_correct_count"] == total and metrics["filter_correct_count"] == total
            and metrics["payload_correct_count"] == total):
        return

    #the most frequent failure reason is the representative one (temperature=0)
    reasons = Counter(failure_reason(rep["parsed"], q) for rep in repetitions)
    reasons.pop(None, None)
    print(f"\n\tWRONG, cause: {reasons.most_common(1)[0][0]}")


def run_model(chain, questions, format_instructions, reps, model, m_dir):
    """ invokes the model reps times and calculates the results """ 
    results = []
    latencies = []

    for q in questions:
        repetitions = []

        #every question is repeated 'reps' times
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

            repetitions.append({"raw": raw, "parsed": parsed, "latency": round(time.time() - start, 3), "error": error})

        latencies.extend(rep["latency"] for rep in repetitions)
        metrics = evaluate_question([rep["parsed"] for rep in repetitions], q)

        save_results(repetitions, q, m_dir)

        print_question_line(q, metrics, repetitions)
        results.append(metrics)

    return results, latencies


def main():
    #loads the config and saves the necessary parameters
    args = parse_args()
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    models = args.models or cfg["models_phase1"]
    temperature = cfg.get("temperature_phase1", 0.0)
    reps = args.repetitions or cfg["repetitions"]

    #reads the questions from the jsonl (single file, filtered by --difficulty at load time)
    questions_path = Path(args.questions) if args.questions else PROJECT_ROOT / cfg["paths"]["questions"]
    with open(questions_path, encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]
    
    #takes only the questions for the specified difficulty
    if args.difficulty:
        questions = [q for q in questions if q.get("difficulty") == args.difficulty]
    #runs and results are both grouped by phase
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"] / "phase1"
    results_dir = PROJECT_ROOT / cfg["paths"]["results"] / "phase1"

    from structured_URL_generator import prompt, parser, PROMPT_VERSION
    format_instructions = parser.get_format_instructions()

    #creates the new folder
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_name = f"{timestamp}__phase1__{args.label}"
    run_dir = writers.create_run_dir(runs_dir, run_name)

    started_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "phase": "phase1", "label": args.label, "run_name": run_name,
        "timestamp": timestamp, "started_at": started_at, "finished_at": None,
        "models": models, "temperature": temperature, "repetitions": reps,
        "difficulty": args.difficulty, "questions_path": str(questions_path),
        "n_questions": len(questions), "prompt_version": PROMPT_VERSION, "config": cfg,
    }
    writers.write_manifest(run_dir, manifest)

    print(f"Models: {models}")
    print(f"Questions: {len(questions)} | repetitions: {reps} | temperature: {temperature}\n")

    summary_rows, index_rows = [], []
    for model in models:
        print(f" MODEL: {model} ")
        m_dir = writers.model_dir(run_dir, model)
        
        #creates a chain
        chain = prompt | build_llm("phase1", model)

        #saves the performance of the model
        results, latencies = run_model(chain, questions, format_instructions, reps, model, m_dir)
        performance = summarize_stats(model, results, latencies)
        writers.write_performance(m_dir, performance)

        summary_rows.append(performance)
        index_rows.append({"run": run_name, "timestamp": timestamp,
                            "difficulty": args.difficulty or "all", **performance})
        print()

    #saves important info 
    writers.write_summary_csv(run_dir, summary_rows)
    writers.write_report_md(run_dir, run_name, summary_rows)
    if args.no_index:
        print("  (--no-index: results/index.csv non toccato)")
    else:
        writers.append_index_csv(results_dir, index_rows)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    writers.write_manifest(run_dir, manifest)

    print("\n SUMMARY ")
    header = (f"  {'model':<22}{'json':>7}{'intent':>8}{'macro':>8}{'filters':>9}"
              f"{'payload':>9}{'unsafe':>8}{'determ':>8}{'stab':>7}{'lat med':>9}{'lat p90':>9}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in summary_rows:
        unsafe = row["unsafe_action_rate"]
        unsafe_str = f"{unsafe * 100:.1f}%" if unsafe is not None else "n/a"
        print(f"  {row['model']:<22}"
              f"{row['json_correct_rate'] * 100:6.1f}%"
              f"{row['intent_accuracy'] * 100:7.1f}%"
              f"{row['macro_section_accuracy'] * 100:7.1f}%"
              f"{row['exact_filter_match_rate'] * 100:8.1f}%"
              f"{row['exact_payload_match_rate'] * 100:8.1f}%"
              f"{unsafe_str:>8}"
              f"{row['determinism_rate'] * 100:7.1f}%"
              f"{row['stability'] * 100:6.1f}%"
              f"{row['median_latency']:8.2f}s"
              f"{row['p90_latency']:8.2f}s")
    print(f"\nResults written to --> {run_dir}")
    if not args.no_index:
        print(f"Appended to        --> {results_dir / 'index.csv'}")


if __name__ == "__main__":
    main()
