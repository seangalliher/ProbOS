"""AD-1337 (#1560): the one owner that masks known credential values in tool output before a model sees them.

``SecretMasker`` replaces every form of every known value with ``<secret:NAME>``. It reads three sources again on
every pass, so a rotated value is masked from the next pass on and a released one no longer is:

1. ``probos.credential_store.masked_credential_values``: what the credential store can name. No CLI command runs
   and no access row is written.
2. ``SecretRegistry``: a value ProbOS hands to a tool for one session, masked until its ``SecretHandle`` is released.
3. ``EnvSecretSource``: the environment's values under a name ``env_name_is_mask_shaped`` accepts. That rule only
   narrows BF-890's (``execution/command_env.py``, unchanged) and decides by name alone: a git config key name, a
   session id or a path is not a secret, and masking one would rewrite ordinary text.

``secret_forms`` gives the forms of one value: raw, JSON-escaped (with and without ASCII escapes), URL-encoded from
its UTF-8 bytes (both hex cases, ``quote_plus``) and base64 of its UTF-8 bytes (standard and URL-safe, padded and
unpadded, and at each of the three byte alignments a value can have inside a longer encoded stream; at most two
bytes at each end of an aligned occurrence stay visible). A value shorter than the floor, and a form shorter than
it, are not masked. Overlapping occurrences are replaced as one span.

Nothing here logs, emits or returns a value. A pass that fails is fail-closed: the caller gets
``MASKING_FAILED_TEXT`` instead of the text or the output, and one ERROR line names the exception type only. The
seams that call this module, and the masking event, are AD-1337 S2 and S3.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple
from urllib.parse import quote, quote_plus

from probos.credential_store import CredentialStore, masked_credential_values
from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)

#: Not measured (AD-1337 consult 4bb6d748, Q3): the shortest value, and the shortest form of one, that is masked.
DEFAULT_FLOOR: int = 8
#: Not measured: how deep, and over how many nodes, ``mask_result`` walks a container output. Past either bound a
#: value is left as it is here, and the render seam (AD-1337 S3) masks the text the model is shown.
DEFAULT_MAX_DEPTH: int = 32
DEFAULT_MAX_NODES: int = 10_000

#: What the caller gets instead of the text or the output when a pass fails.
MASKING_FAILED_TEXT: str = "tool output withheld: secret masking failed"
#: The label shown for a source name that is not a plain label.
UNNAMED_LABEL: str = "unnamed"

#: A name whose last ``_`` segment is one of these names a path, not a secret (``DB_PASSWORD_FILE``,
#: ``SSH_AUTH_SOCK``). Decided by name, never by value: a secret can start with ``/``.
MASK_PATH_SEGMENTS: tuple[str, ...] = ("FILE", "PATH", "SOCK", "SOCKET", "DIR", "DIRECTORY")
#: Whole names that hold a path although they match a word below.
MASK_PATH_NAMES: tuple[str, ...] = ("PWD", "GOOGLE_APPLICATION_CREDENTIALS")
#: A name containing one of these words names a secret.
MASK_NAME_WORDS: tuple[str, ...] = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASSPHRASE", "CREDENTIAL", "APIKEY")
#: Short forms that count only as a whole ``_``-separated segment (``AUTH``, but not ``AUTHOR``).
MASK_NAME_SEGMENTS: tuple[str, ...] = ("PAT", "PASS", "PWD", "DSN", "CREDS", "AUTH")
#: ``KEY`` counts as the last segment (``STRIPE_KEY``) or right after a qualifier (``OPENAI_API_KEY_2``), and never
#: elsewhere: ``GIT_CONFIG_KEY_0`` holds a git config key name.
MASK_KEY_SEGMENTS: tuple[str, ...] = ("KEY", "KEYS")
MASK_KEY_QUALIFIERS: tuple[str, ...] = (
    "API", "ACCESS", "PRIVATE", "SIGNING", "ENCRYPTION", "MASTER", "CLIENT", "ACCOUNT", "SERVICE", "LICENSE",
)

_LABEL_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_UPPER_HEX_RE = re.compile(r"%[0-9A-F]{2}")
_PEM_FENCES: tuple[str, ...] = ("-----BEGIN", "-----END")


class MaskOutcome(NamedTuple):
    """``mask_text``'s answer: the text (the same object when nothing matched), the labels masked, and whether the
    pass failed (``text`` is then ``MASKING_FAILED_TEXT``)."""

    text: str
    names: frozenset[str]
    failed: bool


class MaskedResult(NamedTuple):
    """``mask_result``'s answer: the result (the same object when nothing matched), the labels masked, and whether
    the pass failed (``result`` is then a plain ``ToolResult`` whose error is ``MASKING_FAILED_TEXT``)."""

    result: ToolResult
    names: frozenset[str]
    failed: bool


def env_name_is_mask_shaped(name: str) -> bool:
    """Whether the environment variable ``name`` holds a value to mask (a narrowing of BF-890's rule, by name)."""
    upper = name.upper()
    segments = upper.split("_")
    if segments[-1] in MASK_PATH_SEGMENTS or upper in MASK_PATH_NAMES:
        return False
    if any(word in upper for word in MASK_NAME_WORDS):
        return True
    if any(segment in MASK_NAME_SEGMENTS for segment in segments):
        return True
    last = len(segments) - 1
    return any(
        segment in MASK_KEY_SEGMENTS
        and (index == last or (index > 0 and segments[index - 1] in MASK_KEY_QUALIFIERS))
        for index, segment in enumerate(segments)
    )


def secret_label(name: object) -> str:
    """``name`` when it is a plain label (``[A-Za-z0-9_.:-]{1,64}``), else ``UNNAMED_LABEL``."""
    return name if isinstance(name, str) and _LABEL_RE.fullmatch(name) else UNNAMED_LABEL


def secret_forms(value: str, floor: int = DEFAULT_FLOOR) -> frozenset[str]:
    """Every form of ``value`` that is masked; empty when ``value`` is shorter than ``floor``."""
    if len(value) < floor:
        return frozenset()
    wholes = {value, value.replace("\r\n", "\n")}
    forms: set[str] = set(wholes)
    if "\n" in value or "\r" in value:
        for line in value.splitlines():
            stripped = line.strip()
            if not stripped.startswith(_PEM_FENCES):
                forms.add(stripped)
    for whole in wholes:
        forms.add(json.dumps(whole)[1:-1])
        forms.add(json.dumps(whole, ensure_ascii=False)[1:-1])
        for quoted in (quote(whole, safe=""), quote(whole, safe="/"), quote_plus(whole)):
            forms.add(quoted)
            forms.add(_UPPER_HEX_RE.sub(lambda match: match.group(0).lower(), quoted))
        raw = whole.encode("utf-8")
        for encode in (base64.b64encode, base64.urlsafe_b64encode):
            full = encode(raw).decode("ascii")
            forms.add(full)
            forms.add(full.rstrip("="))
            for shift in (0, 1, 2):
                aligned = raw[shift:]
                aligned = aligned[: len(aligned) - len(aligned) % 3]
                if aligned:
                    forms.add(encode(aligned).decode("ascii"))
    return frozenset(form for form in forms if len(form) >= floor)


def _present(patterns: tuple[tuple[str, str], ...], text: str) -> tuple[tuple[str, str], ...]:
    return tuple(item for item in patterns if item[0] in text)


def _substitute(text: str, patterns: tuple[tuple[str, str], ...], names: set[str]) -> str:
    """``text`` with every occurrence of every pattern replaced; ``text`` itself when none occurs."""
    present = _present(patterns, text)
    if not present:
        return text
    spans: list[tuple[int, int, str]] = []
    for form, label in present:
        start = text.find(form)
        while start >= 0:
            spans.append((start, start + len(form), label))
            start = text.find(form, start + 1)
    spans.sort(key=lambda span: (span[0], span[0] - span[1], span[2]))
    pieces: list[str] = []
    cursor = index = 0
    while index < len(spans):
        start, end, label = spans[index]
        longest = end - start
        names.add(label)
        index += 1
        while index < len(spans) and spans[index][0] < end:
            other_start, other_end, other_label = spans[index]
            names.add(other_label)
            if other_end - other_start > longest:
                longest, label = other_end - other_start, other_label
            end = max(end, other_end)
            index += 1
        pieces.append(text[cursor:start])
        pieces.append(f"<secret:{label}>")
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _log_failure(exc: Exception) -> None:
    # AD-1337: the type name only, and no traceback, so no value or pattern can reach a log.
    logger.error("AD-1337: secret masking failed (%s); the output is withheld", type(exc).__name__)


class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""

    __slots__ = ("_registry", "_key")

    def __init__(self, registry: SecretRegistry, key: int) -> None:
        self._registry = registry
        self._key = key

    def release(self) -> None:
        """Stop masking this registration's value (another registration of the same value stays)."""
        self._registry._release(self._key)

    def __enter__(self) -> SecretHandle:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class SecretRegistry:
    """Values ProbOS hands to a tool for one session, masked while registered. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, tuple[str, str]] = {}
        self._next_key = 0

    def register(self, name: str, value: str) -> SecretHandle:
        """Mask ``value`` under ``name`` until the returned handle is released."""
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("SecretRegistry.register takes a str name and a str value")
        with self._lock:
            key = self._next_key
            self._next_key += 1
            self._entries[key] = (name, value)
        return SecretHandle(self, key)

    def values(self) -> tuple[tuple[str, str], ...]:
        """``(name, value)`` for every live registration."""
        with self._lock:
            return tuple(self._entries.values())

    def _release(self, key: int) -> None:
        with self._lock:
            self._entries.pop(key, None)


class EnvSecretSource:
    """The environment's values under a name ``env_name_is_mask_shaped`` accepts, read on every call.

    ``environ`` is for tests; ``None`` reads ``os.environ`` at each call. The name alone decides: a value is never
    judged by its shape, so a secret starting with ``/`` is kept. Each name is ``env:NAME``.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ

    def values(self) -> tuple[tuple[str, str], ...]:
        """``(env:NAME, value)`` for each masked name with a non-empty stripped value."""
        source = os.environ if self._environ is None else self._environ
        pairs: list[tuple[str, str]] = []
        for name, value in list(source.items()):
            if not env_name_is_mask_shaped(name):
                continue
            stripped = value.strip()
            if stripped:
                pairs.append((f"env:{name}", stripped))
        return tuple(pairs)


class SecretMasker:
    """AD-1337: replaces every form of every known credential value with ``<secret:NAME>``.

    One per runtime (built by AD-1337 S2). ``mask_text`` and ``mask_result`` may run on any thread: the registry is
    locked, the store's dicts are copied before they are read, and the pattern table is replaced whole.
    """

    def __init__(
        self,
        *,
        credential_store: CredentialStore,
        registry: SecretRegistry,
        env_source: EnvSecretSource,
        floor: int = DEFAULT_FLOOR,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
    ) -> None:
        if not isinstance(credential_store, CredentialStore):
            raise TypeError("SecretMasker needs the runtime's CredentialStore")
        if not isinstance(registry, SecretRegistry):
            raise TypeError("SecretMasker needs a SecretRegistry")
        if not isinstance(env_source, EnvSecretSource):
            raise TypeError("SecretMasker needs an EnvSecretSource")
        if min(floor, max_depth, max_nodes) < 1:
            raise ValueError("floor, max_depth and max_nodes must each be at least 1")
        self._credential_store = credential_store
        self._registry = registry
        self._env_source = env_source
        self._floor = floor
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._table: tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]] | None = None

    def mask_text(self, text: str) -> MaskOutcome:
        """Replace every form of every known value in ``text``. ``TypeError`` for anything but a ``str``."""
        if not isinstance(text, str):
            raise TypeError("mask_text takes a str")
        try:
            names: set[str] = set()
            masked = _substitute(text, self._patterns(), names)
            return MaskOutcome(masked, frozenset(names), False)
        except Exception as exc:  # AD-1337 D7: fail closed
            _log_failure(exc)
            return MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)

    def mask_result(self, result: ToolResult) -> MaskedResult:
        """Mask ``result.output`` (strings in exact dicts, lists and tuples, within the bounds) and a ``str`` error.

        ``metadata`` is never touched; a subclass keeps its type and fields. ``TypeError`` for a non-``ToolResult``.
        """
        if not isinstance(result, ToolResult):
            raise TypeError("mask_result takes a ToolResult")
        try:
            patterns = self._patterns()
            if not patterns:
                return MaskedResult(result, frozenset(), False)
            texts: list[str] = []

            def collect(text: str) -> str:
                texts.append(text)
                return text

            self._map_strings(result.output, collect, 0, [0])
            if isinstance(result.error, str):
                texts.append(result.error)
            present = _present(patterns, "\x00".join(texts))
            if not present:
                return MaskedResult(result, frozenset(), False)
            names: set[str] = set()
            output = self._map_strings(result.output, lambda text: _substitute(text, present, names), 0, [0])
            error = result.error
            if isinstance(error, str):
                error = _substitute(error, present, names)
            # Reachable only when a form that contains NUL matched across the NUL join above and in no single
            # string: nothing changed, so the same object is returned.
            if output is result.output and error is result.error:
                return MaskedResult(result, frozenset(), False)
            return MaskedResult(dataclasses.replace(result, output=output, error=error), frozenset(names), False)
        except Exception as exc:  # AD-1337 D7: fail closed
            _log_failure(exc)
            withheld = ToolResult(error=MASKING_FAILED_TEXT, duration_ms=result.duration_ms, metadata=result.metadata)
            return MaskedResult(withheld, frozenset(), True)

    def _values(self) -> tuple[tuple[str, str], ...]:
        """``(value, label)`` for every value; the first source to name it wins: the store, the registry, the env."""
        chosen: dict[str, str] = {}
        for pairs in (
            masked_credential_values(self._credential_store),
            self._registry.values(),
            self._env_source.values(),
        ):
            for name, value in sorted(pairs):
                stripped = value.strip()
                if stripped:
                    chosen.setdefault(stripped, secret_label(name))
        return tuple(sorted(chosen.items()))

    def _patterns(self) -> tuple[tuple[str, str], ...]:
        """``(form, label)``, longest first; rebuilt only when the values differ from the last pass's."""
        values = self._values()
        cached = self._table
        if cached is not None and cached[0] == values:
            return cached[1]
        forms: dict[str, str] = {}
        for value, label in values:
            for form in secret_forms(value, self._floor):
                forms.setdefault(form, label)
        patterns = tuple(sorted(forms.items(), key=lambda item: (-len(item[0]), item[0])))
        self._table = (values, patterns)
        return patterns

    def _map_strings(self, value: Any, apply: Callable[[str], str], depth: int, visited: list[int]) -> Any:
        """``value`` with ``apply`` run on each string inside exact dicts, lists and tuples, within the bounds.

        Returns ``value`` itself when no string changed. Dict keys are not rewritten, so two keys cannot collide.
        """
        visited[0] += 1
        if visited[0] > self._max_nodes:
            return value
        if isinstance(value, str):
            return apply(value)
        if depth >= self._max_depth:
            return value
        kind = type(value)
        if kind is dict:
            items = [(key, self._map_strings(item, apply, depth + 1, visited)) for key, item in value.items()]
            if all(new is old for (_, new), old in zip(items, value.values())):
                return value
            return dict(items)
        if kind is list or kind is tuple:
            mapped = [self._map_strings(item, apply, depth + 1, visited) for item in value]
            if all(new is old for new, old in zip(mapped, value)):
                return value
            return kind(mapped)
        return value
