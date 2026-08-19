""" Builds the world: a single state of the instance, taken from the phase-2 mocks.
    Only the read mocks describe a state and they contradict each other, so conflicts are
    resolved by rule and what is left is decided by hand in TIE_BREAKS.

    usage: python tools/build_world.py
"""

import collections
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "benchmark" / "dataset"
MOCK_DIR = DATASET / "mock_data"
OUT_DIR = DATASET / "world"

#The world taken from the reads does not contain everything needed. Three gaps, and how they are filled.

#1
WRITE_ONLY_WORK_PACKAGES = [
    {"id": 15, "subject": "Import the 2024 invoices", "status": "In progress", "type": "Task",
     "project": "Data Migration", "assignee": "Giulia Bianchi", "priority": "Normal",
     "_why": "two questions close it, and one of them also assigns it to Alba, so it has to exist, "
             "not be closed already, and not already have her as assignee."},
    {"id": 63, "subject": "Update the vendor contact list", "status": "New", "type": "Task",
     "project": "Mobile App", "assignee": "Giulia Bianchi", "priority": "Normal",
     "_why": "a question moves it to another project and puts it back in progress, so it has to "
             "start somewhere else and in a different state, or the write changes nothing."},
]

#2
DEFAULT_PROJECT = ("Mobile App",
                   "no mock gives this one a project, but its version is the one of two work packages "
                   "that both live in Mobile App.")

#3
PROJECT_ID_OVERRIDES = {
    "7": ("Internal Audit",
          "id 7 carries two names across the mocks. The one that wins is the question that names "
          "the id in its own text, since that is the one that would break."),
    "6": ("Design System",
          "no mock gives a name to id 6, but a question names it. It only has to point at a project "
          "that exists: that question changes the description, a field no read reports, so the "
          "choice touches nothing else."),
}

#the three ties neither the filter rule nor the majority settles, decided by reading the questions
TIE_BREAKS = {
    ("work_packages", 8, "dueDate"): (
        "2026-09-03",
        "a question filters due dates inside September and its mock contains this item, so the "
        "other two candidate dates, both in August, would make it disappear from that result."),
    ("work_packages", 87, "status"): (
        "New",
        "no question filters on the status of this item: it is selected by id, by author or by "
        "date, so the status is only reported and the choice makes nobody lose it."),
    ("projects", "data migration", "public"): (
        True,
        "a real contradiction: one question wants the active public projects with 'migration' in "
        "the name and expects this one, another wants the active private ones and expects it too. "
        "One of them loses it either way. Kept public, the other question still returns two "
        "private projects and stays meaningful; kept private, the first one drops to a single "
        "result."),
}


def normalize(value):
    return str(value).strip().lower()


