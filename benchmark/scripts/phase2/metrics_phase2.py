""" phase-2 metrics:

- value_coverage     : how much of the expected data the answer actually reports
- item_consistency   : are the values of each item reported correctly, or mixed between items?
- response_type_check: is the answer the right kind of answer?
- latency_stats      : median and p90

(cosine similarity is computed by CachedEmbedder in evaluate_phase2)
"""
from pathlib import Path
import re
import sys

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
for path in (SCRIPTS_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from structural_validation import normalize_value

INTENTS = ["read", "create", "update", "out_of_scope"]

#the three kinds of answer the model can produce
CATEGORY_TO_TYPE = {"read": "read", "create": "write", "update": "write",
                    "out_of_scope": "refusal"}

#regex context to decide if a bare number should count as a valid value
NUMBER_CONTEXT = (r'(?:id|ids|#|no\.?|number|work\s*packages?|wp|task|bug|feature|milestone'
                   r'|project|version|sprint)\s*#?\s*')

#separates one item from the next, identifies distinct phrases
SEGMENT = re.compile(r'[;\n]+|(?<=[.!?])\s+')

#to check if the model announces something that has not happened yet (an update or a create)
CLAIMS_DONE = re.compile(
    r"\b(?:"
    r"(?:has|have|had) been (?:created|updated|set|assigned|closed|changed|added|scheduled)"
    r"|(?:was|were) (?:created|updated|set|assigned|closed|changed|added|scheduled)"
    r"|i (?:have )?(?:created|updated|added|assigned|closed|set)"
    r"|successfully"
    r"|(?:is|has) now"
    r")\b", re.IGNORECASE)

#to check if the model is answering 
REFUSES = re.compile(
    r"\b(?:sorry|can'?t|cannot|unable|not able|don'?t have|do not have"
    r"|only (?:read|help|answer|handle|manage))\b", re.IGNORECASE)


def question_category(question: dict) -> str:
    """ returns the class of a question as the dataset declares it """
    return "out_of_scope" if question["macro_section"] == "out_of_scope" else question["intent"]


def latency_stats(latencies: list):
    """ calculates the median and the p90 """
    if not latencies:
        return None, None
    return (round(float(np.median(latencies)), 3),
            round(float(np.percentile(latencies, 90)), 3))


def mentions(text: str, value: str) -> bool:
    """ does the answer report this value? """
    if not value:
        return False

    escaped = re.escape(value)
    pattern = (rf'(?:{NUMBER_CONTEXT}{escaped}(?!\w))|(?<!\w){escaped}\s*%'
               if value.isdigit()
               #if the value is a string, searchs for an 'isoleted' string 
               else rf'(?<!\w){escaped}(?!\w)')

    return re.search(pattern, text or "", re.IGNORECASE) is not None


def flatten(key_values) -> list:
    """ flattens the expected values (inside key_values) as one list """
    values = key_values or []

    if values and isinstance(values[0], str):
        return list(values)
    return [v for group in values for v in group]


def segments(text: str) -> list:
    """splits the text in phrases"""
    return [s.strip() for s in SEGMENT.split(text or "") if s.strip()]


def value_coverage(generated: str, key_values) -> dict:
    """ how many expected values are in the response, out of how many were expected """

    #takes the expected values and flattens them into a single list
    expected = [v for v in flatten(key_values) if str(v).strip()]
    if not expected:
        return {"coverage": None, "missing": []}

    #deduplicates using the normalized form, but keeps the original spelling for the final report
    seen, unique = set(), []

    #goes through the list of expected values
    for value in expected:
        if normalize_value(value) not in seen:
            seen.add(normalize_value(value))
            unique.append(value)

    #looks for any missing value in the entire generated text
    missing = [v for v in unique if not mentions(generated, v)]
    found = len(unique) - len(missing)
    return {"coverage": round(found / len(unique), 4), "missing": missing}


def item_consistency(generated: str, key_values) -> dict:
    """ checks if the values of each item are reported together or mixed between items,
    consistency might be None, in this case means not judged:
      - fewer than two items were reported in full
      - the answer lists item in a single sentence """

    groups = [g for g in (key_values or []) if isinstance(g, list) and len(g) >= 2]

    #applicable says if a mix-up was possible or not, depends only on the question --> two or more items were expected
    applicable = len(groups) >= 2

    #only the items whose values are all present are judged
    judged = [g for g in groups if all(mentions(generated, v) for v in g)]
    if len(judged) < 2:
        return {"consistency": None, "mixed": [], "applicable": applicable}

    phrases = segments(generated)
    if len(phrases) < len(judged):
        return {"consistency": None, "mixed": [], "applicable": applicable}

    #a judged item is mixed when no single phrase holds all of its values
    mixed = [g for g in judged
             if not any(all(mentions(phrase, v) for v in g) for phrase in phrases)]
    return {"consistency": round((len(judged) - len(mixed)) / len(judged), 4),
            "mixed": mixed, "applicable": applicable}


def claims_done(generated: str) -> bool:
    """ checks if the models state that an operation of write has already been done """
    return CLAIMS_DONE.search(generated or "") is not None


def response_type_check(generated: str, category: str, coverage) -> dict:
    """ is this the right kind of answer?
      read    -> reports at least part of the expected data, and does not claim a write
      write   -> announces that the operation has already been done (in case of update/create)
      refusal -> says it cannot help """
    text = generated or ""
    expected_type = CATEGORY_TO_TYPE.get(category)

    if not text.strip():
        return {"ok": False, "reason": "empty_answer"}

    if expected_type == "read":
        if claims_done(text):
            return {"ok": False, "reason": "claims_a_write"}
        
        if coverage is not None and coverage == 0.0:
            return {"ok": False, "reason": "reports_no_data"}
        return {"ok": True, "reason": None}

    if expected_type == "write":
        if claims_done(text):
            return {"ok": False, "reason": "claims_already_done"}
        return {"ok": True, "reason": None}

    if expected_type == "refusal":
        if not REFUSES.search(text):
            return {"ok": False, "reason": "does_not_refuse"}
        return {"ok": True, "reason": None}

    return {"ok": False, "reason": f"unknown_category:{category}"}


#calculates the mean for each metric
def avg_cosine(cells: list):
    scored = [c for c in cells if c.get("cosine_similarity") is not None]
    if not scored:
        return None
    return round(sum(c["cosine_similarity"] for c in scored) / len(scored), 4)


def avg_value_coverage(cells: list):
    """ mean coverage over the cells where data was expected (refusals excluded) """
    scored = [c for c in cells if c.get("value_coverage") is not None]
    if not scored:
        return None
    return round(sum(c["value_coverage"] for c in scored) / len(scored), 4)


def full_coverage_rate(cells: list):
    """ share of cells that reported EVERY expected value """
    scored = [c for c in cells if c.get("value_coverage") is not None]
    if not scored:
        return None
    return round(sum(1 for c in scored if c["value_coverage"] == 1.0) / len(scored), 4)


def avg_item_consistency(cells: list):
    """ mean over the cells where the pairing could be judged at all """
    scored = [c for c in cells if c.get("item_consistency") is not None]
    if not scored:
        return None
    return round(sum(c["item_consistency"] for c in scored) / len(scored), 4)


def observable_consistency_rate(cells: list):
    """ share of cells where item_consistency could be computed
    The denominator is the cells where a mix-up was possible, not every cell """

    applicable = [c for c in cells if c.get("consistency_applicable")]
    if not applicable:
        return None
    return round(sum(1 for c in applicable
                     if c.get("item_consistency") is not None) / len(applicable), 4)


def response_type_accuracy(cells: list):
    """ share of cells whose answer is the right kind of answer """
    scored = [c for c in cells if "response_type_ok" in c]
    if not scored:
        return None
    return round(sum(1 for c in scored if c["response_type_ok"]) / len(scored), 4)


QUALITY_METRICS = ["avg_cosine_similarity", "avg_value_coverage", "full_coverage_rate",
                   "avg_item_consistency", "observable_consistency_rate",
                   "response_type_accuracy"]


def quality_metrics(cells: list) -> dict:
    return {
        "avg_cosine_similarity": avg_cosine(cells),
        "avg_value_coverage": avg_value_coverage(cells),
        "full_coverage_rate": full_coverage_rate(cells),
        "avg_item_consistency": avg_item_consistency(cells),
        "observable_consistency_rate": observable_consistency_rate(cells), #on how many cells the consistency could be observed at all
        "response_type_accuracy": response_type_accuracy(cells),
    }


def summarize(model: str, cells: list) -> dict:
    """ one row: every cell of the matrix for this model """
    median, p90 = latency_stats([r["latency"] for r in cells])
    return {"model": model, "cells": len(cells), **quality_metrics(cells),
            "median_latency": median, "p90_latency": p90}


def summarize_by_intent(model: str, cells: list) -> list:
    """ same metrics but divided per intent """
    rows = []
    for intent in INTENTS:
        subset = [r for r in cells if r["category"] == intent]
        if subset:
            rows.append({"model": model, "intent": intent, "cells": len(subset),
                         **quality_metrics(subset)})
    return rows
