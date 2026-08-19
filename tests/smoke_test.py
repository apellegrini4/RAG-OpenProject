""" Checks worth running before the campaign: the files, the offline tests, the network, the
    models, and seven real cells, one per branch.

    usage example:
        python tests/smoke_test.py
        python tests/smoke_test.py --skip-cells
"""

from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "scripts" / "phase_3"))

from accounts import ACCOUNTS, api_key_for
from metrics_phase3 import REFERENCE_FORMAT
from request_helpers import API_V3

CONFIG = PROJECT_ROOT / "benchmark" / "config.yaml"
RUNNER = PROJECT_ROOT / "benchmark" / "scripts" / "phase_3" / "run_phase3.py"
AGGREGATOR = PROJECT_ROOT / "benchmark" / "scripts" / "phase_3" / "aggregate_phase3.py"
CAMPAIGN_USER = "alba.pellegrini"

#one question per branch the system treats differently
SMOKE_QUESTIONS = [
    "E01",   # read   work_packages   -- fills the page
    "E07",   # read   projects        -- fills the page, more results than the page holds
    "E10",   # create work_packages
    "E16",   # create projects        -- boolean payload, public = t
    "E19",   # update work_packages
    "E25",   # update projects
    "E28",   # out of domain: refusal
]

MODELS = ["qwen2.5-coder:1.5b", "gemma3:4b"]

#what a cell must carry for the run to be scored again later without being run again
REQUIRED_CELL_FIELDS = ["openproject_result", "phase2_context", "answer_model", "extraction"]

checks = []


def check(name, ok, detail="", fix=""):
    checks.append((name, ok, detail, fix))
    print(f"  {'OK  ' if ok else 'NO  '} {name}" + (f"   {detail}" if detail else ""))
    if not ok and fix:
        print(f"       -> {fix}")
    return ok


