"""AD-482a v1: Stage Contracts -- typed I/O specs for inter-agent task handoffs.

A `StageContract` declares the shape of one stage in a multi-step workflow:
what inputs it expects, what outputs it produces, the definition of done, the
recoverable error codes, and the maximum retry count. Validation is shape-only
(structural keys + types) -- no runtime coercion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StageContract:
    """Typed I/O specification for one stage in a self-improvement workflow.

    Args:
        name: Stage label (e.g. "discover", "evaluate", "qa", "promote").
        inputs: Required input keys mapped to expected Python types.
        outputs: Required output keys mapped to expected Python types.
        definition_of_done: Human-readable success criterion.
        error_codes: Recoverable error codes the caller may surface.
        max_retries: Maximum retry count before the stage fails terminal.
    """

    name: str
    inputs: dict[str, type]
    outputs: dict[str, type]
    definition_of_done: str
    error_codes: tuple[str, ...] = field(default_factory=tuple)
    max_retries: int = 3

    def validate_input(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Shape-check ``payload`` against ``self.inputs``.

        Returns (True, "") on conformance, or (False, reason) on the first miss.
        Type checks use ``isinstance`` on declared types; subclasses pass.
        """
        for key, expected_type in self.inputs.items():
            if key not in payload:
                return False, f"missing input key: {key!r}"
            if not isinstance(payload[key], expected_type):
                actual = type(payload[key]).__name__
                want = expected_type.__name__
                return False, f"input {key!r}: expected {want}, got {actual}"
        return True, ""

    def validate_output(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Shape-check ``payload`` against ``self.outputs``.

        Returns (True, "") on conformance, or (False, reason) on the first miss.
        """
        for key, expected_type in self.outputs.items():
            if key not in payload:
                return False, f"missing output key: {key!r}"
            if not isinstance(payload[key], expected_type):
                actual = type(payload[key]).__name__
                want = expected_type.__name__
                return False, f"output {key!r}: expected {want}, got {actual}"
        return True, ""
