"""
Cross-Layer Dependency Analysis for ProbOS
Analyzes import relationships between architecture layers and flags violations.
"""

import ast
import os
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent / "src" / "probos"

# Define which directories constitute each layer
PACKAGE_LAYERS = {
    "substrate": "substrate",
    "mesh": "mesh",
    "consensus": "consensus",
    "agents": "agents",
    "cognitive": "cognitive",
    "knowledge": "knowledge",
    "experience": "experience",
    "channels": "channels",
    "federation": "federation",
    "utils": "utils",
}

# Top-level .py files belong to "core"
CORE_LAYER = "core"

# Allowed imports: layer -> set of layers it may import FROM
# "core" (runtime, api, config, etc.) can import anything
ALLOWED_IMPORTS = {
    "core":       {"substrate", "mesh", "consensus", "agents", "cognitive",
                   "knowledge", "experience", "channels", "federation", "utils"},
    "experience": {"cognitive", "consensus", "mesh", "substrate", "knowledge"},
    "channels":   {"consensus", "mesh", "substrate"},
    "cognitive":  {"knowledge", "substrate", "mesh", "consensus"},
    "consensus":  {"mesh", "substrate"},
    "agents":     {"substrate", "cognitive"},
    "knowledge":  {"substrate"},
    "mesh":       {"substrate"},
    "substrate":  set(),          # lowest layer — imports nothing else
    "federation": {"mesh", "substrate"},
    "utils":      set(),          # utilities — imports nothing else
}

ALL_LAYERS = sorted(ALLOWED_IMPORTS.keys())


def file_to_layer(filepath: Path) -> str:
    """Determine which layer a .py file belongs to."""
    rel = filepath.relative_to(BASE)
    parts = rel.parts
    if len(parts) == 1:
        # Top-level module (runtime.py, api.py, etc.)
        return CORE_LAYER
    first_dir = parts[0]
    return PACKAGE_LAYERS.get(first_dir, first_dir)


def extract_probos_imports(filepath: Path):
    """Parse a Python file and return all probos imports with line numbers."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("probos.") or alias.name == "probos":
                    imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module.startswith("probos.") or node.module == "probos"):
                imports.append((node.lineno, node.module))
    return imports


def imported_module_to_layer(module_path: str) -> str | None:
    """Map a dotted import path like 'probos.substrate.pool' to its layer."""
    parts = module_path.split(".")
    if len(parts) < 2:
        return None  # just 'probos'
    second = parts[1]
    if second in PACKAGE_LAYERS:
        return PACKAGE_LAYERS[second]
    # Otherwise it's a top-level module in probos (e.g. probos.config)
    return CORE_LAYER


def main():
    # Collect all .py files
    py_files = sorted(BASE.rglob("*.py"))
    print(f"Scanning {len(py_files)} Python files under {BASE}\n")

    # Data structures
    layer_imports = defaultdict(lambda: defaultdict(int))   # layer_from -> layer_to -> count
    layer_file_count = defaultdict(int)
    layer_import_count = defaultdict(int)
    violations = []  # (source_file, line, import_path, source_layer, target_layer)

    for fpath in py_files:
        src_layer = file_to_layer(fpath)
        layer_file_count[src_layer] += 1

        for lineno, module_path in extract_probos_imports(fpath):
            tgt_layer = imported_module_to_layer(module_path)
            if tgt_layer is None:
                continue
            if tgt_layer == src_layer:
                continue  # intra-layer, skip

            layer_imports[src_layer][tgt_layer] += 1
            layer_import_count[src_layer] += 1

            # Check for violations
            allowed = ALLOWED_IMPORTS.get(src_layer, set())
            if tgt_layer not in allowed:
                violations.append((
                    str(fpath.relative_to(BASE)),
                    lineno,
                    module_path,
                    src_layer,
                    tgt_layer,
                ))

    # ── Print results ──────────────────────────────────────────────
    print("=" * 80)
    print("  LAYER FILE COUNTS")
    print("=" * 80)
    for layer in ALL_LAYERS:
        print(f"  {layer:15s}  {layer_file_count.get(layer, 0):4d} files")
    print()

    # Dependency matrix
    print("=" * 80)
    print("  CROSS-LAYER DEPENDENCY MATRIX  (rows import from columns)")
    print("=" * 80)
    header = f"{'FROM / TO':>15s}"
    for col in ALL_LAYERS:
        header += f" {col[:7]:>7s}"
    header += "  TOTAL"
    print(header)
    print("-" * len(header))

    for row in ALL_LAYERS:
        line = f"{row:>15s}"
        row_total = 0
        for col in ALL_LAYERS:
            cnt = layer_imports[row].get(col, 0)
            row_total += cnt
            if cnt:
                line += f" {cnt:7d}"
            else:
                line += f" {'·':>7s}"
            # Mark violations with asterisk
        line += f"  {row_total:5d}"
        print(line)
    print()

    # Total imports per layer
    print("=" * 80)
    print("  CROSS-LAYER IMPORT TOTALS (outgoing)")
    print("=" * 80)
    for layer in ALL_LAYERS:
        total = layer_import_count.get(layer, 0)
        targets = dict(layer_imports.get(layer, {}))
        if targets:
            detail = ", ".join(f"{k}({v})" for k, v in sorted(targets.items(), key=lambda x: -x[1]))
            print(f"  {layer:15s}  {total:4d} cross-layer imports  ->  {detail}")
        else:
            print(f"  {layer:15s}  {total:4d} cross-layer imports")
    print()

    # Violations
    print("=" * 80)
    print("  VIOLATIONS  (imports going the WRONG direction)")
    print("=" * 80)
    if not violations:
        print("  None! All cross-layer imports follow the allowed dependency rules.")
    else:
        print(f"  Found {len(violations)} violation(s):\n")
        # Group by source_layer -> target_layer
        grouped = defaultdict(list)
        for src_file, lineno, mod, src_layer, tgt_layer in violations:
            grouped[(src_layer, tgt_layer)].append((src_file, lineno, mod))

        for (src_layer, tgt_layer), entries in sorted(grouped.items()):
            print(f"  [{src_layer}] -> [{tgt_layer}]  (NOT ALLOWED)")
            for src_file, lineno, mod in sorted(entries):
                print(f"    {src_file}:{lineno}  import {mod}")
            print()

    # Summary
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    total_files = sum(layer_file_count.values())
    total_cross = sum(layer_import_count.values())
    print(f"  Total .py files scanned:     {total_files}")
    print(f"  Total cross-layer imports:   {total_cross}")
    print(f"  Total violations:            {len(violations)}")

    # Print the allowed dependency rules for reference
    print()
    print("=" * 80)
    print("  ALLOWED DEPENDENCY RULES (for reference)")
    print("=" * 80)
    for layer in ALL_LAYERS:
        allowed = ALLOWED_IMPORTS[layer]
        if allowed:
            print(f"  {layer:15s}  may import from: {', '.join(sorted(allowed))}")
        else:
            print(f"  {layer:15s}  may import from: (nothing — leaf layer)")
    print()


if __name__ == "__main__":
    main()
