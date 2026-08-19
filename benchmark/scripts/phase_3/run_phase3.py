""" phase-3 runner
the whole system against the real OpenProject instance and a gate between the two models (the second model is invoked only when the first did not fail)

Writes are never committed, create and update stop at the /form validation, as the API does.
This is because otherwise data would move during the campaign, and the read questions would find something different at the last repetition

The test is done with one user with full permissions

usage example:
    python benchmark/scripts/phase_3/run_phase3.py --repetitions 1 --label smoke --limit 3
    python benchmark/scripts/phase_3/run_phase3.py --label campagna
    python benchmark/scripts/phase_3/run_phase3.py --difficulty easy --label campagna_easy
    # then, if it was interrupted or to merge:
    python benchmark/scripts/phase_3/aggregate_phase3.py --run <run_name>
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import time
import traceback

import yaml

HERE = Path(__file__).resolve().parent          # benchmark/scripts/phase_3/
SCRIPTS_DIR = HERE.parent
PROJECT_ROOT = SCRIPTS_DIR.parents[1]
for p in (PROJECT_ROOT, SCRIPTS_DIR, HERE, SCRIPTS_DIR / "phase_1", SCRIPTS_DIR / "phase_2"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import writers                                                          
from accounts import api_key_for                                        
from aggregate_phase3 import write_outputs, write_results               
from api import (                                                       
    execute, pagination_warning, phase2_context, refusal_answer, write_notice,
)
from gate import check_gate, extraction_ok                              
from metrics_phase1 import (                                            
    exact_filter_match, exact_payload_match, intent_match, macro_match, schema_validation,
    write_intent,
)
from llm_builder import CONFIG_PATH                                     
from metrics_phase3 import (                                            
    aggregate, canonical_answer, effective_category, latency_summary, reference_from_result,
    score_stage2,
)
from response_generator import define_response_chain                    
from structured_URL_generator import define_urlConstructor_chain, parser  

#choosen models
MODEL_PHASE1 = "qwen2.5-coder:1.5b"
MODEL_PHASE2 = "gemma3:4b"

CAMPAIGN_USER = "alba.pellegrini"


def parse_args():
    ap = argparse.ArgumentParser(description="Phase-3, the campaign end-to-end")
    ap.add_argument("--repetitions", type=int, default=None,
                    help="repetitions per question (default: config.repetitions_phase3)")
    ap.add_argument("--label", default="demo")
    ap.add_argument("--questions", default=None,
                    help="override paths.questions from config.yaml")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N questions: for the smoke test")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"], default=None)
    ap.add_argument("--only", default=None, help="only these questions, comma separated")
    ap.add_argument("--model-phase1", default=MODEL_PHASE1)
    ap.add_argument("--model-phase2", default=MODEL_PHASE2)
    ap.add_argument("--user", default=CAMPAIGN_USER)
    ap.add_argument("--no-cosine", action="store_true",
                    help="skip the cosine similarity: does not load the embedding model")
    ap.add_argument("--no-index", action="store_true",
                    help="do not append to results/phase3/index.csv: for smoke and trial runs")
    return ap.parse_args()


def relative_date_questions(questions):
    """ the questions whose filters OpenProject resolves against the current day """
    return [q["id"] for q in questions
            for values in (q.get("filters") or {}).values()
            if any(str(v) in ("today", "this week")
                   for v in (values if isinstance(values, list) else [values]))]


def load_questions(cfg, args):
    path = Path(args.questions) if args.questions else PROJECT_ROOT / cfg["paths"]["questions"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in wanted]
    if args.difficulty:
        rows = [r for r in rows if r["difficulty"] == args.difficulty]
    if args.limit:
        rows = rows[:args.limit]
    return path, rows


def load_embedder(disabled):
    """ same embedder as phase 2 """
    if disabled:
        return None, "disabled by --no-cosine"
    try:
        from embedder import EMBEDDING_MODEL, CachedEmbedder, get_embedder
        return CachedEmbedder(get_embedder()), EMBEDDING_MODEL
    except Exception as e:
        return None, f"not available ({e})"


def jsonable(value):
    """ anything that does not survive json.dumps is stored as its text, 
    to avoid losing the whole cells.jsonl at write time in case of an unexpected value """
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def run_cell(question, repetition, chain1, chain2, format_instructions, username, api_key,
             embedder=None):
    """ one question, one repetition: extraction, gate, execution, answer, score """
    cell = {
        "question_id": question["id"], "repetition": repetition,
        "difficulty": question["difficulty"], "intent": question["intent"],
        "macro_section": question["macro_section"],
        "t_phase1": None, "t_openproject": None, "t_phase2": None,
        "run_date": datetime.now().date().isoformat(),
        "error": None,
    }

    try:
        mark = time.perf_counter()
        extraction = chain1.invoke({"format_instructions": format_instructions,
                                    "user_query": question["text"]})
        cell["t_phase1"] = round(time.perf_counter() - mark, 2)
    except Exception as e:
        cell["error"] = f"phase1: {e}"
        cell.update({"stage1_ok": False, "block_reason": "phase1_exception",
                     "stage2_invoked": False, "stage2_perfect": False})
        return cell

    cell["extraction"] = {k: v for k, v in extraction.items() if k != "reasoning"} \
        if isinstance(extraction, dict) else extraction
    cell.update(stage1_metrics(extraction, question))

    #a wrong extraction is already wrong without touching OpenProject
    ok, reason = extraction_ok(extraction, question)
    final_data = None
    if ok:
        try:
            mark = time.perf_counter()
            final_data = execute(extraction, username, api_key)
            cell["t_openproject"] = round(time.perf_counter() - mark, 2)
        except Exception as e:
            cell["error"] = f"execute: {e}"

    #the OpenProject answer is kept in the cell, in this way the run can be scored again later
    cell["openproject_result"] = jsonable(final_data)
    cell["total_results"] = final_data.get("total_results") if isinstance(final_data, dict) else None
    cell["results_in_page"] = final_data.get("number_of_results_in_the_page") \
        if isinstance(final_data, dict) else None

    verdict = check_gate(extraction, question, final_data)
    cell.update(verdict)
    cell["result_kind"] = result_kind(final_data)

    if not verdict["stage2_invoked"]:
        cell["stage2_perfect"] = False
        return cell

    #a permission refusal is worded by the system and not by the model
    refusal = refusal_answer(final_data)
    if refusal is not None:
        cell.update({"answer": refusal, "answer_model": None, "answer_generated": False,
                     "stage2_perfect": True, "response_type_reason": "deterministic_refusal"})
        return cell

    notice = write_notice(extraction, final_data) \
        if isinstance(final_data, dict) and final_data.get("ready_to_commit") else None

    context = phase2_context(extraction, final_data)
    cell["phase2_context"] = context

    try:
        mark = time.perf_counter()
        answer_model = chain2.invoke({"json": context, "user_query": question["text"]})
        cell["t_phase2"] = round(time.perf_counter() - mark, 2)
    except Exception as e:
        cell["error"] = f"phase2: {e}"
        cell["stage2_perfect"] = False
        return cell

    #the truncation notice is appended here
    warning = pagination_warning(final_data)
    answer = f"{answer_model.rstrip()} {warning}" if warning else answer_model

    #the reference comes from the same result the model saw
    key_values = reference_from_result(final_data, notice)
    ideal = canonical_answer(final_data, notice, question["macro_section"])
    cell.update(score_stage2(answer, key_values, effective_category(question, final_data),
                             ideal_answer=ideal, embedder=embedder))
    cell["answer"] = answer
    cell["answer_model"] = answer_model
    cell["pagination_warning"] = warning
    cell["answer_generated"] = True
    cell["reference"] = key_values
    cell["ideal_answer"] = ideal
    return cell


def stage1_metrics(extraction, question):
    """ the extraction metrics from the same functions phase 1 uses """
    valid = schema_validation(extraction)
    expected_read = (question.get("intent") or "read") == "read"

    return {
        "json_correct": valid,
        "intent_correct": valid and intent_match(extraction, question),
        "macro_correct": valid and macro_match(extraction, question),
        "filter_correct": valid and exact_filter_match(extraction, question),
        "payload_correct": valid and exact_payload_match(extraction, question),
        "unsafe_action": (valid and write_intent(extraction.get("intent"))) if expected_read else None, #a read-only question the model turned into a write: only defined where a read was expected
    }


def result_kind(final_data):
    """ what shape execute() returned, so the results can be read without reopening every cell """
    if final_data is None:
        return "not_executed"
    if isinstance(final_data, str):
        return "system_info"
    if isinstance(final_data, dict):
        if final_data.get("ready_to_commit"):
            return "write_validated"
        if set(final_data) == {"error_message"}:
            return "read_error"
        return "read"
    return "unknown"


def print_summary(summary):
    """ the two models printed apart, the way their evaluation is apart """
    def line(label, value, width=32):
        print(f"  {label:<{width}} {value}")

    print("\n" + "=" * 78)
    print(f"MODEL 1 -- {summary['phase1']['model']}   (parameter extraction)")
    print(f"denominator: all {summary['cells']} cells -- the first model always runs")
    print("-" * 78)
    for key, value in summary["phase1"]["overall"].items():
        line(key, value)
    print("\n  by level:")
    for level, metrics in summary["phase1"]["by_difficulty"].items():
        print(f"    {level:<8} extraction correct {metrics['extraction_fully_correct']}   "
              f"intent {metrics['intent_accuracy']}   filters {metrics['exact_filter_match']}")

    p2 = summary["phase2"]
    print("\n" + "=" * 78)
    print(f"MODEL 2 -- {p2['model']}   (answer generation)")
    print(f"denominator: the {p2['overall']['cells_generated']} cells where it was really invoked")
    print("-" * 78)
    for key, value in p2["overall"].items():
        line(key, value)
    print("\n  by level:")
    for level, metrics in p2["by_difficulty"].items():
        print(f"    {level:<8} perfect answers {metrics['stage2_perfect_rate']}   "
              f"cosine {metrics['avg_cosine_similarity']}   coverage {metrics['avg_value_coverage']}")

    print("\n" + "=" * 78)
    print("THE SYSTEM -- the two together")
    print("-" * 78)
    for key, value in summary["cascade"]["overall"].items():
        line(key, value)

    #the repetitions are not independent observations: the *_by_question rates are the ones to
    #quote as rates over items
    print("\n" + "=" * 78)
    print("PER QUESTION -- what the repetitions bought")
    print("-" * 78)
    for key, value in summary["stability"].items():
        line(key, value)
    print("=" * 78)


def main():
    args = parse_args()
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    #a phase-3 cell costs two models plus the network, so it has its own number of repetitions
    reps = args.repetitions or cfg.get("repetitions_phase3") or cfg["repetitions"]

    questions_path, questions = load_questions(cfg, args)
    api_key = api_key_for(args.user)
    if not api_key:
        print(f"no key for '{args.user}' in .env, stopping here.")
        return 1

    embedder, embedding_note = load_embedder(args.no_cosine)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_name = f"{timestamp}__phase3__{args.label}"
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"]
    run_dir = writers.create_run_dir(runs_dir, run_name)
    out_dir = writers.model_dir(run_dir, f"{args.model_phase1}__{args.model_phase2}")

    manifest = {
        "phase": "phase3", "label": args.label, "run_name": run_name,
        "model_phase1": args.model_phase1, "model_phase2": args.model_phase2,
        "user": args.user, "repetitions": reps,
        "questions_file": str(questions_path.relative_to(PROJECT_ROOT)),
        "questions": len(questions),
        "writes_committed": False,
        "embedding_model": embedding_note,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "seed": cfg.get("seed"),
        "temperature_phase1": cfg.get("temperature_phase1"),
        "temperature_phase2": cfg.get("temperature_phase2"),
    }
    writers.write_manifest(run_dir, manifest)

    print(f"run: {run_name}")
    print(f"{len(questions)} questions x {reps} repetitions = {len(questions) * reps} cells")
    print(f"models: {args.model_phase1} -> {args.model_phase2}   user: {args.user}")
    print(f"cosine similarity: {embedding_note}")
    print("writes are NOT committed: they stop at the /form validation\n")

    chain1 = define_urlConstructor_chain(args.model_phase1)
    chain2 = define_response_chain(args.model_phase2)
    format_instructions = parser.get_format_instructions()

    cells = []
    for question in questions:
        question_cells = []
        for repetition in range(1, reps + 1):
            try:
                cell = run_cell(question, repetition, chain1, chain2, format_instructions,
                                args.user, api_key, embedder)
            except Exception:
                cell = {"question_id": question["id"], "repetition": repetition,
                        "difficulty": question["difficulty"], "intent": question["intent"],
                        "macro_section": question["macro_section"],
                        "error": traceback.format_exc(limit=3),
                        "stage1_ok": False, "stage2_invoked": False, "stage2_perfect": False}
            question_cells.append(cell)

        writers.append_jsonl(out_dir / "cells.jsonl", question_cells)
        cells.extend(question_cells)

        passed = sum(1 for c in question_cells if c.get("stage1_ok"))
        done = sum(1 for c in question_cells if c.get("stage2_perfect"))
        print(f"  {question['id']:<5} {question['difficulty']:<7} {question['intent']:<7} "
              f"gate {passed}/{reps}   end-to-end {done}/{reps}")

    summary = aggregate(cells, args.model_phase1, args.model_phase2)
    summary["latency"] = latency_summary(cells)
    write_outputs(run_dir, out_dir, run_name, summary)
    if not args.no_index:
        write_results(PROJECT_ROOT / cfg["paths"]["results"] / "phase3", run_name, summary, "as_run")

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    writers.write_manifest(run_dir, manifest)

    #a run that spans two days has answered the relative-date questions against two different
    #"today", while their reference was built once: the cells say so instead of hiding it
    dates = sorted({c.get("run_date") for c in cells if c.get("run_date")})
    manifest["run_dates"] = dates
    relative = relative_date_questions(questions)
    if len(dates) > 1 and relative:
        print(f"\n  WARNING: the run spans {dates}, and {sorted(set(relative))} filter on "
              "'today' or 'this week'. Their reference was built for one day only: check those "
              "questions before quoting them.")

    print_summary(summary)
    print("  --- timings (median / mean, seconds) ---")
    for stage in ("t_phase1", "t_openproject", "t_phase2"):
        print(f"  {stage:<28} {summary['latency'][f'{stage}_median']} / "
              f"{summary['latency'][f'{stage}_mean']}   over "
              f"{summary['latency'][f'{stage}_cells']} cells")
    print("=" * 78)
    print(f"results in {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
