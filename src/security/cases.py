"""The case file: one JSON object per line in ``data/security/cases.jsonl``.

A case names a layer (what is attacked), a family (the kind of attack), whether it is an attack or a control (a legitimate use that must
keep working, so that a suite that refuses everything cannot pass), and a layer-specific ``spec``. Strings in a spec may use role
placeholders: ``{refund[order]}`` (text) or ``$refund.amount`` (the whole value, keeps its type). See ``world.load_roles``.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

LAYERS = ("pipeline", "actions", "approval", "read")
FAMILIES = ("ticket_injection", "approval_bypass", "impersonation", "cross_customer", "refund_abuse", "knowledge_injection", "oversized_malformed",
            "approval_page", "tool_misuse", "control")
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "security" / "cases.jsonl"
MIN_CASES = 60
_ID = re.compile(r"^[A-Z]-\d{3}$")
_WHOLE = re.compile(r"^\$(\w+)\.(\w+)$")
_PLACEHOLDER = re.compile(r"\{(\w+)(?:\[(\w+)\])?\}")


def case_digests(path=DEFAULT_PATH) -> dict:
    """Short hash of each case's parsed content (keys sorted, non-ASCII escaped), by case id. Independent of line endings, a byte-order mark,
    blank lines and key order, so a Windows checkout hashes like the original; any change to a case's content changes its digest."""
    out = {}
    for raw in Path(path).read_bytes().decode("utf-8-sig").splitlines():
        if raw.strip():
            rec = json.loads(raw)
            out[rec["id"]] = hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()[:8]
    return out


def cases_sha256(path=DEFAULT_PATH) -> str:
    """One hash for the whole file's parsed content, in file order (see ``case_digests``)."""
    return hashlib.sha256(" ".join(f"{k}:{v}" for k, v in case_digests(path).items()).encode("ascii")).hexdigest()


class CaseError(Exception):
    pass


@dataclass(frozen=True)
class Case:
    id: str
    layer: str
    family: str
    title: str
    attack: bool
    spec: dict


def load_cases(path=DEFAULT_PATH) -> list:
    cases, seen = [], set()
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
            case = Case(rec["id"], rec["layer"], rec["family"], rec["title"], bool(rec["attack"]), rec["spec"])
        except (ValueError, KeyError) as exc:
            raise CaseError(f"line {n}: {exc!r}") from exc
        if not _ID.match(case.id) or case.id in seen:
            raise CaseError(f"line {n}: bad or duplicate id {case.id!r}")
        if case.layer not in LAYERS or case.family not in FAMILIES:
            raise CaseError(f"line {n}: unknown layer or family ({case.layer!r}, {case.family!r})")
        if (case.family == "control") == case.attack:
            raise CaseError(f"line {n}: a control is not an attack, and every other family is")
        seen.add(case.id)
        cases.append(case)
    return cases


def resolve(value, roles: dict, extra: dict = None):
    """Fill role placeholders in a spec value (recursively). ``$role.key`` stands for the whole value and keeps its type."""
    extra = extra or {}
    if isinstance(value, dict):
        return {k: resolve(v, roles, extra) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, roles, extra) for v in value]
    if isinstance(value, str):
        whole = _WHOLE.match(value)
        if whole and whole.group(1) in roles:
            return roles[whole.group(1)][whole.group(2)]
        def fill(m):
            if m.group(2) is not None and m.group(1) in roles:
                return str(roles[m.group(1)][m.group(2)])
            if m.group(2) is None and m.group(1) in extra:
                return str(extra[m.group(1)])
            return m.group(0)                                    # any other braces (JSON, SQL, templates) are left exactly as written
        return _PLACEHOLDER.sub(fill, value)
    return value