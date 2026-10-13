"""Shadow mode touches the held-out data, so it first checks that the data is still the frozen data and that the gated 7B run is complete.

The full freeze check (``python -m src.evaluation.heldout check``) also lists files added after the freeze, such as the tools written after the
runs, so it cannot be used here. This check covers what matters for shadow mode: the held-out database and labels match the freeze record, and the
single scored 7B run exists, so the sample is drawn after the run and cannot influence it.
"""
from pathlib import Path

from src.evaluation import heldout as h


def require_heldout_intact(root: Path = Path(".")) -> dict:
    root = Path(root)
    record = h.load_record(root)
    held = record["heldout"]
    if h.raw_sha256(root / h.HELDOUT_DB) != held["db_file_sha256"] or h.file_digest(root / h.HELDOUT_LABELS) != held["labels_sha256"]:
        raise h.GateError("The held-out database or labels no longer match the freeze record, so shadow mode stays closed.")
    done = [e for e in h.load_registry(root)["entries"] if e["tag"] == "7b" and e["status"] == "complete"]
    if not done:
        raise h.GateError("The gated 7B held-out run is not complete in the registry; shadow mode starts after it.")
    return record