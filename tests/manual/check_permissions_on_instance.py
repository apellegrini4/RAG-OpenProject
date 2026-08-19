""" Live counterpart of tests/unit/test_permissions.py: checks the permissions on the instance
    are still the ones the logic was written against. Only reads.

    usage: python tests/manual/check_permissions_on_instance.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for p in (PROJECT_ROOT, PROJECT_ROOT / "tests" / "unit"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from accounts import ACCOUNTS, api_key_for
from permissions import (
    clear_capabilities_cache, decide_permission, fetch_capabilities,
)
#the expected matrix lives in the offline tests
from test_permissions import CAPABILITIES, EXPECTED, INTENTS, PROJECTS

PROJECT_NAMES = {"3": "SANDBOX", "4": "Mobile App", "5": "Data Migration",
                 "6": "Website Migration", "7": "Internal Audit"}

#only the actions the system uses: the real capabilities carry many more that do not concern us
RELEVANT = {"work_packages/read", "work_packages/create", "work_packages/update",
            "projects/create", "projects/update"}


def step_1_conformance():
    """do the real permissions still match the ones the tests were written against?"""
    print("=" * 78)
    print("step 1: the real permissions against the matrix the offline tests use")
    print("=" * 78)

    real = {}
    all_ok = True

    for username in ACCOUNTS:
        api_key = api_key_for(username)
        if not api_key:
            print(f"\n{username}: skipped, no key in .env")
            all_ok = False
            continue

        capabilities = fetch_capabilities(ACCOUNTS[username]["op_user_id"], api_key,
                                          use_cache=False)
        if capabilities is None:
            print(f"\n{username}: chiamata a /capabilities FALLITA")
            all_ok = False
            continue

        real[username] = capabilities
        expected = CAPABILITIES[username]
        print(f"\n{username}:")

        for project in PROJECTS:
            got = {a for a in capabilities.get(project, set()) if a in RELEVANT}
            want = {a for a in expected.get(project, set()) if a in RELEVANT}
            name = PROJECT_NAMES.get(project, project)
            if got == want:
                print(f"   ok   {name:<20} {', '.join(sorted(got)) or '(none)'}")
            else:
                all_ok = False
                print(f"   diff {name:<20} expected: {sorted(want)}")
                print(f"        {'':<20} trovato: {sorted(got)}")

        got_global = {a for a in capabilities.get("global", set()) if a in RELEVANT}
        want_global = {a for a in expected.get("global", set()) if a in RELEVANT}
        if got_global == want_global:
            print(f"   ok   {'[global]':<20} {', '.join(sorted(got_global)) or '(none)'}")
        else:
            all_ok = False
            print(f"   diff {'[global]':<20} expected: {sorted(want_global)}, found: {sorted(got_global)}")

    return real, all_ok


def step_2_matrix(real):
    """the 45 combinations decided on the real permissions, not on the copy kept in the tests"""
    print("\n" + "=" * 78)
    print("step 2: the decision on the real permissions, 3 users x 5 projects x 3 intents")
    print("=" * 78)

    all_ok = True
    for username, capabilities in real.items():
        print(f"\n{username}:")
        for project in PROJECTS:
            row = []
            for intent in INTENTS:
                allowed, reason = decide_permission(
                    capabilities, username, intent, "work_packages",
                    project, PROJECT_NAMES.get(project))
                expected = EXPECTED[username][project][intent]
                mark = "si" if allowed else "NO"
                if allowed != expected:
                    all_ok = False
                    mark += f" (expected {'yes' if expected else 'no'})"
                row.append(f"{intent}={mark}")
            print(f"   {PROJECT_NAMES.get(project, project):<20} {'  '.join(row)}")

    return all_ok


def step_3_projects(real):
    """ the two project operations: creating, which is global, and updating """
    print("\n" + "=" * 78)
    print("step 3: the project operations")
    print("=" * 78)

    expected_create = {"alba.pellegrini": True, "mario.rossi": False, "giulia.bianchi": False}
    expected_update = {"alba.pellegrini": True, "mario.rossi": False, "giulia.bianchi": False}
    all_ok = True

    for username, capabilities in real.items():
        allowed_create, _ = decide_permission(capabilities, username, "create", "projects")
        allowed_update, _ = decide_permission(capabilities, username, "update", "projects",
                                              "4", "Mobile App")
        ok_c = allowed_create == expected_create.get(username)
        ok_u = allowed_update == expected_update.get(username)
        all_ok &= ok_c and ok_u
        print(f"   {username:<18} creates projects: {'yes' if allowed_create else 'no':<3}"
              f"{'' if ok_c else '  not expected'}"
              f"   updates Mobile App: {'yes' if allowed_update else 'no':<3}"
              f"{'' if ok_u else '  not expected'}")

    return all_ok


if __name__ == "__main__":
    clear_capabilities_cache()

    real, ok_1 = step_1_conformance()
    if not real:
        print("\nno user can be queried, stopping here.")
        sys.exit(1)

    ok_2 = step_2_matrix(real)
    ok_3 = step_3_projects(real)

    print("\n" + "=" * 78)
    if ok_1 and ok_2 and ok_3:
        print("all green: the permissions on the instance match the expected ones, and the check")
        print("decides as expected on every combination.")
    else:
        print("something does not add up, look at the differences above.")
        print("If the change was intentional, update the matrix in test_permissions.py;")
        print("if it was not, fix the instance.")
    print("=" * 78)
