"""One-off migration: reorganise the repository into logical groups.

Run from the repository root:
    python restructure_repo.py --dry-run     # show what would happen, change nothing
    python restructure_repo.py               # do it (uses `git mv` when inside a git repository)

What it does
1. Moves source modules into layered sub-packages, tests into tests/datagen/, docs into groups.
2. Rewrites every intra-project import to an absolute import at the new location (using the `ast`
   module to find import statements, so strings and comments are never touched).
3. Updates document-path mentions in code comments (docs/data-design.md -> docs/design/data-design.md).
4. Creates the __init__.py files that describe each layer.

The script is safe to re-run: it stops if the migration was already applied. Delete it afterwards.
"""
import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
PKG = "src.datagen"

# ----------------------------------------------------------------------------- the new layout
# old module name (file stem in src/datagen) -> new dotted path below src.datagen
MODULES = {
    # domain: rules and vocabulary, no I/O
    "taxonomy": "domain.taxonomy",
    "priority": "domain.priority",
    "policy": "domain.policy",
    "reference": "domain.reference",
    "kb_catalogue": "domain.kb_catalogue",
    "labels": "domain.labels",
    # store: the SQLite database
    "schema": "store.schema",
    "db": "store.db",
    "checks": "store.checks",
    # generation: building blocks that create data
    "base_data": "generation.base_data",
    "orders": "generation.orders",
    "text": "generation.text",
    # scenarios: one module per family, plus shared machinery
    "scenario_base": "scenarios.base",
    "scenario_registry": "scenarios.registry",
    "scenario_order_status": "scenarios.order_status",
    "scenario_returns": "scenarios.returns",
    "scenario_changes": "scenarios.changes",
    "scenario_accounts": "scenarios.accounts",
    "scenario_adversarial": "scenarios.adversarial",
    "phrasing_heldout": "scenarios.phrasing_heldout",
    # top level: configuration and orchestration stay where they are
    "config": "config",
    "tickets": "tickets",
    "cli": "cli",
}

TESTS = {   # old file -> new file
    "tests/test_datagen_base.py": "tests/datagen/test_base.py",
    "tests/test_datagen_orders.py": "tests/datagen/test_orders.py",
    "tests/test_datagen_tickets.py": "tests/datagen/test_tickets.py",
    "tests/test_datagen_returns.py": "tests/datagen/test_returns.py",
    "tests/test_datagen_changes.py": "tests/datagen/test_changes.py",
    "tests/test_datagen_accounts.py": "tests/datagen/test_accounts.py",
    "tests/test_datagen_adversarial.py": "tests/datagen/test_adversarial.py",
    "tests/test_datagen_heldout.py": "tests/datagen/test_heldout.py",
}

OTHER = {
    "src/scripts/smoke_test_v2.py": "scripts/smoke_test_v2.py",
    "src/scripts/smoke_test.py": "scripts/smoke_test.py",
    "docs/charter.md": "docs/project/charter.md",
    "docs/risk-register.md": "docs/project/risk-register.md",
    "docs/priority-rubric.md": "docs/design/priority-rubric.md",
    "docs/data-design.md": "docs/design/data-design.md",
}

DOC_PATHS = {   # text replacements inside code comments and docs
    "docs/data-design.md": "docs/design/data-design.md",
    "docs/priority-rubric.md": "docs/design/priority-rubric.md",
    "docs/charter.md": "docs/project/charter.md",
    "docs/risk-register.md": "docs/project/risk-register.md",
}

INIT_DOCS = {
    "": '"""Synthetic data generator for the support resolution agent (see docs/design/data-design.md).\n\n'
        'Layers, from the bottom up: domain (rules and vocabulary), store (database), generation (building\n'
        'blocks that create data), scenarios (ticket families), then tickets and cli (assembly and entry point).\n'
        'A layer may import only from layers below it.\n"""\n',
    "domain": '"""Rules and vocabulary: taxonomy, priority rubric, return policy, labels, KB catalogue. No I/O."""\n',
    "store": '"""The SQLite operational database: schema, loading and integrity checks."""\n',
    "generation": '"""Building blocks that create data: seeded customers and products, orders, ticket text."""\n',
    "scenarios": '"""Ticket scenario families, the registry that orders them, and held-out phrasing pools."""\n',
}


def old_path(stem: str) -> Path:
    return ROOT / "src" / "datagen" / f"{stem}.py"


def new_path(dotted: str) -> Path:
    return ROOT / "src" / "datagen" / Path(*dotted.split(".")).with_suffix(".py")


def in_git() -> bool:
    return (ROOT / ".git").exists() and shutil.which("git") is not None


