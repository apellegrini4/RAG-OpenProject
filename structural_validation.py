#functions to normalize values and validate the schema, used not only for the tests but also for the creation of the URL
import re

def normalize_value(v) -> str:
    return str(v).strip().lower()

#date filters: only startDate/dueDate exist (work packages only)
DATE_FIELDS = {"startDate", "dueDate"}
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def resolve_date_filter(val_list):
    """ deduces the date operator from the shape of the extracted list """
    if not isinstance(val_list, list) or not val_list:
        return None, None, "empty or invalid date filter"

    normalized = [normalize_value(v) for v in val_list]

    if any(v == "today" for v in normalized):
        return "t", [], None
    if any(v == "this week" for v in normalized):
        return "w", [], None

    if len(val_list) == 1:
        if not ISO_DATE_RE.match(normalized[0]):
            return None, None, f"'{val_list[0]}' is not a valid YYYY-MM-DD date"
        return "=d", [normalized[0]], None

    if len(val_list) == 2:
        if not all(ISO_DATE_RE.match(v) for v in normalized):
            return None, None, f"date range values must both be YYYY-MM-DD: {val_list}"
        return "<>d", normalized, None

    return None, None, (f"date filter must be a single date, a 2-date range, or the keyword "
                        f"'today'/'this week': {val_list}")


def schema_validation(obj) -> bool:
    """ returns True if obj is a dict with a string macro_section/intent and filters/payload (both must be a dicts of lists) """
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("macro_section"), str)
        and isinstance(obj.get("intent"), str)
        and isinstance(obj.get("filters"), dict)
        and all(isinstance(values, list) for values in obj["filters"].values())
        and isinstance(obj.get("payload"), dict)
        and all(isinstance(values, list) for values in obj["payload"].values())
    )
