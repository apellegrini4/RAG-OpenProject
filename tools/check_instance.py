""" Compares the instance with the world and lists duplicates, missing items and fields out of
    place. It writes nothing.

    usage: python tools/check_instance.py
"""

import collections
import json
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import api_key_for
from request_helpers import API_V3

WORLD = PROJECT_ROOT / "benchmark" / "dataset" / "world" / "world.json"
ADMIN = "alba.pellegrini"

#the world fields that can be compared with what the instance returns
COMPARABLE = ("status", "type", "project", "assignee", "author", "priority", "version",
              "startDate", "dueDate", "percentageDone")


def flatten(el):
    flat = {"id": el.get("id"), "subject": el.get("subject"), "date": el.get("date"),
            "startDate": el.get("startDate"), "dueDate": el.get("dueDate"),
            "percentageDone": el.get("percentageDone")}
    for name, link in (el.get("_links") or {}).items():
        if isinstance(link, dict) and link.get("title"):
            flat[name] = link["title"]
    return flat


def main():
    api_key = api_key_for(ADMIN)
    world = json.loads(WORLD.read_text(encoding="utf-8"))

    response = requests.get(f"{API_V3}work_packages",
                            params={"pageSize": 300, "filters": "[]",
                                    "sortBy": '[["id","asc"]]'},
                            auth=("apikey", api_key), timeout=60)
    response.raise_for_status()
    data = response.json()
    items = [flatten(el) for el in data.get("_embedded", {}).get("elements", [])]
    print(f"sull'istanza: {data.get('total')} work package, ne ho letti {len(items)}\n")

    by_subject = collections.defaultdict(list)
    for it in items:
        by_subject[it["subject"]].append(it)

    dups = {s: v for s, v in by_subject.items() if len(v) > 1}
    print("=" * 78)
    print(f"DOPPIONI: {len(dups)} soggetti compaiono piu' di una volta")
    print("=" * 78)
    for subject, group in sorted(dups.items()):
        print(f"  {subject}")
        for it in group:
            print(f"      id {it['id']:<5} project {it.get('project'):<20} "
                  f"stato {it.get('status'):<14} scadenza {it.get('dueDate')}")
    if not dups:
        print("  none.")

    #comparison with the world
    print("\n" + "=" * 78)
    print("fields that do not match world.json")
    print("=" * 78)
    problems = 0
    for item in world["work_packages"]:
        found = by_subject.get(item["subject"])
        if not found:
            print(f"  missing      {item['subject']}")
            problems += 1
            continue
        real = found[0]
        wrong = []

        #a milestone has no startDate/dueDate
        milestone = real.get("type") == "Milestone"
        if milestone:
            expected = item.get("startDate") or item.get("dueDate")
            if expected and real.get("date") != expected:
                wrong.append(f"date: istanza '{real.get('date')}', mondo '{expected}'")

        for field in COMPARABLE:
            if field not in item:
                continue
            if milestone and field in ("startDate", "dueDate"):
                continue
            got, wanted = real.get(field), item[field]
            if str(got) != str(wanted):
                wrong.append(f"{field}: istanza '{got}', mondo '{wanted}'")
        if wrong:
            problems += 1
            print(f"  id {real['id']:<5} {item['subject'][:42]:<44} {'; '.join(wrong)}")
    if not problems:
        print("  tutto combacia.")

    #projects
    print("\n" + "=" * 78)
    print("PROGETTI: active / public")
    print("=" * 78)
    response = requests.get(f"{API_V3}projects", params={"pageSize": 100},
                            auth=("apikey", api_key), timeout=30)
    response.raise_for_status()
    on_instance = {p["name"]: p for p in response.json().get("_embedded", {}).get("elements", [])}
    for project in world["projects"]:
        real = on_instance.get(project["name"])
        if not real:
            print(f"  missing   {project['name']}")
            continue
        wrong = [f"{f}: istanza {real.get(f)}, mondo {project[f]}"
                 for f in ("active", "public") if f in project and real.get(f) != project[f]]
        state = "  ".join(f"{f}={real.get(f)}" for f in ("active", "public"))
        print(f"  {'DIVERSO ' if wrong else 'ok      '} {project['name']:<24} {state}"
              + (f"   <-- {'; '.join(wrong)}" if wrong else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
