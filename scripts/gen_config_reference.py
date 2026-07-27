"""Generate the configuration reference from the Pydantic models.

The reference is generated rather than hand-written so it cannot drift from
``probos.config``. Every field's documentation is the ``Field(description=...)``
the implementer wrote, so improving a docstring improves the published doc.

Usage::

    python scripts/gen_config_reference.py            # write the doc
    python scripts/gen_config_reference.py --check    # fail if stale (CI/test)

``--check`` is what ``tests/test_config_reference_current.py`` runs, so a config
change that forgets to regenerate turns the suite red instead of silently
publishing a stale reference.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _REPO_ROOT / "docs" / "development" / "config-reference.md"

# Written into the file so a reader who lands on it from search knows it is
# generated and where to change it.
_HEADER = """# Configuration Reference

**Generated file — do not edit by hand.**
Regenerate with `python scripts/gen_config_reference.py`.
Every description below comes from the `Field(description=...)` in
`src/probos/config.py`, so the way to improve this page is to improve that.

ProbOS runs with **zero configuration** — every field has a default. The
shipped `config/system.yaml` deliberately does not list every knob; this page
does.

A value marked **default-OFF** ships inert. Turning it on is an operator
decision, and each one states what changes when you do.

"""

_INTRO_BY_SECTION: dict[str, str] = {
    "agentic_loop": (
        "Conversation mechanics for the agentic loop. `tool_result_max_chars` "
        "is the one to look at first: it ships at `0`, meaning **unbounded**, "
        "and `max_iterations` bounds turns rather than bytes — so a single "
        "large tool result can exhaust the context window."
    ),
    "agentic_tools": (
        "Tools offered inside the agentic loop, including the Σ commons "
        "read/write verbs. The publish path has **no consensus gate** — the "
        "rate and size bounds are the control."
    ),
    "records": (
        "Ship's Records — the durable, classified, cross-session knowledge "
        "commons (Nooplex Σ). Distinct from an agent's sovereign episodic "
        "shard (Nooplex A), which lives behind a different filter."
    ),
}


def _type_name(annotation: Any) -> str:
    """Render a field annotation as a short readable type name."""
    text = str(annotation)
    for prefix in ("typing.", "<class '", "'>"):
        text = text.replace(prefix, "")
    return text.replace("NoneType", "None")


def _format_default(field: Any) -> str:
    """Render a field default, distinguishing 'no default' from ``None``."""
    from pydantic_core import PydanticUndefined

    default = getattr(field, "default", PydanticUndefined)
    if default is PydanticUndefined:
        factory = getattr(field, "default_factory", None)
        if factory is not None:
            try:
                return f"`{factory()!r}`"
            except Exception:
                # A factory that needs arguments or touches the environment is
                # not worth crashing the generator over.
                return "_(computed)_"
        return "**required**"
    return f"`{default!r}`"


def _constraints(field: Any) -> str:
    """Render ge/le/min/max constraints so bounds are visible in the doc."""
    parts: list[str] = []
    for meta in getattr(field, "metadata", []) or []:
        for attr, label in (
            ("ge", "≥"), ("le", "≤"), ("gt", ">"), ("lt", "<"),
            ("min_length", "min len"), ("max_length", "max len"),
        ):
            value = getattr(meta, attr, None)
            if value is not None:
                parts.append(f"{label} {value}")
    return ", ".join(parts)


def _describe_model(name: str, model: type, seen: set[str]) -> list[str]:
    """Render one Pydantic model as a markdown section, recursing into children."""
    if name in seen:
        return []
    seen.add(name)

    lines = [f"## `{name}`", ""]
    intro = _INTRO_BY_SECTION.get(name)
    if intro:
        lines += [intro, ""]

    doc = (model.__doc__ or "").strip()
    if doc:
        # Only the summary paragraph — the full class docstring is often a page
        # of design rationale that belongs in DECISIONS.md, not a reference.
        lines += [doc.split("\n\n")[0].replace("\n", " ").strip(), ""]

    nested: list[tuple[str, type]] = []
    rows = ["| Field | Type | Default | Bounds | Description |",
            "|---|---|---|---|---|"]

    for field_name, field in model.model_fields.items():
        annotation = field.annotation
        if hasattr(annotation, "model_fields"):
            nested.append((field_name, annotation))
            continue
        description = (field.description or "").replace("\n", " ").replace("|", "\\|").strip()
        rows.append(
            f"| `{field_name}` | `{_type_name(annotation)}` "
            f"| {_format_default(field)} | {_constraints(field) or '—'} | {description} |"
        )

    if len(rows) > 2:
        lines += rows + [""]

    for child_name, child_model in nested:
        lines += _describe_model(child_name, child_model, seen)

    return lines


def render() -> str:
    """Build the full reference document."""
    from probos.config import SystemConfig

    lines = [_HEADER]
    seen: set[str] = set()
    for field_name, field in SystemConfig.model_fields.items():
        annotation = field.annotation
        if hasattr(annotation, "model_fields"):
            lines += _describe_model(field_name, annotation, seen)
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed doc differs from the models",
    )
    args = parser.parse_args()

    generated = render()

    if args.check:
        if not _OUTPUT.exists():
            print(f"MISSING: {_OUTPUT}", file=sys.stderr)
            return 1
        current = _OUTPUT.read_text(encoding="utf-8")
        if current != generated:
            print(
                "STALE: docs/development/config-reference.md no longer matches "
                "src/probos/config.py.\nRegenerate with: "
                "python scripts/gen_config_reference.py",
                file=sys.stderr,
            )
            return 1
        print("config reference is current")
        return 0

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(generated, encoding="utf-8")
    print(f"wrote {_OUTPUT.relative_to(_REPO_ROOT)} ({len(generated.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
