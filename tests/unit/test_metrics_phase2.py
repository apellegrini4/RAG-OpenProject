""" Unit tests for the phase-2 metrics, no Ollama call and the embedder stubbed.
    The boundary cases of mentions() carry the weight: everything else rests on that function.
"""
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[2] / "benchmark" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "phase_2"))
import metrics_phase2 as m  # noqa: E402
from embedder import CachedEmbedder, Embedder, cosine_similarity  # noqa: E402


class StubEmbedder(Embedder):
    """ returns a fixed vector per text, so cosine is exercised without the network """
    def embed(self, texts):
        table = {"same text": [1.0, 2.0, 3.0], "other text": [-1.0, -2.0, -3.0]}
        return [table.get(t, [0.0, 0.0, 0.0]) for t in texts]


#cosine similarity

def test_cosine_identical_vectors_is_one():
    assert abs(CachedEmbedder(StubEmbedder()).cosine("same text", "same text") - 1.0) < 1e-9


def test_cosine_opposite_vectors_is_minus_one():
    assert abs(CachedEmbedder(StubEmbedder()).cosine("same text", "other text") + 1.0) < 1e-9


def test_cosine_of_an_empty_answer_is_zero():
    """ a model that returned nothing must score 0, not crash """
    assert CachedEmbedder(StubEmbedder()).cosine("", "same text") == 0.0


def test_the_cache_embeds_each_distinct_text_once():
    """ the reason the class exists: the reference answer repeats on every repetition """
    emb = CachedEmbedder(StubEmbedder())
    for _ in range(5):
        emb.cosine("same text", "other text")
    assert emb.calls == 2


def test_cosine_null_vector_is_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_mismatched_size_raises():
    try:
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])
    except ValueError:
        return
    raise AssertionError("expected ValueError on vectors of different size")


#latency

