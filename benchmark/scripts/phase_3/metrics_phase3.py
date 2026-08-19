""" phase-3 metrics

- reference_from_result: expected values, read off the answer OpenProject really gave
- canonical_answer     : the same answer rendered as a sentence, for the cosine similarity
- score_stage2         : coverage, consistency, response type and the binary verdict of one cell
- aggregate            : the run summary, with the two models kept apart
- by_question          : the same numbers per question, over the repetitions

"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent              # benchmark/scripts/phase_3/
SCRIPTS_DIR = HERE.parent
PROJECT_ROOT = SCRIPTS_DIR.parents[1]
for p in (PROJECT_ROOT, SCRIPTS_DIR, HERE, SCRIPTS_DIR / "phase_1", SCRIPTS_DIR / "phase_2"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import gate
from json_pruning import pagination_warning
from metrics_phase1 import count_distinct, stability
from metrics_phase2 import (
    mentions, question_category, response_type_check, segments,
)
from structural_validation import normalize_value


REFERENCE_FORMAT = 2

#a correct query that found nothing
NO_RESULT = "System Info: no result"

#the refusal sentence for phase-2 prompt
CANONICAL_REFUSAL = ("I'm sorry, I can only read, create and update OpenProject projects and work "
                     "packages -- I can't help with that.")

CANONICAL_NO_RESULT = "I did not find any {what} matching that."

#how a payload field reads in a sentence, for the canonical answer only
FIELD_LABEL = {
    "subject": "the subject", "name": "the name", "description": "the description",
    "status": "the status", "priority": "the priority", "type": "the type",
    "assignee": "the assignee", "project": "the project", "version": "the version",
    "startDate": "the start date", "dueDate": "the due date",
    "active": "the active flag", "public": "the public flag",
}

#OpenProject uses booleans 't' and 'f', which are not contained in a natural sentence
BOOLEAN_ALTERNATIVES = {
    ("active", "t"): ["true", "yes", "enabled", "running", "unarchived"],
    ("active", "f"): ["false", "archived", "archiving", "inactive", "disabled", "not active"],
    ("public", "t"): ["true", "yes", "enabled", "visible to everyone", "publicly visible"],
    ("public", "f"): ["false", "private", "hidden", "not public", "invisible"],
}

BOOLEAN_TEXT = {"t": "true", "f": "false"}

def accepted(field, value):
    """ the wordings that count as reporting a value """
    alternatives = BOOLEAN_ALTERNATIVES.get((field, str(value)))
    return [str(value)] + alternatives if alternatives else str(value)


def reports(generated, expected) -> bool:
    """ like the function mentions() but including the possibility of a list of wordings """
    if isinstance(expected, list):
        return any(mentions(generated, v) for v in expected)
    return mentions(generated, expected)


def spelling(expected) -> str:
    """ the canonical spelling of an expected value """
    return expected[0] if isinstance(expected, list) else expected


def group(item, keys):
    """ the values of one item, in the order the prompt asks for them """
    return [str(item[k]) for k in keys if item.get(k) not in (None, "")]


def reference_from_result(final_data, notice=None):
    """ the expected values, taken from what the system got back: one group for a validated write,
    one group per item for a read, nothing for a 'System Info' string """
    if notice is not None:
        target = [accepted(k, v) for k, v in (notice.get("target") or {}).items()
                  if v not in (None, "")]
        fields = [accepted(k, v) for k, v in (notice.get("payload") or {}).items()
                  if v not in (None, "")]
        written = target + fields
        return [written] if written else []

    if not isinstance(final_data, dict):
        return []

    #a failed read arrives as {"error_message": "..."}
    items = final_data.get("items")
    if not items:
        return []

    groups = []
    for item in items:
        if item.get("entity") == "Project":
            groups.append(group(item, ["name", "id"]))
        else:
            groups.append(group(item, ["subject", "id", "status"]))
    return [g for g in groups if len(g) >= 2]


def plural(n, singular):
    return f"{n} {singular}" if n == 1 else f"{n} {singular}s"


def value_text(field, value):
    return BOOLEAN_TEXT.get(str(value), str(value)) if field in ("active", "public") else value


def readable(field, value):
    return f"{FIELD_LABEL.get(field, field)} to {value_text(field, value)}"


def canonical_answer(final_data, notice=None, macro_section=None):
    """ the same context rendered as the sentence, what the cosine similarity compares against """
    if notice is not None:
        payload = notice.get("payload") or {}
        target = notice.get("target") or {}
        section = notice.get("macro_section") or macro_section or "work_packages"
        thing = "project" if section == "projects" else "work package"

        if target:
            selector = ", ".join(f"{k} {value_text(k, v)}" for k, v in target.items())
            fields = ", ".join(readable(f, v) for f, v in payload.items())
            return f"I'm updating {thing} {selector}, setting {fields}."

        rest = dict(payload)
        kind = rest.pop("type", None)
        title = rest.pop("subject", None) or rest.pop("name", None)
        project = rest.pop("project", None)

        if kind is None and thing == "project":
            head = f"I'm creating the project {title}" if title else "I'm creating a project"
        else:
            head = f"I'm creating a {kind or thing}"
            if title:
                head += f" titled {title}"
        if project:
            head += f" in the {project} project"
        if rest:
            head += ", with " + ", ".join(f"{FIELD_LABEL.get(f, f)} {value_text(f, v)}"
                                          for f, v in rest.items())
        return head + "."

    message = final_data
    if isinstance(final_data, dict) and set(final_data) == {"error_message"}:
        message = final_data["error_message"]
    if isinstance(message, str):
        what = "projects" if macro_section == "projects" else "work packages"
        return CANONICAL_NO_RESULT.format(what=what) \
            if message.startswith(NO_RESULT) else CANONICAL_REFUSAL

    items = (final_data or {}).get("items") or []
    if not items:
        what = "projects" if macro_section == "projects" else "work packages"
        return CANONICAL_NO_RESULT.format(what=what)

   
    total = final_data.get("total_results")
    count = total if isinstance(total, int) and total >= len(items) else len(items)

    if items[0].get("entity") == "Project":
        listed = "; ".join(f"{i.get('name')} (id {i.get('id')})" for i in items)
        sentence = f"I found {plural(count, 'project')}: {listed}."
    else:
        listed = "; ".join(f"{i.get('subject')} (id {i.get('id')}, status {i.get('status')})"
                           for i in items)
        sentence = f"I found {plural(count, 'work package')}: {listed}."

    #the truncation notice, because the API appends it to the answer it returns
    warning = pagination_warning(final_data)
    return f"{sentence} {warning}" if warning else sentence


def effective_category(question, final_data):
    """ determines the final category, converts system-blocked operations to 'rejection' (out_of_scope) 
    and keeps the original category of the request in case of successes or reads without results """
    if isinstance(final_data, str) and not final_data.startswith(NO_RESULT):
        return "out_of_scope"
    if isinstance(final_data, dict) and set(final_data) == {"error_message"}:
        message = final_data["error_message"]
        if not str(message).startswith(NO_RESULT):
            return "out_of_scope"
    return question_category(question)


#score of one cell

def value_coverage(generated, key_values) -> dict:
    """ how many expected values the answer reports, out of how many were expected """
    expected = [v for entry in (key_values or [])
                for v in (entry if isinstance(entry, list) else [entry])
                if str(spelling(v)).strip()]
    if not expected:
        return {"coverage": None, "missing": []}

    seen, unique = set(), []
    for value in expected:
        key = normalize_value(spelling(value))
        if key not in seen:
            seen.add(key)
            unique.append(value)

    missing = [spelling(v) for v in unique if not reports(generated, v)]
    found = len(unique) - len(missing)
    return {"coverage": round(found / len(unique), 4), "missing": missing}


def item_consistency(generated, key_values) -> dict:
    """ are the values of each item reported together, or mixed between items """
    groups = [g for g in (key_values or []) if isinstance(g, list) and len(g) >= 2]
    applicable = len(groups) >= 2

    judged = [g for g in groups if all(reports(generated, v) for v in g)]
    if len(judged) < 2:
        return {"consistency": None, "mixed": [], "applicable": applicable}

    phrases = segments(generated)
    if len(phrases) < len(judged):
        return {"consistency": None, "mixed": [], "applicable": applicable}

    mixed = [[spelling(v) for v in g] for g in judged
             if not any(all(reports(phrase, v) for v in g) for phrase in phrases)]
    return {"consistency": round((len(judged) - len(mixed)) / len(judged), 4),
            "mixed": mixed, "applicable": applicable}


def score_stage2(generated, key_values, category, ideal_answer=None, embedder=None):
    """ the quality metrics of one answer plus stage2_perfect, which is true only when the answer
    is of the right type, reports every expected value and mixes none of them """
    coverage = value_coverage(generated, key_values)
    consistency = item_consistency(generated, key_values)
    response_type = response_type_check(generated, category, coverage["coverage"])

    perfect = bool(response_type["ok"])
    if perfect and coverage["coverage"] is not None:
        perfect = coverage["coverage"] == 1.0
    if perfect and consistency["consistency"] is not None:
        perfect = consistency["consistency"] == 1.0

    cosine = None
    if embedder is not None and ideal_answer:
        cosine = round(embedder.cosine(generated or "", ideal_answer), 4)

    return {
        "cosine_similarity": cosine,
        "value_coverage": coverage["coverage"],
        "missing_values": coverage["missing"],
        "item_consistency": consistency["consistency"],
        "mixed_items": consistency["mixed"],
        "consistency_applicable": consistency["applicable"],
        "response_type_ok": response_type["ok"],
        "response_type_reason": response_type["reason"],
        "stage2_perfect": perfect,
    }


#aggregation
DIFFICULTIES = ["easy", "medium", "hard"]
INTENTS = ["read", "create", "update"]
SECTIONS = ["work_packages", "projects", "out_of_scope"]


def median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return round(values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2, 2)


def rate(cells, key):
    """ fraction of cells where the metric is true """
    if not cells:
        return None
    return round(sum(1 for c in cells if c.get(key)) / len(cells), 3)


def mean(cells, key):
    """ mean over the cells where the metric is defined, None means not applicable """
    scored = [c[key] for c in cells if c.get(key) is not None]
    if not scored:
        return None
    return round(sum(scored) / len(scored), 4)


def phase1_metrics(cells):
    """ what the first model did, considering every cell (there's no gate in this phase)"""
    read_cells = [c for c in cells if c.get("unsafe_action") is not None]
    return {
        "cells": len(cells),
        "json_correct_rate": rate(cells, "json_correct"),
        "intent_accuracy": rate(cells, "intent_correct"),
        "macro_accuracy": rate(cells, "macro_correct"),
        "exact_filter_match": rate(cells, "filter_correct"),
        "exact_payload_match": rate(cells, "payload_correct"),
        "extraction_fully_correct": rate(cells, "stage1_ok"),
        "unsafe_action_rate": rate(read_cells, "unsafe_action"), #defined on the questions that were meant to be reads
        "unsafe_action_cells": len(read_cells), #defined on the questions that were meant to be reads
        "latency_median": median([c.get("t_phase1") for c in cells]),
    }


def phase2_metrics(cells):
    """ what the second model did, considering only the cells where it was really invoked, minus the
    refusals the system worded itself, which are counted apart as deterministic_answers """
    invoked = [c for c in cells if c.get("stage2_invoked")]
    generated = [c for c in invoked if c.get("answer_generated")]
    return {
        "cells_invoked": len(invoked),
        "cells_generated": len(generated),
        "deterministic_answers": len(invoked) - len(generated),
        "stage2_perfect_rate": rate(generated, "stage2_perfect"),
        "avg_cosine_similarity": mean(generated, "cosine_similarity"),
        "avg_value_coverage": mean(generated, "value_coverage"),
        "full_coverage_rate": (
            round(sum(1 for c in generated if c.get("value_coverage") == 1.0)
                  / sum(1 for c in generated if c.get("value_coverage") is not None), 4)
            if any(c.get("value_coverage") is not None for c in generated) else None),
        "avg_item_consistency": mean(generated, "item_consistency"),
        "observable_consistency_rate": (
            round(sum(1 for c in generated
                      if c.get("consistency_applicable") and c.get("item_consistency") is not None)
                  / sum(1 for c in generated if c.get("consistency_applicable")), 4)
            if any(c.get("consistency_applicable") for c in generated) else None),
        "response_type_accuracy": rate(
            [c for c in generated if "response_type_ok" in c], "response_type_ok"),
        "truncated_reads": sum(1 for c in generated if c.get("pagination_warning")),
        "latency_median": median([c.get("t_phase2") for c in generated]),
    }


def cascade_metrics(cells):
    """ what the system did, end_to_end_success divides by the evaluated cells, system_success_all_cells divides by every cell """
    evaluated = [c for c in cells if c.get("stage2_invoked")]
    success = [c for c in cells if c.get("stage1_ok") and c.get("stage2_perfect")]
    return {
        "cells": len(cells),
        "gate_pass_rate": gate.gate_pass_rate(cells) if cells else None,
        "cells_evaluated": len(evaluated),
        "end_to_end_success": (round(sum(1 for c in evaluated if c.get("stage2_perfect"))
                                     / len(evaluated), 3) if evaluated else None),
        "system_success_all_cells": round(len(success) / len(cells), 3) if cells else None,
        "errors": sum(1 for c in cells if c.get("error")),
        "latency_openproject_median": median(
            [c.get("t_openproject") for c in cells if (c.get("t_openproject") or 0) > 0]),
    }


def split(cells, key, values):
    """ non-empty subsets, in the declared order """
    return [(v, [c for c in cells if c.get(key) == v])
            for v in values
            if any(c.get(key) == v for c in cells)]


def by_question(cells):
    """ one row per question over its repetitions """
    rows = []
    for question_id in dict.fromkeys(c.get("question_id") for c in cells):
        runs = [c for c in cells if c.get("question_id") == question_id]
        first = runs[0]
        extractions = [c.get("extraction") for c in runs]
        answers = [c.get("answer") for c in runs if c.get("answer_generated")]
        scored = [c for c in runs if c.get("stage2_invoked") and c.get("answer_generated")]

        rows.append({
            "question_id": question_id,
            "difficulty": first.get("difficulty"),
            "intent": first.get("intent"),
            "macro_section": first.get("macro_section"),
            "repetitions": len(runs),
            "extraction_distinct": count_distinct(extractions),
            "extraction_deterministic": count_distinct(extractions) == 1,
            "extraction_stability": round(stability(extractions), 3),
            "gate_pass_rate": rate(runs, "stage1_ok"),
            "answers_generated": len(answers),
            "answer_distinct": count_distinct(answers) if answers else None,
            "answer_deterministic": (count_distinct(answers) == 1) if answers else None,
            "answer_stability": round(stability(answers), 3) if answers else None,
            "stage2_perfect_rate": rate(scored, "stage2_perfect"),
            "avg_cosine_similarity": mean(scored, "cosine_similarity"),
            "avg_value_coverage": mean(scored, "value_coverage"),
        })
    return rows


def stability_summary(rows):
    """ every question weighs one, whatever its repetitions """
    if not rows:
        return {}
    with_answers = [r for r in rows if r["answer_stability"] is not None]
    with_score = [r for r in rows if r["stage2_perfect_rate"] is not None]
    return {
        "questions": len(rows),
        "repetitions": max(r["repetitions"] for r in rows),
        "extraction_determinism_rate": round(
            sum(1 for r in rows if r["extraction_deterministic"]) / len(rows), 3),
        "extraction_stability": round(
            sum(r["extraction_stability"] for r in rows) / len(rows), 3),
        "answer_determinism_rate": round(
            sum(1 for r in with_answers if r["answer_deterministic"]) / len(with_answers), 3)
        if with_answers else None,
        "answer_stability": round(
            sum(r["answer_stability"] for r in with_answers) / len(with_answers), 3)
        if with_answers else None,
        "gate_pass_rate_by_question": round(
            sum(r["gate_pass_rate"] for r in rows) / len(rows), 3),
        "stage2_perfect_rate_by_question": round(
            sum(r["stage2_perfect_rate"] for r in with_score) / len(with_score), 3)
        if with_score else None,
    }


def aggregate(cells, model_phase1, model_phase2):
    """ the run summary. The two models stay in two blocks with different denominators, or a drop
    in end_to_end_success could not be attributed to either of them """
    def blocks(fn):
        return {
            "overall": fn(cells),
            "by_difficulty": {d: fn(sub) for d, sub in split(cells, "difficulty", DIFFICULTIES)},
            "by_intent": {i: fn(sub) for i, sub in split(cells, "intent", INTENTS)},
            "by_macro_section": {s: fn(sub)
                                 for s, sub in split(cells, "macro_section", SECTIONS)},
        }

    question_rows = by_question(cells)
    return {
        "cells": len(cells),
        "phase1": {"model": model_phase1, "role": "parameter extraction", **blocks(phase1_metrics)},
        "phase2": {"model": model_phase2, "role": "answer generation", **blocks(phase2_metrics)},
        "cascade": blocks(cascade_metrics),
        "stability": stability_summary(question_rows),
        "by_question": question_rows,
    }


def latency_summary(cells):
    """ median and mean per stage, openproject and phase2 count only the cells that reached them """
    summary = {}
    for stage in ("t_phase1", "t_openproject", "t_phase2"):
        values = [c.get(stage) for c in cells if c.get(stage) is not None]
        if stage == "t_openproject":
            values = [v for v in values if v > 0]
        summary[f"{stage}median"] = median(values)
        summary[f"{stage}mean"] = round(sum(values) / len(values), 2) if values else None
        summary[f"{stage}_cells"] = len(values)
    return summary


def flat_rows(summary, stage):
    """ one block of the summary as flat rows, one per cut. One file per stage: the three blocks
    have different columns, and stacking them would leave cells empty for two different reasons """
    block = summary[stage]
    rows = []
    for cut in ("overall", "by_difficulty", "by_intent", "by_macro_section"):
        pairs = [("all", block[cut])] if cut == "overall" else list(block[cut].items())
        for value, metrics in pairs:
            rows.append({"stage": stage, "model": block.get("model", "-"),
                         "cut": cut, "slice": value, **metrics})
    return rows
