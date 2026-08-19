""" Unit tests for decide_permission(), offline and instant, no OpenProject and no model.
    The capability sets below are a copy of what the instance returned, so the expected answers
    are not invented.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from permissions import check_permission, decide_permission

#project ids on the instance
READ = "work_packages/read"
CREATE = "work_packages/create"
UPDATE = "work_packages/update"
PROJECT_UPDATE = "projects/update"
PROJECT_CREATE = "projects/create"

FULL = {READ, CREATE, UPDATE, PROJECT_UPDATE}
READ_ONLY = {READ}

CAPABILITIES = {
    #admin: everything everywhere, plus the global permission to create projects
    "alba.pellegrini": {
        "1": set(FULL), "2": set(FULL), "3": set(FULL), "4": set(FULL),
        "5": set(FULL), "6": set(FULL), "7": set(FULL),
        "global": {PROJECT_CREATE},
    },
    #Reader on every project: read and nothing else, nowhere
    "mario.rossi": {
        "1": set(READ_ONLY), "2": set(READ_ONLY), "3": set(READ_ONLY), "4": set(READ_ONLY),
        "5": set(READ_ONLY), "6": set(READ_ONLY), "7": set(READ_ONLY),
    },
    #Member on Mobile App and Data Migration, Reader elsewhere
    "giulia.bianchi": {
        "1": set(READ_ONLY), "2": set(READ_ONLY), "3": set(READ_ONLY),
        "4": {READ, CREATE, UPDATE}, "5": {READ, CREATE, UPDATE},
        "6": set(READ_ONLY), "7": set(READ_ONLY),
    },
}

PROJECTS = ["3", "4", "5", "6", "7"]   # SANDBOX + the four dataset projects
INTENTS = ["read", "create", "update"]

#expected answer for (user, project, intent) on work packages, straight from the real matrix
EXPECTED = {
    "alba.pellegrini": {p: {"read": True, "create": True, "update": True} for p in PROJECTS},
    "mario.rossi": {p: {"read": True, "create": False, "update": False} for p in PROJECTS},
    "giulia.bianchi": {
        "3": {"read": True, "create": False, "update": False},
        "4": {"read": True, "create": True, "update": True},
        "5": {"read": True, "create": True, "update": True},
        "6": {"read": True, "create": False, "update": False},
        "7": {"read": True, "create": False, "update": False},
    },
}


#the 45 combinations: 3 users x 5 projects x 3 intents on work packages

@pytest.mark.parametrize("username", sorted(CAPABILITIES))
@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("intent", INTENTS)
def test_work_package_matrix(username, project, intent):
    expected = EXPECTED[username][project][intent]
    allowed, reason = decide_permission(
        CAPABILITIES[username], username, intent, "work_packages", project)

    assert allowed is expected, f"{username} / project {project} / {intent}: reason={reason}"
    if expected:
        assert reason is None
    else:
        assert reason and username in reason


#creating a project is a global permission, not one held inside a project

@pytest.mark.parametrize("username,expected", [
    ("alba.pellegrini", True),
    ("mario.rossi", False),
    ("giulia.bianchi", False),
])
def test_create_project_is_global(username, expected):
    allowed, _ = decide_permission(CAPABILITIES[username], username, "create", "projects")
    assert allowed is expected


def test_create_project_ignores_project_scope():
    """ even inside a project she can write in, Giulia cannot create projects """
    allowed, _ = decide_permission(
        CAPABILITIES["giulia.bianchi"], "giulia.bianchi", "create", "projects", project="4")
    assert allowed is False


#updating a project: only the admin holds projects/update

@pytest.mark.parametrize("username,expected", [
    ("alba.pellegrini", True),
    ("giulia.bianchi", False),
    ("mario.rossi", False),
])
def test_update_project(username, expected):
    allowed, _ = decide_permission(
        CAPABILITIES[username], username, "update", "projects", project="4")
    assert allowed is expected


#reading a project: no action required, being able to see it is enough

def test_read_project_only_needs_visibility():
    allowed, _ = decide_permission(
        CAPABILITIES["mario.rossi"], "mario.rossi", "read", "projects", project="7")
    assert allowed is True


def test_no_access_to_an_invisible_project():
    """the refusal must say 'no access', not 'it does not exist'"""
    allowed, reason = decide_permission(
        CAPABILITIES["giulia.bianchi"], "giulia.bianchi", "read", "work_packages",
        project="99", project_name="Secret Project")
    assert allowed is False
    assert "no access" in reason and "Secret Project" in reason


#no project in the request

@pytest.mark.parametrize("username", sorted(CAPABILITIES))
def test_read_without_project_is_allowed(username):
    """ 'show me all the tasks' has no scope to check """
    allowed, _ = decide_permission(CAPABILITIES[username], username, "read", "work_packages")
    assert allowed is True


@pytest.mark.parametrize("username,expected", [
    ("alba.pellegrini", True),
    ("giulia.bianchi", True),    # allowed somewhere: the scoped check runs after the GET
    ("mario.rossi", False),      # allowed nowhere: refuse now, no need to call OpenProject
])
def test_update_without_project_checks_the_verb(username, expected):
    allowed, _ = decide_permission(CAPABILITIES[username], username, "update", "work_packages")
    assert allowed is expected


#things that are not permission problems

def test_out_of_scope_is_not_a_permission_refusal():
    allowed, reason = decide_permission(
        CAPABILITIES["mario.rossi"], "mario.rossi", "read", "out_of_scope")
    assert allowed is True and reason is None


def test_unsupported_operation():
    allowed, reason = decide_permission(
        CAPABILITIES["alba.pellegrini"], "alba.pellegrini", "delete", "work_packages")
    assert allowed is False and "unsupported" in reason


#the public entry point

def test_unknown_user_is_refused():
    """no network: an unknown identity is rejected before any credential is looked up"""
    allowed, reason = check_permission("hacker.anonimo", "create", "work_packages", project="4")
    assert allowed is False and "unknown user" in reason


def test_check_permission_accepts_injected_capabilities():
    """capabilities can be passed in, so the entry point itself is testable offline"""
    allowed, _ = check_permission(
        "mario.rossi", "create", "work_packages", project="4",
        capabilities=CAPABILITIES["mario.rossi"])
    assert allowed is False


def test_identity_is_not_a_free_string():
    """ being called 'alba.pellegrini' is not enough """
    allowed, _ = check_permission(
        "alba.pellegrini", "create", "work_packages", project="4",
        capabilities=CAPABILITIES["mario.rossi"])
    assert allowed is False


#which project does a request act on?

from permissions import permission_scope, project_of_work_package  


@pytest.mark.parametrize("extraction,expected_id,expected_label", [
    #read of work packages inside a project: the project is a filter
    ({"intent": "read", "macro_section": "work_packages",
      "filters": {"project": ["Mobile App"]}, "payload": {}}, 4, "Mobile App"),
    #create of a work package: the project is in the payload
    ({"intent": "create", "macro_section": "work_packages",
      "filters": {}, "payload": {"subject": ["x"], "project": ["SANDBOX"]}}, 3, "SANDBOX"),
    #on an update the filters hold the id of the target, not of a project, so only the verb is checked
    ({"intent": "update", "macro_section": "work_packages",
      "filters": {"id": ["41"]}, "payload": {"status": ["Closed"]}}, None, None),
    #read with no project at all -> nothing to scope
    ({"intent": "read", "macro_section": "work_packages",
      "filters": {"priority": ["High"]}, "payload": {}}, None, None),
    #creating a project is a global permission, there is no project to check against
    ({"intent": "create", "macro_section": "projects",
      "filters": {}, "payload": {"name": ["New one"]}}, None, None),
    #updating a project selected by id: the id IS the project
    ({"intent": "update", "macro_section": "projects",
      "filters": {"id": ["12"]}, "payload": {"active": ["f"]}}, "12", None),
    #updating a project selected by name
    ({"intent": "update", "macro_section": "projects",
      "filters": {"name": ["Data Migration"]}, "payload": {"active": ["f"]}}, 5, "Data Migration"),
    #a project nobody has ever heard of: unresolved, but the name is kept for the message
    ({"intent": "read", "macro_section": "work_packages",
      "filters": {"project": ["Zephyr"]}, "payload": {}}, None, "Zephyr"),
])
def test_permission_scope(extraction, expected_id, expected_label):
    project_id, label = permission_scope(extraction)      # no api_key: no network in unit tests
    assert project_id == expected_id
    assert label == expected_label


def test_permission_scope_unwraps_properties():
    """some models wrap the whole extraction inside 'properties', as the builders already handle"""
    project_id, label = permission_scope({"properties": {
        "intent": "read", "macro_section": "work_packages",
        "filters": {"project": ["Internal Audit"]}, "payload": {}}})
    assert project_id == 7 and label == "Internal Audit"


def test_project_of_work_package():
    """the scope of an update comes from OpenProject's answer, not from the extraction"""
    get_response = {"id": 41, "lockVersion": 3,
                    "_links": {"project": {"href": "/api/v3/projects/5", "title": "Data Migration"}}}
    assert project_of_work_package(get_response) == ("5", "Data Migration")


