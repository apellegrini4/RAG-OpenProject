""" Exercises the 403 of /form on purpose, skipping the guard, to show the second line of
    defence holds. /form is a dry run and writes nothing.

    usage: python tests/manual/check_server_refusal.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import api_key_for
from debug import DEBUG
from request_helpers import validate_via_form
from structured_URL_generator import build_create_request

CREATE_IN_SANDBOX = {
    "intent": "create", "macro_section": "work_packages", "filters": {},
    "payload": {"subject": ["server refusal test"], "type": ["Task"], "project": ["SANDBOX"]},
}

EXPECTED_REFUSAL = "System Info: permission denied, OpenProject refused this request."


def run():
    print(f"DEBUG = {DEBUG}  "
          f"({'il testo di OpenProject viene stampato' if DEBUG else 'log pulito'})\n")

    admin_key = api_key_for("alba.pellegrini")
    reader_key = api_key_for("mario.rossi")
    if not admin_key or not reader_key:
        print("keys missing in .env, stopping here.")
        return

    #built once with the admin key, so the two probes differ only in the credential
    request = build_create_request(CREATE_IN_SANDBOX, admin_key)
    if isinstance(request, str):
        print(f"could not build the request: {request}")
        return
    print(f"richiesta costruita: POST {request['url']}\n")

    all_ok = True

    print("[1] validation with the reader key, with the applicative guard skipped")
    result = validate_via_form(request, reader_key)
    ok = result == EXPECTED_REFUSAL
    all_ok &= ok
    print(f"    {'pass' if ok else 'fail'}  expected: {EXPECTED_REFUSAL}")
    print(f"          ottenuto: {result}")
    if isinstance(result, str) and "not authorized" in result.lower():
        all_ok = False
        print("          the text from OpenProject reached the answer, which should not happen")
    print()

    print("[2] counterproof: the same request with the product owner key")
    result = validate_via_form(request, admin_key)
    ok = isinstance(result, dict) and result.get("can_commit")
    all_ok &= ok
    print(f"    {'pass' if ok else 'fail'}  expected: a successful validation with a commit link")
    print(f"          ottenuto: {result if isinstance(result, str) else 'valida, can_commit=True'}")
    print()

    print("=" * 78)
    if all_ok:
        print("all green: the server refusal has the same shape as the applicative one, and the")
        print("text written by OpenProject stays in the logs. The same request goes through or")
        print("is refused depending on who signs it, so the two levels really are two.")
    else:
        print("something does not add up, look at the failing rows above.")
    print("=" * 78)
    return all_ok


if __name__ == "__main__":
    run()
