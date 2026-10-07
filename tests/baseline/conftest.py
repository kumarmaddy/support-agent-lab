from pathlib import Path

import pytest

from src.datagen import config
from src.datagen.domain import labels as label_io
from src.datagen.store.db import create_database, load_base_data, load_orders
from src.datagen.tickets import create_ticket_dataset
from src.kb.articles import load_articles

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def dev_dataset(tmp_path_factory):
    """The development split built once: (database path, labels path, labels list)."""
    folder = tmp_path_factory.mktemp("baseline_data")
    seed = config.DEFAULT_SEED_DEV
    conn = create_database(folder / "support.db")
    load_base_data(conn, seed)
    load_orders(conn, seed)
    summary = create_ticket_dataset(conn, seed, "dev", folder / "labels")
    conn.close()
    return folder / "support.db", Path(summary["labels_path"]), label_io.read_labels(summary["labels_path"])


@pytest.fixture(scope="session")
def articles():
    return load_articles(REPO / "data" / "seed" / "kb")
