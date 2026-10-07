"""Tests for stage 0.4d-1: held-out phrasing mechanism and the order-status held-out pools."""
import dataclasses
import re

import pytest

from src.datagen import config
from src.datagen.domain import labels
from src.datagen.scenarios import order_status
from src.datagen.store.db import create_database, load_base_data, load_orders
from src.datagen.scenarios.phrasing_heldout import HELDOUT
from src.datagen.scenarios.base import MissingHeldoutPhrasing, Phrasing
from src.datagen.tickets import create_ticket_dataset

DEV_MODULES = [order_status]       # extended as families gain held-out pools (0.4d-2)
COVERED = {"S01", "S02", "S03", "S04", "S22"}


def dev_pool(scenario_id):
    for module in DEV_MODULES:
        pool = getattr(module, f"_{scenario_id}", None)
        if pool is not None:
            return pool
    raise KeyError(scenario_id)


def all_dev_phrasings():
    out = []
    for module in DEV_MODULES:
        for name, value in vars(module).items():
            if re.fullmatch(r"_S\d+(_\w+)?", name) and isinstance(value, list) and value \
                    and isinstance(value[0], Phrasing):
                out += value
    return out


def shingles(text, n=4):
    words = re.findall(r"[a-z']+", re.sub(r"\{[^}]*\}", "X", text.lower()))
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def generate(tmp_path, split, seed, ids=None):
    conn = create_database(tmp_path / f"{split}.db")
    load_base_data(conn, seed)
    load_orders(conn, seed)
    summary = create_ticket_dataset(conn, seed, split, tmp_path / f"labels_{split}", scenario_ids=ids)
    return conn, labels.read_labels(summary["labels_path"])


def bodies(conn):
    return [r[0] for r in conn.execute("SELECT body FROM tickets ORDER BY ticket_id")]


@pytest.mark.parametrize("scenario_id", sorted(COVERED))
def test_pool_mirrors_dev_pool(scenario_id):
    held, dev = HELDOUT[scenario_id], dev_pool(scenario_id)
    assert len(held) == len(dev)
    for h, d in zip(held, dev):
        # same meaning at each index: only the wording differs
        assert dataclasses.replace(h, text="") == dataclasses.replace(d, text="")


@pytest.mark.parametrize("scenario_id", sorted(COVERED))
def test_held_out_wording_is_not_dev_wording(scenario_id):
    dev_text = {p.text for p in all_dev_phrasings()}
    dev_shingles = set().union(*[shingles(t) for t in dev_text])
    for p in HELDOUT[scenario_id]:
        assert p.text not in dev_text
        s = shingles(p.text)
        assert not s or len(s & dev_shingles) / len(s) <= 0.25, p.text


def test_heldout_generates_and_differs(tmp_path):
    conn_d, labs_d = generate(tmp_path, "dev", config.DEFAULT_SEED_DEV, COVERED)
    conn_h, labs_h = generate(tmp_path, "heldout", config.DEFAULT_SEED_HELDOUT, COVERED)
    assert len(labs_d) == len(labs_h) == 10 + 8 + 5 + 6 + 4      # a bad placeholder would have raised
    assert all(l["split"] == "heldout" for l in labs_h)
    assert {l["scenario_id"] for l in labs_h} == COVERED
    assert set(bodies(conn_d)).isdisjoint(bodies(conn_h))


def test_heldout_without_pool_fails_loudly(tmp_path):
    with pytest.raises(MissingHeldoutPhrasing, match="S05"):
        generate(tmp_path, "heldout", config.DEFAULT_SEED_HELDOUT, {"S05"})


def test_heldout_is_reproducible(tmp_path):
    dirs = []
    for name in ("a", "b"):
        d = tmp_path / name
        d.mkdir()
        dirs.append(d)
    a = generate(dirs[0], "heldout", config.DEFAULT_SEED_HELDOUT, COVERED)
    b = generate(dirs[1], "heldout", config.DEFAULT_SEED_HELDOUT, COVERED)
    assert bodies(a[0]) == bodies(b[0])