def parse_args():
    ap = argparse.ArgumentParser(description="checks before the campaign")
    ap.add_argument("--skip-cells", action="store_true",
                    help="preflight checks only, does not run the models")
    return ap.parse_args()


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def check_files(cfg):
    section("1. THE FILES  (costs a second)")
    questions = PROJECT_ROOT / cfg["paths"]["questions"]
    ok = check("the dataset is there", questions.exists(), str(questions.name),
               "check paths.questions in config.yaml")
    rows = []
    if ok:
        rows = [json.loads(l) for l in questions.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        check("99 questions", len(rows) == 99, f"{len(rows)} rows")
        check("every one has an answer_id",
              all(r.get("answer_id") for r in rows),
              f"{sum(1 for r in rows if not r.get('answer_id'))} without",
              "run tools/regenerate_references.py: it assigns the missing answer_id")

    backup = questions.with_suffix(".jsonl.pre-renumber")
    check("the ids have been renumbered", backup.exists(),
          "" if backup.exists() else "the pre-renumber backup is missing",
          "run tools/renumber_ids.py --renumber, then --verify")

    declared = cfg["paths"].get("answers_phase3")
    answers = PROJECT_ROOT / declared if declared else None
    ok = check("the phase-3 ideal answers are there",
               bool(answers) and answers.is_file(),
               answers.name if answers else "paths.answers_phase3 is not in config.yaml",
               "add answers_phase3 to config.yaml and run tools/regenerate_references.py")
    if ok and rows:
        ideal = [json.loads(l) for l in answers.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        have = {r["question_id"] for r in ideal}
        missing = [r["id"] for r in rows if r["id"] not in have]
        check("they cover all 99 questions", not missing,
              f"{len(have)} answers" + (f", missing {missing[:5]}" if missing else ""),
              "run tools/regenerate_references.py again")

        stale = [r["question_id"] for r in ideal if r.get("format") != REFERENCE_FORMAT]
        check("they were produced by the current reference format", not stale,
              f"format {REFERENCE_FORMAT}" if not stale else f"{len(stale)} rows out of date",
              "run tools/regenerate_references.py: the references on disk are older than the code")

    world = PROJECT_ROOT / "benchmark" / "dataset" / "world" / "id_map.json"
    check("the id map is there", world.exists(), "",
          "run tools/load_openproject_data.py: it writes it at the end")

    #the campaign builds its summary only at the end
    check("the aggregator is there", AGGREGATOR.exists(), AGGREGATOR.name,
          "aggregate_phase3.py is missing: an interrupted campaign could not be summarised")


def check_unit_tests():
    """ the offline suite, before anything that costs time """
    section("2. THE UNIT TESTS  (offline, a few seconds)")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/unit"],
                            cwd=PROJECT_ROOT, capture_output=True, text=True)
    last = [l for l in result.stdout.strip().splitlines() if l.strip()]
    check("tests/unit passes", result.returncode == 0,
          last[-1] if last else "",
          "run: pytest -q tests/unit -- do not launch the campaign on broken metrics")


def check_keys():
    section("3. THE KEYS  (in .env, never in the dataset)")
    for username in ACCOUNTS:
        key = api_key_for(username)
        check(f"key for {username}", bool(key),
              "present" if key else "absent",
              f"add {ACCOUNTS[username]['key_env']} to .env")


def check_openproject():
    section("4. OPENPROJECT  (the network)")
    key = api_key_for(CAMPAIGN_USER)
    if not key:
        check("connection", False, "no key, cannot try")
        return
    try:
        mark = time.perf_counter()
        response = requests.get(f"{API_V3}users/me", auth=("apikey", key), timeout=15)
        elapsed = round(time.perf_counter() - mark, 2)
        ok = check("it answers", response.status_code == 200,
                   f"HTTP {response.status_code} in {elapsed}s",
                   "check OP_URL in .env and that the instance is up")
        if ok:
            me = response.json()
            check("the key is the right one", True, me.get("login") or me.get("name"))
    except Exception as e:
        check("it answers", False, str(e)[:60], "the instance is not reachable")


def check_ollama():
    section("5. OLLAMA AND THE TWO MODELS")
    base = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        response = requests.get(f"{base}/api/tags", timeout=10)
        response.raise_for_status()
        installed = {m["name"] for m in response.json().get("models", [])}
        check("ollama answers", True, f"{len(installed)} models installed")
        for model in MODELS:
            present = model in installed or any(m.startswith(model) for m in installed)
            check(f"model {model}", present, "", f"ollama pull {model}")
    except Exception as e:
        check("ollama answers", False, str(e)[:60], "start ollama and try again")


def check_embedder():
    section("6. THE COSINE SIMILARITY  (the phase-2 embedder)")
    for p in (PROJECT_ROOT / "benchmark" / "scripts",
              PROJECT_ROOT / "benchmark" / "scripts" / "phase_2"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from embedder import EMBEDDING_MODEL, CachedEmbedder, get_embedder
        embedder = CachedEmbedder(get_embedder())
        score = embedder.cosine("I found 2 work packages: Alpha (id 1, status New).",
                                "I found 2 work packages: Alpha (id 1, status New).")
        check("the embedder loads", True, EMBEDDING_MODEL)
        check("two identical sentences give ~1.0", score > 0.99, f"{round(score, 4)}")
    except Exception as e:
        check("the embedder loads", False, str(e)[:70],
              "the campaign still runs with --no-cosine, but without cosine similarity")


WRITE_ACTIONS = ("work_packages/create", "work_packages/update",
                 "projects/create", "projects/update")

#where each of them may write
WRITE_SCOPE = {
    "mario.rossi": set(),
    "giulia.bianchi": {"Mobile App", "Data Migration"},
}


def check_roles():
    """ loading work packages authored by Mario means giving him the Member role for a while """
    section("7. THE TEMPORARY ROLES  (is the permission matrix still the one measured?)")
    for username, allowed in WRITE_SCOPE.items():
        key = api_key_for(username)
        if not key:
            continue
        try:
            response = requests.get(f"{API_V3}capabilities",
                                    params={"pageSize": 1000,
                                            "filters": json.dumps([{"principal": {
                                                "operator": "=",
                                                "values": [str(ACCOUNTS[username]["op_user_id"])]}}])},
                                    auth=("apikey", key), timeout=20)
            response.raise_for_status()
            writes = set()
            total = 0
            for el in response.json().get("_embedded", {}).get("elements", []):
                total += 1
                links = el.get("_links", {})
                href = (links.get("action") or {}).get("href", "")
                if "/actions/" not in href:
                    continue
                action = href.split("/actions/", 1)[1]
                if action in WRITE_ACTIONS:
                    writes.add((action, (links.get("context") or {}).get("title") or "global"))

            unexpected = sorted({p for _, p in writes} - allowed)
            expected_text = ", ".join(sorted(allowed)) or "no project"
            check(f"{username} writes only where allowed  ({expected_text})",
                  not unexpected,
                  f"also: {', '.join(unexpected)}" if unexpected
                  else f"{total} capabilities, writes on {len({p for _, p in writes})} projects",
                  "remove the Member role from the extra projects: it was only for the loading")
        except Exception as e:
            check(f"{username} writes only where allowed", False, str(e)[:60],
                  "check the roles by hand in the UI")


def check_cells(cfg):
    section("8. SEVEN REAL CELLS  (the models run here: a few minutes)")
    print("  one question per branch: read wp/projects, create wp/project,")
    print("  update wp/project, out of domain.\n")

    mark = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--repetitions", "1", "--label", "smoke",
         "--no-index", "--only", ",".join(SMOKE_QUESTIONS)],
        cwd=PROJECT_ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - mark

    print(result.stdout[-2500:] if result.stdout else "(no output)")
    if result.returncode != 0:
        print(result.stderr[-1500:])
    ok = check("the campaign runs", result.returncode == 0, f"in {round(elapsed)}s",
               "read the error above: it is the same one you would get after forty hours")
    if not ok:
        return

    check_cells_are_complete(cfg)

    per_cell = elapsed / len(SMOKE_QUESTIONS)
    reps = cfg.get("repetitions_phase3") or cfg["repetitions"]
    total = per_cell * 99 * reps
    print(f"\n  ~{round(per_cell, 1)}s per cell  ->  99 questions x {reps} repetitions "
          f"= about {round(total / 3600, 1)} hours")
    print("  (optimistic: the first cold call is already inside this average)")
    if total / 3600 > 20:
        print("  longer than a night: --difficulty easy|medium|hard splits it into three runs,")
        print("  and aggregate_phase3.py --run a,b,c --into <name> puts them back together.")


def check_cells_are_complete(cfg):
    """ the run just written carries what a re-score needs """
    runs_dir = PROJECT_ROOT / cfg["paths"]["runs"]
    smoke_runs = sorted(runs_dir.glob("*__phase3__smoke"))
    if not smoke_runs:
        check("the cells carry the context", False, "no smoke run found")
        return
    cells_files = sorted(smoke_runs[-1].glob("models/*/cells.jsonl"))
    if not cells_files:
        check("the cells carry the context", False, "cells.jsonl not found")
        return

    cells = [json.loads(l) for l in cells_files[0].read_text(encoding="utf-8").splitlines()
             if l.strip()]
    answered = [c for c in cells if c.get("answer_generated")]
    missing = sorted({f for c in answered for f in REQUIRED_CELL_FIELDS if f not in c})
    check("the cells carry the context", not missing,
          f"{len(cells)} cells" + (f", missing {missing}" if missing else ""),
          "run_cell must store them: without them the campaign cannot be scored again")


def main():
    args = parse_args()
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    print("=" * 78)
    print("SMOKE TEST -- phase 3")
    print("=" * 78)

    check_files(cfg)
    check_unit_tests()
    check_keys()
    check_openproject()
    check_ollama()
    check_embedder()
    check_roles()
    if not args.skip_cells:
        check_cells(cfg)

    failed = [name for name, ok, _, _ in checks if not ok]
    section("VERDICT")
    print(f"  {len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        print("\n  not passed:")
        for name in failed:
            print(f"    - {name}")
        print("\n  do not launch the campaign until they are all green: every line above is a way")
        print("  of getting numbers that look valid and are not.")
        return 1

    print("\n  All good. The campaign is launched with:")
    print("    python benchmark/scripts/phase_3/run_phase3.py --label campagna")
    return 0


if __name__ == "__main__":
    sys.exit(main())
