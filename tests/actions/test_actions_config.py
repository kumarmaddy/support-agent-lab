"""Stage 3.5: the actions configuration. Everything is off unless the file says otherwise, and a bad file stops the server."""
from pathlib import Path

import pytest

from src.actions.config import ACTIONS, ConfigError, load_config, parse_config

SHIPPED = Path(__file__).resolve().parents[2] / "config" / "actions.toml"


def test_the_shipped_file_has_every_write_tool_switched_off():
    config = load_config(SHIPPED)
    assert config.enabled == frozenset() and not any(config.is_enabled(a) for a in ACTIONS)
    assert str(config.sandbox).replace("\\", "/") == "data/sandbox/support.db"


def test_a_switch_turns_one_tool_on():
    config = parse_config(b"[actions]\nrefund = true\ncancel = false\n")
    assert config.is_enabled("refund") and not config.is_enabled("cancel") and not config.is_enabled("replace")


@pytest.mark.parametrize("text", [b"[actions]\nrefund = 'yes'\n", b"[actions]\nrefund = 1\n", b"[actions]\ndelete = true\n", b"[other]\nx = 1\n",
                                  b"[sandbox]\nfile = 'x'\n", b"not toml ==", b"\xff\xfe"])
def test_a_bad_file_stops_the_server(text):
    with pytest.raises(ConfigError):
        parse_config(text)


def test_a_missing_file_is_an_error_not_a_default(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_a_bom_from_windows_is_accepted():
    assert parse_config(b"\xef\xbb\xbf[actions]\ncancel = true\n").is_enabled("cancel")