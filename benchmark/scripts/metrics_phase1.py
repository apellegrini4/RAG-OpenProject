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
    """ counts the number of distinct items """
    distinct = []
    for item in items:
        if item not in distinct:
            distinct.append(item)
    return len(distinct)


def evaluate_question(parsed_outputs: list, real: dict) -> dict:
    """ phase-1 metrics, the first output is kept as the representative extraction """
    # to do: (F1, precision, recall)

    first_out = parsed_outputs[0]
    n_distinct = count_distinct(parsed_outputs)
    deterministic = (n_distinct == 1) and (first_out is not None)
    json_correct = schema_validation(first_out)
    exact_match = exact_filter_match(first_out, real) if json_correct else False

    return {
        "deterministic": deterministic,
        "n_distinct_outputs": n_distinct,
        "json_correct": json_correct,
        "exact_filter_match": exact_match,
        "first_output": first_out,
    }


def summarize_stats(model: str, question_results: list, latencies: list) -> dict:
    """ aggregates results for a singol model """
    n = len(question_results)

    det_count = match_count = schema_count = 0
    for r in question_results:
        det_count += r["deterministic"]
        match_count += r["exact_filter_match"]
        schema_count += r["json_correct"]

    return {
        "model": model,
        "determinism_rate": round(det_count / n, 3) if n else 0.0,
        "json_correct_rate": round(schema_count / n, 3) if n else 0.0,
        "exact_filter_match_rate": round(match_count / n, 3) if n else 0.0,
        "median_latency": round(median(latencies), 3) if latencies else None,
    }
