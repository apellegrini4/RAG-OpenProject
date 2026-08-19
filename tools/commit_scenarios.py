""" Real write scenarios, committed and then read back from the instance, since the campaign
    stops at the validation and never commits.

    usage example:
        python tools/commit_scenarios.py
        python tools/commit_scenarios.py --yes
"""

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import ACCOUNTS, api_key_for
from api import execute
from permissions import clear_capabilities_cache
from request_helpers import API_V3, commit_write

#everything happens in the sandbox project, which no question of the dataset names
SANDBOX = "Sandbox"
OWNER = "alba.pellegrini"

#where to read the real value after the commit: linked fields live under _links.<x>.title, plain ones at the root
LINKED = {"status", "assignee", "priority", "type", "project", "version"}


def parse_args():
    ap = argparse.ArgumentParser(description="real writes, verified by reading them back")
    ap.add_argument("--yes", action="store_true", help="scrivi davvero (senza, e' un dry-run)")
    ap.add_argument("--keep", action="store_true", help="keep what it created instead of deleting it")
    ap.add_argument("--only", default=None, help="only these scenarios, comma separated")
    return ap.parse_args()


def stamp():
    return datetime.now(timezone.utc).strftime("%m%d-%H%M%S")


def read_back(kind, entity_id, api_key):
    url = f"{API_V3}{'projects' if kind == 'projects' else 'work_packages'}/{entity_id}"
    response = requests.get(url, auth=("apikey", api_key), timeout=30)
    response.raise_for_status()
    data = response.json()

    flat = {}
    for key, value in data.items():
        if key == "_links":
            for name, link in value.items():
                if isinstance(link, dict) and link.get("title"):
                    flat[name] = link["title"]
        elif isinstance(value, dict) and "raw" in value:
            flat[key] = value["raw"]
        else:
            flat[key] = value
    return flat


def matches(actual, expected):
    if isinstance(actual, bool):
        return str(expected).strip().lower() in (("t", "true", "1") if actual
                                                 else ("f", "false", "0"))
    return str(actual).strip().lower() == str(expected).strip().lower()


def check(kind, entity_id, expected, api_key):
    """ which fields really cheanged """
    flat = read_back(kind, entity_id, api_key)
    wrong = []
    for field, values in expected.items():
        wanted = values[0] if isinstance(values, list) else values
        got = flat.get(field)
        if got is None or not matches(got, wanted):
            wrong.append(f"{field}: chiesto '{wanted}', sull'istanza '{got}'")
    return not wrong, wrong


def join_project(project_id, api_key):
    """ registers the user to the newly created project, as Project admin """
    roles = requests.get(f"{API_V3}roles", params={"pageSize": 100},
                         auth=("apikey", api_key), timeout=30)
    roles.raise_for_status()
    wanted = None
    for el in roles.json().get("_embedded", {}).get("elements", []):
        if (el.get("name") or "").strip().lower() in ("project admin", "project administrator"):
            wanted = el.get("id")
            break
    if wanted is None:
        return "no 'Project admin' role on the instance"

    body = {"_links": {
        "project": {"href": f"{API_V3}projects/{project_id}"},
        "principal": {"href": f"{API_V3}users/{ACCOUNTS[OWNER]['op_user_id']}"},
        "roles": [{"href": f"{API_V3}roles/{wanted}"}]}}
    response = requests.post(f"{API_V3}memberships", json=body,
                             auth=("apikey", api_key), timeout=30)
    if response.status_code not in (200, 201):
        return f"HTTP {response.status_code} subscribing {OWNER} to the project {project_id}"
    clear_capabilities_cache()
    return None


def commit(extraction, api_key):
    validated = execute(extraction, OWNER, api_key)
    if isinstance(validated, str):
        return None, validated
    if not validated.get("ready_to_commit"):
        return None, f"not validated: {validated}"
    result = commit_write(validated, api_key)
    if isinstance(result, str):
        return None, result
    return result, None


def wp_create(payload):
    return {"intent": "create", "macro_section": "work_packages", "filters": {}, "payload": payload}


def wp_update(wp_id, payload):
    return {"intent": "update", "macro_section": "work_packages",
            "filters": {"id": [str(wp_id)]}, "payload": payload}


