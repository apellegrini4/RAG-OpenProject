""" Puts the instance back the way world.json describes it: removes duplicates, fixes dates and
    assignees, rewrites the id map.

    usage example:
        python tools/fix_instance.py
        python tools/fix_instance.py --yes
"""

import argparse
import collections
import json
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import api_key_for
from request_helpers import API_V3

DATASET = PROJECT_ROOT / "benchmark" / "dataset"
WORLD = DATASET / "world" / "world.json"
ID_MAP = DATASET / "world" / "id_map.json"
ADMIN = "alba.pellegrini"

#the fields this script knows how to put back on its own
FIXABLE_DATES = ("startDate", "dueDate")
LINKED_FIELDS = {"assignee": "users", "priority": "priorities", "status": "statuses",
                 "version": "versions", "type": "types"}


def parse_args():
    ap = argparse.ArgumentParser(description="aligns the instance with the world")
    ap.add_argument("--yes", action="store_true", help="esegui davvero (senza, e' un dry-run)")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="list the duplicates instead of deleting them")
    return ap.parse_args()


def all_work_packages(api_key):
    """ every one of them, not only the open ones: filters=[] switches off the implicit filter """
    response = requests.get(f"{API_V3}work_packages",
                            params={"pageSize": 300, "filters": "[]",
                                    "sortBy": '[["id","asc"]]'},
                            auth=("apikey", api_key), timeout=60)
    response.raise_for_status()
    data = response.json()
    out = []
    for el in data.get("_embedded", {}).get("elements", []):
        flat = {"id": el.get("id"), "subject": el.get("subject"), "date": el.get("date"),
                "startDate": el.get("startDate"), "dueDate": el.get("dueDate"),
                "lockVersion": el.get("lockVersion")}
        for name, link in (el.get("_links") or {}).items():
            if isinstance(link, dict) and link.get("title"):
                flat[name] = link["title"]
        out.append(flat)
    if data.get("total", 0) > len(out):
        print(f"warning: the instance has {data['total']} and only {len(out)} were read.")
    return out


def name_to_id(kind, api_key):
    response = requests.get(f"{API_V3}{kind}", params={"pageSize": 200},
                            auth=("apikey", api_key), timeout=30)
    response.raise_for_status()
    return {el.get("name"): el.get("id")
            for el in response.json().get("_embedded", {}).get("elements", [])}


def patch(wp_id, body, api_key):
    """ a patch with a fresh lockVersion, since a write against a stale one is refused """
    current = requests.get(f"{API_V3}work_packages/{wp_id}", auth=("apikey", api_key), timeout=30)
    current.raise_for_status()
    body = {"lockVersion": current.json().get("lockVersion"), **body}
    response = requests.patch(f"{API_V3}work_packages/{wp_id}", json=body,
                              auth=("apikey", api_key), timeout=30)
    if response.status_code not in (200, 201):
        try:
            return response.json().get("message") or f"HTTP {response.status_code}"
        except Exception:
            return f"HTTP {response.status_code}"
    return None


