#functions to normalize values and validate the schema, used not only for the tests but also for the creation of the URL

def normalize_value(v) -> str:
    return str(v).strip().lower()


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