def project_create(payload):
    return {"intent": "create", "macro_section": "projects", "filters": {}, "payload": payload}


def project_update(name, payload):
    return {"intent": "update", "macro_section": "projects",
            "filters": {"name": [name]}, "payload": payload}


def build_scenarios(tag):
    def subj(n):
        return f"[commit-test {tag}] {n}"

    return [
        {"id": "create-minimal", "what": "create a work package with the required fields only",
         "covers": "E32 and the minimal creates",
         "create": wp_create({"subject": [subj("minimal")], "type": ["Task"],
                              "project": [SANDBOX]})},

        {"id": "create-assignee", "what": "create a work package with assignee and priority",
         "covers": "M32, two fields that have to be resolved from name to id",
         "create": wp_create({"subject": [subj("assignee+priority")], "type": ["Bug"],
                              "project": [SANDBOX], "assignee": ["Giulia Bianchi"],
                              "priority": ["High"]})},

        {"id": "create-dates", "what": "create a work package with two independent dates",
         "covers": "H32, where one date must not be derived from the other",
         "create": wp_create({"subject": [subj("two dates")], "type": ["Feature"],
                              "project": [SANDBOX], "startDate": ["2026-09-21"],
                              "dueDate": ["2026-10-09"]})},

        {"id": "create-description", "what": "create a work package with a description",
         "covers": "the description travels as an object, not as a plain string",
         "create": wp_create({"subject": [subj("description")], "type": ["Task"],
                              "project": [SANDBOX],
                              "description": ["Created by the commit scenarios."]})},

        {"id": "create-project", "what": "create a project with the name only",
         "covers": "the minimal project creates",
         "create": project_create({"name": [f"Commit Test {tag}"]})},

        {"id": "create-project-public", "what": "create a public project with a description",
         "covers": "the boolean flags",
         "create": project_create({"name": [f"Commit Test Public {tag}"], "public": ["t"],
                                   "description": ["Created by the commit scenarios."]})},

        {"id": "update-status", "what": "update a single field, the status",
         "covers": "E19, E33",
         "setup": wp_create({"subject": [subj("u1 status")], "type": ["Task"],
                             "project": [SANDBOX], "status": ["New"]}),
         "update": {"status": ["In progress"]}},

        {"id": "update-assignee", "what": "update assignee and priority together",
         "covers": "M20, M33",
         "setup": wp_create({"subject": [subj("u2 assignee")], "type": ["Task"],
                             "project": [SANDBOX]}),
         "update": {"assignee": ["Giulia Bianchi"], "priority": ["Immediate"]}},

        {"id": "update-text", "what": "update subject and description",
         "covers": "M21, H22",
         "setup": wp_create({"subject": [subj("u3 rename")], "type": ["Task"],
                             "project": [SANDBOX]}),
         "update": {"subject": [f"[commit-test {tag}] u3 renamed"],
                    "description": ["Rewritten by the commit scenarios."]}},

        {"id": "update-dates", "what": "update both dates together",
         "covers": "M23, H24, H33",
         "setup": wp_create({"subject": [subj("u4 dates")], "type": ["Task"],
                             "project": [SANDBOX]}),
         "update": {"startDate": ["2026-09-22"], "dueDate": ["2026-10-15"]}},

        {"id": "update-project", "what": "move a work package to another project",
         "covers": "the case that looked successful while moving nothing: in a patch the project "
                   "can only travel in the body, and it was being left out",
         "setup": wp_create({"subject": [subj("u5 move")], "type": ["Task"],
                             "project": [SANDBOX]}),
         "update": {"project": ["Website Migration"], "status": ["In progress"]}},

        {"id": "update-project-text", "what": "update name and description of a project",
         "covers": "M25, H25",
         "setup_project": {"name": [f"Commit Test Rename {tag}"]},
         "update_project": {"name": [f"Commit Test Renamed {tag}"],
                            "description": ["Rewritten by the commit scenarios."]}},

        {"id": "archive-project", "what": "archive a project",
         "covers": "E25, H25, the active flag",
         "setup_project": {"name": [f"Commit Test Archive {tag}"]},
         "update_project": {"active": ["f"]}},
    ]