def move(src: Path, dst: Path, dry: bool, use_git: bool) -> None:
    print(f"  move {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    if dry:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if use_git:
        subprocess.run(["git", "mv", str(src), str(dst)], check=True, cwd=ROOT)
    else:
        shutil.move(str(src), str(dst))


# ----------------------------------------------------------------------------- import rewriting
def resolve(node: ast.ImportFrom, file_old_dotted: str) -> str | None:
    """Absolute dotted module a `from ... import` refers to, or None if it is not project code."""
    if node.level == 0:
        return node.module if node.module and (node.module == PKG or node.module.startswith(PKG + ".")) else None
    parts = file_old_dotted.split(".")[: -node.level]        # old flat layout: src.datagen.<stem>
    return ".".join(parts + ([node.module] if node.module else []))


def new_statements(node: ast.ImportFrom, resolved: str, indent: str, renames: dict[str, str]) -> str:
    groups: dict[str, list[str]] = {}

    def add(module: str, name: str, asname: str | None) -> None:
        groups.setdefault(module, []).append(f"{name} as {asname}" if asname else name)

    for alias in node.names:
        if resolved == PKG:                                         # "from src.datagen import X"
            if alias.name in MODULES:
                dotted = MODULES[alias.name]
                parent, _, leaf = dotted.rpartition(".")
                add(f"{PKG}.{parent}" if parent else PKG, leaf, alias.asname)
                if leaf != alias.name and not alias.asname:
                    renames[alias.name] = leaf
            else:
                add(PKG, alias.name, alias.asname)
        else:                                                       # "from src.datagen.X import name"
            stem = resolved[len(PKG) + 1:].split(".")[0]
            if stem not in MODULES:
                raise SystemExit(f"unknown module in import: {resolved}")
            add(f"{PKG}.{MODULES[stem]}", alias.name, alias.asname)

    lines = []
    for module in sorted(groups):
        names = ", ".join(groups[module])
        line = f"{indent}from {module} import {names}"
        if len(line) > 100:
            body = f",\n{indent}    ".join(groups[module])
            line = f"{indent}from {module} import (\n{indent}    {body},\n{indent})"
        lines.append(line)
    return "\n".join(lines)


def rewrite_imports(path: Path, old_dotted: str, dry: bool) -> int:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.split("\n")
    edits, renames = [], {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            resolved = resolve(node, old_dotted)
            if resolved is None:
                continue
            indent = " " * node.col_offset
            edits.append((node.lineno, node.end_lineno, new_statements(node, resolved, indent, renames)))
    for start, end, text in sorted(edits, reverse=True):
        lines[start - 1:end] = text.split("\n")
    result = "\n".join(lines)
    for old, new in renames.items():                                # e.g. scenario_accounts -> accounts
        result = re.sub(rf"\b{old}\b", new, result)
    for old, new in DOC_PATHS.items():
        result = result.replace(old, new)
    if result != source and not dry:
        path.write_text(result, encoding="utf-8")
    return len(edits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry, use_git = args.dry_run, in_git()

    if (ROOT / "src/datagen/domain").exists():
        print("Already migrated (src/datagen/domain exists). Nothing to do.")
        return 0
    missing = [s for s in MODULES if not old_path(s).exists() and s != "phrasing_heldout"]
    if missing:
        print(f"Missing modules, is this the repository root? {missing}")
        return 1
    if use_git:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, cwd=ROOT).stdout
        if status.strip() and not dry:
            print("Working tree has uncommitted changes. Commit or stash them first, so this move is its own commit.")
            return 1
    print(f"Mode: {'dry run' if dry else 'apply'}; git mv: {use_git}")

    # 1. rewrite imports in place first (paths are still the old ones, so resolution is simple)
    print("\nRewriting imports")
    targets = [(old_path(s), f"{PKG}.{s}") for s in MODULES if old_path(s).exists()]
    for old_file in TESTS:
        if (ROOT / old_file).exists():
            targets.append((ROOT / old_file, "tests." + Path(old_file).stem))
    total = 0
    for path, dotted in targets:
        n = rewrite_imports(path, dotted, dry)
        total += n
        print(f"  {path.relative_to(ROOT)}: {n} import statement(s)")

    # 2. move files
    print("\nMoving files")
    for stem, dotted in MODULES.items():
        if old_path(stem).exists() and new_path(dotted) != old_path(stem):
            move(old_path(stem), new_path(dotted), dry, use_git)
    for old, new in {**TESTS, **OTHER}.items():
        if (ROOT / old).exists():
            move(ROOT / old, ROOT / new, dry, use_git)

    # 3. package markers
    print("\nCreating package files")
    if not dry:
        for sub, doc in INIT_DOCS.items():
            init = ROOT / "src" / "datagen" / sub / "__init__.py"
            if sub == "":
                init.write_text(doc, encoding="utf-8")        # replaces the previous (empty) marker
            else:
                init.parent.mkdir(parents=True, exist_ok=True)
                init.write_text(doc, encoding="utf-8")
            print(f"  {init.relative_to(ROOT)}")
    # docs mentioning moved docs (build log, other docs)
    for doc in (ROOT / "docs").rglob("*.md") if (ROOT / "docs").exists() else []:
        if doc.name == "build-log.md":
            continue                                           # history is kept as written; see its mapping entry
        text = doc.read_text(encoding="utf-8")
        new = text
        for old, replacement in DOC_PATHS.items():
            new = new.replace(old, replacement)
        if new != text and not dry:
            doc.write_text(new, encoding="utf-8")
    print(f"\nDone. {total} import statements rewritten. Next: python -m pytest")
    return 0


if __name__ == "__main__":
    sys.exit(main())