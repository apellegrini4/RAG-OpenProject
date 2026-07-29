from statistics import median

def normalize_value(v) -> str:
    return str(v).strip().lower()


def filter_pairs_set(filters) -> set:
    """ returns the set of (key, normalized_value) pairs found in filters dictionary """
    pairs_set = set()
    for key, values in (filters or {}).items():
        if not isinstance(values, list):
            values = [values]
        for value in values:
            pairs_set.add((key, normalize_value(value)))
    return pairs_set


def schema_validation(obj) -> bool:
    """ returns True if obj is a dict with a string macro_section and filters as a dict of lists """
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("macro_section"), str)
        and isinstance(obj.get("filters"), dict)
        and all(isinstance(values, list) for values in obj["filters"].values())
    )


def exact_filter_match(pred, real) -> bool:
    """ returns True if macro_section and the (key,value) filter pairs match (order/case insensitive) """
    if not isinstance(pred, dict):
        return False
    if normalize_value(pred.get("macro_section")) != normalize_value(real.get("macro_section")):
        return False

    return filter_pairs_set(pred.get("filters", {})) == filter_pairs_set(real.get("filters", {}))


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
    """finds the response with more repetitions """
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
    """ describes the failure reason of a response, given 3 type of errors"""
    if parsed is None:
        return "parse_error"
    if not schema_validation(parsed):
        return "schema_invalid"
    if not exact_filter_match(parsed, real):
        return "exact_mismatch"
    return None


def evaluate_question(parsed_outputs: list, real: dict) -> dict:
    """ phase-1 metrics, the first output is kept as the representative extraction """

    first_out = parsed_outputs[0]
    n_distinct = count_distinct(parsed_outputs)
    deterministic = (n_distinct == 1) and (first_out is not None)

    total_reps = len(parsed_outputs)
    json_correct_count = 0
    exact_match_count = 0

    for out in parsed_outputs:
        if schema_validation(out):
            json_correct_count += 1
            if exact_filter_match(out, real):
                exact_match_count += 1

    return {
        "deterministic": deterministic,
        "n_distinct_outputs": n_distinct,
        "json_correct_count": json_correct_count,
        "exact_match_count": exact_match_count,
        "total_reps": total_reps,
        "stability": round(stability(parsed_outputs), 3),
        "first_output": first_out
    }


def summarize_stats(model: str, question_results: list, latencies: list) -> dict:
    """ aggregates results for a single model """
    n = len(question_results)

    det_count = 0
    total_json_correct = 0
    total_exact_filter = 0
    total_reps = 0
    stabilities = []

    for r in question_results:
        det_count += r["deterministic"]
        total_json_correct += r.get("json_correct_count", 0)
        total_exact_filter += r.get("exact_match_count", 0)
        total_reps += r.get("total_reps", 1)
        stabilities.append(r.get("stability", 0.0))

    return {
        "model": model,
        "determinism_rate": round(det_count / n, 3) if n else 0.0,
        "json_correct_rate": round(total_json_correct / total_reps, 3) if total_reps else 0.0,
        "exact_filter_match_rate": round(total_exact_filter / total_reps, 3) if total_reps else 0.0,
        "stability": round(sum(stabilities) / len(stabilities), 3) if stabilities else 0.0,
        "median_latency": round(median(latencies), 3) if latencies else None,
    }
