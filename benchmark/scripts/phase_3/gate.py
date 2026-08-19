""" the gate between the two stages: the second model is invoked only when the first did not fail.

A failure of the first model is invalid JSON, an extraction that does not match the one the dataset
expects, or a transport error towards OpenProject. A refusal is not a failure: an out of domain
question, a permission denial, an empty result and a validated write all pass, because wording those
is the job of the second model
"""

from pathlib import Path
import sys

PHASE3_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = PHASE3_DIR.parent
PROJECT_ROOT = SCRIPTS_DIR.parents[1]
for p in (PROJECT_ROOT, SCRIPTS_DIR / "phase_1"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from metrics_phase1 import failure_reason


#the strings that mean a transport failure
_TRANSPORT_ERROR_MARKERS = (
    "communication error",           #fetch_openproject_data
    "form validation call failed",   #validate_via_form, HTTP error other than 403
    "could not reach openproject",   # validate_via_form / commit_write, network exception
)


def is_transport_error(final_data) -> bool:
    """ checks if the output of execute() is a transport failure or not """
    #a read wraps any error as {"error_message": ...}, it's no longer a string
    if isinstance(final_data, dict) and set(final_data.keys()) == {"error_message"}:
        final_data = final_data["error_message"]

    if not isinstance(final_data, str):
        return False

    #network exceptions and timeouts use "Error: ..." with no "System Info:" prefix
    if final_data.startswith("Error:"):
        return True

    lowered = final_data.lower()
    return any(marker in lowered for marker in _TRANSPORT_ERROR_MARKERS)


def extraction_ok(parsed, expected) -> tuple[bool, str | None]:
    """ the check on the extraction alone, without a network call """
    reason = failure_reason(parsed, expected)
    return reason is None, reason


def check_gate(parsed, expected, final_data) -> dict:
    """ checks if the second model can be invoked for this cell """
    ok, reason = extraction_ok(parsed, expected)
    if not ok:
        return {"stage1_ok": False, "block_reason": reason, "stage2_invoked": False}

    if final_data is not None and is_transport_error(final_data):
        return {"stage1_ok": False, "block_reason": "transport_error", "stage2_invoked": False}

    return {"stage1_ok": True, "block_reason": None, "stage2_invoked": True}


def gate_pass_rate(cells) -> float:
    """ fraction of cells where the first stage did not block the gate """
    if not cells:
        return 0.0
    return round(sum(1 for c in cells if c["stage1_ok"]) / len(cells), 3)


def cells_evaluated(cells) -> int:
    """ the denominator of the second model's metrics: how many cells actually invoked it """
    return sum(1 for c in cells if c["stage2_invoked"])


def end_to_end_success(cells) -> float | None:
    """ calculated only if stage1 and stage2 went well over the evaluated cells only """
    evaluated = [c for c in cells if c["stage2_invoked"]]
    if not evaluated:
        return None
    
    if any("stage2_ok" not in c for c in evaluated):
        raise KeyError("'stage2_ok' missing on at least one evaluated cell: the answer scoring "
                       "has to add it before end_to_end_success() is called")
    return round(sum(1 for c in evaluated if c["stage2_ok"]) / len(evaluated), 3)
