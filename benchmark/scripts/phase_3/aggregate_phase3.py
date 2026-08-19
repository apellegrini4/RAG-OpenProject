""" phase-3 aggregation, separate from the run so a campaign can be summarised again without being
executed again. It also merges runs, and re-scores a finished run against corrected metrics, using the OpenProject
answer every cell carries.

usage:
    python benchmark/scripts/phase_3/aggregate_phase3.py --run 20260816-091500__phase3__campagna
    python benchmark/scripts/phase_3/aggregate_phase3.py --run runA,runB,runC --into campagna_full
    python benchmark/scripts/phase_3/aggregate_phase3.py --run <run> --rescore
"""
from pathlib import Path
import argparse
import json
import sys

import yaml

HERE = Path(__file__).resolve().parent          # benchmark/scripts/phase_3/
SCRIPTS_DIR = HERE.parent
PROJECT_ROOT = SCRIPTS_DIR.parents[1]
for p in (PROJECT_ROOT, SCRIPTS_DIR, HERE, SCRIPTS_DIR / "phase_1", SCRIPTS_DIR / "phase_2"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import writers
from metrics_phase3 import (
    aggregate, canonical_answer, effective_category, flat_rows, latency_summary,
    reference_from_result, score_stage2,
)

CONFIG_PATH = PROJECT_ROOT / "benchmark" / "config.yaml"

TITLES = {
    "phase1": "Model 1 — {model} — parameter extraction",
    "phase2": "Model 2 — {model} — answer generation",
    "cascade": "The system — the two models together",
}

NOTES = {
    "phase1": "Denominator: **every** cell. The first model always runs.",
    "phase2": "Denominator: the cells where the second model was **really invoked**, minus the "
              "answers the system wrote itself.",
    "cascade": "`end_to_end_success` divides by the evaluated cells, `system_success_all_cells` "
               "by all of them: they are read together.",
}

#what a cell needs for a re-score: the answer OpenProject gave, and the extraction that asked for it
RESCORABLE = ("openproject_result", "extraction")


def parse_args():
    ap = argparse.ArgumentParser(description="Phase-3, aggregation from cells.jsonl")
    ap.add_argument("--run", required=True,
                    help="run name under benchmark/runs, comma separated to merge more than one")
    ap.add_argument("--into", default=None,
                    help="name of the merged run: required when --run lists more than one")
    ap.add_argument("--rescore", action="store_true",
                    help="recompute the answer scores from the stored OpenProject result")
    ap.add_argument("--no-cosine", action="store_true",
                    help="while re-scoring, skip the cosine similarity")
    ap.add_argument("--no-index", action="store_true",
                    help="do not append a row to results/phase3/index.csv")
    return ap.parse_args()


def find_cells(run_dir: Path) -> Path:
    """ the cells file of a run """
    candidates = sorted((run_dir / "models").glob("*/cells.jsonl"))
    if not candidates:
        raise FileNotFoundError(f"no models/*/cells.jsonl under {run_dir}")
    if len(candidates) > 1:
        raise FileNotFoundError(f"more than one cells.jsonl under {run_dir}: {candidates}")
    return candidates[0]


def load_cells(run_dir: Path) -> list:
    """ every cell of a run. A truncated last line is dropped and reported """
    path = find_cells(run_dir)
    cells, broken = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            cells.append(json.loads(line))
        except json.JSONDecodeError:
            broken += 1
    if broken:
        print(f"  {path.name}: {broken} unreadable row(s) skipped (interrupted run?)")
    return cells


def models_of(run_dir: Path) -> tuple:
    """ the two model names, from the manifest, falling back to the folder name """
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("model_phase1"):
            return manifest["model_phase1"], manifest.get("model_phase2", "?")
    name = find_cells(run_dir).parent.name
    return tuple(name.split("__")) if "__" in name else (name, "?")


#re-scoring

def load_embedder(disabled):
    """ the phase-2 embedder, or None with the reason why """
    if disabled:
        return None, "disabled by --no-cosine"
    try:
        from embedder import EMBEDDING_MODEL, CachedEmbedder, get_embedder
        return CachedEmbedder(get_embedder()), EMBEDDING_MODEL
    except Exception as e:
        return None, f"not available ({e})"


def rescore(cells, embedder):
    """ recompute reference, ideal answer and scores of every answered cell, from the OpenProject
    result it carries. The generated answers are never touched, only the judgement on them """
    from api import write_notice

    rescored, skipped = [], 0
    for cell in cells:
        cell = dict(cell)
        if not cell.get("answer_generated") or any(k not in cell for k in RESCORABLE):
            if cell.get("answer_generated"):
                skipped += 1
            rescored.append(cell)
            continue

        final_data = cell["openproject_result"]
        notice = write_notice(cell["extraction"], final_data) \
            if isinstance(final_data, dict) and final_data.get("ready_to_commit") else None

        key_values = reference_from_result(final_data, notice)
        ideal = canonical_answer(final_data, notice, cell.get("macro_section"))
        category = effective_category(
            {"intent": cell.get("intent"), "macro_section": cell.get("macro_section")}, final_data)

        cell.update(score_stage2(cell.get("answer"), key_values, category,
                                 ideal_answer=ideal, embedder=embedder))
        cell["reference"] = key_values
        cell["ideal_answer"] = ideal
        rescored.append(cell)

    if skipped:
        print(f"  {skipped} answered cell(s) had no stored OpenProject result: left as they were")
    return rescored


#the outputs of a run

def table(rows):
    rows = [r for r in rows if r]
    if not rows:
        return ["_no cells._", ""]
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    out.append("")
    return out


def write_report(run_dir, run_name, summary):
    """ three tables and not one because the three blocks have different columns """
    lines = [f"# {run_name}", ""]
    for stage in ("phase1", "phase2", "cascade"):
        model = summary[stage].get("model", "")
        lines += [f"## {TITLES[stage].format(model=model)}", "", NOTES[stage], ""]
        lines += table(flat_rows(summary, stage))

    lines += ["## Per question — the repetitions", "",
              "The cells are not independent: every question is repeated, so the rates above weigh "
              "a question as many times as it was run. These divide by question.", ""]
    lines += table([summary.get("stability", {})])

    (Path(run_dir) / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(run_dir, out_dir, run_name, summary):
    """ everything a run leaves behind besides cells.jsonl """
    writers.write_performance(out_dir, summary)
    for stage in ("phase1", "phase2", "cascade"):
        writers.write_summary_csv(run_dir, flat_rows(summary, stage), f"summary_{stage}.csv")
    writers.write_summary_csv(run_dir, summary.get("by_question", []), "summary_by_question.csv")
    write_report(run_dir, run_name, summary)


# --- the outputs that outlive a run -----------------------------------------------------------------

def index_row(run_name, summary, scored):
    """ one flat row per run for the append-only index """
    p1, p2 = summary["phase1"]["overall"], summary["phase2"]["overall"]
    casc, stab = summary["cascade"]["overall"], summary.get("stability", {})
    lat = summary.get("latency", {})
    return {
        "run_name": run_name,
        "model_phase1": summary["phase1"]["model"], "model_phase2": summary["phase2"]["model"],
        "scored": scored,
        "cells": summary["cells"], "questions": stab.get("questions"),
        "repetitions": stab.get("repetitions"),
        "json_correct_rate": p1["json_correct_rate"],
        "intent_accuracy": p1["intent_accuracy"],
        "exact_filter_match": p1["exact_filter_match"],
        "exact_payload_match": p1["exact_payload_match"],
        "extraction_fully_correct": p1["extraction_fully_correct"],
        "unsafe_action_rate": p1["unsafe_action_rate"],
        "gate_pass_rate": casc["gate_pass_rate"], "cells_evaluated": casc["cells_evaluated"],
        "stage2_perfect_rate": p2["stage2_perfect_rate"],
        "avg_cosine_similarity": p2["avg_cosine_similarity"],
        "avg_value_coverage": p2["avg_value_coverage"],
        "full_coverage_rate": p2["full_coverage_rate"],
        "avg_item_consistency": p2["avg_item_consistency"],
        "response_type_accuracy": p2["response_type_accuracy"],
        "truncated_reads": p2["truncated_reads"],
        "end_to_end_success": casc["end_to_end_success"],
        "system_success_all_cells": casc["system_success_all_cells"],
        "errors": casc["errors"],
        "extraction_determinism_rate": stab.get("extraction_determinism_rate"),
        "extraction_stability": stab.get("extraction_stability"),
        "answer_determinism_rate": stab.get("answer_determinism_rate"),
        "answer_stability": stab.get("answer_stability"),
        "gate_pass_rate_by_question": stab.get("gate_pass_rate_by_question"),
        "stage2_perfect_rate_by_question": stab.get("stage2_perfect_rate_by_question"),
        "t_phase1_median": lat.get("t_phase1_median"),
        "t_openproject_median": lat.get("t_openproject_median"),
        "t_phase2_median": lat.get("t_phase2_median"),
    }


def long(run_name, stage, cut, slice_name, metrics):
    return [{"run_name": run_name, "stage": stage, "cut": cut, "slice": slice_name,
             "metric": key, "value": value} for key, value in metrics.items()]


def write_results(results_dir, run_name, summary, scored):
    """ the three files that outlive a run: the append-only index, the headline numbers and the cuts """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    writers.append_index_csv(results_dir, [index_row(run_name, summary, scored)])

    totals = []
    for stage in ("phase1", "phase2", "cascade"):
        totals += long(run_name, stage, "overall", "all", summary[stage]["overall"])
    totals += long(run_name, "stability", "by_question", "all", summary.get("stability", {}))
    writers.write_summary_csv(results_dir, totals, "total_results_phase3.csv")

    cuts = []
    for stage in ("phase1", "phase2", "cascade"):
        for cut in ("by_difficulty", "by_intent", "by_macro_section"):
            for slice_name, metrics in summary[stage][cut].items():
                cuts += long(run_name, stage, cut, slice_name, metrics)
    writers.write_summary_csv(results_dir, cuts, "split_by_intent_phase3.csv")
    print(f"  results in {results_dir}")


def main():
    args = parse_args()
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"]

    names = [n.strip() for n in args.run.split(",") if n.strip()]
    if len(names) > 1 and not args.into:
        print("more than one run: --into <name> is needed to say where the merge goes")
        return 1

    cells, model1, model2 = [], None, None
    for name in names:
        run_dir = runs_dir / name
        if not run_dir.is_dir():
            print(f"run not found: {run_dir}")
            return 1
        rows = load_cells(run_dir)
        print(f"  {name}: {len(rows)} cells")
        cells.extend(rows)
        model1, model2 = models_of(run_dir)

    if not cells:
        print("no cells to aggregate.")
        return 1

    scored = "as_run"
    if args.rescore:
        embedder, note = load_embedder(args.no_cosine)
        print(f"  re-scoring, cosine similarity: {note}")
        cells = rescore(cells, embedder)
        scored = "rescored"

    #a merge writes into a new run directory, so the runs it came from stay as they are
    if len(names) > 1:
        target = writers.create_run_dir(runs_dir, args.into)
        out_dir = writers.model_dir(target, f"{model1}__{model2}")
        writers.append_jsonl(out_dir / "cells.jsonl", cells)
        writers.write_manifest(target, {"phase": "phase3", "run_name": args.into,
                                        "merged_from": names, "model_phase1": model1,
                                        "model_phase2": model2, "cells": len(cells),
                                        "scored": scored, "writes_committed": False})
        run_name = args.into
    else:
        target = runs_dir / names[0]
        out_dir = find_cells(target).parent
        run_name = names[0]

    #a re-score never overwrites cells.jsonl: the raw run has to stay exactly as it came out
    if args.rescore and len(names) == 1:
        writers.append_jsonl(out_dir / "cells_rescored.jsonl", cells)
        print(f"  re-scored cells in {out_dir / 'cells_rescored.jsonl'}")

    summary = aggregate(cells, model1, model2)
    summary["latency"] = latency_summary(cells)
    write_outputs(target, out_dir, run_name, summary)
    if not args.no_index:
        write_results(PROJECT_ROOT / cfg["paths"]["results"] / "phase3",
                      run_name + ("__rescored" if args.rescore else ""), summary, scored)

    print(f"\n{len(cells)} cells, {summary['stability'].get('questions')} questions")
    print(f"gate_pass_rate           {summary['cascade']['overall']['gate_pass_rate']}")
    print(f"end_to_end_success       {summary['cascade']['overall']['end_to_end_success']}")
    print(f"system_success_all_cells {summary['cascade']['overall']['system_success_all_cells']}")
    print(f"results in {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
