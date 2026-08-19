""" Loads the world described by world.json onto the instance, through the same write path
    the pipeline uses. Checks types, members and versions before writing anything.

    usage example:
        python tools/load_openproject_data.py --check
        python tools/load_openproject_data.py --dry-run
        python tools/load_openproject_data.py
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
from api import execute
from request_helpers import API_V3, commit_write, create_ID_map

DATASET = PROJECT_ROOT / "benchmark" / "dataset"
WORLD = DATASET / "world" / "world.json"
ID_MAP = DATASET / "world" / "id_map.json"
QUESTIONS = DATASET / "questions_99.jsonl"

ADMIN = "alba.pellegrini"

#the name appearing in the mocks -> the user who creates it, when we hold their key
AUTHOR_ACCOUNTS = {
    "Alba Pellegrini": "alba.pellegrini",
    "Mario Rossi": "mario.rossi",
    "Giulia Bianchi": "giulia.bianchi",
}

#world fields that cannot be written: OpenProject computes or imposes them
READ_ONLY_FIELDS = {"percentageDone", "author", "entity", "id"}

#versions the questions name that no work package of the world uses
EXTRA_VERSIONS = ("Sprint 1", "Sprint 3")


def parse_args():
    ap = argparse.ArgumentParser(description="loads the world onto the instance")
    ap.add_argument("--check", action="store_true",
                    help="preflight only: what is missing, without creating anything")
    ap.add_argument("--dry-run", action="store_true",
                    help="writes nothing: lists what would be created and what is missing")
    ap.add_argument("--only-projects", action="store_true",
                    help="create the projects only, so the versions can be added from the interface")
    ap.add_argument("--force", action="store_true",
                    help="write even if the preflight is not clean, which is a bad idea")
    return ap.parse_args()


def existing_projects(api_key):
    """ nome normalizzato -> id, di quello che c'e' gia' sull'istanza """
    return dict(create_ID_map("project", api_key))


def existing_work_packages(api_key):
    """ (project, subject) -> id, so the same item is not created twice """
    found = {}
    response = requests.get(f"{API_V3}work_packages",
                            params={"pageSize": 200, "filters": "[]",
                                    "sortBy": '[["id","asc"]]'},
                            auth=("apikey", api_key), timeout=60)
    response.raise_for_status()
    data = response.json()
    for el in data.get("_embedded", {}).get("elements", []):
        project = (el.get("_links", {}).get("project", {}) or {}).get("title")
        found[(project, el.get("subject"))] = el.get("id")
    if data.get("total", 0) > len(found):
        print(f"  warning: the instance has {data['total']} work packages and only "
              f"{len(found)} were read. Raise the page size before going on.")
    return found


def types_enabled(project_id, api_key):
    """ the types enabled in a project """
    response = requests.get(f"{API_V3}projects/{project_id}/types",
                            params={"pageSize": 100}, auth=("apikey", api_key), timeout=30)
    response.raise_for_status()
    return {el.get("name") for el in response.json().get("_embedded", {}).get("elements", [])}


def members_of(project_id, api_key):
    """ who is a member of a project. The assignee has to be one, or OpenProject refuses the write """
    response = requests.get(f"{API_V3}memberships",
                            params={"pageSize": 100,
                                    "filters": json.dumps([{"project": {
                                        "operator": "=", "values": [str(project_id)]}}])},
                            auth=("apikey", api_key), timeout=30)
    response.raise_for_status()
    return {(el.get("_links", {}).get("principal", {}) or {}).get("title")
            for el in response.json().get("_embedded", {}).get("elements", [])}


def versions_on_instance(api_key):
    """ version name -> [(the project that defines it, its sharing)] """
    response = requests.get(f"{API_V3}versions", params={"pageSize": 200},
                            auth=("apikey", api_key), timeout=60)
    response.raise_for_status()
    out = {}
    for el in response.json().get("_embedded", {}).get("elements", []):
        project = (el.get("_links", {}).get("definingProject", {}) or {}).get("title")
        out.setdefault(el.get("name"), []).append((project, el.get("sharing")))
    return out



def requirements(world):
    """ for each project, which types and which people have to be there """
    types = collections.defaultdict(set)
    people = collections.defaultdict(set)
    versions = collections.defaultdict(set)

    #from the world: what has to be created now
    project_of = {}
    for item in world["work_packages"]:
        project = item.get("project")
        project_of[str(item["id"])] = project
        if item.get("type"):
            types[project].add(item["type"])
        for field in ("assignee", "author"):
            if item.get(field):
                people[project].add(item[field])
        if item.get("version"):
            versions[project].add(item["version"])

    #from the questions: what the campaign will ask for
    if QUESTIONS.exists():
        rows = [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        for row in rows:
            if row.get("macro_section") != "work_packages":
                continue
            payload = row.get("payload") or {}
            filters = row.get("filters") or {}
            #a create names the project, an update names the work package and the world knows its project
            project = (payload.get("project") or [None])[0]
            if not project and filters.get("id"):
                project = project_of.get(str(filters["id"][0]))
            if not project:
                continue
            if payload.get("type"):
                types[project].add(payload["type"][0])
            if payload.get("assignee"):
                people[project].add(payload["assignee"][0])
            if payload.get("version"):
                versions[project].add(payload["version"][0])

    return types, people, versions


def preflight(world, project_ids, api_key):
    """ everything OpenProject would only reveal at write time, checked beforehand """
    types_needed, people_needed, versions_needed = requirements(world)
    problems = []

    print("\n" + "=" * 78)
    print("preflight: what has to be in place on the instance already")
    print("=" * 78)

    #the types enabled per project
    print("\n  types (project settings, work package types)")
    for project, wanted in sorted(types_needed.items()):
        pid = project_ids.get(project)
        if not pid:
            continue
        have = types_enabled(pid, api_key)
        missing = sorted(wanted - have)
        if missing:
            problems.append(f"{project}: enable the types {', '.join(missing)} "
                            f"in the project settings")
            print(f"    missing {project:<24} {', '.join(missing)}")
        else:
            print(f"    ok      {project:<24} {', '.join(sorted(wanted))}")

    print("\n  members, needed before anyone can be an assignee")
    for project, wanted in sorted(people_needed.items()):
        pid = project_ids.get(project)
        if not pid:
            continue
        have = members_of(pid, api_key)
        missing = sorted(w for w in wanted if w not in have)
        if missing:
            problems.append(f"{project}: aggiungi come membri {', '.join(missing)}")
            print(f"    missing {project:<24} {', '.join(missing)}")
        else:
            print(f"    ok      {project:<24} {', '.join(sorted(wanted))}")

    print("\n  versions (project settings, versions)")
    wanted_versions = {v for group in versions_needed.values() for v in group}
    wanted_versions.update(EXTRA_VERSIONS)
    have_versions = versions_on_instance(api_key)
    for version in sorted(wanted_versions):
        found = have_versions.get(version, [])
        if not found:
            problems.append(f"version '{version}': it does not exist, create it and share it with "
                            "every project")
            print(f"    missing {version}")
        elif len(found) > 1:
            where = ", ".join(p for p, _ in found)
            problems.append(f"version '{version}': defined {len(found)} times ({where}). "
                            "Keep one.")
            print(f"    twice   {version:<12} in: {where}")
        else:
            project, sharing = found[0]
            if sharing != "system":
                problems.append(f"version '{version}': sharing='{sharing}'. Set it to "
                                "'With all projects', or the other projects cannot see it.")
                print(f"    sharing {version:<12} in {project}, sharing='{sharing}'")
            else:
                print(f"    ok      {version:<12} in {project}, shared with every project")

    return problems


def write(extraction, username, api_key, dry_run):
    """ the full write path: execute() validates through /form, commit_write() performs it """
    if dry_run:
        return None, "dry-run"
    validated = execute(extraction, username, api_key)
    if isinstance(validated, str):
        return None, validated
    if not validated.get("ready_to_commit"):
        return None, f"non validato: {validated}"
    result = commit_write(validated, api_key)
    if isinstance(result, str):
        return None, result
    return result.get("id"), None


def create_project(project, api_key, dry_run):
    """ active is not passed on creation """
    payload = {"name": [project["name"]]}
    if "public" in project:
        payload["public"] = ["t" if project["public"] else "f"]
    return write({"intent": "create", "macro_section": "projects",
                  "filters": {}, "payload": payload}, ADMIN, api_key, dry_run)


def project_flags(project_id, api_key):
    """ active and public as they currently are on the instance """
    response = requests.get(f"{API_V3}projects/{project_id}", auth=("apikey", api_key), timeout=30)
    response.raise_for_status()
    data = response.json()
    return {"active": data.get("active"), "public": data.get("public")}


def sync_project(name, wanted, project_id, api_key, dry_run):
    """ brings active and public of a project that already exists in line with the world """
    if "public" not in wanted:
        return None
    current = project_flags(project_id, api_key)
    if current.get("public") == wanted["public"]:
        return None
    if dry_run:
        return f"da allineare: public {current.get('public')} -> {wanted['public']}"
    _, error = write({"intent": "update", "macro_section": "projects",
                      "filters": {"name": [name]},
                      "payload": {"public": ["t" if wanted["public"] else "f"]}},
                     ADMIN, api_key, False)
    return error or f"public {current.get('public')} -> {wanted['public']}"


def deactivate_project(name, api_key, dry_run):
    return write({"intent": "update", "macro_section": "projects",
                  "filters": {"name": [name]}, "payload": {"active": ["f"]}},
                 ADMIN, api_key, dry_run)


def create_work_package(item, username, api_key, dry_run, skip_assignee):
    """ creates the work package """
    payload = {}
    for field, value in item.items():
        if field in READ_ONLY_FIELDS:
            continue
        if field == "assignee" and skip_assignee:
            continue
        payload[field] = [str(value)]
    return write({"intent": "create", "macro_section": "work_packages",
                  "filters": {}, "payload": payload}, username, api_key, dry_run)


def set_assignee(wp_id, assignee, api_key, dry_run):
    return write({"intent": "update", "macro_section": "work_packages",
                  "filters": {"id": [str(wp_id)]}, "payload": {"assignee": [assignee]}},
                 ADMIN, api_key, dry_run)


def main():
    args = parse_args()
    admin_key = api_key_for(ADMIN)
    if not admin_key:
        print(f"no key for {ADMIN} in .env, stopping here.")
        return 1
    if not WORLD.exists():
        print(f"{WORLD} is missing. Run python tools/build_world.py first")
        return 1

    world = json.loads(WORLD.read_text(encoding="utf-8"))
    id_map = {"projects": {}, "project_names": {}, "work_packages": {}, "notes": []}

    print("=" * 78)
    print("PROGETTI")
    print("=" * 78)
    have = existing_projects(admin_key)
    for project in world["projects"]:
        name = project["name"]
        key = name.lower().strip()
        if key in have:
            id_map["project_names"][name] = have[key]
            #the flags of a project that already exists have to be aligned with the world
            note = sync_project(name, project, have[key], admin_key, args.dry_run or args.check)
            print(f"  esiste gia'   {name:<24} id reale {have[key]}"
                  + (f"   {note}" if note else ""))
            continue
        new_id, error = create_project(project, admin_key, args.dry_run or args.check)
        if error and error not in ("dry-run",):
            print(f"  FALLITO       {name:<24} {error}")
        elif args.dry_run or args.check:
            print(f"  da creare     {name:<24} active={project.get('active')} "
                  f"public={project.get('public')}")
        else:
            id_map["project_names"][name] = new_id
            print(f"  creato        {name:<24} id reale {new_id}")

    to_archive = [p["name"] for p in world["projects"] if p.get("active") is False]

    #the questions select projects by id
    for mock_id, name in (world.get("project_ids") or {}).items():
        real = id_map["project_names"].get(name)
        if real:
            id_map["projects"][mock_id] = real

    if args.only_projects:
        print("\n--only-projects: mi fermo qui.")
        return 0

    problems = preflight(world, id_map["project_names"], admin_key)
    if problems:
        print("\n" + "=" * 78)
        print(f"{len(problems)} things to fix in the interface before loading")
        print("=" * 78)
        for problem in problems:
            print(f"  - {problem}")
        if not args.force:
            print("\nnothing written. Fix them and run again: otherwise the loading creates half the")
            print("work packages and fails on the other half, leaving the instance halfway.")
            return 1
        print("\n--force: going ahead anyway. Expect failures.")
    else:
        print("\n  preflight clean: types, members and versions are in place.")

    if args.check:
        print("\n--check: stopping here, nothing written.")
        return 0

    print("\n" + "=" * 78)
    print("WORK PACKAGE")
    print("=" * 78)
    already = {} if args.dry_run else existing_work_packages(admin_key)
    skipped_fields, deferred = set(), []

    for item in world["work_packages"]:
        subject, project = item.get("subject"), item.get("project")
        if (project, subject) in already:
            id_map["work_packages"][str(item["id"])] = already[(project, subject)]
            print(f"  esiste gia'   {str(item['id']):<5} {subject[:44]:<46} id reale "
                  f"{already[(project, subject)]}")
            continue

        #the author is decided by the key: the author's own is used when we have it
        author = item.get("author")
        username = AUTHOR_ACCOUNTS.get(author, ADMIN)
        api_key = api_key_for(username) or admin_key
        used_admin = username != ADMIN and api_key == admin_key

        #a Member cannot resolve a user name into an id: the assignee is set afterwards
        skip_assignee = bool(item.get("assignee")) and username != ADMIN and not used_admin

        for field in item:
            if field in READ_ONLY_FIELDS and field not in ("entity", "id"):
                skipped_fields.add(field)

        new_id, error = create_work_package(item, username, api_key, args.dry_run, skip_assignee)
        if args.dry_run:
            note = "  (assegnatario in un secondo passaggio)" if skip_assignee else ""
            print(f"  da creare     {str(item['id']):<5} {subject[:44]:<46} "
                  f"autore={author or '-'} ({username}){note}")
            continue
        if error:
            print(f"  FALLITO       {str(item['id']):<5} {subject[:44]:<46} {error}")
            id_map["notes"].append({"mock_id": item["id"], "subject": subject, "error": error})
            continue

        id_map["work_packages"][str(item["id"])] = new_id
        note = "  <-- creato dall'admin, l'autore non risultera' corretto" if used_admin else ""
        print(f"  creato        {str(item['id']):<5} {subject[:44]:<46} id reale {new_id}{note}")
        if skip_assignee:
            deferred.append((new_id, item["assignee"], subject))
        if used_admin:
            id_map["notes"].append({"mock_id": item["id"], "subject": subject,
                                    "expected_author": author, "actual_author": ADMIN})

    if deferred and not args.dry_run:
        print("\n  second pass: the assignees, with the administrator key")
        for wp_id, assignee, subject in deferred:
            _, error = set_assignee(wp_id, assignee, admin_key, args.dry_run)
            if error:
                print(f"  FALLITO       {wp_id:<6} assegnatario {assignee}: {error}")
                id_map["notes"].append({"work_package": wp_id, "missing_assignee": assignee,
                                        "error": error})
            else:
                print(f"  assegnato     {wp_id:<6} {assignee:<18} {subject[:40]}")

    if skipped_fields:
        print(f"\nworld fields that cannot be written, skipped: {sorted(skipped_fields)}")

    if to_archive:
        print("\n" + "=" * 78)
        print("archiving, last of all, since an archived project takes no work packages")
        print("=" * 78)
        for name in to_archive:
            _, error = deactivate_project(name, admin_key, args.dry_run)
            if args.dry_run:
                print(f"  da archiviare {name}")
            elif error:
                print(f"  FALLITO       {name:<24} {error}")
            else:
                print(f"  archiviato    {name}")

    if not args.dry_run:
        ID_MAP.write_text(json.dumps(id_map, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nmappa id scritta in {ID_MAP}")
        print(f"  progetti mappati: {len(id_map['projects'])}, "
              f"work package mappati: {len(id_map['work_packages'])} su "
              f"{len(world['work_packages'])}")

        failures = [n for n in id_map["notes"] if n.get("error")]
        if failures:
            print(f"\n  {len(failures)} work packages were not loaded: the map does not contain them")
            print("  and the questions that name them would hit nothing. Run again after fixing:")
            print("  the ones already created are recognised and skipped.")
            return 1

        wrong_author = [n for n in id_map["notes"] if n.get("expected_author")]
        if wrong_author:
            print(f"\n  warning: {len(wrong_author)} work packages have the wrong author.")
            print("  The questions that filter by author will not find them.")

    print("\nnext step: python tools/renumber_ids.py --renumber")
    return 0


if __name__ == "__main__":
    sys.exit(main())
