"""Architecture rule: a layer may import only from itself and the layers below it.

Layers, lowest first: domain, generation, store, scenarios. config is shared by all. The top-level
modules (tickets, cli) assemble the layers and may import any of them.
"""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "src" / "datagen"
ALLOWED = {
    "domain": {"domain"},
    "generation": {"domain", "generation"},
    "store": {"domain", "generation", "store"},
    "scenarios": {"domain", "generation", "store", "scenarios"},
}


def imported_layers(path):
    layers = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                and node.module.startswith("src.datagen"):
            parts = node.module.split(".")
            if len(parts) > 2:
                layers.add(parts[2])
            else:                                         # "from src.datagen import generation, config"
                layers.update(alias.name for alias in node.names)
    return layers - {"config"}


def test_layers_only_import_downwards():
    violations = []
    for layer, allowed in ALLOWED.items():
        for path in sorted((PKG / layer).glob("*.py")):
            extra = imported_layers(path) - allowed
            if extra:
                violations.append(f"{path.relative_to(PKG)} imports {sorted(extra)}")
    assert not violations, violations


def test_no_relative_imports_remain():
    offenders = [str(p.relative_to(PKG)) for p in PKG.rglob("*.py")
                 if any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))))]
    assert not offenders, offenders