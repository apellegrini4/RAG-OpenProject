""" Test of the first phase, filters extraction.

For each phase-1 model in config.yaml each question is repeated N times (default 30).
Checks if the json is identical to the real one and verifies also that the output is a
valid schema (json_correct).

Usage example:
    python benchmark/scripts/run_phase1.py
    python benchmark/scripts/run_phase1.py --repetitions 30 --label demo
    python benchmark/scripts/run_phase1.py --models qwen2.5-coder:1.5b
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import time
import yaml

CWD = Path(__file__).resolve().parent
PROJECT_ROOT = CWD.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CWD))

from metrics_phase1 import evaluate_question, summarize_stats, failure_reason, schema_validation, exact_filter_match
from llm_builder import build_llm, CONFIG_PATH
import writers

#function to customize run parameters from the terminal
def parse_args():
    ap = argparse.ArgumentParser(description="Phase-1")
    ap.add_argument("--repetitions", type=int, default=None,
                    help="repetitions per question (default: 30)")
    ap.add_argument("--models", nargs="*", default=None,
                    help="override the model list from config (space separated)")
    ap.add_argument("--label", default="demo")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"], default=None,
                    help="filter the dataset to only this difficulty level (default: all)")
    ap.add_argument("--questions", default=None,
                    help="override the questions.jsonl path from config.yaml (useful for trial runs)")
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

        status = "identical" if metrics["deterministic"] else f"{metrics['n_distinct_outputs']} variants"
        print(f"  {q['id']:<4} {q['difficulty']:<7}"
              f" determinism: {status:<12}"
              f" stability: {metrics['stability'] * 100:5.1f}%"
              f" json_correct: {metrics['json_correct_count']}/{metrics['total_reps']:<5}"
              f" intent: {metrics['intent_correct_count']}/{metrics['total_reps']:<5}"
              f" filters: {metrics['filter_correct_count']}/{metrics['total_reps']:<5}"
              f" payload: {metrics['payload_correct_count']}/{metrics['total_reps']}")
        results.append(metrics)

    return results, latencies


def main():
    #loads the config and saves the necessary parameters
    args = parse_args()
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    models = args.models or cfg["models_phase1"]
    temperature = cfg.get("temperature_phase1", 0.0)
    reps = args.repetitions or cfg.get("repetitions_latency", 30)

    #reads the questions from the jsonl (single file, filtered by --difficulty at load time)
    questions_path = Path(args.questions) if args.questions else PROJECT_ROOT / cfg["paths"]["questions"]
    with open(questions_path, encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]
    
    #takes only the questions for the specified difficulty
    if args.difficulty:
        questions = [q for q in questions if q.get("difficulty") == args.difficulty]
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"]
    results_dir = PROJECT_ROOT / cfg["paths"].get("results", "benchmark/results")

    from structured_URL_generator import prompt, parser
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
        "n_questions": len(questions), "config": cfg,
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
    writers.append_index_csv(results_dir, index_rows)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    writers.write_manifest(run_dir, manifest)

    print(" SUMMARY ")
    for row in summary_rows:
        unsafe = row.get("unsafe_action_rate")
        unsafe_str = f"{unsafe * 100:5.1f}%" if unsafe is not None else "   n/a"
        print(f"  {row['model']:<26}"
              f" intent: {row['intent_accuracy'] * 100:5.1f}% "
              f" filters: {row['exact_filter_match_rate'] * 100:5.1f}% "
              f" payload: {row['exact_payload_match_rate'] * 100:5.1f}% "
              f" unsafe: {unsafe_str} "
              f" determinism: {row['determinism_rate'] * 100:5.1f}% "
              f" stability: {row['stability'] * 100:5.1f}% "
              f" json_correct: {row['json_correct_rate'] * 100:5.1f}% "
              f" latency: median, p90 --> {row['median_latency']}s , {row['p90_latency']}s")
    print(f"\nResults written to --> {run_dir}")
    print(f"Appended to        --> {results_dir / 'index.csv'}")


if __name__ == "__main__":
    main()
