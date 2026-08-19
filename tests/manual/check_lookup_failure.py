""" Checks that a support list we are not allowed to read is reported as such, and not as an
    item that does not exist. Reads and validations only.

    usage: python tests/manual/check_lookup_failure.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import api_key_for
from api import execute

LOOKUP_REFUSAL = ("System Info: permission denied, the current user is not allowed to "
                  "look up users.")

#Mario and Giulia cannot read /users, and any question naming a person goes through it
READ_BY_ASSIGNEE = {
    "intent": "read", "macro_section": "work_packages",
    "filters": {"assignee": ["Giulia Bianchi"]}, "payload": {},
}

#same list, different path: a create resolves the names while building the body
CREATE_WITH_ASSIGNEE = {
    "intent": "create", "macro_section": "work_packages", "filters": {},
    "payload": {"subject": ["lookup test"], "type": ["Task"], "project": ["Mobile App"],
                "assignee": ["Giulia Bianchi"]},
}

#counterproof on a list everybody may read: the 403 has to be about /users
READ_BY_PRIORITY = {
    "intent": "read", "macro_section": "work_packages",
    "filters": {"priority": ["High"]}, "payload": {},
}

CASES = [
    ("mario.rossi", "reads filtering by assignee, and cannot read /users",
     READ_BY_ASSIGNEE, LOOKUP_REFUSAL),

    ("giulia.bianchi", "creates in Mobile App with an assignee, same 403 on a different path",
     CREATE_WITH_ASSIGNEE, LOOKUP_REFUSAL),

    ("mario.rossi", "reads filtering by priority, a list everybody can read",
     READ_BY_PRIORITY, None),

    ("alba.pellegrini", "counterproof: the admin reads /users and the query goes through",
     READ_BY_ASSIGNEE, None),
]


def run():
    all_ok = True

    for username, description, extraction, expected in CASES:
        api_key = api_key_for(username)
        if not api_key:
            print(f"skipped  {username}: no key in .env\n")
            all_ok = False
            continue

        result = execute(extraction, username, api_key)
        text = result if isinstance(result, str) else json.dumps(result)[:150]

        if expected is None:
            #it just has to not be the lookup refusal, and above all not say the entity is missing
            ok = not (isinstance(result, str) and result.startswith("System Info: permission denied"))
            if isinstance(result, str) and "do not exist" in result:
                ok = False
        else:
            ok = isinstance(result, str) and result == expected

        all_ok &= ok
        print(f"{'PASS' if ok else 'FAIL'}  {username} -- {description}")
        print(f"      expected: {expected if expected else 'no permission refusal'}")
        print(f"      ottenuto: {text}\n")

    print("=" * 78)
    if all_ok:
        print("all green: a list we cannot read is reported as such, and not")
        print("piu' spacciata per un elenco di entita' inesistenti. Era l'ultima bugia rimasta.")
    else:
        print("something does not add up, look at the failing rows above.")
        print("Se compare 'these entities requested by the user do not exist' su un caso di")
        print("permissions, then one of the name resolution paths is still uncovered.")
    print("=" * 78)
    return all_ok


if __name__ == "__main__":
    run()
