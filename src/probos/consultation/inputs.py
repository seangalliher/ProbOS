"""AD-594a v1: ``InputProcessor`` Protocol seam + passthrough text impl.

Captain ships a Protocol seam in v1 so the workspace API has a stable
integration point for future PDF / image / audio processors. v1 ships
``PassthroughTextProcessor`` only; future processors (separate AD) plug in
here. The ``Northstar II Transporter Pattern`` referenced in the AD-594
roadmap entry is a forthcoming input-ingestion subsystem; today's
``cognitive/builder.py`` Transporter Pattern is unrelated (builder code-chunk
decomposition).
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class InputProcessor(Protocol):
    """Process a staged input (filename + raw bytes) into agent-readable form.

    Implementations may rewrite the filename (e.g. ``report.pdf`` →
    ``report.pdf.txt``) and transform the bytes (e.g. PDF extraction). v1
    contract is text-bytes-in / text-bytes-out; binary outputs must be
    encoded by the implementation.
    """

    def process(self, filename: str, content: bytes) -> tuple[str, bytes]:
        ...


class PassthroughTextProcessor:
    """v1 default: returns input unchanged.

    Filename and content are passed through verbatim. Used when no real
    processor is configured. Suitable for plain-text inputs.
    """

    name = "passthrough"

    def process(self, filename: str, content: bytes) -> tuple[str, bytes]:
        return filename, content


def build_input_processor(name: str) -> InputProcessor:
    """Resolve a registered processor name to an instance.

    v1 only knows ``"passthrough"``. Unknown names log-and-degrade to
    PassthroughTextProcessor so misconfiguration cannot break the workspace.
    """
    if name == "passthrough":
        return PassthroughTextProcessor()
    logger.warning(
        "AD-594a: unknown input_processor=%r; falling back to passthrough", name
    )
    return PassthroughTextProcessor()
