""" Unit tests for benchmark/scripts/metrics_phase1.py — synthetic data only, no Ollama call
everything is validated on synthetic data. """
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmark" / "scripts" / "phase_1"))
import metrics_phase1 as m  # noqa: E402


#schema_validation() also requires 'intent' and 'payload', so every fixture below carries them
REAL = {"intent": "read", "macro_section": "work_packages", "filters": {"priority": ["High"]}, "payload": {}}
CORRECT = {"reasoning": "r1", "intent": "read", "macro_section": "work_packages",
           "filters": {"priority": ["High"]}, "payload": {}}
CORRECT_OTHER_REASONING = {"reasoning": "different text entirely", "intent": "read",
                            "macro_section": "work_packages", "filters": {"priority": ["High"]}, "payload": {}}
WRONG = {"reasoning": "r2", "intent": "read", "macro_section": "work_packages",
         "filters": {"priority": ["Low"]}, "payload": {}}
SCHEMA_INVALID = {"macro_section": "work_packages", "filters": "not-a-dict"}  # missing intent/payload too

#fixtures for the write intents
REAL_UPDATE = {"intent": "update", "macro_section": "work_packages",
               "filters": {"id": ["42"]}, "payload": {"status": ["Closed"]}}
CORRECT_UPDATE = {"reasoning": "r3", "intent": "update", "macro_section": "work_packages",
                   "filters": {"id": ["42"]}, "payload": {"status": ["Closed"]}}
WRONG_PAYLOAD_UPDATE = {"reasoning": "r4", "intent": "update", "macro_section": "work_packages",
                         "filters": {"id": ["42"]}, "payload": {"status": ["Open"]}}
WRONG_INTENT = {"reasoning": "r5", "intent": "create", "macro_section": "work_packages",
                "filters": {}, "payload": {"subject": ["New task"]}}


#schema / exact match building blocks

def test_schema_validation_rejects_non_list_filter_values():
    assert m.schema_validation(SCHEMA_INVALID) is False
    assert m.schema_validation(CORRECT) is True
    assert m.schema_validation(None) is False


def test_exact_filter_match_case_and_order_insensitive():
    pred = {"macro_section": "Work_Packages", "filters": {"priority": ["high"]}}
    assert m.exact_filter_match(pred, REAL) is True
    assert m.exact_filter_match(WRONG, REAL) is False


#evaluate_question: all correct

def test_evaluate_question_all_correct():
    reps = [CORRECT, CORRECT, CORRECT]
    res = m.evaluate_question(reps, REAL)
    assert res["deterministic"] is True
    assert res["n_distinct_outputs"] == 1
    assert res["json_correct_count"] == 3
    assert res["filter_correct_count"] == 3
    assert res["stability"] == 1.0


#evaluate_question: all wrong

def test_evaluate_question_all_wrong():
    reps = [WRONG, WRONG, WRONG]
    res = m.evaluate_question(reps, REAL)
    assert res["deterministic"] is True  # they all agree with each other, just not with real
    assert res["json_correct_count"] == 3
    assert res["filter_correct_count"] == 0


#evaluate_question: 50/50 split

def test_evaluate_question_fifty_fifty_split():
    reps = [CORRECT, CORRECT, WRONG, WRONG]
    res = m.evaluate_question(reps, REAL)
    assert res["deterministic"] is False
    assert res["n_distinct_outputs"] == 2
    assert res["filter_correct_count"] == 2
    assert res["json_correct_count"] == 4
    assert res["stability"] == 0.5


#evaluate_question: invalid JSON (parse failure -> None)

def test_evaluate_question_invalid_json_is_none():
    reps = [CORRECT, None, None]
    res = m.evaluate_question(reps, REAL)
    assert res["json_correct_count"] == 1
    assert res["filter_correct_count"] == 1
    # None counts as its own distinct group, deterministic must be False since not all equal
    assert res["deterministic"] is False


#reasoning differs but filters match -> must still count as the same output

def test_reasoning_difference_does_not_break_determinism():
    reps = [CORRECT, CORRECT_OTHER_REASONING, CORRECT]
    res = m.evaluate_question(reps, REAL)
    assert res["deterministic"] is True
    assert res["n_distinct_outputs"] == 1
    assert res["stability"] == 1.0


#determinism_rate == 0 but stability high: the case that justifies the new metric