def main():
    args = parse_args()
    api_key = api_key_for(ADMIN)
    if not api_key:
        print(f"no key for {ADMIN} in .env.")
        return 1

    world = json.loads(WORLD.read_text(encoding="utf-8"))
    items = all_work_packages(api_key)
    mode = "ESEGUO" if args.yes else "DRY-RUN (non tocco niente)"
    print(f"{len(items)} work package sull'istanza, {len(world['work_packages'])} nel mondo — {mode}\n")

    print("=" * 78)
    print("1. DOPPIONI")
    print("=" * 78)
    groups = collections.defaultdict(list)
    for it in items:
        groups[(it.get("project"), it.get("subject"))].append(it)

    removed = set()
    for (project, subject), group in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(group) < 2:
            continue
        group.sort(key=lambda x: x["id"])
        keep, extra = group[0], group[1:]
        print(f"  {subject}  ({project})")
        print(f"      tengo    id {keep['id']}")
        for it in extra:
            if args.yes and not args.keep_duplicates:
                response = requests.delete(f"{API_V3}work_packages/{it['id']}",
                                           auth=("apikey", api_key), timeout=60)
                ok = response.status_code in (200, 202, 204)
                print(f"      {'cancellato' if ok else 'FALLITO   '} id {it['id']}"
                      + ("" if ok else f"  HTTP {response.status_code}"))
                if ok:
                    removed.add(it["id"])
            else:
                print(f"      to delete, id {it['id']}")
    if not any(len(g) > 1 for g in groups.values()):
        print("  none.")

    items = [it for it in items if it["id"] not in removed]

    print("\n" + "=" * 78)
    print("2. on the instance but not in the world, left alone")
    print("=" * 78)
    wanted = {(w.get("project"), w.get("subject")) for w in world["work_packages"]}
    strangers = [it for it in items if (it.get("project"), it.get("subject")) not in wanted]
    for it in strangers:
        print(f"  id {it['id']:<5} {str(it.get('project')):<20} {it.get('subject')}")
    if not strangers:
        print("  none.")
    print(f"\n  {len(items) - len(strangers)} work package del mondo, {len(strangers)} estranei.")

    print("\n" + "=" * 78)
    print("3. CAMPI DA RIMETTERE A POSTO")
    print("=" * 78)
    by_key = {(it.get("project"), it.get("subject")): it for it in items}
    users = name_to_id("users", api_key) if args.yes else {}
    failures = []

    for item in world["work_packages"]:
        real = by_key.get((item.get("project"), item.get("subject")))
        if not real:
            print(f"  missing   {item['subject']}  ({item.get('project')})")
            failures.append(item["subject"])
            continue

        body, described = {}, []

        #a milestone has no startDate/dueDate but a single 'date'
        if real.get("type") == "Milestone":
            date = item.get("startDate") or item.get("dueDate")
            if date and real.get("date") != date:
                body["date"] = date
                described.append(f"date {real.get('date')} -> {date}")
        else:
            for field in FIXABLE_DATES:
                if item.get(field) and real.get(field) != item[field]:
                    body[field] = item[field]
                    described.append(f"{field} {real.get(field)} -> {item[field]}")

        if item.get("assignee") and real.get("assignee") != item["assignee"]:
            if args.yes:
                user_id = users.get(item["assignee"])
                if user_id:
                    body.setdefault("_links", {})["assignee"] = {
                        "href": f"{API_V3}users/{user_id}"}
            described.append(f"assignee {real.get('assignee')} -> {item['assignee']}")

        if not described:
            continue
        if not args.yes:
            print(f"  id {real['id']:<5} {item['subject'][:38]:<40} {'; '.join(described)}")
            continue

        error = patch(real["id"], body, api_key)
        print(f"  {'corretto' if not error else 'FALLITO '} id {real['id']:<5} "
              f"{item['subject'][:38]:<40} {'; '.join(described)}"
              + (f"   -> {error}" if error else ""))
        if error:
            failures.append(f"{item['subject']}: {error}")

    if args.yes:
        print("\n" + "=" * 78)
        print("4. MAPPA DEGLI ID")
        print("=" * 78)
        id_map = json.loads(ID_MAP.read_text(encoding="utf-8")) if ID_MAP.exists() else {}
        id_map["work_packages"] = {}
        missing = []
        for item in world["work_packages"]:
            real = by_key.get((item.get("project"), item.get("subject")))
            if real:
                id_map["work_packages"][str(item["id"])] = real["id"]
            else:
                missing.append(item["id"])
        ID_MAP.write_text(json.dumps(id_map, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {len(id_map['work_packages'])} work package mappati su "
              f"{len(world['work_packages'])}")
        if missing:
            print(f"  non mappati: {missing}")

    print("\n" + "=" * 78)
    if not args.yes:
        print("that was a dry run. Use --yes to apply.")
        return 0
    if failures:
        print(f"{len(failures)} things did not go through:")
        for f in failures:
            print(f"  - {f}")
        print("\nSe leggi 'not a working day', abilita sabato e domenica in Amministrazione ->")
        print("Calendari e date -> Giorni lavorativi, e rilancia.")
        return 1
    print("Istanza allineata al mondo. Adesso, in quest'ordine:")
    print("  python tools/check_instance.py           deve dire 'tutto combacia'")
    print("  python tools/renumber_ids.py --renumber")
    print("  python tools/renumber_ids.py --verify")
    print("  python tools/regenerate_references.py --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
