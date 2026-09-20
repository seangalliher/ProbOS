"""AD-1243: shared safe evidence policy for stored tool traces.

The AD-1242 key/value/URL sanitisation policy previously lived only inside
:mod:`probos.cognitive.crew_verifier`, private to the judge-prompt trace
section. AD-1243 needs the identical policy for a second, unrelated consumer
-- a read-only HTTP projection of "what was consulted" for a stored trace
(``GET /api/traces/{ref}/consulted``) -- so the policy is extracted here as
the single shared implementation. Duplicating it would have let the two
call sites silently drift; this module is now the only place either can
change.

Two public entry points:

``sanitize_trace_render(rendered, payload_limit)``
    Byte-for-byte what ``crew_verifier._trace_sanitize_render`` used to do,
    moved verbatim. The verifier keeps a thin compatibility wrapper of the
    same private name so its existing prompt framing, budget arithmetic, and
    fallback/cancellation behavior -- and tests that monkeypatch that name --
    are unaffected by the move.

``build_consulted_receipt(entries, ref)``
    New: a bounded, redacted projection of a raw persisted trace (the
    ``list[Any]`` decoded from a ``crew_trace`` attachment) for a caller that
    must never receive raw tool arguments, outputs, or error bodies. It is a
    *shape*, not a promise -- a bounded redaction policy, not proof that all
    free text it passes through is harmless, and a recorded request is not
    proof an external effect succeeded.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from probos.cognitive.trace_analysis import analyse_trace, quote_for_prose
from probos.security.pii_redaction import PIIRedactor

# Contract: "Bound raw scalar/name inspection at 4,096 code points. Omit
# oversized values whole, not a shortened prefix that could hide a protected
# key." Applied to each raw entry's name/tool and argument keys/values
# *before* ``analyse_trace`` renders them: ``analyse_trace``'s own per-call
# bound (BF-774: at most 6 arguments, ``_clip``-ed to 80 characters each)
# already produces a short *rendered* line regardless of how large the raw
# value was, so a check on the rendered line never sees the raw value at all
# -- and ``_clip``'s ellipsis truncation is itself the "shortened prefix"
# the contract is warning could hide a protected key past the cut. Oversized
# raw values are therefore replaced whole, here, before rendering.
_MAX_RAW_INSPECTION_CHARS = 4_096
_OVERSIZED_MARKER = "<omitted: oversized>"

# Shared with the value branch of _trace_sanitize_call: identifies a string
# value shaped like a URL so it is routed through _trace_sanitize_url rather
# than the free-text redactor. One pattern, reused, so the two call sites
# (pre-render bounding here, and post-render sanitisation there) can never
# drift on what counts as "URL-shaped".
_URL_SHAPE_RE = re.compile(r"(?i)^https?:|^[A-Za-z][A-Za-z0-9+.-]*://")

# Contract: "Bound the COMPLETE UTF-8 response to 16 KiB, removing whole
# trailing request lines when needed."
_MAX_RECEIPT_BYTES = 16 * 1024

_RECEIPT_NOTICE = (
    "Sensitive values are redacted. Request excerpts are bounded to 40 lines "
    "and 16 KiB; arguments may be shortened, and oversized or unrecognized "
    "fragments are omitted. URLs retain sanitized origin/path only: userinfo, "
    "query, and fragment are omitted. "
    "A recorded request is not proof that an external effect succeeded."
)


def _trace_key_policy(name: str) -> str:
    normalized = name.casefold().replace("_", "").replace("-", "")
    if (
        any(part in normalized for part in (
            "password", "secret", "credential", "authorization",
        ))
        or normalized.endswith("token")
        or normalized == "apikey"
        or normalized in {"docid", "fileid", "itemid"}
    ):
        return "protected"
    if normalized in {
        "phone", "mobile", "telephone", "fax", "msisdn", "contactnumber",
    }:
        return "protected"
    if normalized in {
        "recordid", "timestamp", "epoch", "page", "offset", "limit", "count", "index",
    }:
        return "numeric"
    return "ordinary"


def _trace_redact_text(text: str, *, urls: bool = True) -> str:
    for assignment in re.finditer(
        r"[\"']?([A-Za-z_][A-Za-z0-9_.-]*)[\"']?\s*[:=]", text,
    ):
        if _trace_key_policy(assignment.group(1)) == "protected":
            return "[REDACTED]"
    text = PIIRedactor.redact_email(text)
    text = PIIRedactor.redact_phone(text)
    text = PIIRedactor.redact_doc_ids(text)
    text = PIIRedactor.redact_tokens(text)
    return PIIRedactor.redact_url(text) if urls else text


def _trace_url_component(component: str) -> tuple[str, bool]:
    decoded = component
    for _pass in range(3):
        if "%" not in decoded:
            break
        if re.search(r"%(?![0-9A-Fa-f]{2})", decoded):
            return "[REDACTED]", True
        expanded = unquote(decoded, encoding="utf-8", errors="strict")
        if any(character in expanded for character in "/?#@\\:"):
            return "[REDACTED]", True
        decoded = expanded
    if "%" in decoded or any(
        ord(character) < 32 or ord(character) == 127 for character in decoded
    ):
        return "[REDACTED]", True
    return _trace_redact_text(decoded, urls=False), (
        _trace_key_policy(decoded) == "protected"
    )


def _trace_sanitize_url(value: str) -> str:
    try:
        if (
            any(character.isspace() or ord(character) < 32 or ord(character) == 127
                for character in value)
            or "\\" in value
            or re.search(r"%(?![0-9A-Fa-f]{2})", value)
        ):
            return "[REDACTED_URL]"
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            return "[REDACTED_URL]"
        port = parsed.port
        authority = parsed.netloc.rsplit("@", 1)[-1]
        if authority.endswith(":"):
            return "[REDACTED_URL]"
        host, _protected = _trace_url_component(parsed.hostname)
        if ":" in parsed.hostname:
            if not authority.startswith("[") or host != parsed.hostname:
                return "[REDACTED_URL]"
            host = "[" + host + "]"
        else:
            if any(character in parsed.hostname for character in "/?#@[]"):
                return "[REDACTED_URL]"
            host = quote(host, safe=".-")
        if port is not None:
            host += f":{port}"
        components: list[str] = []
        mask_next = False
        for component in parsed.path.split("/"):
            sanitized, protects_next = _trace_url_component(component)
            components.append(quote("[REDACTED]" if mask_next else sanitized, safe=""))
            mask_next = protects_next
        return urlunsplit((parsed.scheme, host, "/".join(components), "", ""))
    except (ValueError, UnicodeError):
        return "[REDACTED_URL]"


def _trace_read_name(text: str, position: int) -> tuple[str, str, int]:
    if text[position:position + 1] == '"':
        decoded, end = json.JSONDecoder().raw_decode(text, position)
        return decoded, quote_for_prose(_trace_redact_text(decoded)), end
    match = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*|<unnamed>").match(text, position)
    if match is None:
        raise ValueError("trace_name_unrecognized")
    name = match.group()
    sanitized = _trace_redact_text(name)
    return name, name if sanitized == name else quote_for_prose(sanitized), match.end()


def _trace_sanitize_call(text: str) -> str | None:
    try:
        _name, tool, position = _trace_read_name(text, 0)
        if text[position:position + 1] != "(":
            return None
        position += 1
        parts: list[str] = []
        if re.fullmatch(
            r"<(?:unreadable arguments|invalid arguments: [A-Za-z_][A-Za-z0-9_]*)>\)",
            text[position:],
        ):
            return tool + "(" + text[position:]
        while text[position:position + 1] != ")":
            if len(parts) >= 7:
                return None
            if text[position:] == "\u2026)":
                parts.append("\u2026")
                position += 1
                break
            key, display_key, position = _trace_read_name(text, position)
            if text[position:position + 1] != "=":
                return None
            position += 1
            policy = _trace_key_policy(key)
            if text[position:position + 1] == '"':
                value, position = json.JSONDecoder().raw_decode(text, position)
                if policy == "protected":
                    sanitized = "[REDACTED]"
                elif _URL_SHAPE_RE.match(value):
                    sanitized = _trace_sanitize_url(value)
                else:
                    sanitized = _trace_redact_text(value)
                rendered_value = quote_for_prose(sanitized)
            else:
                scalar = re.compile(
                    r"None|True|False|<[A-Za-z_][A-Za-z0-9_]*>|"
                    r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|nan|-?inf"
                ).match(text, position)
                if scalar is None:
                    return None
                value = scalar.group()
                position = scalar.end()
                if policy == "protected":
                    rendered_value = quote_for_prose("[REDACTED]")
                elif value in {"None", "True", "False"} or value.startswith("<"):
                    rendered_value = value
                elif not math.isfinite(float(value)):
                    rendered_value = quote_for_prose("[REDACTED]")
                elif policy == "numeric":
                    rendered_value = value
                else:
                    sanitized = _trace_redact_text(value)
                    rendered_value = (
                        value if sanitized == value else quote_for_prose(sanitized)
                    )
            parts.append(display_key + "=" + rendered_value)
            if text[position:position + 1] == ")":
                break
            if text[position:position + 2] != ", ":
                return None
            position += 2
        if text[position:] != ")":
            return None
        return tool + "(" + ", ".join(parts) + ")"
    except (ValueError, OverflowError):
        return None


def _trace_sanitize_prose(text: str) -> str:
    position = 0
    skeleton: list[str] = []
    sanitized: list[str] = []
    try:
        while position < len(text):
            if text[position] == '"':
                value, position = json.JSONDecoder().raw_decode(text, position)
                skeleton.append("QUOTED")
                sanitized.append(quote_for_prose(_trace_redact_text(value)))
            else:
                end = text.find('"', position)
                end = len(text) if end == -1 else end
                fragment = text[position:end]
                skeleton.append(fragment)
                sanitized.append(_trace_redact_text(fragment))
                position = end
    except ValueError:
        return "[Unrecognized trace fragment] " + quote_for_prose(_trace_redact_text(text))
    name = r"(?:[A-Za-z_][A-Za-z0-9_.-]*|QUOTED)"
    grammar = (
        r"No tool calls were recorded for this run\.|What it asked:|"
        rf"The {name} tool failed the same way \d+ times: QUOTED|"
        r"First at call \d+, again at call \d+ of \d+\.|"
        rf"\d+ tool calls, \d+ failed, across \d+ tool\(s\): {name}(?:, {name})*\.|"
        r"  \u2026and \d+ more\.|"
        r"The run ended on \d+ consecutive failures, so it stopped making progress "
        r"before it stopped\."
    )
    if re.fullmatch(grammar, "".join(skeleton)):
        return "".join(sanitized)
    return "[Unrecognized trace fragment] " + quote_for_prose(_trace_redact_text(text))


def sanitize_trace_render(rendered: str, payload_limit: int) -> str:
    """Sanitise a rendered :meth:`TraceSummary.render` payload for an LLM prompt.

    Moved verbatim from ``crew_verifier._trace_sanitize_render`` (AD-1242).
    Line-by-line: 2-space-indented lines are treated as tool calls and run
    through :func:`_trace_sanitize_call`; everything else through
    :func:`_trace_sanitize_prose`. A 65,536-character source-size safety
    cutoff applies before ``payload_limit`` (typically ~8 KiB) truncates the
    joined payload by dropping whole trailing fragments -- never mid-fragment,
    which could otherwise expose a partially redacted value.
    """
    marker = "\n[Trace evidence truncated]"
    fragments: list[str] = []
    source_chars = 0
    for line in rendered.split("\n"):
        source_chars += len(line) + 1
        if source_chars > 65_536:
            fragments.append("[Unrecognized trace fragment omitted: size limit]")
            fragments.append(marker.lstrip("\n"))
            break
        call = _trace_sanitize_call(line[2:]) if line.startswith("  ") else None
        fragments.append("  " + call if call is not None else _trace_sanitize_prose(line))
    payload = "\n".join(fragments)
    if len(payload) <= payload_limit:
        return payload
    retained: list[str] = []
    remaining = payload_limit - len(marker)
    for fragment in fragments:
        needed = len(fragment) + bool(retained)
        if needed > remaining:
            break
        retained.append(fragment)
        remaining -= needed
    return "\n".join(retained) + marker


def _bound_raw_scalar(value: Any) -> Any:
    """Replace one raw string longer than the 4,096-code-point bound.

    Only strings are in scope: the contract's "oversized values" concern is
    text that could carry a protected key past whatever inspects it, which is
    not a meaningful risk for ``int``/``float``/``bool``/``None``. Returns the
    value unchanged when it is not an oversized string, so this is safe to
    call on anything a trace entry can hold.
    """
    if isinstance(value, str) and len(value) > _MAX_RAW_INSPECTION_CHARS:
        return _OVERSIZED_MARKER
    return value


def _bound_raw_argument_value(value: Any) -> Any:
    """Bound one raw *argument value*, pre-sanitising URL-shaped strings.

    Same 4,096-code-point oversized bound as :func:`_bound_raw_scalar`, plus
    one more case unique to argument values: ``analyse_trace``'s own
    per-argument ``_clip`` (BF-774: 80 characters, ellipsis-truncated) runs
    on the *raw* value, long before ``_trace_sanitize_call`` ever gets to
    apply the URL policy to the *rendered* one. A URL between roughly 80 and
    4,096 characters -- well under this module's oversized bound, so
    :func:`_bound_raw_scalar` leaves it untouched -- would already have had
    an arbitrary byte clipped out of its middle (landing anywhere: userinfo,
    host, path, query) before the URL sanitiser ever saw it, which is
    exactly the "shortened prefix" the contract warns could hide something
    the policy was supposed to strip -- observed as credentials or query
    strings surviving into a mangled, percent-re-encoded path.

    A string recognised as URL-shaped (the same test :func:`_trace_sanitize_call`
    uses) is therefore sanitised here, on the complete raw value, before
    ``analyse_trace`` ever renders or clips it. The result -- a short
    ``scheme://host[:port]/path`` with no credentials, query, or fragment --
    is what reaches the renderer instead of the raw value, so the later,
    rendered-line sanitisation pass is idempotent on it (verified in tests)
    rather than load-bearing for URLs. Free text is also redacted in full
    before shortening, using the verifier's existing embedded-URL policy.
    Non-string values retain the existing scalar/shape-only formatting.
    """
    if not isinstance(value, str):
        return value
    if len(value) > _MAX_RAW_INSPECTION_CHARS:
        return _OVERSIZED_MARKER
    if _URL_SHAPE_RE.match(value):
        return _trace_sanitize_url(value)
    return _trace_redact_text(value)


def _bound_raw_entries(entries: list[Any]) -> tuple[list[Any], bool]:
    """Bound raw scalar/name inspection at 4,096 code points (contract, s.3).

    Runs *before* :func:`probos.cognitive.trace_analysis.analyse_trace`. That
    function's own rendering already bounds every argument to 6 entries of at
    most 80 characters each (BF-774), but it gets there by *clipping* an
    already-decoded raw value with an ellipsis -- exactly the "shortened
    prefix that could hide a protected key" the contract warns against, since
    a redaction check downstream only ever sees the clipped 80 characters. An
    oversized raw name or argument value is replaced whole, here, so nothing
    past the 4,096th code point is ever inspected, clipped, or rendered.

    Only ``dict`` entries are touched (non-dict entries are already counted
    as ``invalid_entries`` and never reach ``analyse_trace``'s renderer).
    Only the ``name``/``tool`` field and ``arguments`` mapping are inspected,
    matching the two raw string sites ``analyse_trace`` itself reads
    (:func:`probos.cognitive.trace_analysis._entry_name`,
    :func:`probos.cognitive.trace_analysis._render_arguments`). A copy is
    returned; the caller's ``entries`` list and its dict/mapping values are
    never mutated in place.

    Argument values additionally go through :func:`_bound_raw_argument_value`
    rather than :func:`_bound_raw_scalar`: a URL-shaped value within the
    4,096-character bound is pre-sanitised here (full origin/path policy,
    on the untruncated raw string) rather than left for ``analyse_trace`` to
    clip first -- see that function's docstring for why the 80-character
    per-argument clip is a second, lower "oversized" threshold this module
    has to guard, not just the 4,096-character one.

    Returns ``(bounded_entries, any_omitted)`` -- the second element lets
    :func:`build_consulted_receipt` fold an oversized-raw-value omission (and
    now, a pre-sanitised URL argument) into its ``redacted`` flag, since both
    are as much an alteration of the recorded request as the key/value/URL
    sanitisation policy applied to the rendered line is.
    """
    bounded: list[Any] = []
    any_omitted = False
    for entry in entries:
        if not isinstance(entry, dict):
            bounded.append(entry)
            continue
        # Request formatting has no reason to inspect outputs or error bodies.
        new_entry = {key: entry[key] for key in ("name", "tool", "arguments") if key in entry}
        for key in ("name", "tool"):
            if key in new_entry:
                value = new_entry[key]
                new_value = _bound_raw_scalar(value)
                if type(new_value) is str:
                    new_value = _trace_redact_text(new_value)
                elif new_value is not None:
                    new_value = "<omitted: unrecognized name>"
                if new_value != value:
                    any_omitted = True
                new_entry[key] = new_value
        arguments = new_entry.get("arguments")
        if isinstance(arguments, dict):
            new_arguments: dict[Any, Any] = {}
            for arg_key, arg_value in arguments.items():
                oversized_key = (
                    isinstance(arg_key, str) and len(arg_key) > _MAX_RAW_INSPECTION_CHARS
                )
                if oversized_key:
                    bounded_key = bounded_value = _OVERSIZED_MARKER
                elif type(arg_key) is not str:
                    bounded_key = bounded_value = "<omitted: unrecognized name>"
                else:
                    # Classify the ORIGINAL name before _render_token can clip
                    # or digest it. A hidden protected suffix still owns its value.
                    policy = _trace_key_policy(arg_key)
                    bounded_key = _trace_redact_text(arg_key)
                    bounded_value = (
                        "[REDACTED]" if policy == "protected"
                        else _bound_raw_argument_value(arg_value)
                    )
                if bounded_key != arg_key or bounded_value != arg_value:
                    any_omitted = True
                new_arguments[bounded_key] = bounded_value
            new_entry["arguments"] = new_arguments
        bounded.append(new_entry)
    return bounded, any_omitted



def _sanitize_request_line(line: str) -> str:
    """Apply the AD-1242 call policy to one already-rendered request line.

    By the time a request line reaches this function, any oversized raw
    scalar/name has already been replaced whole by :func:`_bound_raw_entries`
    (contract s.3) and ``analyse_trace`` has rendered it into a short line
    (BF-774: at most 6 arguments, each clipped to 80 characters). This just
    runs the existing key/value/URL sanitisation policy over that line.
    """
    call = _trace_sanitize_call(line)
    return call if call is not None else "[Unrecognized trace request omitted]"


def build_consulted_receipt(entries: list[Any], ref: str) -> dict[str, Any]:
    """A safe, bounded, redacted projection of one persisted tool trace.

    ``entries`` is the raw ``list[Any]`` decoded from a ``crew_trace``
    attachment (see :func:`probos.cognitive.trace_analysis.load_trace`).
    First bounds and sanitises original names and values at 4,096 code points
    (:func:`_bound_raw_entries`, contract s.3), then reuses
    :func:`probos.cognitive.trace_analysis.analyse_trace` for its existing
    bounded request rendering (at most 40 lines, BF-774). The rendered lines
    also pass the shared policy, but are never the first place a protected
    name, free-text assignment, or URL is classified. Never returns raw tool
    outputs, error bodies, or an unsanitised summary render.

    This is a bounded redaction policy, not a proof that all free text it
    passes through is harmless, and a recorded request is not proof that an
    external effect it named succeeded.

    Returns a dict shaped::

        {
            "ref": str,
            "requests": list[str],       # sanitised, at most 40 entries
            "requests_total": int,       # >= 0, counts dict entries only
            "requests_omitted": int,     # >= 0; requests_total == len(requests) + requests_omitted
            "invalid_entries": int,      # >= 0, non-dict entries in `entries`
            "redacted": bool,            # True if any request line was altered
            "truncated": bool,           # True if any request line was omitted
            "notice": str,
        }
    """
    if type(ref) is not str or re.fullmatch(r"[0-9a-f]{8,64}", ref) is None:
        raise ValueError("consulted_trace_ref_invalid")
    ordered = entries if isinstance(entries, list) else []
    invalid_entries = sum(1 for entry in ordered if not isinstance(entry, dict))

    # Contract s.3: bound raw scalar/name inspection at 4,096 code points
    # *before* analyse_trace renders (and in the process, ellipsis-clips)
    # each argument -- see _bound_raw_entries for why the order matters.
    bounded_entries, any_omitted = _bound_raw_entries(ordered)
    summary = analyse_trace(bounded_entries)
    requests: list[str] = []
    redacted = any_omitted
    for line in summary.requests:
        sanitized = _sanitize_request_line(line)
        if sanitized != line:
            redacted = True
        requests.append(sanitized)

    requests_total = summary.requests_total
    requests_omitted = max(0, requests_total - len(requests))

    def _payload() -> dict[str, Any]:
        return {
            "ref": ref,
            "requests": requests,
            "requests_total": requests_total,
            "requests_omitted": requests_omitted,
            "invalid_entries": invalid_entries,
            "redacted": redacted,
            "truncated": requests_omitted > 0,
            "notice": _RECEIPT_NOTICE,
        }

    # Contract: "Bound the COMPLETE UTF-8 response to 16 KiB, removing whole
    # trailing request lines when needed." Drop whole lines from the tail,
    # never truncate mid-line, which could split (and misrepresent) an
    # already-sanitised value.
    while requests and len(
        json.dumps(_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    ) > _MAX_RECEIPT_BYTES:
        requests.pop()
        requests_omitted += 1

    return _payload()
