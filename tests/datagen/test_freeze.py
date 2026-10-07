"""Tests for stage 0.4d-3: dataset manifest, freeze and verification."""
import json
import sqlite3
from pathlib import Path

import pytest

from src.datagen import config, freeze
from src.datagen.domain import labels as label_io
from src.datagen.scenarios.phrasing_heldout import HELDOUT

REPO = Path(__file__).resolve().parents[2]
COMMITTED = REPO / "data" / "manifest.json"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    work = tmp_path_factory.mktemp("freeze")
    content, problems = freeze.build_and_describe(work)
    return work, content, problems


def test_build_has_no_problems(built):
    _, content, problems = built
    assert problems == []
    assert set(content["splits"]) == {"dev", "heldout"}
    assert all(s["tickets"] == 150 for s in content["splits"].values())


def test_build_is_deterministic(built, tmp_path):
    _, content, _ = built
    again, _ = freeze.build_and_describe(tmp_path)
    assert freeze.differences(content, again) == []
    assert content == again


def test_splits_have_different_digests(built):
    _, content, _ = built
    dev, held = content["splits"]["dev"], content["splits"]["heldout"]
    assert dev["labels"]["sha256"] != held["labels"]["sha256"]
    assert dev["database_tables"]["tickets"]["sha256"] != held["database_tables"]["tickets"]["sha256"]


def test_dataset_problems_detect_tampering(built):
    work, _, _ = built
    conn = sqlite3.connect(work / "dev" / "support.db")
    labs = label_io.read_labels(work / "labels" / "dev" / "labels.jsonl")
    assert freeze.dataset_problems(conn, labs, "dev", config.DEFAULT_SEED_DEV) == []

    broken = [dict(l) for l in labs]
    broken[0]["referenced_order_id"] = "O-999999"
    broken[0]["order_identifiable"] = True
    broken[1]["priority"] = "LOW" if broken[1]["priority"] != "LOW" else "HIGH"
    problems = freeze.dataset_problems(conn, broken, "dev", config.DEFAULT_SEED_DEV)
    assert any("referenced order does not exist" in p for p in problems)
    assert any("does not match attributes" in p for p in problems)

    assert any("ticket ids" in p for p in freeze.dataset_problems(conn, labs[1:], "dev", config.DEFAULT_SEED_DEV))
    assert any("split or seed" in p for p in freeze.dataset_problems(conn, labs, "heldout", config.DEFAULT_SEED_DEV))
    conn.close()


def test_write_then_verify_round_trip(tmp_path):
    args = ["--manifest", str(tmp_path / "m.json"), "--doc", str(tmp_path / "m.md")]
    assert freeze.main(["write", *args, "--frozen-on", "2026-10-07"]) == 0
    manifest = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert manifest["frozen_on"] == "2026-10-07" and manifest["environment"]["python"]
    assert "Dataset Manifest" in (tmp_path / "m.md").read_text(encoding="utf-8")
    assert freeze.main(["verify", *args]) == 0
    assert freeze.main(["write", *args]) == 1                    # frozen: refuses to overwrite
    assert freeze.main(["write", *args, "--force"]) == 0


def test_verify_detects_a_changed_phrasing(tmp_path, monkeypatch, capsys):
    args = ["--manifest", str(tmp_path / "m.json"), "--doc", str(tmp_path / "m.md")]
    assert freeze.main(["write", *args]) == 0
    monkeypatch.setitem(HELDOUT, "S20", ["Can I buy a gift card from you today?", *HELDOUT["S20"][1:]])
    capsys.readouterr()
    assert freeze.main(["verify", *args]) == 1
    out = capsys.readouterr().out
    # wording lives in the tickets table, not in the labels, so only that table's digest changes
    assert "heldout.database.tickets: content differs" in out
    assert "dev." not in out                                      # the development split is untouched


def test_verify_without_manifest_fails(tmp_path):
    assert freeze.main(["verify", "--manifest", str(tmp_path / "none.json")]) == 1


def test_committed_manifest_matches_the_generator(built):
    """The freeze: this fails when the generator, a phrasing pool or a seed changes the dataset."""
    _, content, _ = built
    assert COMMITTED.exists(), "data/manifest.json is missing; run: python -m src.datagen.freeze write"
    expected = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert freeze.differences(expected, content) == [], \
        "dataset no longer matches data/manifest.json (see data-design.md section 13 before re-freezing)"