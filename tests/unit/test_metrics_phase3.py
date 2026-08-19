""" Unit tests for the phase-3 metrics, synthetic data only, no Ollama and no embedder.
    Two groups matter: the booleans, and the count of a read that filled its page.
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "scripts" / "phase_3"))
sys.path.insert(0, str(PROJECT_ROOT))
import metrics_phase3 as m  
from json_pruning import PAGE_SIZE  


#the reference: booleans

CREATE_NOTICE = {"intent": "create", "macro_section": "projects", "ready_to_commit": True,
                 "payload": {"name": "Vendor Onboarding", "public": "t"}}
UPDATE_NOTICE = {"intent": "update", "macro_section": "projects", "ready_to_commit": True,
                 "payload": {"active": "f"}, "target": {"id": "5"}}


def test_a_boolean_carries_its_wordings_a_plain_field_does_not():
    reference = m.reference_from_result(None, CREATE_NOTICE)
    name, public = reference[0]
    assert name == "Vendor Onboarding"
    assert isinstance(public, list) and public[0] == "t" and "true" in public


def test_the_field_name_is_never_an_accepted_wording():
    """ with "public" among them, "the public flag set to false" would count as public = t """
    for value in ("t", "f"):
        assert "public" not in m.accepted("public", value)
        assert "active" not in m.accepted("active", value)


def test_a_worded_boolean_is_covered():
    """ the answer is right and used to score 0.5 """
    reference = m.reference_from_result(None, CREATE_NOTICE)
    answer = "I'm creating a project named Vendor Onboarding with the public flag set to true."
    assert m.value_coverage(answer, reference)["coverage"] == 1.0


def test_the_wrong_polarity_is_still_missing():
    reference = m.reference_from_result(None, CREATE_NOTICE)
    answer = "I'm creating a project named Vendor Onboarding with the public flag set to false."
    coverage = m.value_coverage(answer, reference)
    assert coverage["coverage"] == 0.5
    assert coverage["missing"] == ["t"]


def test_archived_counts_as_active_false():
    reference = m.reference_from_result(None, UPDATE_NOTICE)
    assert m.value_coverage("I'm updating project id 5, archiving it.", reference)["coverage"] == 1.0
    assert m.value_coverage("I'm updating project id 5, activating it.",
                            reference)["coverage"] == 0.5


#the reference: reads

OVER = PAGE_SIZE + 3          # a read that found more than a page holds
NOTICE = f"I found {OVER} results, these are the {PAGE_SIZE} most recently created."


def read(total, n):
    items = [{"entity": "Project", "id": 10 - i, "name": f"P{10 - i}"} for i in range(n)]
    return {"total_results": total, "number_of_results_in_the_page": n, "items": items}


def test_a_read_reference_is_plain_strings():
    reference = m.reference_from_result(read(3, 3))
    assert reference == [["P10", "10"], ["P9", "9"], ["P8", "8"]]


def test_an_untruncated_read_counts_its_items():
    assert m.canonical_answer(read(3, 3)).startswith("I found 3 projects:")
    assert "most recently created" not in m.canonical_answer(read(3, 3))


def test_a_truncated_read_counts_the_total_and_carries_the_notice():
    """ 8 results, 7 returned """
    answer = m.canonical_answer(read(OVER, PAGE_SIZE))
    assert answer.startswith(f"I found {OVER} projects:")
    assert answer.endswith(NOTICE)


def test_the_notice_does_not_inflate_the_coverage():
    """ a bare number counts only after id, project, wp and friends, so the 8 and the 7 of the notice are not read as """
    reference = m.reference_from_result(read(OVER, 2))
    bare = f"I found {OVER} projects: P10 (id 10); P9 (id 9)."
    with_notice = bare + " " + NOTICE
    assert m.value_coverage(bare, reference)["coverage"] == \
           m.value_coverage(with_notice, reference)["coverage"]


#the canonical answer

def test_a_boolean_reads_as_a_word_in_the_canonical_answer():
    assert "the public flag true" in m.canonical_answer(None, CREATE_NOTICE)
    assert "the active flag to false" in m.canonical_answer(None, UPDATE_NOTICE)


def test_a_refusal_is_the_sentence_the_prompt_prescribes():
    assert m.canonical_answer("System Info: operation not allowed, query out of domain.") \
        == m.CANONICAL_REFUSAL


def test_no_result_is_a_read_that_found_nothing_not_a_refusal():
    data = {"error_message": "System Info: no result"}
    assert m.canonical_answer(data, macro_section="projects") == "I did not find any projects matching that."
    assert m.effective_category({"macro_section": "work_packages", "intent": "read"}, data) == "read"
    assert m.effective_category({"macro_section": "work_packages", "intent": "read"},
                                "System Info: operation not allowed.") == "out_of_scope"


#item_consistency still separates the items

def test_mixed_items_are_caught():
    reference = m.reference_from_result(read(2, 2))
    good = "I found 2 projects: P10 (id 10); P9 (id 9)."
    mixed = "I found 2 projects: P10 (id 9); P9 (id 10)."
    assert m.item_consistency(good, reference)["consistency"] == 1.0
    assert m.item_consistency(mixed, reference)["consistency"] == 0.0


#aggregation: the denominators

def cell(qid, rep, **kw):
    base = {"question_id": qid, "repetition": rep, "difficulty": "easy", "intent": "read",
            "macro_section": "work_packages", "extraction": {"intent": "read"},
            "stage1_ok": True, "stage2_invoked": True, "answer_generated": True,
            "stage2_perfect": True, "answer": "same answer", "t_phase1": 1.0}
    base.update(kw)
    return base


def test_the_second_model_is_not_charged_for_the_cells_it_never_saw():
    cells = [cell("A", 1),
             cell("B", 1, stage1_ok=False, stage2_invoked=False, answer_generated=False,
                  stage2_perfect=False, answer=None)]
    phase2 = m.phase2_metrics(cells)
    cascade = m.cascade_metrics(cells)
    assert phase2["cells_generated"] == 1
    assert phase2["stage2_perfect_rate"] == 1.0      # over the cell it answered
    assert cascade["end_to_end_success"] == 1.0      # over the evaluated cells
    assert cascade["system_success_all_cells"] == 0.5  # over all of them
    assert cascade["gate_pass_rate"] == 0.5


def test_a_deterministic_refusal_is_counted_apart_from_the_model():
    cells = [cell("A", 1), cell("B", 1, answer_generated=False, answer="written by the system")]
    phase2 = m.phase2_metrics(cells)
    assert phase2["cells_invoked"] == 2
    assert phase2["cells_generated"] == 1
    assert phase2["deterministic_answers"] == 1


#aggregation: the per-question view

def test_stability_sees_the_repetitions_the_flat_rates_hide():
    """ two answers alike and one different: the flat rate says nothing, stability says 2/3 """
    cells = [cell("A", 1), cell("A", 2), cell("A", 3, answer="a different answer",
                                              stage2_perfect=False)]
    rows = m.by_question(cells)
    assert len(rows) == 1
    row = rows[0]
    assert row["repetitions"] == 3
    assert row["extraction_deterministic"] is True     # the extraction never moved
    assert row["answer_deterministic"] is False
    assert row["answer_stability"] == 0.667
    assert row["stage2_perfect_rate"] == 0.667


def test_a_question_weighs_one_however_many_times_it_ran():
    """ A fails three times, B succeeds once: over cells that is 1/4, over questions 1/2 """
    cells = [cell("A", i, stage2_perfect=False) for i in (1, 2, 3)] + [cell("B", 1)]
    flat = m.cascade_metrics(cells)["system_success_all_cells"]
    macro = m.stability_summary(m.by_question(cells))["stage2_perfect_rate_by_question"]
    assert flat == 0.25
    assert macro == 0.5


def test_aggregate_carries_both_views():
    cells = [cell("A", 1), cell("A", 2)]
    summary = m.aggregate(cells, "model1", "model2")
    assert summary["phase1"]["model"] == "model1"
    assert summary["phase2"]["model"] == "model2"
    assert summary["stability"]["questions"] == 1
    assert summary["stability"]["repetitions"] == 2
    assert len(summary["by_question"]) == 1
    #one stage per file: the three blocks do not share their columns
    assert {r["stage"] for r in m.flat_rows(summary, "phase1")} == {"phase1"}
