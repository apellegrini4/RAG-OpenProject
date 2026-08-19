#!/usr/bin/env python3
""" validates the dataset used for the benchmark

checks if:
- each line of questions.jsonl is valid JSON;
- every non-null answer_id exists in paths.answers (the file of ideal answers)
- la macro_section sia una tra {projects, work_packages, out_of_scope}
- l'intent is a read, a create or an update
- the keys of the real filters belong to the set allowed for the macro-section (READ/UPDATE selector)
- the payload keys actually belong to the set of writable fields for the macro-section (CREATE/UPDATE)
- the filters/payload on 'startDate'/'dueDate' have a valid format

usage:
    python benchmark/scripts/validate_dataset.py
    python benchmark/scripts/validate_dataset.py benchmark/dataset/altro_file.jsonl
"""
import json
import re
import sys
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
CONFIG_PATH = PROJECT_ROOT / "benchmark" / "config.yaml"


with CONFIG_PATH.open(encoding="utf-8") as f:
    _cfg = yaml.safe_load(f)

QUESTIONS = (Path(sys.argv[1]) if len(sys.argv) > 1
             else PROJECT_ROOT / _cfg["paths"]["questions"])
ANSWERS = PROJECT_ROOT / _cfg["paths"]["answers"]
MOCK_DIR = PROJECT_ROOT / _cfg["paths"]["mock_data"]


ALLOWED_FILTERS = {
    "work_packages": {"author", "assignee", "priority", "status", "id", "subject", "type",
                      "version", "project", "percentageDone", "startDate", "dueDate"},
    "projects": {"active", "public", "name", "id"},
    "out_of_scope": set(),
}

#author and percentageDone are not writable
ALLOWED_PAYLOAD = {
    "work_packages": {"subject", "description", "startDate", "dueDate",
                      "type", "project", "priority", "status", "version", "assignee"},
    "projects": {"active", "public", "name", "description"},
    "out_of_scope": set(),
}

MACROS = set(ALLOWED_FILTERS)
INTENTS = {"read", "create", "update"}
DATE_FIELDS = {"startDate", "dueDate"}
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_date_values(qid, field, values, errors, *, writable_only):
    """ validates filter/payload form on startDate/dueDate, only single dates, intervals or today/this week are allowed"""
    if not isinstance(values, list) or not values:
        errors.append(f"{qid}: '{field}' must be a non empty list, found {values!r}")
        return

    normalized = [str(v).strip().lower() for v in values]
    keywords = {"today", "this week"}

    if any(v in keywords for v in normalized):
        if writable_only:
            errors.append(f"{qid}: '{field}' cannot use the keyword'{normalized[0]}' "
                          f"dates are always explicit")
        elif len(values) > 1:
            errors.append(f"{qid}: '{field}' with keyword must have one single value, found {values}")
        return

    if len(values) not in (1, 2):
        errors.append(f"{qid}: '{field}'must have 1 date, 2 date (interval), or 'today'/'this week' "
                      f"in filters; found {values}")
        return

    for v in normalized:
        if not ISO_DATE_RE.match(v):
            errors.append(f"{qid}: '{field}' contains '{v}' which is not a valid date, the format is: YYYY-MM-DD")


def main() -> int:
    errors = []

    answers = {}
    if ANSWERS.exists():
        for line in ANSWERS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                answers[row["answer_id"]] = row

    mocks = {p.stem for p in MOCK_DIR.glob("*.json")} if MOCK_DIR.exists() else set()
    for answer_id, row in answers.items():
        if row.get("mock_id") not in mocks:
            errors.append(f"{answer_id}: mock_id '{row.get('mock_id')}'does not have a file in {MOCK_DIR.name}/")
        if not row.get("ideal_answer"):
            errors.append(f"{answer_id}: missing 'ideal_answer'")

    questions = []
    for i, line in enumerate(QUESTIONS.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            q = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"row {i}: JSON not valid ({e})")
            continue
        questions.append(q)

        qid = q.get("id", f"row{i}")
        macro = q.get("macro_section")
        if macro not in MACROS:
            errors.append(f"{qid}: macro_section '{macro}' not allowed")
            continue

        intent = q.get("intent")
        if intent not in INTENTS:
            errors.append(f"{qid}: intent '{intent}' not allowed (must be one between {sorted(INTENTS)})")

        filters = q.get("filters", {})
        payload = q.get("payload", {})
        if not isinstance(filters, dict):
            errors.append(f"{qid}: 'filters' must be a dict, found {type(filters).__name__}")
            filters = {}
        if not isinstance(payload, dict):
            errors.append(f"{qid}: 'payload' must be un dict, found {type(payload).__name__}")
            payload = {}

        bad_filter_keys = set(filters) - ALLOWED_FILTERS[macro]
        if bad_filter_keys:
            errors.append(f"{qid}: filter keys not allowed for '{macro}': {sorted(bad_filter_keys)}")

        bad_payload_keys = set(payload) - ALLOWED_PAYLOAD[macro]
        if bad_payload_keys:
            errors.append(f"{qid}: payload keys not allowed for '{macro}': {sorted(bad_payload_keys)}")

        for field in DATE_FIELDS & set(filters):
            check_date_values(qid, field, filters[field], errors, writable_only=False)

        for field in DATE_FIELDS & set(payload):
            check_date_values(qid, field, payload[field], errors, writable_only=True)

        aid = q.get("answer_id")
        if aid is not None and answers and aid not in answers:
            errors.append(f"{qid}: answer_id '{aid}' absent in {ANSWERS.name}")

    if errors:
        print(f"Trovati {len(errors)} errors:")
        for e in errors:
            print("  -", e)
        return 1

    print(f"OK -- {len(questions)} questions loaded and validated; {len(answers)} expected ansers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
