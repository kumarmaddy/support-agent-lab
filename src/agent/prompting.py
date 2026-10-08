
"""Versioned prompt files (phase-1-design.md, section 5).

Prompts are files in the repository named ``<name>.<version>.md``. Loading returns the text with its name, version and
SHA-256 so a trace can say exactly which prompt produced a result.
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_NAME = re.compile(r"^[a-z_]+$")
_VERSION = re.compile(r"^v\d+$")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str
    sha256: str

    @property
    def label(self) -> str:
        return f"{self.name}.{self.version}"


def load_prompt(name: str, version: str, directory: Path = PROMPT_DIR) -> Prompt:
    if not (_NAME.fullmatch(name) and _VERSION.fullmatch(version)):
        raise ValueError(f"invalid prompt name or version: {name!r}, {version!r}")
    raw = (directory / f"{name}.{version}.md").read_bytes()
    return Prompt(name, version, raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())