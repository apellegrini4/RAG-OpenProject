""" Renumbers the ids of the dataset onto the real ones of the instance, and verifies that each
    one points at the object the question means.

    usage example:
        python tools/renumber_ids.py --renumber
        python tools/renumber_ids.py --verify
"""

import argparse
import json
import re
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import api_key_for
from request_helpers import API_V3

DATASET = PROJECT_ROOT / "benchmark" / "dataset"
QUESTIONS = DATASET / "questions_99.jsonl"
WORLD = DATASET / "world" / "world.json"
ID_MAP = DATASET / "world" / "id_map.json"
ADMIN = "alba.pellegrini"


def parse_args():
    ap = argparse.ArgumentParser(description="renumbers the dataset ids and verifies them")
    ap.add_argument("--renumber", action="store_true")
    ap.add_argument("--verify", action="store_true")
    return ap.parse_args()


def load_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def save_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def renumber_text(text, old, new):
    """ replaces the id inside the question text """
    return re.sub(rf"\b{old}\b", str(new), text)


def renumber():
    if not ID_MAP.exists():
        print(f"{ID_MAP} is missing: run load_openproject_data.py first")
        return 1

    id_map = json.loads(ID_MAP.read_text(encoding="utf-8"))
    wp_map = {str(k): v for k, v in id_map["work_packages"].items()}
    project_map = {str(k): v for k, v in id_map["projects"].items()}

    #always start from the original
    backup = QUESTIONS.with_suffix(".jsonl.pre-renumber")
    if backup.exists():
        rows = load_jsonl(backup)
        print(f"starting from {backup.name}, the original, not from the renumbered file")
    else:
        rows = load_jsonl(QUESTIONS)
        save_jsonl(backup, rows)
        print(f"originale salvato in {backup.name}")

    changed, unmapped = [], []
    for row in rows:
        ids = (row.get("filters") or {}).get("id")
        if not ids:
            continue
        mapping = project_map if row["macro_section"] == "projects" else wp_map
        old = str(ids[0])
        new = mapping.get(old)
        if new is None:
            unmapped.append((row["id"], row["macro_section"], old))
            continue
        if str(new) == old:
            continue

        row["filters"]["id"] = [str(new)]
        before = row["text"]
        row["text"] = renumber_text(row["text"], old, new)
        changed.append((row["id"], old, new, before != row["text"]))

    save_jsonl(QUESTIONS, rows)

    print(f"\n{len(changed)} questions renumbered:")
    for qid, old, new, text_changed in changed:
        flag = "" if text_changed else "   the id was not in the text, only the filters changed"
        print(f"   {qid}: {old} -> {new}{flag}")

    if unmapped:
        print(f"\nwarning: {len(unmapped)} questions carry an id the map does not know.")
        print("That item was never loaded, so the question would hit nothing, or worse something")
        print("that belongs to another question. Load those items or drop the questions.")
        for qid, section, old in unmapped:
            print(f"   {qid} ({section}) id {old}")
    return 0


def verify():
    api_key = api_key_for(ADMIN)
    world = json.loads(WORLD.read_text(encoding="utf-8"))
    id_map = json.loads(ID_MAP.read_text(encoding="utf-8"))

    #mock id -> the subject the world gives it
    expected_subject = {str(w["id"]): w.get("subject") for w in world["work_packages"]}
    reverse_wp = {str(v): k for k, v in id_map["work_packages"].items()}
    #real project id -> the name the dataset expects to find there
    project_name = {str(v): k for k, v in id_map["project_names"].items()}

    rows = load_jsonl(QUESTIONS)
    problems, checked = [], 0

    for row in rows:
        ids = (row.get("filters") or {}).get("id")
        if not ids:
            continue
        checked += 1
        real_id = str(ids[0])

        if row["macro_section"] == "projects":
            response = requests.get(f"{API_V3}projects/{real_id}", auth=("apikey", api_key),
                                    timeout=30)
            if response.status_code != 200:
                problems.append((row["id"], real_id, f"HTTP {response.status_code}"))
                continue
            actual = response.json().get("name")
            wanted = project_name.get(real_id)
            if wanted and actual and actual.strip().lower() != str(wanted).strip().lower():
                problems.append((row["id"], real_id, f"e' '{actual}', il dataset intende '{wanted}'"))
            continue

        response = requests.get(f"{API_V3}work_packages/{real_id}", auth=("apikey", api_key),
                                timeout=30)
        if response.status_code != 200:
            problems.append((row["id"], real_id, f"HTTP {response.status_code}"))
            continue
        actual = response.json().get("subject")
        mock_id = reverse_wp.get(real_id)
        wanted = expected_subject.get(mock_id)
        if wanted and actual != wanted:
            problems.append((row["id"], real_id, f"is '{actual}', the world says '{wanted}'"))

    print(f"{checked} ids named by the dataset were checked")
    if not problems:
        print("\nall green: every id points at the item its question means.")
        print("The smoke test can run now.")
        return 0

    print(f"\n{len(problems)} ids do not point where they should:")
    for qid, real_id, why in problems:
        print(f"   {qid}: id {real_id} {why}")
    print("\ndo not launch the campaign like this: an update would hit the wrong object and the")
    print("result would look like a success.")
    return 1


def main():
    args = parse_args()
    if not (args.renumber or args.verify):
        print(__doc__)
        return 1
    if args.renumber:
        code = renumber()
        if code:
            return code
    if args.verify:
        return verify()
    return 0


if __name__ == "__main__":
    sys.exit(main())
