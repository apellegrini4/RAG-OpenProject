""" Rebuilds the phase-3 ideal answers by asking the live instance, using the extraction the
    dataset declares instead of the model. Run it again whenever the world changes.

    usage example:
        python tools/regenerate_references.py --dry-run
        python tools/regenerate_references.py
"""

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3_DIR = PROJECT_ROOT / "benchmark" / "scripts" / "phase_3"
for p in (PROJECT_ROOT, PHASE3_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from accounts import api_key_for
from api import execute, write_notice
from metrics_phase3 import (
    REFERENCE_FORMAT, canonical_answer, reference_from_result,
)
from structural_validation import schema_validation

DATASET = PROJECT_ROOT / "benchmark" / "dataset"
QUESTIONS = DATASET / "questions_99.jsonl"
OUT = DATASET / "answers" / "ideal_answers_99.jsonl"

#the campaign user, with full permissions
CAMPAIGN_USER = "alba.pellegrini"


def parse_args():
    ap = argparse.ArgumentParser(description="ideal answers rebuilt from the live instance")
    ap.add_argument("--dry-run", action="store_true", help="show everything, write no file")
    ap.add_argument("--only", default=None, help="only these questions, comma separated")
    ap.add_argument("--user", default=CAMPAIGN_USER)
    return ap.parse_args()


def load_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def save_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def gold_extraction(question):
    """ the extraction the dataset declares """
    return {
        "intent": question["intent"],
        "macro_section": question["macro_section"],
        "filters": question.get("filters") or {},
        "payload": question.get("payload") or {},
    }


def result_kind(final_data):
    if isinstance(final_data, str):
        return "system_info"
    if isinstance(final_data, dict):
        if final_data.get("ready_to_commit"):
            return "write_validated"
        if set(final_data) == {"error_message"}:
            return "read_error"
        return "read"
    return "unknown"


def main():
    args = parse_args()
    api_key = api_key_for(args.user)
    if not api_key:
        print(f"no key for '{args.user}' in .env, stopping here.")
        return 1

    questions = load_jsonl(QUESTIONS)
    wanted = set(args.only.split(",")) if args.only else None
    rows, problems = [], []

    print(f"{len(questions)} questions, user {args.user}")
    print("writes stop at the /form validation: nothing is committed\n")
    print(f"{'id':<5} {'outcome':<16} {'val':<4} ideal answer")
    print("-" * 110)

    for question in questions:
        qid = question["id"]
        if wanted and qid not in wanted:
            continue

        extraction = gold_extraction(question)
        if not schema_validation(extraction):
            problems.append((qid, "the extraction the dataset declares does not pass the schema"))
            continue

        try:
            final_data = execute(extraction, args.user, api_key)
        except Exception as e:
            problems.append((qid, f"execute raised: {e}"))
            continue

        notice = write_notice(extraction, final_data) \
            if isinstance(final_data, dict) and final_data.get("ready_to_commit") else None

        key_values = reference_from_result(final_data, notice)
        ideal = canonical_answer(final_data, notice, question["macro_section"])
        kind = result_kind(final_data)

        #a read finding nothing is not an error
        if kind == "read" and not key_values:
            problems.append((qid, "read with no results: check the data is loaded"))
        if kind == "read_error":
            problems.append((qid, f"read failed: {final_data['error_message']}"))
        if kind == "system_info" and question["macro_section"] != "out_of_scope":
            problems.append((qid, f"refused by the system: {final_data}"))

        rows.append({
            "answer_id": f"answer_{qid}",
            "question_id": qid,
            "ideal_answer": ideal,
            "key_values": key_values,
            "result_kind": kind,
            "total_results": final_data.get("total_results") if isinstance(final_data, dict) else None,
            "format": REFERENCE_FORMAT,
            "source": "generated_from_instance",
        })
        print(f"{qid:<5} {kind:<16} {len(key_values):<4} {ideal[:78]}")

    if args.dry_run:
        print(f"\n--dry-run: nothing written. {len(rows)} answers ready.")
    else:
        save_jsonl(OUT, rows)
        print(f"\n{len(rows)} ideal answers written to {OUT.relative_to(PROJECT_ROOT)}")

        produced = {r["question_id"] for r in rows}
        filled = 0
        for question in questions:
            if question["id"] in produced and not question.get("answer_id"):
                question["answer_id"] = f"answer_{question['id']}"
                filled += 1
        if filled:
            save_jsonl(QUESTIONS, questions)
            print(f"answer_id assigned to {filled} questions that had none")

    if problems:
        print(f"\n{len(problems)} questions to look at before trusting the reference:")
        for qid, why in problems:
            print(f"   {qid}: {why}")
        print("\nA wrong ideal answer does not make the campaign fail, it makes it MEASURE WRONG, and")
        print("the result still looks plausible. Better to fix them now.")
        return 1

    print("\nEvery ideal answer came from a sensible result.")
    print(f"generated at {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
