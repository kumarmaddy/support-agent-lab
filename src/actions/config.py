"""Actions configuration: which write tools are switched on, and where the sandbox database is. Fails closed."""
import tomllib
from dataclasses import dataclass
from pathlib import Path

ACTIONS = ("refund", "replace", "change_address", "cancel")
DEFAULT_CONFIG_PATH = Path("config/actions.toml")
DEFAULT_SANDBOX = Path("data/sandbox/support.db")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class ActionsConfig:
    enabled: frozenset = frozenset()
    sandbox: Path = DEFAULT_SANDBOX

    def is_enabled(self, action: str) -> bool:
        return action in self.enabled


def parse_config(raw: bytes) -> ActionsConfig:
    try:
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"actions config is not valid TOML: {exc}")
    if set(data) - {"actions", "sandbox"}:
        raise ConfigError(f"unknown section(s): {sorted(set(data) - {'actions', 'sandbox'})}")
    actions = data.get("actions", {})
    if set(actions) - set(ACTIONS):
        raise ConfigError(f"unknown action(s): {sorted(set(actions) - set(ACTIONS))}")
    for name, value in actions.items():
        if not isinstance(value, bool):
            raise ConfigError(f"action {name}: must be true or false")
    sandbox = data.get("sandbox", {})
    if set(sandbox) - {"path"} or not isinstance(sandbox.get("path", str(DEFAULT_SANDBOX)), str):
        raise ConfigError("[sandbox] takes only a text 'path'")
    return ActionsConfig(frozenset(k for k, v in actions.items() if v), Path(sandbox.get("path", str(DEFAULT_SANDBOX))))


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ActionsConfig:
    try:
        return parse_config(Path(path).read_bytes())
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}")