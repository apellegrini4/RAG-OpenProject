""" Live counterpart of tests/unit/test_http_errors.py: checks the instance really returns the
    statuses the offline tests assume. Only reads.

    usage: python tests/manual/check_http_statuses.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import api_key_for
from debug import DEBUG
from request_helpers import API_V3
from structured_URL_generator import fetch_openproject_data

#a filter that does not exist
BAD_FILTER = '[{"thisFieldDoesNotExist":{"operator":"=","values":["1"]}}]'

CASES = [
    ("404 -- work package inesistente",
     "alba.pellegrini", f"{API_V3}work_packages/999999",
     "does not exist"),

    ("400 -- filtro inesistente (richiesta malformata)",
     "alba.pellegrini", f"{API_V3}work_packages?filters={BAD_FILTER}",
     "invalid parameters"),

    ("403 on /users with the key of a non administrator",
     "mario.rossi", f"{API_V3}users",
     "permission denied"),

    ("200, counterproof: a normal read still works",
     "alba.pellegrini", f"{API_V3}projects",
     None),
]


def run():
    print(f"DEBUG = {DEBUG}  ({'i corpi degli errori vengono stampati' if DEBUG else 'log pulito'})")
    print(f"API_V3 = {API_V3}")
    if "//api/v3" in API_V3:
        print("   warning: the base URL still has a double slash")
    print()

    all_ok = True
    for description, username, url, expected_fragment in CASES:
        api_key = api_key_for(username)
        if not api_key:
            print(f"skipped  {description}: no key for {username}\n")
            all_ok = False
            continue

        result = fetch_openproject_data(url, api_key)
        is_error_string = isinstance(result, str) and result.startswith("System Info:")

        if expected_fragment is None:
            ok = not is_error_string
            shown = "risposta valida (dizionario)" if ok else result
        else:
            ok = is_error_string and expected_fragment in result
            shown = result if isinstance(result, str) else "no error, but one was expected"

        all_ok &= ok
        print(f"{'PASS' if ok else 'FAIL'}  {description}  [{username}]")
        if expected_fragment:
            print(f"      expected a message containing {expected_fragment!r}")
        print(f"      ottenuto: {shown}\n")

    print("=" * 78)
    if all_ok:
        print("all green: every status ends up in the right message, and so in the right branch")
        print("of the gate (a 404 no longer blocks the cell, a 403 becomes a refusal).")
    else:
        print("something does not add up, look at the failing rows above.")
    print("=" * 78)
    return all_ok


if __name__ == "__main__":
    run()
