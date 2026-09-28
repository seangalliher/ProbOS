"""AD-1137 (#1056): which of ProbOS's optional extras are installed?

Read from the installed distribution's own metadata (``Provides-Extra`` and the
``extra == ...`` markers in ``Requires-Dist``), so an extra added to
pyproject.toml is reported without a change here. Presence only: a version
outside the declared range is not detected. Never FAIL, and never WARN for a
missing extra: extras are optional, so the result lists them with the command
that adds one for the way this copy was installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import metadata

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

_DISTRIBUTION = "probos"
# Development tooling, not a runtime feature.
_NOT_FEATURES = frozenset({"dev"})
_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXTRA_MARKER = re.compile(r"""\bextra\s*==\s*["']([^"']+)["']""")


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _installed(requirement: str) -> bool:
    try:
        metadata.distribution(requirement)
    except metadata.PackageNotFoundError:
        return False
    return True


def _distribution() -> metadata.Distribution:
    return metadata.distribution(_DISTRIBUTION)


def extras_status(distribution: metadata.Distribution) -> dict[str, list[str]]:
    """Each feature extra, in metadata order, mapped to the requirements it lacks ([] when installed)."""
    declared = [_canonical(extra) for extra in distribution.metadata.get_all("Provides-Extra") or []]
    missing: dict[str, list[str]] = {extra: [] for extra in declared if extra not in _NOT_FEATURES}
    for requirement in distribution.requires or []:
        marker = _EXTRA_MARKER.search(requirement)
        name = _REQUIREMENT_NAME.match(requirement)
        if marker is None or name is None:
            continue
        extra = _canonical(marker.group(1))
        if extra in missing and not _installed(name.group(1)):
            missing[extra].append(name.group(1))
    return missing


def install_hint(distribution: metadata.Distribution) -> str:
    """The command that adds an extra, for how this copy was installed (PEP 610 ``direct_url.json``)."""
    try:
        origin = json.loads(distribution.read_text("direct_url.json") or "{}")
    except ValueError:
        origin = {}
    dir_info = origin.get("dir_info") if isinstance(origin, dict) else None
    if isinstance(dir_info, dict):  # installed from a directory: a source checkout
        editable = "-e " if dir_info.get("editable") else ""
        return f'pip install {editable}".[<extra>]", run in the ProbOS checkout'
    return 'pip install "probos[<extra>]"'


@dataclass(frozen=True)
class _ExtrasCheck:
    name: str = "extras"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        try:
            distribution = _distribution()
        except metadata.PackageNotFoundError:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Optional extras: not checked (ProbOS's package metadata was not found)",
                remediation="Install ProbOS with pip (`pip install -e .` in the checkout) so its metadata exists.",
            )
        status = extras_status(distribution)
        installed = [extra for extra, lacking in status.items() if not lacking]
        absent = [extra for extra, lacking in status.items() if lacking]
        if not absent:
            listed = ", ".join(installed) if installed else "none declared"
            return CheckResult(outcome=CheckOutcome.OK, message=f"Optional extras: all installed ({listed})")
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=(
                f"Optional extras installed: {', '.join(installed) or 'none'}; not installed: "
                f"{', '.join(absent)} (add one with {install_hint(distribution)})"
            ),
        )


register_check(_ExtrasCheck())
