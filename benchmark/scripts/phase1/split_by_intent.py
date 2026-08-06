""" splits the phase 1 results by difficulty level and by intent,
    read / create / update / out_of_scope are divided like this: 9+9+9+3 questions per level,
    the class of a question is the class given by the dataset, not the model

    usage example: python benchmark/scripts/phase_1/split_by_intent.py
"""
from pathlib import Path
import csv
import json
import sys
import yaml

HERE = Path(__file__).resolve().parent         # benchmark/scripts/phase_1/
SCRIPTS_DIR = HERE.parent
PROJECT_ROOT = HERE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(HERE))

from metrics_phase1 import (exact_filter_match, exact_payload_match, intent_match, macro_match,
                            schema_validation, write_intent)
from aggregate_results import TEST_DIR
from writers import validate_name

CONFIG_PATH = PROJECT_ROOT / "benchmark" / "config.yaml"
QUESTIONS = PROJECT_ROOT / "benchmark" / "dataset" / "questions_90.jsonl"
RUNS_DIR = PROJECT_ROOT / "benchmark" / "runs" / "phase1"
OUTPUT = PROJECT_ROOT / "benchmark" / "results" / "phase1" / "split_by_intent_phase1.csv"

LEVELS = ["easy", "medium", "hard"]
INTENTS = ["read", "create", "update", "out_of_scope"]

METRICS = ["fully_correct_rate", "json_correct_rate", "intent_accuracy",
           "macro_section_accuracy", "exact_filter_match_rate", "exact_payload_match_rate",
           "unsafe_action_rate"]

READ_INTENTS = ["read", "out_of_scope"]


def question_class(q: dict) -> str:
    return "out_of_scope" if q["macro_section"] == "out_of_scope" else q["intent"]


def score(parsed, real: dict) -> dict:
    #if the schema is not valid every metric is 0
    if not schema_validation(parsed):
        return {m: False for m in METRICS}

    ok_intent = intent_match(parsed, real)
    ok_macro = macro_match(parsed, real)
    ok_filters = exact_filter_match(parsed, real)
    ok_payload = exact_payload_match(parsed, real)

    return {
        "fully_correct_rate": ok_intent and ok_macro and ok_filters and ok_payload,
        "json_correct_rate": True,
        "intent_accuracy": ok_intent,
        "macro_section_accuracy": ok_macro,
        "exact_filter_match_rate": ok_filters,
        "exact_payload_match_rate": ok_payload,
        "unsafe_action_rate": real["intent"] == "read" and write_intent(parsed.get("intent")),
    }


def collect(real_by_id: dict, models: list) -> dict:
    results = {}

    for level in LEVELS:
        for model in models:
            answers = RUNS_DIR / TEST_DIR[level] / "models" / validate_name(model) / "answers.jsonl"

            #an empty dictionary with a list for every intent
            scored = {intent: [] for intent in INTENTS}

            for line in answers.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                    
                row = json.loads(line)
                #gets the real answer dict from the dict filtering by the corrisponding id
                real = real_by_id[row["question_id"]]
                #calculates the metrics for every intent
                scored[question_class(real)].append(score(row["parsed"], real))

            for intent, cells in scored.items():
                if cells:
                    #cells is a list of dicts, each one of them is returned by the function score
                    results[(level, intent, model)] = {
                        #calulates the mean for every metric
                        m: round(sum(c[m] for c in cells) / len(cells), 3) for m in METRICS}

    return results


def write_csv(results: dict, models: list) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for level in LEVELS:
            for intent in INTENTS:
                #reports the metrics for every combo: level, intent
                writer.writerow([level, intent])
                writer.writerow(["model"] + METRICS)

                for model in models:
                    rates = results.get((level, intent, model))
                    if rates is None:
                        continue

                    #writes the value of unsafe_action_rate only if the original intent was of type read
                    writer.writerow([model] + [
                        rates[m] if m != "unsafe_action_rate" or intent in READ_INTENTS else ""
                        for m in METRICS])

                writer.writerow([])


def main() -> int:
    real_by_id = {}
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            #saves every row of the file 'questions_90' by id
            real_by_id[q["id"]] = q

    with CONFIG_PATH.open(encoding="utf-8") as f:
        models = yaml.safe_load(f)["models_phase1"]

    #calculates the metrics
    results = collect(real_by_id, models)

    write_csv(results, models)
    print(f"\nWritten to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
