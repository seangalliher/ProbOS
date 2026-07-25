"""AD-1144: RFC 8785 JSON Canonicalization Scheme (JCS) -- pure stdlib.

DD-1/DD-5 purity invariant: this module imports NOTHING outside the standard
library (and, in particular, nothing from the rest of this package's parent
project). That non-import is what lets a third-party agentic harness VENDOR
this file verbatim and verify an ARD trust manifest with a stock JOSE stack.

Why this exists at all: AD-1095 signed over
``json.dumps(payload, sort_keys=True, separators=(",", ":"))``, which is
*nearly* RFC 8785 but not it --

* **Key ordering.** ``sort_keys=True`` orders by Unicode CODE POINT; JCS
  (RFC 8785 section 3.2.3) orders by UTF-16 CODE UNIT. The two disagree for any
  key holding a non-BMP character, because such a character is a surrogate
  PAIR in UTF-16 (0xD800-0xDBFF) and therefore sorts BEFORE code points in
  0xE000-0xFFFF -- the opposite of code-point order.
* **Number serialization.** JCS mandates the ECMAScript ``Number::toString``
  algorithm (ECMA-262); Python's ``repr`` disagrees for a whole class of
  doubles (``1.0``, ``1e20``, ``1e-6``, ``1e-7``, ``-0.0``, ...).

For ASCII-only keys with no floats the two agree -- the dangerous case, because
it LOOKS interoperable and is not.

Public surface: :func:`canonicalize`.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["canonicalize"]

# RFC 7493 (I-JSON) integer safety bound, which RFC 8785 inherits: values
# outside it are not exactly representable as an IEEE-754 double, so there is
# no ECMAScript ``Number::toString`` answer for them.
_MAX_SAFE_INTEGER = 2**53 - 1

# The two-character escapes ECMAScript ``JSON.stringify`` emits. Everything
# else below 0x20 becomes ``\u00xx`` (lowercase hex); nothing at or above 0x20
# other than ``"`` and ``\`` is escaped -- non-ASCII passes through as UTF-8.
_ESCAPES: dict[int, str] = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


def canonicalize(value: object) -> bytes:
    """Serialize ``value`` to its RFC 8785 canonical UTF-8 form.

    Args:
        value: A JSON-shaped Python value -- ``dict`` (string keys only),
            ``list``/``tuple``, ``str``, ``bool``, ``int``, ``float`` or
            ``None``, nested arbitrarily.

    Returns:
        The canonical serialization as UTF-8 bytes: no insignificant
        whitespace, object members ordered by UTF-16 code unit, numbers in
        ECMAScript ``Number::toString`` form, minimal string escaping.

    Raises:
        ValueError: If the input is not canonicalizable -- ``NaN``/``Infinity``
            (both JCS-invalid), an integer outside the I-JSON safe range, a
            non-string object key, an unsupported Python type, or a string
            carrying a lone surrogate (``UnicodeEncodeError`` is a
            ``ValueError`` subclass).
    """
    return _serialize(value).encode("utf-8")


def _serialize(value: object) -> str:
    """Dispatch one JSON value to its canonical text form."""
    if value is None:
        return "null"
    # ``bool`` is an ``int`` subclass -- it MUST be tested first or ``True``
    # would canonicalize to ``1``.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _serialize_string(value)
    if isinstance(value, (int, float)):
        return _serialize_number(value)
    if isinstance(value, dict):
        return _serialize_object(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    raise ValueError(
        f"RFC 8785: cannot canonicalize value of type {type(value).__name__!r}"
    )


def _serialize_object(value: dict[Any, Any]) -> str:
    """Serialize an object with members ordered by UTF-16 code unit.

    Sorting on the UTF-16-BE encoding is exactly a code-unit sort: each unit is
    two big-endian bytes, so lexicographic byte order equals lexicographic
    code-unit order. This is the single point where JCS and Python's
    ``sort_keys=True`` diverge.
    """
    for key in value:
        if not isinstance(key, str):
            raise ValueError(
                "RFC 8785: object keys MUST be strings, got "
                f"{type(key).__name__!r}"
            )
    ordered = sorted(value.items(), key=lambda item: item[0].encode("utf-16-be"))
    members = (f"{_serialize_string(k)}:{_serialize(v)}" for k, v in ordered)
    return "{" + ",".join(members) + "}"


def _serialize_string(value: str) -> str:
    """Serialize a string with the minimal escaping RFC 8785 section 3.2.2.2 allows."""
    out: list[str] = ['"']
    for char in value:
        code = ord(char)
        escape = _ESCAPES.get(code)
        if escape is not None:
            out.append(escape)
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _serialize_number(value: int | float) -> str:
    """Serialize per ECMAScript ``Number::toString`` (RFC 8785 section 3.2.2.3)."""
    if isinstance(value, int):
        if not -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER:
            raise ValueError(
                "RFC 8785: integer outside the I-JSON safe range "
                f"(+/-{_MAX_SAFE_INTEGER}) has no ECMAScript number form: {value}"
            )
        return str(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError(
            f"RFC 8785: NaN and Infinity are not valid JSON numbers, got {value!r}"
        )
    return _es_number_to_string(value)


def _es_number_to_string(value: float) -> str:
    """ECMA-262 ``Number::toString`` with radix 10, transcribed literally.

    The spec picks the shortest decimal digit string ``s`` (of length ``k``)
    and an exponent ``n`` with ``s * 10**(n - k) == value``, then chooses among
    four presentations depending on where ``n`` falls.
    """
    # ECMAScript renders both +0 and -0 as "0"; this branch catches both.
    if value == 0.0:
        return "0"
    if value < 0:
        return "-" + _es_number_to_string(-value)

    digits, n = _shortest_decimal(value)
    k = len(digits)
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    exponent = n - 1
    sign = "+" if exponent >= 0 else "-"
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{mantissa}e{sign}{abs(exponent)}"


def _shortest_decimal(value: float) -> tuple[str, int]:
    """Return ``(digits, n)`` for a positive finite ``value``.

    ``digits`` is the shortest round-tripping decimal digit string with no
    leading or trailing zeros; ``n`` is the ECMAScript exponent such that
    ``int(digits) * 10 ** (n - len(digits)) == value``. ``repr`` already yields
    the shortest round-tripping decimal (PEP 3141 / CPython 3.1+); only its
    PRESENTATION differs from ECMAScript, so it is re-presented here.
    """
    text = repr(value)
    mantissa, _, exponent_text = text.partition("e")
    exponent = int(exponent_text) if exponent_text else 0
    int_part, _, frac_part = mantissa.partition(".")
    digits = int_part + frac_part
    n = len(int_part) + exponent
    without_leading = digits.lstrip("0")
    n -= len(digits) - len(without_leading)
    return without_leading.rstrip("0") or "0", n
