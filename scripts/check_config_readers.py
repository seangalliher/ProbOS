"""BF-926 (#1656): report config fields no production code reads to act on, and yaml keys no field declares.

REPORT-ONLY: this check warns and never fails. Its exit status is 0 on every input -- a missing
or malformed yaml file, a source file that does not parse, an unknown or incomplete argument --
because nothing may gate on it until the Captain decides to enforce it (#1656). It is a separate
command; ``scripts/run_test_gate.py`` does not run it.

A field counts as read when its name occurs in ``src/probos`` outside the declaring modules
(``config.py`` and ``config_models/``) as an attribute name, a string constant or a call keyword.
That is a name match, not a resolved receiver (the shape of vulture's dead-code scan), so it
under-reports: a generic name such as ``enabled`` counts as read wherever any object has that
attribute. It cannot see a name built at run time, a dump read by key in ``ui/``, or a model
nested inside a list or dict field. Generic config I/O is not a reader here: the config API
(``routers/config.py``) dumps and rewrites every field without naming one, so "unread" and
"inert" mean that no code names the field to act on it, not that no code touches its value.

A field is inert when its ``Field(description=...)`` or the first paragraph of its model's
docstring contains ``INERT_MARKER``. Inert fields are listed apart from the unread ones; an inert
field whose name does occur is listed again for a check by hand.

Usage::

    python -P scripts/check_config_readers.py [--yaml PATH] [--src PATH]
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

INERT_MARKER = "Inert: no production code reads this"
PREFIX = "CONFIG READERS (report-only): "
DEFAULT_YAML = _REPO_ROOT / "config" / "system.yaml"
DEFAULT_SOURCE = _SRC / "probos"
DECLARING = ("config.py", "config_models")


@dataclass
class Report:
    """What one run found, in model and file order."""

    unread: list[str] = field(default_factory=list)
    inert: list[str] = field(default_factory=list)
    inert_referenced: list[str] = field(default_factory=list)
    orphan_yaml_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and hasattr(annotation, "model_fields")


def _summary(model: type) -> str:
    return (model.__doc__ or "").strip().split("\n\n")[0]


def iter_leaves(model: type, prefix: str = "", seen: tuple[type, ...] = ()) -> list[tuple[str, str, bool]]:
    """``(dotted path, field name, inert)`` for every leaf field reachable from ``model``."""
    leaves: list[tuple[str, str, bool]] = []
    section_inert = INERT_MARKER in _summary(model)
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        if _is_model(info.annotation) and info.annotation not in (*seen, model):
            leaves.extend(iter_leaves(info.annotation, f"{path}.", (*seen, model)))
            continue
        inert = section_inert or INERT_MARKER in (info.description or "")
        leaves.append((path, name, inert))
    return leaves


def referenced_names(source_root: Path, declaring: tuple[str, ...] = DECLARING) -> tuple[set[str], list[str]]:
    """Every attribute name, string constant and call keyword outside the declaring modules."""
    names: set[str] = set()
    warnings: list[str] = []
    if not source_root.is_dir():
        warnings.append(f"source root {source_root.as_posix()} is not a directory")
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if relative.parts[0] in declaring:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as exc:
            warnings.append(f"skipped {relative.as_posix()}: {type(exc).__name__}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
    return names, warnings


def _accepted(info: Any, name: str) -> set[str]:
    """The yaml keys a field accepts: its name and any alias."""
    accepted = {name}
    validation_alias = getattr(info, "validation_alias", None)
    for alias in (getattr(info, "alias", None), validation_alias):
        if isinstance(alias, str):
            accepted.add(alias)
    accepted.update(choice for choice in getattr(validation_alias, "choices", None) or () if isinstance(choice, str))
    return accepted


def orphan_keys(model: type, document: Any, prefix: str = "") -> list[str]:
    """Dotted yaml keys under ``model`` that no field of it accepts."""
    if not isinstance(document, dict):
        return []
    fields_by_key = {key: info for name, info in model.model_fields.items() for key in _accepted(info, name)}
    orphans: list[str] = []
    for key, value in document.items():
        path = f"{prefix}{key}"
        info = fields_by_key.get(key)
        if info is None:
            orphans.append(path)
        elif _is_model(info.annotation):
            orphans.extend(orphan_keys(info.annotation, value, f"{path}."))
    return orphans


def build_report(model: type, source_root: Path, yaml_document: Any, declaring: tuple[str, ...] = DECLARING) -> Report:
    report = Report()
    names, report.warnings = referenced_names(Path(source_root), declaring)
    for path, name, inert in iter_leaves(model):
        if inert:
            report.inert.append(path)
            if name in names:
                report.inert_referenced.append(path)
        elif name not in names:
            report.unread.append(path)
    report.orphan_yaml_keys = orphan_keys(model, yaml_document)
    return report


def render(report: Report) -> str:
    lines = [
        f"{PREFIX}{len(report.unread)} unread field(s), {len(report.inert)} inert, "
        f"{len(report.orphan_yaml_keys)} yaml key(s) with no field; this check warns and never fails"
    ]
    for label, items in (
        ("unread", report.unread),
        ("inert", report.inert),
        ("inert, name referenced (check by hand)", report.inert_referenced),
        ("yaml key with no field", report.orphan_yaml_keys),
        ("warning", report.warnings),
    ):
        lines.extend(f"  {label}: {item}" for item in items)
    return "\n".join(lines)


def _read_yaml(path: Path, warnings: list[str]) -> Any:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        warnings.append(f"yaml not read ({path.as_posix()}): {type(exc).__name__}")
        return None


def main(argv: list[str] | None = None) -> int:
    """Print the report. Returns 0 on every path: a check that cannot run says so and passes."""
    try:
        parser = argparse.ArgumentParser(description="Report config fields no production code names to act on (report-only).")
        parser.add_argument("--yaml", default=str(DEFAULT_YAML), help="config file whose keys are checked")
        parser.add_argument("--src", default=str(DEFAULT_SOURCE), help="source tree searched for readers")
        args, unknown = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse exits on a malformed command line; this check never does
        if exc.code not in (0, None):
            print(f"{PREFIX}could not parse the arguments (argparse exit {exc.code}); nothing checked")
        return 0
    try:
        from probos.config import SystemConfig

        yaml_warnings: list[str] = []
        document = _read_yaml(Path(args.yaml), yaml_warnings)
        report = build_report(SystemConfig, Path(args.src), document)
        report.warnings.extend(yaml_warnings)
        report.warnings.extend(f"ignored argument {item!r}" for item in unknown)
        print(render(report))
    except Exception as exc:  # report-only: a failure to report is itself only reported
        print(f"{PREFIX}could not run: {type(exc).__name__}: {exc}")
    return 0  # report-only: the status never reflects the findings


if __name__ == "__main__":
    raise SystemExit(main())
