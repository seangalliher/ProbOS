"""AD-724: Lightweight sanity gate for DM one-shot replies.

Migrates three existing regex cleanups (BF-120 markdown strip, BF-119
challenge parse, AD-572 move parse) into a named, individually-testable
module, and adds three log-only quality checks (length floor, repetition,
orphaned tags).

Tier-2 log-and-degrade. The gate NEVER blocks a reply. Rejections log a
warning and the original text is shipped unchanged. Strict mode is a
forward marker (AD-724-1+).

State (per-agent last-reply cache for repetition detection) is in-memory
and lost on restart. Persistence is out of scope.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from probos.runtime import RuntimeOS

logger = logging.getLogger(__name__)


# --- Compiled regexes ---
# BF-120: markdown wrapper around structured tags.
_MARKDOWN_OPEN_RE = re.compile(r"[`*]{1,3}\[")
_MARKDOWN_CLOSE_RE = re.compile(r"\][`*]{1,3}")

# BF-119: well-formed challenge tag.
_CHALLENGE_RE = re.compile(r"\[CHALLENGE\s+@(\w+)\s+(\w+)\]")
_CHALLENGE_STRIP_RE = re.compile(r"\[CHALLENGE\s+@\w+\s+\w+\]")

# AD-572: well-formed move tag.
_MOVE_RE = re.compile(r"\[MOVE\s+(\S+)\]")
_MOVE_STRIP_RE = re.compile(r"\[MOVE\s+\S+\]")

# AD-845: well-formed task-creation tag emitted by Yeo in a 1:1 chat reply.
# Pipe-delimited key=value fields. ``title``/``instructions`` are free-form
# (no embedded ``|``, ``]`` or newline); ``specialist`` is an optional
# @-prefixed callsign (letters/digits/space/apostrophe/hyphen/underscore, to
# cover callsigns like "Number One" and "O'Brien"). Length ceilings guard
# against runaway regex backtracking; per-field semantic limits are enforced
# at creation time.
_CREATE_TASK_RE = re.compile(
    r"\[CREATE_TASK\s+title=([^|\]\n]{1,200})\|\s*"
    r"instructions=([^|\]\n]{1,2000})\|\s*"
    r"specialist=@?([A-Za-z0-9 '_-]{1,40})\]"
)
# Lax strip removes well-formed AND malformed variants so no marker leaks
# into Captain-visible text (mirrors AD-728d / AD-730-3 contract).
_CREATE_TASK_STRIP_RE = re.compile(r"\[CREATE_TASK\b[^\]\n]*\]?")

# AD-934 (Option C): deep-tier re-roll marker. [THINK] or [DELIBERATE], with an
# optional trailing focus hint (e.g. [THINK be rigorous]) reserved for AD-934a.
# The well-formed regex requires the closing bracket; the lax strip removes
# malformed variants too so no marker leaks into Captain-visible text
# (mirrors the AD-845 / AD-730-3 strip contract).
_DELIBERATE_RE = re.compile(r"\[(?:THINK|DELIBERATE)\b[^\]\n]*\]")
_DELIBERATE_STRIP_RE = re.compile(r"\[(?:THINK|DELIBERATE)\b[^\]\n]*\]?")

# AD-869: synchronous mesh-read tag emitted by Yeo in a 1:1 chat reply.
# Shape: ``[MESH <intent> key=value key=value]``. ``<intent>`` is a lowercase
# read-intent name (the read-only allowlist is enforced at EXECUTION time in
# the reply pipeline, NOT here); the params blob is space-separated
# ``key=value`` pairs whose values may contain spaces (e.g. a search query).
# Length ceilings guard against runaway regex backtracking.
_MESH_READ_RE = re.compile(r"\[MESH\s+([a-z_]{1,40})\s+([^\]\n]{1,500})\]")
# Lax strip removes well-formed AND malformed variants so no marker leaks
# into Captain-visible text (mirrors AD-728d / AD-845 contract).
_MESH_READ_STRIP_RE = re.compile(r"\[MESH\b[^\]\n]*\]?")
# A param key is a lowercase/underscore token at a token boundary (start of
# the blob or after whitespace), immediately followed by ``=``. The
# boundary anchor means a ``=`` inside a value (e.g. a URL query string
# ``?a=b``) is NOT mistaken for a new key.
_MESH_PARAM_KEY_RE = re.compile(r"(?:^|\s)([a-z_]+)=")

# AD-728d: self-image-awareness marker. Reason is 1-64 chars of
# [a-z_-]+ — invalid reasons fall through to silent strip, no dispatch.
_SELF_CHECK_RE = re.compile(r"\[SELF_CHECK\s+([a-z_-]{1,64})\]")
# Strip ALL occurrences (including malformed bracket variants the regex
# above did not capture but the agent emitted in error). The lax strip
# regex removes obvious malformed `[SELF_CHECK ...]` leftovers so they
# don't bleed into Captain-visible text.
_SELF_CHECK_STRIP_RE = re.compile(r"\[SELF_CHECK\b[^\]\n]*\]")

# AD-730-3: image generation marker. Prompt is 1..N chars of free-form
# text (the 4000 ceiling here is to prevent runaway regex backtracking;
# the per-call enforcement happens against
# AvatarsConfig.image_gen_max_prompt_chars at extraction time). Closing
# bracket terminates the prompt; embedded ] is not supported in v1.
_GEN_IMAGE_RE = re.compile(r"\[GEN_IMAGE\s+([^\]\n]{1,4000})\]")
# Lax strip removes well-formed AND malformed variants so no marker
# leaks into Captain-visible text.
_GEN_IMAGE_STRIP_RE = re.compile(r"\[GEN_IMAGE\b[^\]\n]*\]?")

# AD-743: adaptive conversational pacing marker. ``delay`` is 1..300
# seconds; ``reason`` is 1..64 chars of [a-z_-]+. Invalid markers fall
# through to silent strip with no follow-up scheduled.
_FOLLOW_UP_RE = re.compile(r"\[FOLLOW_UP\s+(\d{1,3})\s+([a-z_-]{1,64})\]")
# Lax strip removes well-formed AND malformed variants so no marker
# leaks into Captain-visible text (mirrors AD-728d / AD-730-3 contract).
_FOLLOW_UP_STRIP_RE = re.compile(r"\[FOLLOW_UP\b[^\]\n]*\]?")

# AD-724: malformed tags (open bracket + keyword, but missing close bracket
# OR missing value). These do NOT match the well-formed regexes above.
_ORPHANED_CHALLENGE_RE = re.compile(r"\[CHALLENGE\b(?![^\[\]]*\])")
_ORPHANED_MOVE_RE = re.compile(r"\[MOVE\b(?![^\[\]]*\S+\s*\])")
# A pair of square brackets containing nothing but whitespace, or an
# unmatched single open/close bracket on a line.
_EMPTY_BRACKETS_RE = re.compile(r"\[\s*\]")

# AD-724-2: whitespace + structured-tag noise normalization for fuzzy
# repetition detection.
_WHITESPACE_RE = re.compile(r"\s+")
_TAG_NOISE_RE = re.compile(
    r"\[(?:CHALLENGE|MOVE|REPLY|/REPLY|DM|/DM|NOTEBOOK|/NOTEBOOK)[^\]]*\]"
)


def _normalize_for_repetition(text: str) -> str:
    """AD-724-2: lowercase, strip structured-tag noise, collapse whitespace.

    Used by the similarity-based repetition check so trivial whitespace or
    structured-tag churn doesn't hide a repeated reply.
    """
    if not text:
        return ""
    out = _TAG_NOISE_RE.sub(" ", text)
    out = _WHITESPACE_RE.sub(" ", out).strip().lower()
    return out


def _similarity_ratio(a: str, b: str) -> float:
    """AD-724-2: stdlib ``difflib.SequenceMatcher`` ratio.

    License hygiene: ``rapidfuzz`` is not installed (verified via
    ``pip show rapidfuzz`` → exit 1). Stdlib only.
    """
    if not a or not b:
        return 0.0
    import difflib
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()


class DmSanityGateConfig(BaseModel):
    """AD-724: configuration for the DM sanity gate.

    Default-ON because the three migrated behaviors (BF-120, BF-119, AD-572)
    are already running unconditionally in HEAD. Disabling this config
    DISABLES those migrations too — see warning in `process()`.
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100

    # AD-724-2: similarity-based repetition. 0.85 ≈ "almost identical after
    # normalization" — set high to avoid false positives on agents with
    # characteristic phrasing. Exact-prefix check still gates the fast path.
    repetition_similarity_threshold: float = 0.85

    # AD-724-1: controlled one-shot retry on rejection.
    retry_on_rejection: bool = True
    retry_warnings: list[str] = Field(
        default_factory=lambda: ["length_floor", "orphaned_tag"]
    )


