""" Unit tests for benchmark/scripts/writers.py — filesystem-only, no Ollama call.
A fake run must produce the full tree + one row in index.csv, and creating the same run twice
must fail loudly instead of overwriting. """
from pathlib import Path
import csv
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmark" / "scripts"))
import writers as w  # noqa: E402


#validate_name

def test_validate_name_replaces_invalid_characters():
    assert w.validate_name("qwen2.5-coder:1.5b") == "qwen2.5-coder_1.5b"
    assert w.validate_name("granite3.1-moe:1b") == "granite3.1-moe_1b"
    assert ":" not in w.validate_name("a:b:c")


#run creation never overwrites

def test_create_run_dir_fails_if_already_exists(tmp_path):
    runs_dir = tmp_path / "runs"
    w.create_run_dir(runs_dir, "20260729-000000__phase1__demo")
    with pytest.raises(w.RunExistsError):
        w.create_run_dir(runs_dir, "20260729-000000__phase1__demo")


#full fake run produces the complete tree

def test_fake_run_produces_full_tree_and_index_row(tmp_path):
    runs_dir = tmp_path / "runs"
    results_dir = tmp_path / "results"

    run_dir = w.create_run_dir(runs_dir, "20260729-000000__phase1__demo")
    w.write_manifest(run_dir, {"phase": "phase1", "models": ["qwen2.5-coder:1.5b"]})

    m_dir = w.model_dir(run_dir, "qwen2.5-coder:1.5b")
    assert m_dir == run_dir / "models" / "qwen2.5-coder_1.5b"

    w.write_answers(m_dir, [{"question_id": "E01", "repetition": 0, "json_correct": True}])
    w.write_reasoning(m_dir, [{"question_id": "E01", "repetition": 0, "reasoning": "because..."}])
    w.write_failures(m_dir, [{"question_id": "E01", "repetition": 0, "failure_reason": "filter_mismatch"}])
    performance = {"model": "qwen2.5-coder:1.5b", "determinism_rate": 1.0, "stability": 1.0,
                   "json_correct_rate": 1.0, "exact_filter_match_rate": 0.5, "median_latency": 1.2}
    w.write_performance(m_dir, performance)

    w.write_summary_csv(run_dir, [performance])
    w.write_report_md(run_dir, "demo-run", [performance])
    w.append_index_csv(results_dir, [{"run": "demo-run", **performance}])

    assert (run_dir / "manifest.json").exists()
    assert (m_dir / "answers.jsonl").exists()
    assert (m_dir / "reasoning.jsonl").exists()
    assert (m_dir / "failures.jsonl").exists()
    assert (m_dir / "performance.json").exists()
    assert (run_dir / "summary.csv").exists()
    assert (run_dir / "report.md").exists()

    with open(m_dir / "answers.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    assert rows == [{"question_id": "E01", "repetition": 0, "json_correct": True}]

    index_path = results_dir / "index.csv"
    assert index_path.exists()
    with open(index_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["run"] == "demo-run"


#index.csv is append-only across multiple calls

def test_append_index_csv_accumulates_rows(tmp_path):
    results_dir = tmp_path / "results"
    w.append_index_csv(results_dir, [{"run": "run-1", "model": "a", "determinism_rate": 1.0}])
    w.append_index_csv(results_dir, [{"run": "run-2", "model": "b", "determinism_rate": 0.5}])

    with open(results_dir / "index.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["run"] for r in rows] == ["run-1", "run-2"]