def load_questions():
    path = DATASET / "questions_90.jsonl"
    return {json.loads(l)["id"]: json.loads(l)
            for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def filtered_values(questions):
    """ (field, value) -> the questions that filter on it, the ones that would lose the item if the world picked a """
    index = collections.defaultdict(set)
    for q in questions.values():
        for field, values in (q.get("filters") or {}).items():
            for v in values:
                index[(field, normalize(v))].add(q["id"])
    return index


def collect_claims(questions):
    """ (kind, id) -> field -> [(serialised value, the question that claims it)] """
    claims = collections.defaultdict(lambda: collections.defaultdict(list))
    project_names = collections.defaultdict(collections.Counter)
    order = []
    for path in sorted(MOCK_DIR.glob("mock_*.json")):
        qid = path.stem.replace("mock_", "")
        if questions.get(qid, {}).get("intent") != "read":
            continue                      #only the reads describe a state
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        items = data.get("items") or ([data] if data.get("entity") else [])
        for item in items:
            if not isinstance(item, dict) or "id" not in item:
                continue
            if item.get("entity") == "Project":
                #projects are keyed by name and not by id: see the note at the top of the file
                if not item.get("name"):
                    continue
                #the name stays an ordinary field: being the key, it cannot be in conflict
                key = ("projects", normalize(item["name"]))
                skip = ("entity", "id")
                project_names[str(item["id"])][item["name"]] += 1
            else:
                key = ("work_packages", item["id"])
                skip = ("entity", "id")
            if key not in order:
                order.append(key)
            for field, value in item.items():
                if field not in skip:
                    claims[key][field].append((json.dumps(value), qid))
    return claims, order, project_names


def build():
    questions = load_questions()
    filters = filtered_values(questions)
    claims, order, project_names = collect_claims(questions)

    world = {"work_packages": [], "projects": []}
    decisions = []

    for kind, oid in order:
        #for a project the key is the name: the real id comes from OpenProject at loading time
        obj = {} if kind == "projects" else {"id": oid}
        for field, entries in claims[(kind, oid)].items():
            counts = collections.Counter(v for v, _ in entries)

            if len(counts) == 1:
                obj[field] = json.loads(next(iter(counts)))
                continue

            manual = TIE_BREAKS.get((kind, oid, field))
            if manual:
                chosen, why = manual
                rule = "deciso a mano"
            else:
                ranked = sorted(
                    ((len(filters.get((field, normalize(json.loads(v))), set())), n, v)
                     for v, n in counts.items()), reverse=True)
                chosen = json.loads(ranked[0][2])
                rule = ("filtrato da una domanda" if ranked[0][0] else "maggioranza")
                why = ""

            obj[field] = chosen
            contradicted = sorted({q for v, q in entries if json.loads(v) != chosen})
            decisions.append({
                "object": f"project '{oid}'" if kind == "projects" else f"WP{oid}",
                "field": field,
                "chosen": chosen, "rule": rule, "why": why,
                "rejected": sorted({json.loads(v) if not isinstance(json.loads(v), bool)
                                    else json.loads(v)
                                    for v, _ in entries if json.loads(v) != chosen},
                                   key=str),
                "questions_contradicted": contradicted,
            })
        world[kind].append(obj)

    #three gaps the reads alone do not fill
    added = []
    for extra in WRITE_ONLY_WORK_PACKAGES:
        item = {k: v for k, v in extra.items() if not k.startswith("_")}
        world["work_packages"].append(item)
        added.append((item["id"], extra["_why"]))

    default_project, default_why = DEFAULT_PROJECT
    orphans = [w for w in world["work_packages"] if not w.get("project")]
    for w in orphans:
        w["project"] = default_project

    #project id in the mocks -> name in the world
    known = {name for name in (p["name"] for p in world["projects"])}
    project_ids, ambiguous = {}, []
    for pid, names in project_names.items():
        if pid in PROJECT_ID_OVERRIDES:
            continue
        winner = names.most_common(1)[0][0]
        if len(names) > 1:
            ambiguous.append((pid, dict(names)))
        project_ids[pid] = winner
    for pid, (name, why) in PROJECT_ID_OVERRIDES.items():
        project_ids[pid] = name
        if name not in known:
            print(f"warning: the override for id {pid} points at '{name}', which is not in the world.")
    world["project_ids"] = dict(sorted(project_ids.items(), key=lambda kv: int(kv[0])))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "world.json").write_text(
        json.dumps(world, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# The world loaded on the instance, and how the conflicts were resolved", "",
             f"{len(world['work_packages'])} work packages, {len(world['projects'])} projects, "
             f"taken from the {sum(1 for q in questions.values() if q['intent'] == 'read')} read "
             "mocks.", "",
             "Generated by `tools/build_world.py`. Do not edit by hand, change the script "
             "and run it again.", "",
             "| object | field | chosen | discarded | rule | questions contradicted |",
             "| --- | --- | --- | --- | --- | --- |"]
    for d in decisions:
        lines.append(f"| {d['object']} | `{d['field']}` | `{d['chosen']}` | "
                     f"{', '.join(f'`{r}`' for r in d['rejected'])} | {d['rule']} | "
                     f"{', '.join(d['questions_contradicted']) or '—'} |")

    manual = [d for d in decisions if d["rule"] == "deciso a mano"]
    if manual:
        lines += ["", "## Ties decided by hand", ""]
        for d in manual:
            lines += [f"**{d['object']}.{d['field']} = `{d['chosen']}`** — {d['why']}", ""]

    lines += ["", "## What the reads did not say", "",
              "Three gaps the read mocks could not fill, because they concern items only the write "
              "questions name.", ""]
    for wp_id, why in added:
        lines += [f"**Work package {wp_id} added** - {why}", ""]
    if orphans:
        lines += [f"**Project assigned to work packages {', '.join(str(w['id']) for w in orphans)}"
                  f": {default_project}** - {default_why}", ""]
    lines += ["### From project id to name", "",
              "The questions select projects by id, the world keys them by name, and the ids in the "
              "mocks are not reproducible. This table is the translation, and it ends up in "
              "`world.json` under `project_ids`.", "",
              "| id in the mocks | name | source |", "| --- | --- | --- |"]
    for pid, name in world["project_ids"].items():
        source = "decided by hand" if pid in PROJECT_ID_OVERRIDES else "from the mocks"
        lines.append(f"| {pid} | {name} | {source} |")
    lines.append("")
    for pid, (name, why) in PROJECT_ID_OVERRIDES.items():
        lines += [f"**id {pid} to {name}** - {why}", ""]

    contradicted = sorted({q for d in decisions for q in d["questions_contradicted"]})
    lines += ["", "## Questions whose ideal answer has to be rebuilt", "",
              "The chosen world contradicts them: what they will find on the instance is not what "
              "their mock described.", "",
              ", ".join(f"`{q}`" for q in contradicted) or "none", ""]

    (OUT_DIR / "world_conflicts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"world: {len(world['work_packages'])} work packages, {len(world['projects'])} projects")
    print(f"added because only the writes name them: "
          f"{[wp_id for wp_id, _ in added]}")
    if orphans:
        print(f"no project in the mocks, assigned to '{default_project}': "
              f"{[w['id'] for w in orphans]}")
    print(f"project ids translated into names: {len(world['project_ids'])}"
          f"{' (' + str(len(ambiguous)) + ' ambiguous, resolved)' if ambiguous else ''}")
    print(f"conflicts resolved: {len(decisions)}, {len(manual)} of them by hand")
    print(f"questions to regenerate: {len(contradicted)} -> {contradicted}")
    print(f"\nwritten:\n  {OUT_DIR / 'world.json'}\n  {OUT_DIR / 'world_conflicts.md'}")


if __name__ == "__main__":
    build()
