""" merges the three scored phase-2 runs (easy, medium, hard) into a summary of the whole dataset

usage:
    python benchmark/scripts/phase_2/aggregate_phase2.py
    python benchmark/scripts/phase_2/aggregate_phase2.py --easy 20260809-200156__phase2__easy
"""
from pathlib import Path
import argparse
import csv
import json
import sys

import yaml

HERE = Path(__file__).resolve().parent          # benchmark/scripts/phase_2/
SCRIPTS_DIR = HERE.parent
PROJECT_ROOT = HERE.parents[2]
for path in (PROJECT_ROOT, SCRIPTS_DIR, HERE):
    sys.path.insert(0, str(path))

from metrics_phase2 import INTENTS, QUALITY_METRICS, quality_metrics, summarize
from writers import validate_name

CONFIG_PATH = PROJECT_ROOT / "benchmark" / "config.yaml"

LEVELS = ["easy", "medium", "hard"]

TEST_DIR = {"easy": None, "medium": None, "hard": None}


def parse_args():
    ap = argparse.ArgumentParser(description="merge the three phase-2 runs")
    for level in LEVELS:
        ap.add_argument(f"--{level}", default=None, help=f"run to use as the {level} level")
    return ap.parse_args()


def resolve_run(level: str, runs_dir: Path, override) -> Path:
    """ the run of a level: the one named on the command line, the one pinned in TEST_DIR,
    or the most recent one carrying that suffix """
    name = override or TEST_DIR.get(level)
    if name:
        return runs_dir / name

    found = sorted(p for p in runs_dir.iterdir()
                   if p.is_dir() and p.name.endswith(f"__{level}"))
    if not found:
        raise FileNotFoundError(f"no run labelled '{level}' in {runs_dir}")
    #run names start with the timestamp, so the last one is the newest
    return found[-1]


def load_cells(run_dir: Path, model: str) -> list:
    """ the scored cells of one model in one run """
    path = run_dir / "models" / validate_name(model) / "scores.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist: score the run first "
            f"(python benchmark/scripts/phase_2/evaluate_phase2.py --run {run_dir.name})")

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def collect(runs_dir: Path, models: list, overrides: dict) -> tuple:
    """ {(level, model): cells} and the run each level came from """
    cells, used = {}, {}
    for level in LEVELS:
        run_dir = resolve_run(level, runs_dir, overrides.get(level))
        used[level] = run_dir.name
        for model in models:
            cells[(level, model)] = load_cells(run_dir, model)
    return cells, used


def total_rows(cells: dict, models: list) -> list:
    """ one row per level and model, then one row per model over the three levels """
    rows = []
    for level in LEVELS:
        for model in models:
            rows.append({"difficulty": level, **summarize(model, cells[(level, model)])})

    for model in models:
        pooled = [c for level in LEVELS for c in cells[(level, model)]]
        rows.append({"difficulty": "all", **summarize(model, pooled)})
    return rows


def write_total(rows: list, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()

        previous = None
        for row in rows:
            #insert a blank line between different difficulty level 
            if previous and row["difficulty"] != previous:
                f.write("\n")
            writer.writerow(row)
            previous = row["difficulty"]


def write_by_intent(cells: dict, models: list, output: Path) -> None:
    """ the metrics per intent, over the whole dataset: one block per intent """
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        for intent in INTENTS:
            writer.writerow([intent])
            writer.writerow(["model", "cells"] + QUALITY_METRICS)

            for model in models:
                subset = [c for level in LEVELS for c in cells[(level, model)]
                          if c["category"] == intent]
                if not subset:
                    continue

                rates = quality_metrics(subset)
                writer.writerow([model, len(subset)]
                                + ["" if rates[m] is None else rates[m] for m in QUALITY_METRICS])

            writer.writerow([])


def main() -> int:
    args = parse_args()
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    models = cfg["models_phase2"]
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"] / "phase2"
    results_dir = PROJECT_ROOT / cfg["paths"]["results"] / "phase2"

    cells, used = collect(runs_dir, models, {level: getattr(args, level) for level in LEVELS})
    for level, run_name in used.items():
        print(f"  {level:<7} {run_name}")

    total = total_rows(cells, models)
    print(f"\n{sum(len(c) for c in cells.values())} cells, "
          f"{total[-1]['cells']} per model over the three levels\n")

    total_path = results_dir / "total_results_phase2.csv"
    intent_path = results_dir / "split_by_intent_phase2.csv"
    write_total(total, total_path)
    write_by_intent(cells, models, intent_path)

    print(f"Written to --> {total_path}")
    print(f"Written to --> {intent_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
