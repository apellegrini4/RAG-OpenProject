from pathlib import Path
import numpy as np
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from structural_validation import normalize_value, schema_validation


def filter_pairs_set(filters) -> set:
    """ returns the set of (key, normalized_value) pairs found in filters dictionary """
    pairs_set = set()
    for key, values in (filters or {}).items():
        if not isinstance(values, list):
            values = [values]
        for value in values:
            pairs_set.add((key, normalize_value(value)))
    return pairs_set


def macro_match(pred, real) -> bool:
    """ checks only the macro-section """
    if not isinstance(pred, dict):
        return False
    return normalize_value(pred.get("macro_section")) == normalize_value(real.get("macro_section"))


def exact_filter_match(pred, real) -> bool:
    """ checks the (key,value) filter pairs, order and case insensitive """
    return filter_pairs_set(pred.get("filters")) == filter_pairs_set(real.get("filters"))


def exact_payload_match(pred, real) -> bool:
    """ same function as exact_filter_match but applied to the field payload """
    return filter_pairs_set(pred.get("payload")) == filter_pairs_set(real.get("payload"))


def intent_match(pred, real) -> bool:
    """ checks if the intent extracted is the one really wanted """
    if not isinstance(pred, dict):
        return False
    return normalize_value(pred.get("intent")) == normalize_value(real.get("intent"))


def write_intent(intent) -> bool:
    """ returns True if the intent is a create or an update """
    return normalize_value(intent) in ("create", "update")


def count_distinct(items) -> int:
    """ counts the number of distinct items ignoring the reasoning field"""
    distinct = []
    for item in items:
        #creates a new dictionary without the reasoning
        key = {k: v for k, v in item.items() if k != "reasoning"} if isinstance(item, dict) else item
        if key not in distinct:
            distinct.append(key)
    return len(distinct)


def stability(items) -> float:
    """ finds the response with more repetitions """
    if not items:
        return 0.0

    count_distinct = []
    for item in items:
        key = {k: v for k, v in item.items() if k != "reasoning"} if isinstance(item, dict) else item

        for c in count_distinct:
            if c[0] == key:
                c[1] += 1
                break
        else:
            count_distinct.append([key, 1])

    most_frequent_response = max(c[1] for c in count_distinct)
    return most_frequent_response / len(items)


def failure_reason(parsed, real: dict):
    """ describes the failure reason of a response in order from the most structural failure to the most specific """
    if parsed is None:
        return "parse_error"
    if not schema_validation(parsed):
        return "schema_invalid"
    if not intent_match(parsed, real):
        return "intent_mismatch"
    if not macro_match(parsed, real):
        return "macro_mismatch"
    if not exact_filter_match(parsed, real):
        return "filter_mismatch"
    if not exact_payload_match(parsed, real):
        return "payload_mismatch"
    return None


def evaluate_question(parsed_outputs: list, real: dict) -> dict:
    """ phase-1 metrics, the first output is kept as the representative extraction """

    first_out = parsed_outputs[0]
    n_distinct = count_distinct(parsed_outputs)
    deterministic = (n_distinct == 1) and (first_out is not None)

    total_reps = len(parsed_outputs)
    json_correct_count = 0
    macro_correct_count = 0
    filter_correct_count = 0
    intent_correct_count = 0
    payload_correct_count = 0
    unsafe_count = 0

    expected_read = normalize_value(real.get("intent", "read")) == "read"

    #every correctness metric is conditioned on the output respecting the schema
    for out in parsed_outputs:
        if schema_validation(out):
            json_correct_count += 1
            if intent_match(out, real):
                intent_correct_count += 1
            if macro_match(out, real):
                macro_correct_count += 1
            if exact_filter_match(out, real):
                filter_correct_count += 1
            if exact_payload_match(out, real):
                payload_correct_count += 1

            if expected_read and write_intent(out.get("intent")):
                unsafe_count += 1

    return {
        "deterministic": deterministic,
        "n_distinct_outputs": n_distinct,
        "json_correct_count": json_correct_count,
        "macro_correct_count": macro_correct_count,
        "filter_correct_count": filter_correct_count,
        "intent_correct_count": intent_correct_count,
        "payload_correct_count": payload_correct_count,
        "expected_read": expected_read,
        "unsafe_count": unsafe_count,
        "total_reps": total_reps,
        "stability": round(stability(parsed_outputs), 3),
        "first_output": first_out
    }


def summarize_stats(model: str, question_results: list, latencies: list) -> dict:
    """ aggregates results for a single model """
    n = len(question_results)

    det_count = 0
    total_json_correct = 0
    total_macro_correct = 0
    total_exact_filter = 0
    total_intent_correct = 0
    total_payload_correct = 0
    total_reps = 0
    stabilities = []
    total_unsafe = 0
    total_read_reps = 0

    #every dictionary here comes from evaluate_question, so all these keys are always present
    for r in question_results:
        det_count += r["deterministic"]
        total_json_correct += r["json_correct_count"]
        total_macro_correct += r["macro_correct_count"]
        total_exact_filter += r["filter_correct_count"]
        total_intent_correct += r["intent_correct_count"]
        total_payload_correct += r["payload_correct_count"]
        total_reps += r["total_reps"]
        stabilities.append(r["stability"])

        if r["expected_read"]:
            total_unsafe += r["unsafe_count"]
            total_read_reps += r["total_reps"]

    latencies = list(latencies)

    return {
        "model": model,
        "json_correct_rate": round(total_json_correct / total_reps, 3) if total_reps else 0.0,
        "intent_accuracy": round(total_intent_correct / total_reps, 3) if total_reps else 0.0,
        "macro_section_accuracy": round(total_macro_correct / total_reps, 3) if total_reps else 0.0,
        "exact_filter_match_rate": round(total_exact_filter / total_reps, 3) if total_reps else 0.0,
        "exact_payload_match_rate": round(total_payload_correct / total_reps, 3) if total_reps else 0.0,
        "unsafe_action_rate": round(total_unsafe / total_read_reps, 3) if total_read_reps else None,
        "determinism_rate": round(det_count / n, 3) if n else 0.0,
        "stability": round(sum(stabilities) / len(stabilities), 3) if stabilities else 0.0,
        "median_latency": round(float(np.median(latencies)), 3) if latencies else None,
        "p90_latency": round(float(np.percentile(latencies, 90)), 3) if latencies else None,
    }
