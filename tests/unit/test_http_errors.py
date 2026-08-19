""" Unit tests for http_error_message(), offline and instant.
    What matters is not the wording but that each status lands in the right branch downstream.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from request_helpers import http_error_message

#the markers the gate looks for: a message containing one of them blocks the cell
GATE_TRANSPORT_MARKERS = ("communication error", "form validation call failed",
                          "could not reach openproject")

#the prefix api.py intercepts to answer with a deterministic sentence instead of calling phase 2
PERMISSION_DENIED_PREFIX = "System Info: permission denied, "


def blocks_the_gate(message):
    return any(marker in message.lower() for marker in GATE_TRANSPORT_MARKERS)


def test_400_no_longer_blames_permissions():
    """ it used to say "invalid parameters or unsufficient permissions", mixing two causes that have different fixes """
    message = http_error_message(400)
    assert "permission" not in message.lower()
    assert not blocks_the_gate(message)


def test_403_matches_the_applicative_refusal():
    """ one event, one answer """
    assert http_error_message(403).startswith(PERMISSION_DENIED_PREFIX)
    assert not blocks_the_gate(http_error_message(403))


def test_404_is_an_answer_not_a_failure():
    """a well formed question about something that does not exist deserves an answer"""
    message = http_error_message(404)
    assert not blocks_the_gate(message)
    assert "does not exist" in message


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_failures_still_block_the_cell(status):
    assert blocks_the_gate(http_error_message(status))


def test_401_blocks_the_cell():
    """a rejected credential is a misconfiguration, not a decision about the user"""
    assert blocks_the_gate(http_error_message(401))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 423, 500])
def test_every_message_is_a_system_info_sentence(status):
    message = http_error_message(status)
    assert message.startswith("System Info: ") and message.endswith(".")
    assert ")" not in message


import json

import requests

import request_helpers
from request_helpers import commit_write, validate_via_form

#the sentence OpenProject actually writes in a 403 on /form
OP_TEXT = "You are not authorized to access this resource."

class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


def fake_call(status, payload=None):
    body = payload if payload is not None else {"_type": "Error", "message": OP_TEXT}

    def call(*args, **kwargs):
        return FakeResponse(status, body)
    return call


WRITE_REQUEST = {"method": "POST", "url": "https://example.invalid/api/v3/work_packages",
                 "body": {"subject": "x"}}
VALIDATED = {**WRITE_REQUEST, "ready_to_commit": True,
             "commit_href": "/api/v3/work_packages", "commit_method": "post"}


def test_form_403_is_our_sentence_not_theirs(monkeypatch):
    monkeypatch.setattr(request_helpers.requests, "post", fake_call(403))
    result = validate_via_form(WRITE_REQUEST, "fake-key")

    assert result == "System Info: permission denied, OpenProject refused this request."
    assert OP_TEXT not in result


def test_form_403_matches_the_applicative_refusal_exactly(monkeypatch):
    """ the two levels of the guard must produce the identical string """
    monkeypatch.setattr(request_helpers.requests, "post", fake_call(403))
    assert validate_via_form(WRITE_REQUEST, "k").startswith(PERMISSION_DENIED_PREFIX)


def test_form_server_error_still_blocks_the_cell(monkeypatch):
    monkeypatch.setattr(request_helpers.requests, "post", fake_call(500))
    assert blocks_the_gate(validate_via_form(WRITE_REQUEST, "k"))


def test_commit_failure_is_normalised_too(monkeypatch):
    """same defect, same fix: commit_write embedded OpenProject's text in the answer as well"""
    monkeypatch.setattr(request_helpers.requests, "request", fake_call(403))
    result = commit_write(VALIDATED, "k")

    assert result == "System Info: permission denied, OpenProject refused this request."
    assert OP_TEXT not in result


#validation errors
from request_helpers import validation_error_summary


def test_validation_error_keeps_the_message_and_drops_the_machinery():
    errors = {"subject": {
        "_type": "Error",
        "errorIdentifier": "urn:openproject-org:api:v3:errors:PropertyConstraintViolation",
        "message": "Subject can't be blank.",
        "_embedded": {"details": {"attribute": "subject"}},
    }}
    summary = validation_error_summary(errors)

    assert summary == "the request is not valid: Subject can't be blank"
    assert "urn:" not in summary and "_type" not in summary


def test_validation_errors_are_sorted_and_joined():
    """ same failure, same string """
    errors = {
        "subject": {"message": "Subject can't be blank."},
        "dueDate": {"message": "Due date is not a valid date."},
    }
    assert validation_error_summary(errors) == (
        "the request is not valid: Due date is not a valid date; Subject can't be blank")


def test_validation_error_without_a_message_still_names_the_field():
    assert validation_error_summary({"assignee": {"_type": "Error"}}) == (
        "the request is not valid: 'assignee' is not acceptable")