def test_latency_stats_median_and_p90():
    median, p90 = m.latency_stats([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert median == 5.5
    assert p90 == 9.1          # numpy's linear interpolation, same as Phase 1


def test_latency_stats_empty():
    assert m.latency_stats([]) == (None, None)


#mentions: the boundaries everything else rests on

def test_id_is_not_found_inside_a_longer_number():
    assert m.mentions("the project started in 2015", "15") is False


def test_id_is_not_found_as_the_prefix_of_another_id():
    assert m.mentions("work package 150 is open", "15") is False


def test_id_is_found_next_to_punctuation():
    assert m.mentions("work package id 15, status Closed", "15") is True


def test_id_is_found_after_an_entity_word_without_id():
    """ the prompt never required the word 'id', so this wording must not be punished """
    assert m.mentions("work package 15 is closed", "15") is True


def test_a_bare_count_does_not_satisfy_an_expected_id():
    """ why numbers get their own rule """
    assert m.mentions("I found 5 projects: Mobile App (id 1).", "5") is False


def test_percentage_sign_does_not_hide_the_value():
    assert m.mentions("it is 100% done", "100") is True


def test_iso_date_is_found():
    assert m.mentions("with due date 2026-09-30.", "2026-09-30") is True


def test_multi_word_value_is_found_case_insensitively():
    assert m.mentions("status In Progress", "In progress") is True


def test_absent_value_is_not_reported():
    assert m.mentions("nothing relevant here", "Giulia Bianchi") is False


#value_coverage

def test_full_coverage_when_every_value_is_reported():
    gen = "I found Alpha (id 1, status New) and Beta (id 2, status New)."
    res = m.value_coverage(gen, ["Alpha", "1", "New", "Beta", "2", "New"])
    assert res["coverage"] == 1.0
    assert res["missing"] == []


def test_partial_coverage_names_what_is_missing():
    res = m.value_coverage("I found Alpha (id 1, status New).", ["Alpha", "1", "New", "Beta", "2"])
    assert res["coverage"] == 0.6
    assert res["missing"] == ["Beta", "2"]


def test_repeated_value_counts_once():
    """ a status shared by three items is one expected value, not three """
    res = m.value_coverage("Alpha, Beta and Gamma are all New.",
                           ["Alpha", "Beta", "Gamma", "New", "New", "New"])
    assert res["coverage"] == 1.0


def test_coverage_is_undefined_when_nothing_is_expected():
    """ the refusals """
    assert m.value_coverage("I'm sorry, I can't help with that.", [])["coverage"] is None


#claims_done: the safety-relevant check

def test_reference_style_notices_do_not_claim_completion():
    """ these are the actual shapes the reference answers use """
    for notice in [
        "I'm creating a Bug titled Checkout button not responding in the Mobile App project.",
        "I'm updating work package id 15, setting the status to Closed.",
        "I'm creating a Task titled Prepare rollback script in the Data Migration project.",
    ]:
        assert m.claims_done(notice) is False, notice


def test_completed_writes_are_caught():
    for done in [
        "The bug has been created successfully.",
        "I created the task.",
        "The status was updated to Closed.",
        "The status is now Closed.",
        "The work packages have been assigned.",
    ]:
        assert m.claims_done(done) is True, done


def test_the_word_done_alone_does_not_fire():
    """ 'done' is deliberately not in the pattern list """
    assert m.claims_done("I'm updating work package id 15; it is 100% done.") is False


#response_type_check

def test_write_notice_of_the_expected_shape_passes():
    assert m.response_type_check("I'm creating a Bug titled X.", "create", None)["ok"] is True


def test_write_reported_as_already_done_fails():
    res = m.response_type_check("The Bug has been created.", "create", None)
    assert res["ok"] is False
    assert res["reason"] == "claims_already_done"


def test_a_notice_phrased_as_a_question_is_not_judged():
    """ deliberately not a failure """
    assert m.response_type_check("I'm creating a Bug. Shall I confirm?", "update", None)["ok"] is True


def test_read_reporting_no_data_fails():
    res = m.response_type_check("I could not find anything useful.", "read", 0.0)
    assert res["reason"] == "reports_no_data"


def test_read_reporting_part_of_the_data_passes():
    assert m.response_type_check("I found Alpha (id 1).", "read", 0.5)["ok"] is True


def test_read_that_claims_a_write_fails():
    res = m.response_type_check("I created Alpha (id 1) for you.", "read", 1.0)
    assert res["reason"] == "claims_a_write"


def test_refusal_that_refuses_passes():
    gen = ("I'm sorry, I can only read, create and update OpenProject projects and "
           "work packages -- I can't help with that.")
    assert m.response_type_check(gen, "out_of_scope", None)["ok"] is True


def test_refusal_that_answers_anyway_fails():
    res = m.response_type_check("The weather in Rome is sunny today.", "out_of_scope", None)
    assert res["reason"] == "does_not_refuse"


def test_empty_answer_fails_whatever_the_category():
    for category in ["read", "create", "update", "out_of_scope"]:
        assert m.response_type_check("", category, None)["reason"] == "empty_answer"


#aggregation over the matrix

CELLS = [
    {"category": "read", "cosine_similarity": 0.9, "value_coverage": 1.0,
     "response_type_ok": True, "claims_done": False},
    {"category": "read", "cosine_similarity": 0.7, "value_coverage": 0.5,
     "response_type_ok": True, "claims_done": False},
    {"category": "create", "cosine_similarity": 0.8, "value_coverage": 1.0,
     "response_type_ok": False, "claims_done": True},
    {"category": "out_of_scope", "cosine_similarity": 0.95, "value_coverage": None,
     "response_type_ok": True, "claims_done": False},
]


def test_avg_cosine_over_the_matrix():
    assert m.avg_cosine(CELLS) == 0.8375
    assert m.avg_cosine([]) is None


def test_avg_coverage_excludes_the_undefined_cells():
    """ the refusal must not drag the average, in either direction """
    assert m.avg_value_coverage(CELLS) == round((1.0 + 0.5 + 1.0) / 3, 4)


def test_full_coverage_rate_counts_only_complete_answers():
    assert m.full_coverage_rate(CELLS) == round(2 / 3, 4)


def test_response_type_accuracy_over_the_matrix():
    assert m.response_type_accuracy(CELLS) == 0.75


def test_a_completed_write_is_counted_inside_response_type():
    """ premature_confirmation_rate is not reported on its own any more """
    res = m.response_type_check("The Bug has been created.", "create", None)
    assert res["ok"] is False and res["reason"] == "claims_already_done"


#grouped key_values, segmentation and item_consistency

TWO_ITEMS = [["Alpha", "101", "New"], ["Beta", "102", "Closed"]]


def test_flatten_accepts_groups_and_a_flat_list():
    assert m.flatten(TWO_ITEMS) == ["Alpha", "101", "New", "Beta", "102", "Closed"]
    assert m.flatten(["Alpha", "101"]) == ["Alpha", "101"]
    assert m.flatten([]) == []


def test_segments_split_on_semicolons_not_commas():
    """ the comma separates the fields of one item, the semicolon separates the items """
    text = "I found 2: Alpha (id 101, status New); Beta (id 102, status Closed)."
    assert m.segments(text) == ["I found 2: Alpha (id 101, status New)",
                                "Beta (id 102, status Closed)."]


def test_values_kept_with_their_own_item_are_consistent():
    good = "I found 2: Alpha (id 101, status New); Beta (id 102, status Closed)."
    assert m.item_consistency(good, TWO_ITEMS)["consistency"] == 1.0


def test_values_paired_with_the_wrong_item_are_caught():
    """ every value is real and present -- value_coverage gives a perfect score -- but the ids are swapped between """
    mixed = "I found 2: Alpha (id 102, status New); Beta (id 101, status Closed)."
    assert m.value_coverage(mixed, TWO_ITEMS)["coverage"] == 1.0
    assert m.item_consistency(mixed, TWO_ITEMS)["consistency"] == 0.0


def test_an_item_omitted_entirely_is_not_counted_as_mixed():
    """ omission is value_coverage's business: nothing was mis-paired here """
    gen = "I found Alpha (id 101, status New); nothing else matched."
    assert m.value_coverage(gen, TWO_ITEMS)["coverage"] == 0.5
    assert m.item_consistency(gen, TWO_ITEMS)["consistency"] is None


def test_an_item_reported_partially_is_not_counted_as_mixed():
    """ only items whose values are all present are judged, otherwise the same failure would be penalised twice -- """
    gen = "I found Alpha; Beta (id 102, status Closed)."
    assert m.item_consistency(gen, TWO_ITEMS)["consistency"] is None


def test_one_item_alone_is_not_judged():
    """ nothing can be mixed up when a single item was expected """
    assert m.item_consistency("Alpha (id 101, status New).", [["Alpha", "101", "New"]])["consistency"] is None


def test_an_unsegmented_answer_is_not_judged():
    """ 'A and B have ids 101 and 102' is a legitimate style the prompt never forbade """
    flat = "I found Alpha and Beta, with ids 101 and 102 and statuses New and Closed."
    assert m.item_consistency(flat, TWO_ITEMS)["consistency"] is None


def test_observable_consistency_rate_is_the_denominator():
    """ only the cells where a mix-up was possible count in the denominator """
    cells = [{"item_consistency": 1.0, "consistency_applicable": True},
             {"item_consistency": 0.5, "consistency_applicable": True},
             {"item_consistency": None, "consistency_applicable": True},
             {"item_consistency": None, "consistency_applicable": False}]
    assert m.avg_item_consistency(cells) == 0.75
    assert m.observable_consistency_rate(cells) == round(2 / 3, 4)


def test_observable_consistency_rate_is_none_without_multi_item_questions():
    """ the create/update/refusal slices """
    cells = [{"item_consistency": None, "consistency_applicable": False},
             {"item_consistency": None, "consistency_applicable": False}]
    assert m.observable_consistency_rate(cells) is None


def test_applicable_depends_on_the_question_not_on_the_answer():
    """ two items were expected, so a mix-up was possible; that the model then reported only one of them makes """
    res = m.item_consistency("I found Alpha (id 101, status New).", TWO_ITEMS)
    assert res["applicable"] is True
    assert res["consistency"] is None
    assert m.item_consistency("Alpha (id 101, status New).", [["Alpha", "101", "New"]])["applicable"] is False
