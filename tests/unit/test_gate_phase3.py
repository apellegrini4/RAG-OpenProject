""" Unit tests for the phase-3 gate -- synthetic values only, no Ollama and no OpenProject """
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "scripts" / "phase_3"))
import gate


#(label, value, expected result of is_transport_error)
TRANSPORT_CASES = [
    # reads always come back wrapped
    ("no result, wrapped", {"error_message": "System Info: no result"}, False),
    ("communication error, wrapped",
     {"error_message": "System Info: communication error, error: 503)."}, True),
    ("timeout, wrapped", {"error_message": "Error: timed out"}, True),

    # writes stay bare
    ("form validation failed, bare", "System Info: form validation call failed, error 500.", True),
    ("could not reach OpenProject, bare",
     "System Info: could not reach OpenProject to validate, error: timeout.", True),
    ("permission denied, bare",
     "System Info: permission denied, you are not allowed to perform this action.", False),

    # refused before a request was built: bare, even though the intent was a read
    ("out_of_scope, bare", "System Info: operation not allowed, query out of domain.", False),

    # positive outcomes
    ("successful read", {"total_results": 2, "number_of_results_in_the_page": 2, "items": []}, False),
    ("validated write", {"method": "POST", "url": "...", "body": {}, "ready_to_commit": True,
                         "commit_href": "/api/v3/work_packages", "commit_method": "post"}, False),
]


@pytest.mark.parametrize("label,value,expected",
                         TRANSPORT_CASES, ids=[c[0] for c in TRANSPORT_CASES])
def test_is_transport_error(label, value, expected):
    assert gate.is_transport_error(value) is expected


READ_QUESTION = {"intent": "read", "macro_section": "work_packages",
                 "filters": {"status": ["New"]}, "payload": {}}
GOOD = {"intent": "read", "macro_section": "work_packages",
        "filters": {"status": ["New"]}, "payload": {}}
WRONG_FILTER = {"intent": "read", "macro_section": "work_packages",
                "filters": {"status": ["Closed"]}, "payload": {}}


def test_wrong_extraction_blocks_and_says_why():
    verdict = gate.check_gate(WRONG_FILTER, READ_QUESTION, None)
    assert verdict["stage1_ok"] is False
    assert verdict["stage2_invoked"] is False
    assert verdict["block_reason"] == "filter_mismatch"


def test_correct_out_of_scope_passes():
    """ a refusal is not a failure of the first model: wording it is the second model's job """
    verdict = gate.check_gate(GOOD, READ_QUESTION,
                              "System Info: operation not allowed, query out of domain.")
    assert verdict["stage1_ok"] is True
    assert verdict["stage2_invoked"] is True


def test_no_result_passes():
    verdict = gate.check_gate(GOOD, READ_QUESTION, {"error_message": "System Info: no result"})
    assert verdict["stage2_invoked"] is True


def test_transport_error_blocks_even_with_a_correct_extraction():
    verdict = gate.check_gate(GOOD, READ_QUESTION, {"error_message": "Error: timed out"})
    assert verdict["stage1_ok"] is False
    assert verdict["block_reason"] == "transport_error"


def test_extraction_ok_does_not_need_the_network():
    ok, reason = gate.extraction_ok(GOOD, READ_QUESTION)
    assert ok is True and reason is None
    ok, reason = gate.extraction_ok(WRONG_FILTER, READ_QUESTION)
    assert ok is False and reason == "filter_mismatch"


def test_gate_pass_rate_and_cells_evaluated():
    cells = [{"stage1_ok": True, "stage2_invoked": True},
             {"stage1_ok": True, "stage2_invoked": True},
             {"stage1_ok": False, "stage2_invoked": False}]
    assert gate.gate_pass_rate(cells) == 0.667
    assert gate.cells_evaluated(cells) == 2


def test_end_to_end_success_refuses_to_guess_a_missing_verdict():
    """ a silent zero would look like a bad answer instead of a scoring step that never ran """
    with pytest.raises(KeyError):
        gate.end_to_end_success([{"stage1_ok": True, "stage2_invoked": True}])