@pytest.mark.parametrize("errors", [{}, None, "not a dict"])
def test_validation_summary_never_breaks(errors):
    assert validation_error_summary(errors) == "the request is not valid"


def test_safe_write_uses_the_summary(monkeypatch):
    """the whole point: what reaches phase 2 is the sentence, not the dictionary"""
    from request_helpers import safe_write

    form_answer = {"_embedded": {"validationErrors": {
        "subject": {"_type": "Error",
                    "errorIdentifier": "urn:openproject-org:api:v3:errors:PropertyConstraintViolation",
                    "message": "Subject can't be blank."}}},
        "_links": {}}
    monkeypatch.setattr(request_helpers.requests, "post", fake_call(200, form_answer))

    result = safe_write(WRITE_REQUEST, "k")
    assert result == "System Info: the request is not valid: Subject can't be blank."
    assert "urn:" not in result


from permissions import denial_sentence
from request_helpers import LookupFailed, create_ID_map, workpack_patch


def test_create_id_map_raises_instead_of_returning_empty(monkeypatch):
    """ it used to swallow the 403 and return {} """
    monkeypatch.setattr(request_helpers.requests, "get", fake_call(403))

    with pytest.raises(LookupFailed) as raised:
        create_ID_map("assignee", "reader-key")
    assert raised.value.status == 403


def test_lookup_refusal_names_the_list_not_the_person():
    message = LookupFailed("assignee", 403).system_info

    assert message == ("System Info: permission denied, the current user is not allowed to "
                       "look up users.")
    assert "does not exist" not in message
    assert message.startswith(PERMISSION_DENIED_PREFIX)


def test_lookup_refusal_becomes_a_readable_sentence():
    """it goes through the same deterministic path as every other refusal """
    reason = LookupFailed("author", 403).system_info[len(PERMISSION_DENIED_PREFIX):].rstrip(".")
    assert denial_sentence(reason) == "I'm sorry, you don't have permission to look up users."


def test_lookup_network_failure_is_not_a_refusal():
    """not reaching OpenProject is our failure, not the user's: it must block the cell"""
    message = LookupFailed("status").system_info
    assert blocks_the_gate(message)
    assert PERMISSION_DENIED_PREFIX not in message


def test_lookup_server_error_uses_the_shared_mapping():
    assert LookupFailed("type", 500).system_info == http_error_message(500)


def test_update_path_reports_the_refusal_too(monkeypatch):
    """the update resolves names as well (assignee, status, type): same 403, same message"""
    monkeypatch.setattr(request_helpers.requests, "get", fake_call(403))
    get_response = {"lockVersion": 3, "_links": {"project": {"href": "/api/v3/projects/3"}}}

    result = workpack_patch(get_response, {"assignee": ["Giulia Bianchi"]},
                            "https://example.invalid/api/v3/work_packages/41", "reader-key")

    assert result == ("System Info: permission denied, the current user is not allowed to "
                      "look up users.")
    assert "do not exist" not in result


#where the project ends up, on create and on update
from request_helpers import API_V3, workpack_body_builder

PROJECTS_LIST = {"_embedded": {"elements": [
    {"id": 4, "name": "Mobile App"}, {"id": 6, "name": "Website Migration"}]}}


def test_create_leaves_the_project_out_of_the_body(monkeypatch):
    """creating addresses the project in the URL, so repeating it in the body is redundant"""
    monkeypatch.setattr(request_helpers.requests, "get", fake_call(200, PROJECTS_LIST))
    body, missing = workpack_body_builder(
        {"subject": ["x"], "project": ["Mobile App"]}, "k", for_update=False)

    assert missing == []
    assert "_links" not in body or "project" not in body["_links"]


def test_update_puts_the_project_in_the_body(monkeypatch):
    """updating addresses the work package, so a move can only travel in the body """
    monkeypatch.setattr(request_helpers.requests, "get", fake_call(200, PROJECTS_LIST))
    body, missing = workpack_body_builder(
        {"subject": ["x"], "project": ["Website Migration"]}, "k", for_update=True)

    assert missing == []
    assert body["_links"]["project"] == {"href": f"{API_V3}projects/6"}


def test_update_reports_an_unknown_project(monkeypatch):
    """and if the project does not exist it has to say so, not disappear"""
    monkeypatch.setattr(request_helpers.requests, "get", fake_call(200, PROJECTS_LIST))
    _, missing = workpack_body_builder({"project": ["Zephyr"]}, "k", for_update=True)

    assert any("Zephyr" in m for m in missing)


def test_update_reports_a_lookup_refusal_on_the_project(monkeypatch):
    """the project lookup can hit the same 403 as the others """
    monkeypatch.setattr(request_helpers.requests, "get", fake_call(403))
    with pytest.raises(LookupFailed):
        workpack_body_builder({"project": ["Mobile App"]}, "k", for_update=True)
