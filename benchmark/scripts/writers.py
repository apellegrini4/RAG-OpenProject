#module allowed to write inside benchmark/runs/ and benchmark/results/

from pathlib import Path
import csv
import json

INVALID_CHAR = ["'", "[", "<", ">", ":", "\"", "/", "\\", "|", "?", "*", "]"]

class RunExistsError(RuntimeError):
    """ raised when a run directory already exists (writers never overwrite silently) """


def validate_name(model_name: str) -> str:
    """ turns the name of the model into a valid folder name """
    return "".join("_" if char in INVALID_CHAR else char for char in model_name)


def create_run_dir(runs_dir, run_name: str) -> Path:
    """ creates benchmark/runs/<run_name>/models/ """
    run_dir = Path(runs_dir) / run_name
    if run_dir.exists():
        raise RunExistsError(f"run directory already exists: {run_dir}")

    (run_dir / "models").mkdir(parents=True)
    return run_dir


def model_dir(run_dir, model_name: str) -> Path:
    """ returns (and creates) benchmark/runs/<run>/models/<valid_name>/ """
    run_dir = Path(run_dir)
    d = run_dir / "models" / validate_name(model_name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_jsonl(path: Path, rows: list):
    if not rows:
        return

    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_answers(model_dir, rows: list):
    """ writes the parsed JSON of the output """
    append_jsonl(Path(model_dir) / "answers.jsonl", rows)


def write_reasoning(model_dir, rows: list):
    """ writes only the `reasoning` field of the output """
    append_jsonl(Path(model_dir) / "reasoning.jsonl", rows)


def write_failures(model_dir, rows: list):
    """ writes the raw output, triggered only in case of failure """
    append_jsonl(Path(model_dir) / "failures.jsonl", rows)


def write_performance(model_dir, performance: dict):
    path = Path(model_dir) / "performance.json"
    path.write_text(json.dumps(performance, indent=2, ensure_ascii=False), encoding="utf-8")


def write_manifest(run_dir, manifest: dict):
    path = Path(run_dir) / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def write_summary_csv(run_dir, rows: list):
    path = Path(run_dir) / "summary.csv"
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report_md(run_dir, run_name: str, rows: list):
    """ creates a table with human readable results """
    path = Path(run_dir) / "report.md"
    if not rows:
        path.write_text(f"# {run_name}\n\nNo results.\n", encoding="utf-8")
        return

    cols = list(rows[0].keys())
    lines = [f"# {run_name}", "", "| " + " | ".join(cols) + " |",
              "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_index_csv(results_dir, rows: list):
    """ appends to the single append-only benchmark/results/index.csv """
    results_dir = Path(results_dir)
    if not rows:
        return
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "index.csv"
    file_exists = path.exists()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