@dataclass
class DmSanityResult:
    """Outcome of one `DmSanityGate.process()` call.

    `cleaned_text` is what the caller should use for downstream parsing
    and Captain-visible output. `warnings` is a list of `(check_name, detail)`
    tuples that the caller MAY surface (currently logged only).
    """

    cleaned_text: str
    warnings: list[tuple[str, str]] = field(default_factory=list)
    # AD-724-1: True when a configurable subset of warnings fired AND the
    # caller has not yet retried this turn. Caller decides whether to honor
    # it; the gate itself never blocks.
    should_retry: bool = False


class DmSanityGate:
    """AD-724: synchronous, in-process sanity gate for DM one-shot replies.

    Stateful (per-agent last-reply cache). Construct once per runtime.
    Thread-safety: caller responsibility. The chat router calls this
    inside the FastAPI request handler, which is already serialized per
    request by Starlette.
    """

    def __init__(self, config: DmSanityGateConfig | None = None) -> None:
        self.config = config or DmSanityGateConfig()
        # agent_id -> last cleaned reply text. Bounded by agent population.
        self._last_reply_by_agent: dict[str, str] = {}

    # --- Migrated regex helpers (behavior-preserving) ---

    def strip_markdown(self, text: str) -> str:
        """BF-120: strip markdown wrappers from structured tags.

        Identical behavior to the inline `re.sub` pair at
        `routers/agents.py:944-945` (HEAD).
        """
        if not text:
            return text
        text = _MARKDOWN_OPEN_RE.sub("[", text)
        text = _MARKDOWN_CLOSE_RE.sub("]", text)
        return text

    def extract_challenge(self, text: str) -> tuple[str, str] | None:
        """BF-119: extract `(target_callsign, game_type)` from a challenge tag.

        Returns ``None`` if no well-formed `[CHALLENGE @x y]` tag is present.
        """
        if not text:
            return None
        m = _CHALLENGE_RE.search(text)
        if not m:
            return None
        return m.group(1), m.group(2)

    def strip_challenge(self, text: str) -> str:
        """BF-119: remove `[CHALLENGE ...]` tags from Captain-visible text.

        Mirrors the inline `re.sub` at `routers/agents.py:1003` (HEAD),
        including the trailing `.strip()`.
        """
        if not text:
            return text
        return _CHALLENGE_STRIP_RE.sub("", text).strip()

    def extract_move(self, text: str) -> str | None:
        """AD-572: extract the move position from a `[MOVE pos]` tag.

        Returns ``None`` if no well-formed move tag is present.
        """
        if not text:
            return None
        m = _MOVE_RE.search(text)
        if not m:
            return None
        return m.group(1)

    def strip_move(self, text: str) -> str:
        """AD-572: remove `[MOVE ...]` tags from Captain-visible text.

        Mirrors the inline `re.sub` at `routers/agents.py:1041` (HEAD),
        including the trailing `.strip()`.
        """
        if not text:
            return text
        return _MOVE_STRIP_RE.sub("", text).strip()

    def extract_create_task(self, text: str) -> tuple[str, str, str] | None:
        """AD-845: extract ``(title, instructions, specialist)`` from a
        well-formed ``[CREATE_TASK ...]`` tag.

        Returns ``None`` when no well-formed tag is present. The specialist
        is returned without its leading ``@`` and with surrounding
        whitespace stripped; an empty specialist field yields ``None`` for
        the whole match (the tag is then treated as malformed and only
        stripped, never dispatched).
        """
        if not text:
            return None
        m = _CREATE_TASK_RE.search(text)
        if not m:
            return None
        title = m.group(1).strip()
        instructions = m.group(2).strip()
        specialist = m.group(3).strip()
        if not title or not instructions or not specialist:
            return None
        return (title, instructions, specialist)

    def strip_create_task(self, text: str) -> str:
        """AD-845: remove all ``[CREATE_TASK ...]`` markers (well-formed and
        malformed) from Captain-visible text, including the trailing
        ``.strip()`` (mirrors the AD-572 / AD-728d strip contract)."""
        if not text:
            return text
        return _CREATE_TASK_STRIP_RE.sub("", text).strip()

    def extract_deliberate(self, text: str) -> bool:
        """AD-934: True iff a well-formed [THINK]/[DELIBERATE] marker is present."""
        return bool(text) and _DELIBERATE_RE.search(text) is not None

    def strip_deliberate(self, text: str) -> str:
        """AD-934: remove all [THINK]/[DELIBERATE] markers (well-formed +
        malformed) from Captain-visible text, including the trailing
        ``.strip()`` (AD-572/AD-845 contract)."""
        if not text:
            return text
        return _DELIBERATE_STRIP_RE.sub("", text).strip()

    @staticmethod
    def _parse_mesh_params(raw: str) -> dict[str, str]:
        """AD-869: parse a ``key=value key=value`` blob into a dict.

        Values may contain spaces (so ``query=Nvidia SPARK RTX`` parses to
        ``{"query": "Nvidia SPARK RTX"}``): each value runs from just after
        its ``=`` to the start of the next token-boundary key (or end of the
        blob). A ``=`` embedded inside a value (e.g. a URL query string) is
        not a key boundary because :data:`_MESH_PARAM_KEY_RE` anchors on a
        leading start/whitespace. Empty keys or values are dropped.
        """
        raw = raw.strip()
        if not raw:
            return {}
        keys = list(_MESH_PARAM_KEY_RE.finditer(raw))
        if not keys:
            return {}
        params: dict[str, str] = {}
        for i, m in enumerate(keys):
            key = m.group(1)
            val_start = m.end()
            val_end = keys[i + 1].start() if i + 1 < len(keys) else len(raw)
            value = raw[val_start:val_end].strip()
            if key and value:
                params[key] = value
        return params

    def extract_mesh_read(self, text: str) -> tuple[str, dict[str, str]] | None:
        """AD-869: extract ``(intent, params)`` from a well-formed
        ``[MESH <intent> key=value ...]`` tag.

        Returns ``None`` when no well-formed tag is present OR when the
        params blob yields no usable ``key=value`` pairs (a parameterless
        read is treated as malformed and only stripped, never dispatched —
        every allowlisted read intent requires at least one param). The
        read-only allowlist is enforced by the caller at execution time,
        not here; this method is intent-agnostic.
        """
        if not text:
            return None
        m = _MESH_READ_RE.search(text)
        if not m:
            return None
        intent = m.group(1).strip()
        params = self._parse_mesh_params(m.group(2))
        if not intent or not params:
            return None
        return (intent, params)

    def strip_mesh_read(self, text: str) -> str:
        """AD-869: remove all ``[MESH ...]`` markers (well-formed and
        malformed) from Captain-visible text, including the trailing
        ``.strip()`` (mirrors the AD-845 strip contract)."""
        if not text:
            return text
        return _MESH_READ_STRIP_RE.sub("", text).strip()

    def extract_self_check(self, text: str) -> list[str]:
        """AD-728d: return all valid [SELF_CHECK reason] reasons in order.

        Only reasons matching ``[a-z_-]{1,64}`` are returned. Malformed
        markers are not included in the result but are still stripped
        by :meth:`strip_self_check`. Callers should dispatch only the
        FIRST returned reason; additional ones are informational.
        """
        if not text:
            return []
        return [m.group(1) for m in _SELF_CHECK_RE.finditer(text)]

    def strip_self_check(self, text: str) -> str:
        """AD-728d: remove ALL `[SELF_CHECK ...]` markers from reply text.

        Strips both well-formed and malformed variants so no bracket
        marker leaks into Captain-visible output. Mirrors the
        :meth:`strip_challenge` / :meth:`strip_move` contract including
        the trailing ``.strip()``.
        """
        if not text:
            return text
        return _SELF_CHECK_STRIP_RE.sub("", text).strip()

    def extract_gen_image(self, text: str, *, max_chars: int = 512) -> list[str]:
        """AD-730-3: return all valid ``[GEN_IMAGE prompt]`` prompts in order.

        Prompts whose length is not in ``[1, max_chars]`` are excluded
        from the result but still stripped by :meth:`strip_gen_image`.
        Callers should dispatch only the FIRST returned prompt;
        additional ones are informational and stripped silently.
        """
        if not text:
            return []
        prompts: list[str] = []
        for m in _GEN_IMAGE_RE.finditer(text):
            p = m.group(1).strip()
            if 1 <= len(p) <= max_chars:
                prompts.append(p)
        return prompts

    def strip_gen_image(self, text: str) -> str:
        """AD-730-3: remove ALL ``[GEN_IMAGE ...]`` markers from reply text.

        Strips both well-formed and malformed variants so no bracket
        marker leaks into Captain-visible output. Mirrors the
        :meth:`strip_self_check` contract including the trailing
        ``.strip()``.
        """
        if not text:
            return text
        return _GEN_IMAGE_STRIP_RE.sub("", text).strip()

    def extract_followup(self, text: str) -> tuple[int, str] | None:
        """AD-743: extract the first valid ``[FOLLOW_UP delay reason]``.

        Returns ``(delay_seconds, reason)`` for the first well-formed
        marker with ``1 <= delay <= 300``, or ``None`` if no valid
        marker is present. Malformed markers are not returned but are
        stripped by :meth:`strip_followup`.
        """
        if not text:
            return None
        for m in _FOLLOW_UP_RE.finditer(text):
            try:
                delay = int(m.group(1))
            except ValueError:
                continue
            reason = m.group(2)
            if 1 <= delay <= 300 and 1 <= len(reason) <= 64:
                return delay, reason
        return None

    def strip_followup(self, text: str) -> str:
        """AD-743: remove ALL ``[FOLLOW_UP ...]`` markers from reply text.

        Strips both well-formed and malformed variants so no bracket
        marker leaks into Captain-visible output. Mirrors the
        :meth:`strip_gen_image` contract.
        """
        if not text:
            return text
        return _FOLLOW_UP_STRIP_RE.sub("", text).strip()

    # --- New checks (Tier-2 log-and-degrade) ---

    def check_length_floor(self, agent_id: str, text: str) -> tuple[str, str] | None:
        """Return a `(check_name, detail)` warning if `text.strip()` is shorter
        than `config.length_floor`, else ``None``. Logs at WARNING level.
        """
        stripped_len = len(text.strip())
        if stripped_len < self.config.length_floor:
            detail = (
                f"reply length {stripped_len} < floor {self.config.length_floor}"
            )
            logger.warning(
                "AD-724: DM length floor breached for agent %s: %s",
                agent_id, detail,
            )
            return ("length_floor", detail)
        return None

    def check_repetition(self, agent_id: str, text: str) -> tuple[str, str] | None:
        """AD-724-2: similarity-based repetition (was exact-prefix only).

        Compares the normalized form of ``text`` against the normalized form
        of the previous reply for this agent. The exact-prefix check is
        preserved as the FAST PATH (ratio == 1.0). Logs at WARNING.

        Does NOT update the cache — the caller does that via ``process()``
        after all checks have run.
        """
        prev = self._last_reply_by_agent.get(agent_id, "")
        n = self.config.repetition_prefix_chars
        if not prev or not text:
            return None
        if text[:n] == prev[:n]:
            detail = (
                f"first {n} chars match previous reply (possible decoder loop)"
            )
            logger.warning(
                "AD-724: DM repetition detected for agent %s (exact-prefix): %s",
                agent_id, detail,
            )
            return ("repetition", detail)
        # AD-724-2: similarity ratio over normalized text — catches whitespace
        # / structured-tag churn that the exact-prefix check would miss.
        norm_a = _normalize_for_repetition(text)
        norm_b = _normalize_for_repetition(prev)
        if not norm_a or not norm_b:
            return None
        ratio = _similarity_ratio(norm_a, norm_b)
        if ratio >= self.config.repetition_similarity_threshold:
            detail = (
                f"normalized similarity={ratio:.2f} >= "
                f"threshold={self.config.repetition_similarity_threshold:.2f}"
            )
            logger.warning(
                "AD-724-2: DM repetition detected for agent %s (similarity): %s",
                agent_id, detail,
            )
            return ("repetition", detail)
        return None

    def check_orphaned_tags(self, text: str) -> tuple[str, str] | None:
        """Return a warning if the text contains a malformed structured tag:
        a `[CHALLENGE` or `[MOVE` without a closing bracket, or `[]`.
        Logs at WARNING.
        """
        if not text:
            return None
        if _ORPHANED_CHALLENGE_RE.search(text):
            detail = "orphaned [CHALLENGE — missing closing bracket"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        if _ORPHANED_MOVE_RE.search(text):
            detail = "orphaned [MOVE — missing value or closing bracket"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        if _EMPTY_BRACKETS_RE.search(text):
            detail = "empty []"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        return None

    # --- Orchestration entry point ---

    def process(self, agent_id: str, text: str) -> DmSanityResult:
        """Run the full gate. Returns a `DmSanityResult` carrying the cleaned
        text and any non-fatal warnings.

        If the config is disabled, the markdown strip still runs (it is a
        pure-string normalization with no behavioral risk) but the three
        new checks are skipped. This preserves the BF-120 migration
        invariant when an operator disables the gate.

        Order:
            1. strip_markdown (BF-120 migration; always runs)
            2. check_orphaned_tags (on stripped text, before extraction)
            3. check_length_floor
            4. check_repetition
            5. update last-reply cache
        """
        cleaned = self.strip_markdown(text)

        warnings: list[tuple[str, str]] = []
        if self.config.enabled:
            for check in (
                self.check_orphaned_tags(cleaned),
                self.check_length_floor(agent_id, cleaned),
                self.check_repetition(agent_id, cleaned),
            ):
                if check is not None:
                    warnings.append(check)

        # Update cache AFTER repetition check; bound to live agents only.
        # Empty replies do not poison the cache.
        if cleaned.strip():
            self._last_reply_by_agent[agent_id] = cleaned

        # AD-724-1: surface should_retry when configured warnings fired.
        fired = {name for (name, _) in warnings}
        should_retry = bool(
            self.config.retry_on_rejection
            and fired & set(self.config.retry_warnings)
        )

        return DmSanityResult(
            cleaned_text=cleaned,
            warnings=warnings,
            should_retry=should_retry,
        )


def apply_dm_sanity(
    runtime: "RuntimeOS", agent_id: str, text: str
) -> DmSanityResult:
    """AD-724-5: one-line helper for non-DM callers (WR replies, chain).

    Fetches the DM sanity gate from the runtime via the public
    ``dm_sanity_gate`` attribute (wired in ``runtime.py:566``). When the
    gate is unavailable OR is not a real ``DmSanityGate`` (e.g. a test
    ``MagicMock`` runtime that auto-creates the attribute), returns a no-op
    ``DmSanityResult`` that preserves the input — Tier-2 log-and-degrade.
    """
    gate = getattr(runtime, "dm_sanity_gate", None)
    if not isinstance(gate, DmSanityGate):
        return DmSanityResult(cleaned_text=text)
    return gate.process(agent_id, text)
