"""BF-734 (#TBD): `import ship` must not look like a missing package.

AD-1221 writes the fetch helper into the sandbox working directory at execution
time, and the AD-1221 launcher puts that directory on `sys.path`. So `ship` is
importable INSIDE the sandbox — but `find_spec("ship")` in the runtime process,
which happens moments earlier, cannot resolve it.

Both missing-import detectors therefore reported it. Measured on the reference
vessel 2026-08-08, an agent that followed the AD-1221 tool description and wrote
`import ship` produced, on the Captain's console:

    This agent requires packages that are not installed:
      • ship

and the run then blocked on an approval prompt for a package pip could never
supply. Every promoted run that took the advice stalled this way — which is
also why no `AD-1221` broker line ever appeared in the log: the run never
reached `_start_fetch_broker`.

The tool is the only component that knows which modules the ship generates, so
that is where the exclusion lives.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.execution.fetch_broker import SANDBOX_HELPER_FILENAME
from probos.tools.code_execution_tool import (
    _WORKDIR_PROVIDED_MODULES,
    CodeExecutionTool,
    detect_unimportable,
)

SHIP = SANDBOX_HELPER_FILENAME.removesuffix(".py")


# ── the detector ──────────────────────────────────────────────────────────
def test_the_ship_helper_is_not_reported_unimportable() -> None:
    assert detect_unimportable(f"import {SHIP}\nprint(1)\n") == []


def test_a_genuinely_missing_package_is_still_reported() -> None:
    """The carve-out must not blunt the detector."""
    out = detect_unimportable("import definitely_not_a_real_pkg_bf734\n")
    assert out == ["definitely_not_a_real_pkg_bf734"]


def test_the_carve_out_is_exactly_the_generated_module() -> None:
    """A near-miss name must NOT be excluded — the set is not a prefix match."""
    assert detect_unimportable("import shipping_manifest_bf734\n") == [
        "shipping_manifest_bf734"
    ]


def test_mixed_imports_report_only_the_real_miss() -> None:
    out = detect_unimportable(
        f"import json\nimport {SHIP}\nimport still_not_real_bf734\n"
    )
    assert out == ["still_not_real_bf734"]


def test_the_exclusion_set_tracks_the_generated_filename() -> None:
    """Derived, not hardcoded: renaming the helper must not silently reopen
    this defect."""
    assert SHIP in _WORKDIR_PROVIDED_MODULES
    assert SANDBOX_HELPER_FILENAME.endswith(".py")


# ── the install path ──────────────────────────────────────────────────────
class _Resolver:
    def __init__(self, missing: list[str]) -> None:
        self._missing = missing

    def detect_missing(self, code: str) -> list[str]:
        return list(self._missing)


class _Runtime:
    def __init__(self, missing: list[str]) -> None:
        self.config = type(
            "C", (), {"dependency": type("D", (), {"dynamic_install_enabled": True})()}
        )()
        self.dependency_resolver = _Resolver(missing)
        self.asked: list[list[str]] = []

    async def ensure_dependency(self, packages: Any, **kw: Any) -> Any:
        self.asked.append(list(packages))
        return {"installed": [], "declined": list(packages), "error": ""}


@pytest.mark.asyncio
async def test_the_captain_is_never_asked_to_install_ship() -> None:
    """The load-bearing one. Asking pip for `ship` is unanswerable, and the run
    blocks on the prompt."""
    rt = _Runtime([SHIP])
    tool = CodeExecutionTool(runtime=rt)

    result = await tool._maybe_install_missing(f"import {SHIP}\n", requested_by="a")

    assert rt.asked == [], "the ship's own helper reached the install path"
    assert result is None, (
        "a run importing only the ship helper must take the byte-identical "
        "no-install path"
    )


@pytest.mark.asyncio
async def test_a_real_missing_package_still_reaches_the_install_path() -> None:
    rt = _Runtime(["reportlab"])
    tool = CodeExecutionTool(runtime=rt)

    await tool._maybe_install_missing("import reportlab\n", requested_by="a")

    assert rt.asked == [["reportlab"]]


@pytest.mark.asyncio
async def test_a_mixed_set_asks_only_for_the_real_one() -> None:
    rt = _Runtime([SHIP, "reportlab"])
    tool = CodeExecutionTool(runtime=rt)

    await tool._maybe_install_missing(
        f"import {SHIP}\nimport reportlab\n", requested_by="a",
    )

    assert rt.asked == [["reportlab"]]
    assert SHIP not in rt.asked[0]