@pytest.mark.parametrize("bad", [None, "System Info: no result", {}, {"_links": {}}])
def test_project_of_work_package_when_unusable(bad):
    assert project_of_work_package(bad) == (None, None)


def test_refusal_is_readable():
    """the refusal is read by the second model: it must not contain our internal tokens"""
    _, reason = decide_permission(
        CAPABILITIES["mario.rossi"], "mario.rossi", "create", "work_packages", "4", "Mobile App")
    assert "work packages" in reason and "work_packages" not in reason


#the refusal the user reads: written by us, not generated (13/08)

from permissions import VERIFICATION_FAILED, denial_sentence  


@pytest.mark.parametrize("username,intent,section,project,label,expected", [
    ("mario.rossi", "create", "work_packages", "3", "SANDBOX",
     "I'm sorry, you don't have permission to create work packages in SANDBOX."),
    ("giulia.bianchi", "create", "work_packages", "6", "Website Migration",
     "I'm sorry, you don't have permission to create work packages in Website Migration."),
    ("mario.rossi", "create", "projects", None, None,
     "I'm sorry, you don't have permission to create projects on this instance."),
])
def test_denial_sentence_from_a_real_refusal(username, intent, section, project, label, expected):
    """the sentence is built from the same reason that goes in the logs, so the two cannot drift"""
    allowed, reason = decide_permission(
        CAPABILITIES[username], username, intent, section, project, label)
    assert allowed is False
    assert denial_sentence(reason) == expected


