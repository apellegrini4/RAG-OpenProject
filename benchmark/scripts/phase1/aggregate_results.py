""" merges the summary.csv of the three phase 1 runs and adds fully_correct_rate
    usage example: python benchmark/scripts/aggregate_results.py
"""
from pathlib import Path
import csv
import json
import sys

HERE = Path(__file__).resolve().parent         # benchmark/scripts/phase_1/
PROJECT_ROOT = HERE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(HERE))

from metrics_phase1 import (exact_filter_match, exact_payload_match, intent_match, macro_match,
                            schema_validation)

QUESTIONS = PROJECT_ROOT / "benchmark" / "dataset" / "questions_90.jsonl"
RUNS_DIR = PROJECT_ROOT / "benchmark" / "runs" / "phase1"
OUTPUT = PROJECT_ROOT / "benchmark" / "results" / "phase1" / "total_results_phase1.csv"

#the three runs of the final TEST_DIR, prompt v2-verbose
TEST_DIR = {
    "easy": "20260802-064112__phase1__easy",
    "medium": "20260802-152547__phase1__medium",
    "hard": "20260803-023127__phase1__hard",
}

def folder_to_model(folder: str) -> str:
    return folder.replace("_", ":", 1)


def fully_correct(parsed, real: dict) -> bool:
    """ a cell counts only if the schema and all four fields are right at the same time """
    return (schema_validation(parsed)
            and intent_match(parsed, real)
            and macro_match(parsed, real)
            and exact_filter_match(parsed, real)
            and exact_payload_match(parsed, real))


def fully_correct_rate(level: str, model_folder: str, real_by_id: dict) -> float:
    """ fraction of (question x repetition) cells that are correct on every field """
    path = RUNS_DIR / TEST_DIR[level] / "models" / model_folder / "answers.jsonl"
    correct = cells = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        correct += fully_correct(row["parsed"], real_by_id[row["question_id"]])
        cells += 1
    return round(correct / cells, 3) if cells else 0.0


def model_folders(level: str) -> list:
    """ the model folders of a run, in the order the summary.csv lists them """
    return sorted((RUNS_DIR / TEST_DIR[level] / "models").iterdir(), key=lambda p: p.name)


def main() -> int:
    real_by_id = {}
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            real_by_id[q["id"]] = q

    rows = []
    for level in TEST_DIR:
        folders = {folder_to_model(p.name): p.name for p in model_folders(level)}
        summary = RUNS_DIR / TEST_DIR[level] / "summary.csv"
        with summary.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append({
                    "difficulty": level,
                    **row,
                    "fully_correct_rate": fully_correct_rate(level, folders[row["model"]], real_by_id),
                })

    fieldnames = list(rows[0].keys())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        previous = None
        for row in rows:
            if previous and row["difficulty"] != previous:
                f.write("\n")
            writer.writerow(row)
            previous = row["difficulty"]


    print(f"\nWritten to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