def test_determinism_zero_but_stability_high():
    #9/10 repetitions agree, 1 flips -> never *perfectly* deterministic across all questions, but "almost stable"
    reps = [CORRECT] * 9 + [WRONG]
    res = m.evaluate_question(reps, REAL)
    assert res["deterministic"] is False
    assert res["stability"] == 0.9

    chaotic_reps = [CORRECT, WRONG, CORRECT, WRONG, CORRECT]
    chaotic_res = m.evaluate_question(chaotic_reps, REAL)
    assert chaotic_res["deterministic"] is False
    assert chaotic_res["stability"] == 0.6  # much lower: this model is genuinely unstable

    stats_stable = m.summarize_stats("stable-model", [res], latencies=[])
    stats_chaotic = m.summarize_stats("chaotic-model", [chaotic_res], latencies=[])
    assert stats_stable["determinism_rate"] == 0.0
    assert stats_chaotic["determinism_rate"] == 0.0
    assert stats_stable["stability"] > stats_chaotic["stability"]


#summarize_stats aggregation

def test_summarize_stats_aggregates_across_questions():
    q1 = m.evaluate_question([CORRECT, CORRECT], REAL)
    q2 = m.evaluate_question([WRONG, WRONG], REAL)
    stats = m.summarize_stats("model-x", [q1, q2], latencies=[0.1, 0.2, 0.3])
    assert stats["model"] == "model-x"
    assert stats["determinism_rate"] == 1.0       # both questions were internally consistent
    assert stats["exact_filter_match_rate"] == 0.5  # only q1's 2 reps were correct, out of 4 total
    assert stats["stability"] == 1.0
    assert stats["median_latency"] == 0.2


def test_summarize_stats_empty_is_safe():
    stats = m.summarize_stats("empty-model", [], latencies=[])
    assert stats["determinism_rate"] == 0.0
    assert stats["stability"] == 0.0
    assert stats["median_latency"] is None


#failure_reason: the three cases

def test_failure_reason_parse_error():
    assert m.failure_reason(None, REAL) == "parse_error"


def test_failure_reason_schema_invalid():
    assert m.failure_reason(SCHEMA_INVALID, REAL) == "schema_invalid"


def test_failure_reason_filter_mismatch():
    assert m.failure_reason(WRONG, REAL) == "filter_mismatch"


def test_failure_reason_none_on_full_match():
    assert m.failure_reason(CORRECT, REAL) is None


#exact_payload_match, intent_match and write_intent

def test_exact_payload_match():
    assert m.exact_payload_match(CORRECT_UPDATE, REAL_UPDATE) is True
    assert m.exact_payload_match(WRONG_PAYLOAD_UPDATE, REAL_UPDATE) is False


def test_intent_match_case_insensitive():
    pred = {"intent": "Update"}
    assert m.intent_match(pred, REAL_UPDATE) is True
    assert m.intent_match(WRONG_INTENT, REAL_UPDATE) is False


def test_write_intent():
    assert m.write_intent("create") is True
    assert m.write_intent("Update") is True
    assert m.write_intent("read") is False
    assert m.write_intent(None) is False


#the extra fields of evaluate_question and summarize_stats

def test_evaluate_question_intent_and_payload_accuracy():
    reps = [CORRECT_UPDATE, CORRECT_UPDATE, WRONG_PAYLOAD_UPDATE]
    res = m.evaluate_question(reps, REAL_UPDATE)
    assert res["intent_correct_count"] == 3  # all three got the intent ('update') right
    assert res["payload_correct_count"] == 2  # only the first two match the exact payload
    assert res["expected_read"] is False
    assert res["unsafe_count"] == 0  # real isn't a read, so nothing here counts as "unsafe"


def test_evaluate_question_unsafe_action_on_read_gold():
    # real question is a 'read', but the model answers with a write intent -> unsafe
    reps = [CORRECT, WRONG_INTENT, CORRECT]
    res = m.evaluate_question(reps, REAL)
    assert res["expected_read"] is True
    assert res["unsafe_count"] == 1
    assert res["intent_correct_count"] == 2  # only the two 'read' predictions match


def test_summarize_stats_extended_rates():
    q_read = m.evaluate_question([CORRECT, WRONG_INTENT], REAL)          # 1/2 unsafe on read-real
    q_update = m.evaluate_question([CORRECT_UPDATE, WRONG_PAYLOAD_UPDATE], REAL_UPDATE)  # not read-real
    stats = m.summarize_stats("model-y", [q_read, q_update], latencies=[])

    assert stats["intent_accuracy"] == round(3 / 4, 3)  # 1 wrong intent out of 4 total reps
    # the payload matches on two of the four repetitions
    assert stats["exact_payload_match_rate"] == round(2 / 4, 3)
    assert stats["unsafe_action_rate"] == round(1 / 2, 3)  # 1 unsafe out of 2 read-real reps


def test_summarize_stats_unsafe_action_rate_none_without_read_gold():
    q_update = m.evaluate_question([CORRECT_UPDATE], REAL_UPDATE)
    stats = m.summarize_stats("model-z", [q_update], latencies=[])
    assert stats["unsafe_action_rate"] is None  # no read-real questions at all, not 0.0