def cleanup(created, api_key, keep):
    """ deletes what the scenarios created """
    if keep:
        print("\n--keep: nothing deleted. Remove these by hand:")
        for kind, entity_id, label in created:
            print(f"   {kind[:-1]} {entity_id}  {label}")
        return

    print("\n" + "=" * 78)
    print("cleanup")
    print("=" * 78)
    leftovers = []
    for kind, entity_id, label in reversed(created):
        url = f"{API_V3}{'projects' if kind == 'projects' else 'work_packages'}/{entity_id}"
        try:
            response = requests.delete(url, auth=("apikey", api_key), timeout=60)
            if response.status_code in (200, 202, 204):
                print(f"  cancellato   {kind[:-1]} {entity_id}  {label}")
            else:
                leftovers.append((kind, entity_id, label, f"HTTP {response.status_code}"))
        except Exception as e:
            leftovers.append((kind, entity_id, label, str(e)))

    if leftovers:
        print("\n  warning: these are still on the instance and have to be removed by hand:")
        for kind, entity_id, label, why in leftovers:
            print(f"   {kind[:-1]} {entity_id}  {label}  ({why})")


def main():
    args = parse_args()
    api_key = api_key_for(OWNER)
    if not api_key:
        print(f"no key for {OWNER} in .env, stopping here.")
        return 1

    tag = stamp()
    scenarios = build_scenarios(tag)
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]

    print("=" * 78)
    print(f"real write scenarios: {len(scenarios)}, user {OWNER}")
    print("=" * 78)
    if not args.yes:
        print("dry run, nothing is written. Use --yes to perform them.\n")
        for s in scenarios:
            print(f"  {s['id']:<4} {s['what']}")
            print(f"       covers: {s['covers']}")
        return 0

    print(f"everything is created in {SANDBOX} with the stamp {tag}, and "
          f"{'kept' if args.keep else 'deleted'} at the end\n")

    created, results = [], []
    for s in scenarios:
        entity_id, error, kind = None, None, "work_packages"

        #the target: created now, never taken from the campaign world
        if "setup" in s:
            result, error = commit(s["setup"], api_key)
            if result:
                entity_id = result.get("id")
                created.append(("work_packages", entity_id, s["id"]))
        elif "setup_project" in s:
            kind = "projects"
            result, error = commit(project_create(s["setup_project"]), api_key)
            if result:
                entity_id = result.get("id")
                created.append(("projects", entity_id, s["id"]))
                #creating a project does not make you a member, and the update would be refused
                error = join_project(entity_id, api_key)

        if error:
            results.append((s, False, [f"la preparazione e' fallita: {error}"]))
            print(f"  {s['id']:<4} SETUP FALLITO   {error}")
            continue

        #the write this scenario exists to demonstrate
        if "create" in s:
            extraction = s["create"]
            expected = extraction["payload"]
            kind = "projects" if extraction["macro_section"] == "projects" else "work_packages"
        elif "update" in s:
            extraction = wp_update(entity_id, s["update"])
            expected = s["update"]
        else:
            name = s["setup_project"]["name"][0]
            extraction = project_update(name, s["update_project"])
            expected = s["update_project"]
            kind = "projects"

        result, error = commit(extraction, api_key)
        if error:
            results.append((s, False, [f"il commit e' fallito: {error}"]))
            print(f"  {s['id']:<4} COMMIT FALLITO  {error}")
            continue

        if "create" in s:
            entity_id = result.get("id")
            created.append((kind, entity_id, s["id"]))

        #read it back from the instance, a 200 on its own proves nothing
        ok, wrong = check(kind, entity_id, expected, api_key)
        results.append((s, ok, wrong))
        print(f"  {s['id']:<4} {'OK ' if ok else 'NO '}  {kind[:-1]} {entity_id:<6} {s['what']}")
        for line in wrong:
            print(f"        -> {line}")

    cleanup(created, api_key, args.keep)

    passed = sum(1 for _, ok, _ in results if ok)
    print("\n" + "=" * 78)
    print(f"{passed}/{len(results)} scenarios verified on the instance")
    if passed == len(results):
        print("the writes work: every field was read back from the instance with the right value,")
        print("so the campaign can stop at the validation without losing anything.")
    else:
        print("some scenarios do not add up: the commit succeeds but the data does not change,")
        print("which is the kind of failure that looks like a success in the results.")
    print("=" * 78)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
