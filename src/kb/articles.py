"""Load and validate knowledge-base articles (docs/design/data-design.md sections 3 and 7a).

Articles are markdown files in data/seed/kb/, one per article id, with a small front-matter header:

    ---
    id: KB-RET-01
    title: Return policy and the 30-day return window
    category: returns
    version: 1.0
    effective: 2026-10-07
    ---
    ## Key facts            atomic, checkable statements (what a citation must support)
    ## Details              customer-facing explanation
    ## Support guidance (internal)   how the agent should act; never shown to customers
"""
from dataclasses import dataclass
from pathlib import Path

FRONT_MATTER_KEYS = ("id", "title", "category", "version", "effective")
SECTION_KEY_FACTS, SECTION_DETAILS, SECTION_GUIDANCE = "Key facts", "Details", "Support guidance (internal)"
REQUIRED_SECTIONS = (SECTION_KEY_FACTS, SECTION_DETAILS, SECTION_GUIDANCE)
DEFAULT_DIR = Path("data/seed/kb")


@dataclass(frozen=True)
class Article:
    kb_id: str
    title: str
    category: str
    version: str
    effective: str
    sections: dict[str, str]
    path: Path

    @property
    def key_facts(self) -> list[str]:
        return [line[2:].strip() for line in self.sections.get(SECTION_KEY_FACTS, "").splitlines()
                if line.startswith("- ")]

    @property
    def customer_text(self) -> str:
        """What a customer may be shown: everything except the internal guidance."""
        return "\n".join(v for k, v in self.sections.items() if k != SECTION_GUIDANCE)

    @property
    def full_text(self) -> str:
        return "\n".join(self.sections.values())


def parse_article(path: Path) -> Article:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: missing front matter")
    end = lines.index("---", 1) if "---" in lines[1:] else -1
    if end == -1:
        raise ValueError(f"{path}: front matter is not closed")
    meta = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    missing = [k for k in FRONT_MATTER_KEYS if not meta.get(k)]
    if missing:
        raise ValueError(f"{path}: missing front matter keys {missing}")
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines[end + 1:]:
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return Article(meta["id"], meta["title"], meta["category"], meta["version"], meta["effective"],
                   {k: "\n".join(v).strip() for k, v in sections.items()}, Path(path))


def load_articles(directory: Path = DEFAULT_DIR) -> dict[str, Article]:
    articles = [parse_article(p) for p in sorted(Path(directory).glob("*.md"))]
    return {a.kb_id: a for a in articles}