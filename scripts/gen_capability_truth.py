"""Generate the capability-truth inventory from the maturity declarations.

The inventory is generated rather than hand-written so it cannot drift from the
declarations or from the authorities they resolve against. It is observation
only: nothing in ``src/probos/`` reads it and nothing behaves differently
because of it.

Usage::

    python scripts/gen_capability_truth.py                    # write the doc
    python scripts/gen_capability_truth.py --check            # fail if stale
    python scripts/gen_capability_truth.py --json rows.json   # machine-readable
    python scripts/gen_capability_truth.py --config other.yaml

``--check`` is what ``tests/test_ad1270a_capability_truth.py`` runs, so adding a
declaration without regenerating turns the suite red instead of silently
publishing a stale inventory.

The generator constructs **no runtime**. That keeps ``--check`` hermetic and
deterministic, which is the whole value of a committed artifact; the cost is
that ``advertised`` is ``unknown`` for every row, and the document says so.
Attaching a live runtime is migration step 5's job.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _REPO_ROOT / "docs" / "development" / "capability-truth-inventory.md"
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "system.yaml"

_REGENERATE = "python scripts/gen_capability_truth.py"


def _rows(config_path: Path) -> tuple[Any, ...]:
    """Resolve every declaration offline against the given config file."""
    from probos.config import load_config
    from probos.maturity.registry import load_default_registry
    from probos.maturity.report import build_rows

    config = load_config(config_path)
    registry = load_default_registry()
    return asyncio.run(build_rows(registry, config=config, runtime=None))


def render(config_path: Path) -> str:
    """Build the full inventory document."""
    from probos.maturity.report import render_markdown

    return render_markdown(_rows(config_path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed doc differs from the declarations",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="also write the machine-readable row set to PATH",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=str(_DEFAULT_CONFIG),
        help="config file the 'configured' axis resolves against",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    rows = _rows(config_path)

    from probos.maturity.report import render_json, render_markdown

    generated = render_markdown(rows)

    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(render_json(rows), indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {json_path}")

    if args.check:
        if not _OUTPUT.exists():
            print(f"MISSING: {_OUTPUT}", file=sys.stderr)
            return 1
        current = _OUTPUT.read_text(encoding="utf-8")
        if current != generated:
            print(
                "STALE: docs/development/capability-truth-inventory.md no longer "
                "matches the maturity declarations.\nRegenerate with: "
                f"{_REGENERATE}",
                file=sys.stderr,
            )
            return 1
        print("capability truth inventory is current")
        return 0

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(generated, encoding="utf-8")
    print(f"wrote {_OUTPUT.relative_to(_REPO_ROOT)} ({len(generated.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
