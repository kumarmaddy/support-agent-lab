import json

from src.baseline import cli
from src.baseline.sampling import select_sample


def prepare_args(tmp_path, labels_path, *extra):
    return ["prepare", "--labels", str(labels_path), "--sample", str(tmp_path / "sample.json"),
            "--results", str(tmp_path / "results.jsonl"), *extra]


def perfect_results(sample, labs, seconds=90.0, flaw=None):
    """Results of a flawless handler, for exercising scoring and the report (test data, not real timings)."""
    by_id = {l["ticket_id"]: l for l in labs}
    rows = []
    for position, tid in enumerate(sample["ticket_ids"], 1):
        lab = by_id[tid]
        category = "other" if flaw == tid else lab["category"]
        rows.append({"ticket_id": tid, "practice": False, "position": position, "seconds": seconds + position,
                     "pauses": 0, "category": category, "actions": lab["expected_actions"],
                     "kb_ids": lab["required_kb_ids"], "started_at": "2026-10-08T09:00:00"})
    return rows


def write_results(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_prepare_writes_a_fixed_sample(tmp_path, dev_dataset, capsys):
    labels_path = dev_dataset[1]
    assert cli.main(prepare_args(tmp_path, labels_path, "--size", "30")) == 0
    sample = json.loads((tmp_path / "sample.json").read_text(encoding="utf-8"))
    assert len(sample["ticket_ids"]) == 30 and sample["split"] == "dev"
    assert cli.main(prepare_args(tmp_path, labels_path)) == 1             # fixed once chosen
    (tmp_path / "results.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    assert cli.main(prepare_args(tmp_path, labels_path, "--force")) == 1  # never after results exist


def test_report_refuses_partial_runs(tmp_path, dev_dataset, capsys):
    db, labels_path, labs = dev_dataset
    sample = select_sample(labs, 30, 1)
    (tmp_path / "sample.json").write_text(json.dumps(sample), encoding="utf-8")
    write_results(tmp_path / "results.jsonl", perfect_results(sample, labs)[:10])
    args = ["report", "--labels", str(labels_path), "--sample", str(tmp_path / "sample.json"),
            "--results", str(tmp_path / "results.jsonl"), "--report", str(tmp_path / "report.md")]
    assert cli.main(args) == 1 and "20 of 30" in capsys.readouterr().out
    assert cli.main([*args, "--allow-partial"]) == 0


def test_report_end_to_end(tmp_path, dev_dataset):
    db, labels_path, labs = dev_dataset
    sample = select_sample(labs, 30, 1)
    (tmp_path / "sample.json").write_text(json.dumps(sample), encoding="utf-8")
    write_results(tmp_path / "results.jsonl", perfect_results(sample, labs, flaw=sample["ticket_ids"][0]))
    args = ["report", "--labels", str(labels_path), "--sample", str(tmp_path / "sample.json"),
            "--results", str(tmp_path / "results.jsonl"), "--report", str(tmp_path / "report.md"),
            "--hourly-rate", "25", "--hourly-rate", "50", "--manifest", str(tmp_path / "manifest.json")]
    (tmp_path / "manifest.json").write_text('{"dataset_version": "9.8.7"}', encoding="utf-8")
    assert cli.main(args) == 0
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    for heading in ("# Baseline Report", "## 1. Handling time", "## 2. Accuracy", "## 3. Cost per ticket", "## 4. Limitations"):
        assert heading in text
    assert "| $25.00 |" in text and "| $50.00 |" in text and "| $30.00 |" not in text
    assert sample["ticket_ids"][0] in text                                 # the deliberately wrong ticket is listed
    assert "96.7%" in text                                                 # 29 of 30 categories right
    assert "one person" in text.lower() and "familiarity" in text.lower()
    assert "dataset version 9.8.7" in text                                 # version comes from the manifest
    assert "95% CI" in text and "### Escalation as a decision" in text and "### Disagreements with the labels" in text
    assert "Precision:" in text and "Recall:" in text