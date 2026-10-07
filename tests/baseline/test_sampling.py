import pytest

from src.baseline.sampling import PRACTICE_TICKETS, allocate, select_sample


def test_allocate_gives_every_scenario_a_slot_and_sums_to_n():
    counts = {"A": 10, "B": 6, "C": 1, "D": 3}
    for n in (4, 7, 12, 20):
        alloc = allocate(counts, n)
        assert sum(alloc.values()) == n
        assert all(1 <= alloc[s] <= counts[s] for s in counts)


def test_allocate_follows_scenario_size():
    alloc = allocate({"big": 100, "small": 10}, 22)
    assert alloc["big"] > alloc["small"] >= 1


def test_allocate_rejects_impossible_sizes():
    with pytest.raises(ValueError):
        allocate({"A": 5, "B": 5}, 1)
    with pytest.raises(ValueError):
        allocate({"A": 5, "B": 5}, 11)


def test_sample_is_stratified_reproducible_and_dev_only(dev_dataset):
    *_, labs = dev_dataset
    sample = select_sample(labs, 40, 20261006)
    assert sample == select_sample(labs, 40, 20261006)
    assert sample != select_sample(labs, 40, 1)
    by_id = {l["ticket_id"]: l for l in labs}
    assert len(sample["ticket_ids"]) == len(set(sample["ticket_ids"])) == 40
    assert {by_id[t]["scenario_id"] for t in sample["ticket_ids"]} == {l["scenario_id"] for l in labs}
    assert len(sample["practice_ids"]) == PRACTICE_TICKETS
    assert not set(sample["practice_ids"]) & set(sample["ticket_ids"])


def test_held_out_labels_are_refused(dev_dataset):
    *_, labs = dev_dataset
    with pytest.raises(ValueError, match="development"):
        select_sample([{**labs[0], "split": "heldout"}, *labs[1:]], 40, 1)
