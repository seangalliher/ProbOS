"""AD-801: doctor-check protocol + result types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class CheckOutcome(Enum):
    """Tri-state result of a single check."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    """Result of running a single check.

    `outcome` drives glyph + exit code (FAIL count). `message` is the
    one-line summary always printed. `remediation` is shown on WARN/FAIL
    only; if empty, no remediation line is rendered.
    """

    outcome: CheckOutcome
    message: str
    remediation: str = ""


@dataclass(frozen=True)
class DoctorContext:
    """Immutable execution context handed to every check.

    `config` is the loaded `SystemConfig`, or `None` when the config-file
    check itself failed (subsequent checks should degrade gracefully).
    """

    config: Any
    home_dir: Path
    data_dir: Path
    config_path: Path | None


class DoctorCheck(Protocol):
    """Structural contract for a doctor check.

    Each check is a small object with a stable `name` and an async
    `run(ctx)` returning a `CheckResult`. Async so checks that probe
    network endpoints (LLM tiers, NATS, federation peers) can use
    `asyncio.wait_for` directly.

    Marked `@runtime_checkable` so tests can `isinstance(check, DoctorCheck)`.
    """

    @property
    def name(self) -> str: ...

    async def run(self, ctx: DoctorContext) -> CheckResult: ...


DoctorCheck = runtime_checkable(DoctorCheck)  # type: ignore[assignment]