def test_denial_sentence_drops_anywhere():
    """ 'not allowed to update work packages anywhere' is an explanation to us, an accusation to the user """
    _, reason = decide_permission(
        CAPABILITIES["mario.rossi"], "mario.rossi", "update", "work_packages")
    assert denial_sentence(reason) == "I'm sorry, you don't have permission to update work packages."


def test_denial_sentence_for_an_invisible_project():
    _, reason = decide_permission(
        CAPABILITIES["giulia.bianchi"], "giulia.bianchi", "read", "work_packages",
        project="99", project_name="Secret Project")
    assert denial_sentence(reason) == "I'm sorry, you don't have access to Secret Project."


def test_denial_sentence_for_an_unknown_identity():
    _, reason = check_permission("hacker.anonimo", "read", "work_packages")
    assert "recognise your account" in denial_sentence(reason)


@pytest.mark.parametrize("reason", [
    "something we have never written before",
    "unsupported operation 'delete' on 'work_packages'",
])
def test_denial_sentence_never_returns_an_empty_or_technical_string(reason):
    sentence = denial_sentence(reason)
    assert sentence.startswith("I'm sorry") and sentence.endswith(".")
    assert "_" not in sentence


def test_failed_verification_keeps_matching_the_gate():
    """ Not knowing whether the user was allowed must never be reported as "you are not allowed", and the message has """
    assert "could not reach openproject" in f"System Info: {VERIFICATION_FAILED}.".lower()
