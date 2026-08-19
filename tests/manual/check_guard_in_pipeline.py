""" The permission guard inside the pipeline. Part A has no model and separates the refusal on
    the verb from the refusal on the scope, part B goes through the endpoint.

    usage: python tests/manual/check_guard_in_pipeline.py
"""

import json
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from accounts import api_key_for
from api import execute

API_URL = "http://127.0.0.1:8000/ask"
MODEL_PHASE1 = "qwen2.5-coder:1.5b"
MODEL_PHASE2 = "gemma3:4b"


def read(project):
    return {"intent": "read", "macro_section": "work_packages",
            "filters": {"project": [project]}, "payload": {}}


def create(project, subject="guard test"):
    return {"intent": "create", "macro_section": "work_packages",
            "filters": {}, "payload": {"subject": [subject], "project": [project],
                                       "type": ["Task"]}}


def update(wp_id):
    return {"intent": "update", "macro_section": "work_packages",
            "filters": {"id": [str(wp_id)]}, "payload": {"status": ["Closed"]}}


def create_project(name="TEST-f6"):
    return {"intent": "create", "macro_section": "projects",
            "filters": {}, "payload": {"name": [name]}}


def part_a(wp_id_in_sandbox):
    """ one row: (user, description, extraction, should_be_refused, expected fragment) """
    cases = [
        #the reader reads everywhere and writes nowhere
        ("mario.rossi", "reads in SANDBOX", read("SANDBOX"), False, None),
        ("mario.rossi", "tries to create in SANDBOX", create("SANDBOX"), True,
         "not allowed to create work packages in SANDBOX"),
        ("mario.rossi", "tries to create a project", create_project(), True,
         "not allowed to create projects"),


        ("mario.rossi", "tries to update a work package, refused on the verb",
         update(wp_id_in_sandbox), True, "not allowed to update work packages anywhere"),

        #  the Member writes where she is assigned, reads everywhere else
        ("giulia.bianchi", "reads in Mobile App", read("Mobile App"), False, None),
        ("giulia.bianchi", "creates in Mobile App, stopping at /form", create("Mobile App"),
         False, None),
        ("giulia.bianchi", "tries to create in Website Migration", create("Website Migration"),
         True, "not allowed to create work packages in Website Migration"),

        ("giulia.bianchi", "tries to update a work package in SANDBOX, refused on the scope",
         update(wp_id_in_sandbox), True, "update work packages in"),

        # the Product Owner can do everything, everywhere
        ("alba.pellegrini", "reads in SANDBOX", read("SANDBOX"), False, None),
        ("alba.pellegrini", "creates in SANDBOX, stopping at /form", create("SANDBOX"), False, None),
        ("alba.pellegrini", "updates a work package in SANDBOX, stopping at /form",
         update(wp_id_in_sandbox), False, None),
    ]

    print("=" * 78)
    print("part A: the guard inside execute(), no models")
    print("=" * 78)

    all_ok = True
    for username, description, extraction, should_refuse, expected_fragment in cases:
        api_key = api_key_for(username)
        if not api_key:
            print(f"\nskipped  {username}: no key in .env")
            all_ok = False
            continue

        result = execute(extraction, username, api_key)
        text = result if isinstance(result, str) else json.dumps(result)[:160]
        refused = isinstance(result, str) and result.startswith("System Info: permission denied")

        ok = refused == should_refuse
        if ok and expected_fragment:
            ok = expected_fragment in result
        all_ok &= ok

        print(f"\n{'PASS' if ok else 'FAIL'}  {username} -- {description}")
        print(f"      expected: {'refusal' if should_refuse else 'goes through'}"
              + (f", contenente {expected_fragment!r}" if expected_fragment else ""))
        print(f"      ottenuto: {text}")

    return all_ok


def ask(question, username, api_key):
    body = {"username": username, "question": question,
            "model_name_phase1": MODEL_PHASE1, "model_name_phase2": MODEL_PHASE2,
            "api_key": api_key}
    print(f"\n {username}: {question!r} ")
    response = requests.post(API_URL, json=body, timeout=600)
    print(f"status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(response.text)


def part_b():
    """needs the API served and Ollama up. The first call can take minutes."""
    print("=" * 78)
    print("part B: the refusal through the endpoint, worded by the second model")
    print("=" * 78)
    print("(uvicorn api:app --reload has to be running)")

    #the case that matters: a refusal of ours, decided before any call, that has to come out as a natural sentence and not as a technical error
    ask("Create a task called 'Not allowed' in the SANDBOX project",
        "mario.rossi", api_key_for("mario.rossi"))

    #the counterproof: the same question from someone allowed must reach ready_to_commit
    ask("Create a task called 'Allowed' in the SANDBOX project",
        "alba.pellegrini", api_key_for("alba.pellegrini"))

    #a read the Reader is allowed: the guard must not get in the way of who may
    ask("What are the work packages in the SANDBOX project?",
        "mario.rossi", api_key_for("mario.rossi"))


if __name__ == "__main__":
    print("1. part A: the guard inside execute(), no models, fast")
    print("2. part B: the refusal through the endpoint, needs the API and Ollama")
    choice = input("\nWhat do I run? ").strip()

    if choice == "2":
        part_b()
    else:
        wp_id = input("id di un work package che vive in SANDBOX: ").strip()
        ok = part_a(wp_id)
        print("\n" + "=" * 78)
        print("all green: the guard fires where it must and lets through where it must."
              if ok else "something does not add up, look at the failing rows above.")
        print("=" * 78)
