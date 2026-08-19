"""AD-1248 / BF-801: ``DmReply`` -- a reply is a value, not a string.

FOUNDATION tier, deliberately. This is a contract *about* ``IntentResult``,
whose definition lives beside it in ``types.py``: it names a key in that
result's ``metadata``, reconstructs from one, and composes the text a sink
displays. Living in ``cognitive/`` put it above two layers that legitimately
need it -- ``channels/`` for the adapter disclosure and ``federation/`` for
BF-799 directed carriage -- and neither could import it. Two layers wanting a
module they may not have is the module being in the wrong place, not two
independent judgement calls.

The problem it solves: a DM reply was an untyped ``str`` doing double duty as
both the payload and the metadata channel. Any fact *about* the reply had
nowhere to live, so it was either smuggled inside the text and parsed back out,
or routed around the text through a side channel only some delivery paths
carried. BF-773 ("a failed tool call must reach the text the Captain reads")
was built and rejected four times against that shape.

The load-bearing property is that **no component ever re-parses display text to
recover a fact** -- which deletes the ownership question rather than answering
it.

The PRODUCER (``correlate_tool_outcomes``) stays in
``cognitive/dm/reply_value.py``: it reads agentic-run shapes and is genuinely
cognitive-layer knowledge. Only the value moves.

Design decisions live in ``prompts/ad-1248-dm-reply-value.md``. The ones that
are easy to undo by accident are restated at their point of use below.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "RenderedDmText",
    "ToolFailures",
    "ToolFailuresMergeClosed",
    "DmReply",
    "mint_scope",
    "scope_from_source",
    "split_for_wire",
    "call_signature",
    "failure_key",
    "key_scope",
    "collapse_to_names",
    "require_rendered",
    "UNKNOWN_TOOL_LABEL",
    "DM_REPLY_METADATA_KEY",
]


# ── DD-12 layer 1: the nominal egress boundary ──────────────────────────────
#
# DD-5 puts the un-rendered body on the bus and composes only at egress, which
# is only sound if "which surfaces render" is enforceable. Six review rounds
# proved a hand-written sink list is not: it was wrong every round, and the last
# one found a pseudo-sink hiding seven real ones. A *provenance* assertion over
# ``str`` is not statically decidable either -- at the Discord write the analyzer
# sees only ``chunk``.
#
# So the boundary is a TYPE. A bare ``str`` cannot reach a registered egress.

_RENDER_TOKEN = object()


class RenderedDmText(str):
    """The composed, Captain-visible form of a :class:`DmReply`.

    Produced ONLY by :meth:`DmReply.render`. The sinks guarded by
    :func:`require_rendered` accept this and not a bare ``str``. Channel
    adapters deliberately still take plain strings -- they are handed the
    result of composition, not the value.

    This is an *admission token*, not durable provenance. Every string
    operation -- ``str()``, f-strings, ``.join``, slicing, ``+``, ``.strip``,
    JSON round-trip, a ``str``-annotated Pydantic field -- returns a plain
    ``str`` and drops the marker. That erosion is deliberate and fail-closed:
    the guard runs on the direct result of ``render()``, so anything that
    transformed the text on the way is rejected rather than delivered.

    Never "repair" an eroded value by re-wrapping it. That converts the token
    into a rubber stamp and silently restores the defect this type prevents.
    """

    __slots__ = ()

    def __new__(cls, value: str, _token: object = None) -> "RenderedDmText":
        if _token is not _RENDER_TOKEN:
            raise TypeError(
                "RenderedDmText is constructed only by DmReply.render(); "
                "wrapping an existing string defeats the egress guard"
            )
        return super().__new__(cls, value)


def require_rendered(text: Any, *, sink: str) -> RenderedDmText:
    """DD-12 layer 2. Raise unless ``text`` came straight from ``render()``.

    A bare ``assert`` is removed by ``python -O`` -- measured reaching an egress
    body with a plain string -- so this raises instead. Call it as the FIRST
    statement of a registered egress helper, before any slicing, formatting,
    chunking, JSON encoding or Pydantic construction.
    """
    if not isinstance(text, RenderedDmText):
        raise TypeError(
            f"egress {sink!r} requires RenderedDmText from DmReply.render(); "
            f"got {type(text).__name__}. A transformed or hand-built string "
            f"has lost its attachments and must not reach the Captain."
        )
    return text


# ── Scope and signature identity (DD-1) ─────────────────────────────────────

_SCOPE_RE = re.compile(r"^[0-9a-f]{12}$")
_KEY_RE = re.compile(r"^[0-9a-f]{12}\.[0-9a-f]{12}:[0-9a-f]{16}$")

#: DD-1a. The provider-facing grammar every offered tool name satisfies
#: (BF-754/BF-757, ``swe_harness/tool_call.py``). ``fullmatch`` matters: ``$``
#: also matches before a trailing newline.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

UNKNOWN_TOOL_LABEL = "an unrecognised tool"

#: Where the attachments ride on ``IntentResult.metadata``. The body itself
#: stays in ``IntentResult.result`` -- never duplicated (DD-5).
DM_REPLY_METADATA_KEY = "dm_reply"

_WIRE_VERSION = 1
_MAX_ENTRIES = 64
_MAX_NAMES = 32
_MAX_UNRESOLVED = 10_000


def mint_scope() -> str:
    """A fresh 12-hex scope for an execution that has no stable id of its own."""
    return uuid.uuid4().hex[:12]


def scope_from_source(source_id: str) -> str:
    """Derive a 12-hex scope from an existing identifier.

    Pass-through when the source is already a 12-hex token (the cognitive
    ``correlation_id``); hashed otherwise, because crew work-item ids run to
    128 characters and would blow the key bound.

    ``fullmatch``, not ``match``: BF-757 already paid for this lesson once --
    ``$`` also matches before a trailing newline, so ``"<12hex>\\n"`` would sail
    through as a 13-character scope and produce an unparseable key.
    """
    if _SCOPE_RE.fullmatch(source_id or ""):
        return source_id
    return hashlib.sha256((source_id or "").encode("utf-8", "replace")).hexdigest()[:12]


def call_signature(name: str, arguments: Any) -> str:
    """Stable 16-hex id for ONE logical call: its name plus normalised arguments.

    The tool NAME alone is the wrong key. Two independent parallel searches --
    ``web_search(query=A)`` and ``web_search(query=B)`` -- are not retries of one
    another, so a success on B must not erase A's failure.
    """
    try:
        canonical = json.dumps(
            arguments, sort_keys=True, separators=(",", ":"), default=str,
        )
    except Exception:
        canonical = repr(arguments)
    digest = hashlib.sha256(f"{name}\x00{canonical}".encode("utf-8", "replace"))
    return digest.hexdigest()[:16]


def failure_key(root: str, scope: str, signature: str) -> str:
    """``{root}.{scope}:{signature}`` -- 42 chars.

    The key carries LINEAGE, not just a scope. Without a root, a prior pass with
    scopes ``{parent, child-A}`` and a fresh pass with ``{parent, child-B}`` is
    neither same-scope (so supersession cannot apply) nor disjoint (so union
    cannot), and the algebra has no answer.
    """
    return f"{root}.{scope}:{signature}"


def key_scope(key: str) -> str:
    """The producing scope of a key -- what supersession is keyed on."""
    return key.split(".", 1)[1].split(":", 1)[0]


class ToolFailuresMergeClosed(RuntimeError):
    """Raised when supersession is attempted on a reconstructed value.

    A value rebuilt from the wire or a durable record has lost its success
    tombstones, so it cannot tell "pass 2 never retried this call" from "pass 2
    retried it and it succeeded" -- which must produce *retain* and *clear*
    respectively. Guessing either way is a silent wrong answer, so this raises
    instead. It also enforces the precondition DD-1 rests on: no supersession
    crosses a serialization boundary today, and if one ever does, this finds it
    on the first run rather than in a transcript.
    """


@dataclass(frozen=True)
class ToolFailures:
    """Which tool calls failed, in a form that survives a body rewrite.

    Two orthogonal axes, both load-bearing:

    PRECISE vs SUMMARY
        PRECISE carries ``entries``; ``names()`` is derived. SUMMARY carries
        ``summary_names`` + ``unresolved_count`` because the entry set exceeded
        its wire bound. Disclosure never degrades; merge precision does.

    merge-open vs merge-closed
        merge-open carries ``""`` success tombstones and supports the full
        last-write-wins algebra. merge-closed was reconstructed and raises on
        supersession. A value can be any combination of the four.

    ``entries`` is a sorted tuple of pairs rather than a ``Mapping`` field: a
    ``Mapping`` on a frozen dataclass retains the CALLER'S dict, and mutating it
    afterwards mutates the "frozen" value.
    """

    entries: tuple[tuple[str, str], ...] = ()
    summary_names: tuple[str, ...] = ()
    unresolved_count: int = 0
    merge_open: bool = False

    @classmethod
    def from_mapping(
        cls, mapping: Mapping[str, str] | None, *, merge_open: bool = True,
    ) -> "ToolFailures":
        """Build from a ``key -> display name`` map, copying defensively."""
        if not mapping:
            return cls(merge_open=merge_open)
        return cls(
            entries=tuple(sorted(
                (str(k), str(v)) for k, v in mapping.items()
            )),
            merge_open=merge_open,
        )._bounded()

    @property
    def is_summary(self) -> bool:
        return bool(self.summary_names) or (not self.entries and self.unresolved_count > 0)

    @property
    def failed_call_count(self) -> int:
        """How many CALLS failed -- not how many distinct tools.

        Two failed ``web_search`` calls are two failures and one name. Deriving
        the count from names understates it, which is how the count-only render
        reported "1 tool call failed" for two.
        """
        if self.is_summary:
            return self.unresolved_count
        return sum(1 for _, v in self.entries if v)

    @property
    def is_empty(self) -> bool:
        return not self.names() and self.failed_call_count == 0

    def names(self) -> tuple[str, ...]:
        """Sorted unique display names of calls whose last attempt failed."""
        if self.is_summary:
            return self.summary_names
        return tuple(sorted({v for _, v in self.entries if v}))

    def _summarised(self) -> "ToolFailures":
        """Collapse to the SUMMARY state, keeping disclosure and losing merge."""
        names = self.names()[:_MAX_NAMES]
        return ToolFailures(
            summary_names=names,
            unresolved_count=min(
                max(self.failed_call_count, len(names)), _MAX_UNRESOLVED,
            ),
            merge_open=self.merge_open,
        )

    def _bounded(self) -> "ToolFailures":
        """Collapse past the entry bound, in memory as well as on the wire.

        Applied after construction and after every merge. Summarising only at
        serialization would leave the SUMMARY algebra in :meth:`superseded_by`
        unreachable -- documented behaviour that never runs is not behaviour.

        BF-797: this bounds FAILING entries only. Success tombstones are not
        counted and can accumulate freely in memory -- 1,000 tombstones stay
        1,000 entries with ``is_summary`` False. That is deliberate: tombstones
        are what make supersession expressible (DD-1), dropping them to save
        memory would silently break the algebra, and they never cross a
        serialization boundary. A turn is bounded by its iteration count, so
        the growth is bounded in practice by the run itself.
        """
        if sum(1 for _, v in self.entries if v) <= _MAX_ENTRIES:
            return self
        return self._summarised()

    def superseded_by(self, other: "ToolFailures") -> "ToolFailures":
        """A later pass of the SAME execution. Last-write-wins per key.

        The scope lives IN the key, so a plain per-key merge is already scoped:
        ``other``'s keys can only collide with keys from the same execution, and
        a delegated child's failure sits under a different scope and survives.

        A key present here and absent from ``other`` means the later pass never
        retried that call, so it is RETAINED. Replacing the whole scope instead
        would delete exactly the failure AD-1164 continuations must preserve --
        the prompt says "build on the previous output, do not start over".

        Known, bounded over-disclosure: if a later pass *successfully* redid what
        a delegated child failed at, the child's failure still renders.
        Resolving that needs delegation identity stable across passes, which does
        not exist.
        """
        if not self.merge_open or not other.merge_open:
            raise ToolFailuresMergeClosed(
                "superseded_by requires both operands to be merge-open; a "
                "reconstructed value cannot prove a later success"
            )
        if self.is_summary or other.is_summary:
            # Cannot clear what we can no longer key. Retain and say so.
            logger.warning(
                "AD-1248: supersession over a summarised ToolFailures retains "
                "%d disclosure name(s); merge precision was lost at the entry "
                "bound and cannot be recovered",
                len(self.names()),
            )
            merged_names = tuple(sorted(set(self.names()) | set(other.names())))
            return ToolFailures(
                summary_names=merged_names[:_MAX_NAMES],
                unresolved_count=min(
                    max(
                        self.failed_call_count,
                        other.failed_call_count,
                        len(merged_names),
                    ),
                    _MAX_UNRESOLVED,
                ),
                merge_open=True,
            )

        merged_map = dict(self.entries)
        merged_map.update(dict(other.entries))
        return ToolFailures(
            entries=tuple(sorted(merged_map.items())), merge_open=True,
        )._bounded()

    def combined_with(self, other: "ToolFailures") -> "ToolFailures":
        """Independent executions folded together -- crew fan-in, delegation.

        Union, with scopes asserted disjoint. Deliberately not the same function
        as :meth:`superseded_by`: union is only safe when scopes are disjoint and
        LWW is only correct when they are identical, so each asserts its
        precondition rather than inferring it. A mis-wired call site fails loudly
        instead of silently deleting a disclosure.

        Needs no tombstones, so it is defined on merge-closed values too.
        """
        if self.is_summary or other.is_summary:
            merged_names = tuple(sorted(set(self.names()) | set(other.names())))
            return ToolFailures(
                summary_names=merged_names[:_MAX_NAMES],
                unresolved_count=min(
                    self.failed_call_count + other.failed_call_count, _MAX_UNRESOLVED,
                ),
                merge_open=self.merge_open and other.merge_open,
            )
        mine = {key_scope(k) for k, _ in self.entries}
        theirs = {key_scope(k) for k, _ in other.entries}
        overlap = mine & theirs
        if overlap:
            raise ValueError(
                f"combined_with requires disjoint scopes; {sorted(overlap)!r} "
                f"appear in both operands. Use superseded_by for later passes "
                f"of one execution."
            )
        return ToolFailures(
            entries=tuple(sorted(tuple(self.entries) + tuple(other.entries))),
            merge_open=self.merge_open and other.merge_open,
        )._bounded()

    # ── wire form (DD-5) ────────────────────────────────────────────────────

    def to_wire(self) -> dict[str, Any] | None:
        """Bounded, JSON-safe payload for ``IntentResult.metadata``.

        Two MUTUALLY EXCLUSIVE states, never both -- a payload carrying keys
        from each is self-contradictory, and bounding the fields independently
        does not catch it.

        Success tombstones are dropped here. That is safe only because no
        supersession crosses a serialization boundary, which
        :class:`ToolFailuresMergeClosed` enforces on the far side.
        """
        if self.is_empty:
            return None
        if self.is_summary:
            return {
                "v": _WIRE_VERSION,
                "truncated": True,
                "names": list(self.names()[:_MAX_NAMES]),
                "unresolved_count": min(self.unresolved_count, _MAX_UNRESOLVED),
            }
        failing = [(k, v) for k, v in self.entries if v]
        if len(failing) > _MAX_ENTRIES:
            return self._summarised().to_wire()
        return {"v": _WIRE_VERSION, "entries": [[k, v] for k, v in failing]}

    @classmethod
    def from_wire(cls, payload: Any) -> "ToolFailures":
        """Reconstruct, degrading in the two ways that mean different things.

        Malformed / unknown version / both states present / bad key or name
        shape -> the metadata is not trustworthy, so return empty and log.

        Valid but summarised -> trustworthy and merely large, so keep the
        disclosure and lose only merge precision.

        The result is always **merge-closed**.
        """
        try:
            if not isinstance(payload, dict):
                return cls()
            # ``type(...) is int`` rather than ``isinstance``: ``bool`` is a
            # subclass of ``int``, so ``{"v": True}`` would otherwise validate.
            if type(payload.get("v")) is not int or payload["v"] != _WIRE_VERSION:
                logger.warning(
                    "AD-1248: dm_reply metadata version %r is not %d; dropping "
                    "attachments and delivering the body alone",
                    payload.get("v"), _WIRE_VERSION,
                )
                return cls()

            # EXACT field sets. A payload carrying keys from both states, or
            # stray keys, is malformed -- not something to reconcile.
            keys = set(payload)
            if keys == {"v", "entries"}:
                return cls._precise_from_wire(payload)
            if keys == {"v", "truncated", "names", "unresolved_count"}:
                return cls._summary_from_wire(payload)
            logger.warning(
                "AD-1248: dm_reply metadata field set %r matches neither wire "
                "state exactly; treating as malformed rather than reconciling",
                sorted(keys),
            )
            return cls()
        except Exception:
            logger.warning(
                "AD-1248: dm_reply metadata reconstruction raised; delivering "
                "the body with no attachments", exc_info=True,
            )
            return cls()

    @classmethod
    def _summary_from_wire(cls, payload: dict) -> "ToolFailures":
        if payload.get("truncated") is not True:
            return cls()
        names = payload.get("names")
        if not isinstance(names, list) or not names or len(names) > _MAX_NAMES:
            return cls()
        clean = [
            n for n in names
            if isinstance(n, str)
            and (_NAME_RE.fullmatch(n) or n == UNKNOWN_TOOL_LABEL)
        ]
        if len(clean) != len(names):
            logger.warning(
                "AD-1248: dm_reply summary names failed the provider grammar; "
                "dropping attachments"
            )
            return cls()
        count = payload.get("unresolved_count")
        if type(count) is not int or count < len(clean) or count > _MAX_UNRESOLVED:
            return cls()
        return cls(summary_names=tuple(clean), unresolved_count=count, merge_open=False)

    @classmethod
    def _precise_from_wire(cls, payload: dict) -> "ToolFailures":
        raw = payload.get("entries")
        if not isinstance(raw, list) or not raw or len(raw) > _MAX_ENTRIES:
            logger.warning(
                "AD-1248: dm_reply entries absent, empty or over the %d bound; "
                "dropping attachments", _MAX_ENTRIES,
            )
            return cls()
        out: list[tuple[str, str]] = []
        for pair in raw:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                return cls()
            key, name = pair
            if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
                logger.warning(
                    "AD-1248: dm_reply entry key %r fails the lineage grammar; "
                    "returning an empty failure set, so the caller composes "
                    "with no attachments. A short or non-hex root is the usual "
                    "cause.",
                    key,
                )
                return cls()
            if not isinstance(name, str) or not name:
                return cls()
            if not _NAME_RE.fullmatch(name) and name != UNKNOWN_TOOL_LABEL:
                return cls()
            out.append((key, name))
        return cls(entries=tuple(sorted(out)), merge_open=False)


# ── The reply ───────────────────────────────────────────────────────────────

_DISCLOSURE_PREFIX = "\n\n"


def _compose_disclosure(names: tuple[str, ...], count: int) -> str:
    if not names and count <= 0:
        return ""
    if names:
        if len(names) == 1:
            listed = names[0]
        elif len(names) == 2:
            listed = f"{names[0]} and {names[1]}"
        else:
            listed = ", ".join(names[:-1]) + f", and {names[-1]}"
        noun = "tool" if len(names) == 1 else "tools"
        return f"I could not complete this using {listed} -- {noun} returned an error."
    plural = "" if count == 1 else "s"
    return f"{count} tool call{plural} failed while answering this."


def _count_only(count: int) -> str:
    plural = "" if count == 1 else "s"
    return f"{max(count, 1)} tool call{plural} failed while answering this."


def split_for_wire(text: str, limit: int) -> list[str]:
    """Divide text into pieces of at most ``limit`` characters, losing nothing.

    ``"".join(split_for_wire(t, n)) == t`` for every input -- exactly, not
    modulo whitespace.

    Prefers a newline boundary, then a space, then a hard cut -- the strategy
    the Discord adapter has used since AD-472, hoisted here so every
    wire-limited sink shares one implementation rather than each inventing its
    own (BF-802 found only one of seven adapters had one at all).

    Adversarial review found two defects in the hoisted original, both fixed
    here:

    * It could **not terminate**. ``split_for_wire(" x", 1)`` chose a cut at
      index 0, appended an empty piece and left the text unchanged -- an
      infinite loop that would hang a live vessel. Every cut is now >= 1, and
      a non-positive ``limit`` raises instead of looping forever.
    * It **deleted the delimiter** it split on (``.lstrip("\\n")``), so
      ``"a\\nb"`` came back as ``["a", "b"]`` and rejoining lost the newline.
      The cut is now taken just AFTER the boundary, keeping that character
      with the preceding piece -- lossless, while the next piece still does
      not begin with a blank line.
    """
    if limit <= 0:
        raise ValueError(f"split_for_wire(limit={limit}) needs a positive limit")
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    while text:
        if len(text) <= limit:
            pieces.append(text)
            break

        # +1 keeps the delimiter with the piece being emitted, so nothing is
        # dropped and the FOLLOWING piece does not start with the boundary.
        cut = text.rfind("\n", 0, limit)
        cut = cut + 1 if cut != -1 else -1
        if cut <= 0 or cut < limit // 2:
            space = text.rfind(" ", 0, limit)
            cut = space + 1 if space != -1 else -1
        if cut <= 0 or cut < limit // 2:
            cut = limit  # hard cut; >= 1, so progress is guaranteed

        pieces.append(text[:cut])
        text = text[cut:]

    return pieces


@dataclass(frozen=True)
class DmReply:
    """A reply body plus the facts that must survive a rewrite of that body.

    Produced once at the agent boundary, carried across every component boundary
    as a value, and composed into display text exactly once per route per
    variant, at a registered egress sink.

    ``body`` is the agent's prose and is NEVER re-parsed to recover a fact.
    """

    body: str
    tool_failures: ToolFailures = field(default_factory=ToolFailures)

    # ── composition ─────────────────────────────────────────────────────────

    def render(self, *, max_chars: int | None = None) -> RenderedDmText:
        """Compose body + attachments into the Captain-visible text.

        With zero attachments this is byte-identical to ``body``, exactly -- the
        property that makes the migration auditable.

        ``max_chars`` is CHARACTERS, not bytes: the real consumer bound counts
        ``len()`` on a ``str``, so 4,096 accented characters are 8,192 UTF-8
        bytes and a byte budget would be a silent stricter regression.

        The attachment is what must survive a budget, not what a budget drops,
        so the ladder is: truncate the body; else fall back to a count-only
        disclosure; else raise, because a budget below the minimum is a caller
        error and dropping the disclosure is the defect this AD removes.
        Truncation cuts on code-point boundaries -- it does not promise grapheme
        clusters, which would need a segmentation dependency this does not add.
        """
        disclosure = _compose_disclosure(
            self.tool_failures.names(), self.tool_failures.failed_call_count,
        )
        if not disclosure:
            text = self.body
            if max_chars is not None and len(text) > max_chars:
                text = text[:max_chars]
            return RenderedDmText(text, _RENDER_TOKEN)

        tail = _DISCLOSURE_PREFIX + disclosure
        if max_chars is None:
            return RenderedDmText(self.body + tail, _RENDER_TOKEN)

        if len(tail) <= max_chars:
            keep = max_chars - len(tail)
            return RenderedDmText(self.body[:keep] + tail, _RENDER_TOKEN)

        short = _DISCLOSURE_PREFIX + _count_only(self.tool_failures.failed_call_count)
        if len(short) <= max_chars:
            logger.warning(
                "AD-1248: render budget %d could not fit the full disclosure; "
                "falling back to the count-only form", max_chars,
            )
            return RenderedDmText(short[:max_chars], _RENDER_TOKEN)

        raise ValueError(
            f"render(max_chars={max_chars}) is below the minimum needed to "
            f"disclose a tool failure ({len(short)}); a budget this small "
            f"cannot carry a truthful reply"
        )

    def __str__(self) -> str:
        return str(self.render())

    # ── the four operations (DD-2) ──────────────────────────────────────────

    def with_body(self, body: str) -> "DmReply":
        """A prose transform of ONE run. Attachments preserved."""
        return replace(self, body=body)

    def superseded_by(self, other: "DmReply") -> "DmReply":
        """A later pass of the SAME execution. Scoped LWW."""
        return DmReply(
            body=other.body,
            tool_failures=self.tool_failures.superseded_by(other.tool_failures),
        )

    def replaced_by(self, other: "DmReply") -> "DmReply":
        """A fresh answer to the same question. Attachments replaced."""
        return other

    def combined_with(self, other: "DmReply") -> "DmReply":
        """Independent executions folded in. Body is the caller's, facts union."""
        return DmReply(
            body=self.body,
            tool_failures=self.tool_failures.combined_with(other.tool_failures),
        )

    # ── wire (DD-5) ─────────────────────────────────────────────────────────

    def metadata_payload(self) -> dict[str, Any] | None:
        """The attachments-only payload. The body travels in ``result``."""
        return self.tool_failures.to_wire()

    @classmethod
    def from_intent_result(cls, result: Any) -> "DmReply":
        """Reconstruct from an ``IntentResult``. The single reconstruction path.

        The body comes from ``result.result`` un-rendered, so there is no
        rendered/body pair to fall out of agreement and no consistency guard to
        get wrong.
        """
        body = getattr(result, "result", None)
        if not isinstance(body, str):
            body = "" if body is None else str(body)
        metadata = getattr(result, "metadata", None)
        payload = metadata.get(DM_REPLY_METADATA_KEY) if isinstance(metadata, dict) else None
        if payload is None:
            return cls(body=body)
        return cls(body=body, tool_failures=ToolFailures.from_wire(payload))


def collapse_to_names(state: Mapping[str, str] | None) -> list[str]:
    """Sorted unique unresolved names from a raw ``key -> name`` map."""
    if not state:
        return []
    return sorted({v for v in state.values() if isinstance(v, str) and v})
