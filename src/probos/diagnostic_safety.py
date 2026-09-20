"""Shared named diagnostic policy, applied before rendering or clipping."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any, Protocol

from probos.security.pii_redaction import PIIRedactor

logger = logging.getLogger(__name__)

# Named outbound policy, including the repository's relay key/prefix vocabulary.
# This boundary does not attempt to detect every possible secret format.
_OUTBOUND_SECRET_FIELDS = (
    r"(?:headers?|(?:set[-_])?cookie|authorization|password|passwd|passphrase|"
    r"secret|(?:access[_-]?|refresh[_-]?)?token|credentials?|api.?key|"
    r"private.?key|client[_-]?secret)"
)
_SECRET_FIELD_RE = re.compile(_OUTBOUND_SECRET_FIELDS, re.IGNORECASE)
_SECRET_VALUE_PATTERN = (
    r'''(?:"(?:\\.|[^"\\])*(?:"|\Z)|'(?:\\.|[^'\\])*(?:'|\Z)|[^\s,;}\]"']+)'''
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?P<prefix>(?P<quote>["']?)\b""" + _OUTBOUND_SECRET_FIELDS
    + r"""\b(?P=quote)\s*[:=]\s*)""" + _SECRET_VALUE_PATTERN,
    re.IGNORECASE,
)
_AUTH_VALUE_RE = re.compile(r"\b(?:Basic|Bearer)\s+" + _SECRET_VALUE_PATTERN, re.IGNORECASE)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?P<kind>(?:[A-Z0-9]+ )*PRIVATE KEY)-----"
    r".*?(?:-----END (?P=kind)-----|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_DATA_URI_RE = re.compile(r"""\bdata:[^\s"'<>]+""", re.IGNORECASE)


class TraceReader(Protocol):
    async def read(self, ref: str) -> bytes | str | None: ...


def sanitise_diagnostic_value(
    value: Any, secrets: tuple[str, ...] = (), depth: int = 0,
) -> Any:
    if depth > 16:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            sanitise_diagnostic_value(str(key), secrets): (
                "[REDACTED]" if _SECRET_FIELD_RE.search(str(key))
                else sanitise_diagnostic_value(item, secrets, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitise_diagnostic_value(item, secrets, depth + 1) for item in value]
    if isinstance(value, str):
        value = _PRIVATE_KEY_RE.sub("[REDACTED]", value)
        value = _AUTH_VALUE_RE.sub("[REDACTED]", value)
        value = _DATA_URI_RE.sub("[REDACTED]", value)
        value = _SECRET_ASSIGNMENT_RE.sub(r"\g<prefix>[REDACTED]", value)
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return PIIRedactor.redact_all(value).encode("utf-8", "replace").decode("utf-8")
    return value if value is None or type(value) in (int, float, bool) else "[unavailable]"


def _warn_trace_unavailable() -> None:
    logger.warning(
        "Fault trace could not be read safely; diagnostic trace evidence "
        "will be unavailable"
    )


class SanitisedTraceReader:
    def __init__(
        self, reader: TraceReader | None, secrets: tuple[str, ...] = (), *,
        warn_unavailable: Callable[[], None] | None = None,
    ) -> None:
        if warn_unavailable is not None and not callable(warn_unavailable):
            raise TypeError("warn_unavailable must be callable")
        self._reader, self._secrets = reader, secrets
        self._warn_unavailable = (
            warn_unavailable if warn_unavailable is not None else _warn_trace_unavailable
        )

    async def read(self, ref: str) -> bytes | None:
        if self._reader is None:
            return None
        try:
            blob = await self._reader.read(ref)
            if not isinstance(blob, (bytes, str)):
                return None
            entries = json.loads(blob)
            return json.dumps(sanitise_diagnostic_value(entries, self._secrets)).encode("utf-8")
        except Exception:
            self._warn_unavailable()
            return None
