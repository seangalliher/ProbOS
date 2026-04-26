"""AD-618c: BillLoader — discovers and loads built-in Bill YAML files.

Scans the builtin/ directory at startup, parses each YAML file with
parse_bill_file(), returns a dict of BillDefinition objects keyed by
bill slug.

Also loads custom bills from Ship's Records bills/ directory if available.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from probos.sop.parser import BillValidationError, parse_bill_file
from probos.sop.schema import BillDefinition

logger = logging.getLogger(__name__)

# Path to built-in bills shipped with ProbOS.
# Uses __file__ resolution — sufficient while ProbOS runs from source.
# If ProbOS ever ships as a wheel, switch to importlib.resources.files().
_BUILTIN_DIR = Path(__file__).parent / "builtin"


def load_builtin_bills() -> dict[str, BillDefinition]:
    """Load all built-in Bill YAML files from the builtin/ directory.

    Returns a dict of {bill_slug: BillDefinition}. Logs warnings for
    any files that fail to parse (does not raise — best-effort loading).
    """
    bills: dict[str, BillDefinition] = {}

    if not _BUILTIN_DIR.is_dir():
        logger.warning("AD-618c: Built-in bills directory not found: %s", _BUILTIN_DIR)
        return bills

    for yaml_path in sorted(_BUILTIN_DIR.glob("*.yaml")):
        try:
            bill = parse_bill_file(yaml_path)
            bills[bill.bill] = bill
            logger.debug("AD-618c: Loaded built-in bill: %s", bill.bill)
        except (BillValidationError, FileNotFoundError, yaml.YAMLError) as exc:
            logger.warning(
                "AD-618c: Failed to load built-in bill '%s': %s — skipping",
                yaml_path.name, exc,
            )

    logger.info("AD-618c: Loaded %d built-in bill(s)", len(bills))
    return bills


def load_custom_bills(records_bills_dir: Path | str) -> dict[str, BillDefinition]:
    """Load custom Bill YAML files from Ship's Records bills/ directory.

    Same parsing logic as built-in, but from user-created files.
    Returns empty dict if directory doesn't exist or is empty.

    Note: Custom bills may shadow built-in bills of the same slug.
    Callers are responsible for merging with appropriate precedence
    (typically custom overrides builtin). Within this directory,
    duplicate slugs are logged and skipped (first-wins).
    """
    bills_dir = Path(records_bills_dir)
    bills: dict[str, BillDefinition] = {}

    if not bills_dir.is_dir():
        return bills

    for yaml_path in sorted(bills_dir.glob("*.yaml")):
        try:
            bill = parse_bill_file(yaml_path)
            if bill.bill in bills:
                logger.warning(
                    "AD-618c: Duplicate custom bill slug '%s' in %s — skipping",
                    bill.bill, yaml_path.name,
                )
                continue
            bills[bill.bill] = bill
        except (BillValidationError, FileNotFoundError, yaml.YAMLError) as exc:
            logger.warning(
                "AD-618c: Failed to load custom bill '%s': %s — skipping",
                yaml_path.name, exc,
            )

    if bills:
        logger.info("AD-618c: Loaded %d custom bill(s)", len(bills))
    return bills
