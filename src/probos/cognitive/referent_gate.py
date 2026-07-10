"""AD-1119: Referent-Grounding Gate (guard G1) — cascade-confabulation prevention.

Live-runtime forensics (2026-07-08) traced a crew "Oracle Health Check"
investigation that reasoned at length about node ``e77acec7`` — a *fabricated*
identifier that is not a git object, an agent, a ward-room channel, or in any
source file / DB. The root mechanism: **no agent verifies that an identifier or
entity exists before reasoning about it**. This module resolves candidate
referents against ship ground truth *before* the crew builds an investigation
on them, and — for the unresolved ones — produces a gap-regex-safe
honest-absence cue.

Layer: COGNITIVE. The module is ``runtime``-free (DIP): the gate depends only on
a ``list`` of constructor-injected ``ReferentResolver`` protocol objects, and the
concrete resolvers take narrow deps (registry / callsign registry / ward room /
repo root) — never the runtime. It imports nothing from a higher layer.

Scope (AD-1119 only): this is the deterministic *guard* half. It EXTRACTS,
RESOLVES, and computes the cue. It does NOT inject the cue into any agent's
context (that is AD-1120) and does NOT run a divergence probe or persist a
transcript (that is AD-1121).
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Verdict labels (single source of truth for the RESOLVED/UNRESOLVED strings).
RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"

# Extraction cap: bound the number of referents evaluated per seed so a
# pathological message cannot fan out into dozens of git subprocesses.
_MAX_REFERENTS = 20

# --- DD-5 extraction regexes (case-sensitive except `entity`) -----------------
# hex: a git-SHA / node-id shape. The lookahead requires >=1 a-f letter so a
# plain decimal (e.g. 1234567) is excluded (that is a number, not an id).
_HEX_RE = re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{7,40}\b")
# entity: `node <tok>` / `node id <tok>` / `record <tok>` / `entity <tok>`.
_ENTITY_RE = re.compile(
    r"\b(?:node(?:\s+id)?|record|entity)\s+([A-Za-z0-9_\-]{2,64})\b",
    re.IGNORECASE,
)
_ENTITY_GRAMMAR_STOP_WORDS = frozenset(
    {
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "shows",
        "showed",
        "showing",
        "has",
        "have",
        "had",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "should",
        "seems",
        "appears",
        "indicates",
        "exists",
        "may",
        "not",
        "of",
        "to",
        "the",
        "this",
        "that",
        "these",
        "those",
        "a",
        "an",
    }
)
# service: a conservative "asserted live system" span — a Capitalized word (or a
# `*_service` snake token) immediately followed by one of the system keywords.
# Deliberately case-sensitive on the leading name to bound false positives (an
# ordinary lowercase "the membership" must NOT match).
_SERVICE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]*|[A-Za-z0-9_]*_service)\s+"
    r"(?:service|membership|telemetry|cluster|node)\b"
)

# Code-span strippers: fenced ``` blocks first (non-greedy, DOTALL), then inline
# `code` spans — so a sha inside a code fence is NOT extracted.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


@dataclass(frozen=True)
class Referent:
    """A candidate referent extracted from a message.

    ``token`` is the resolvable identifier; ``kind`` is one of ``hex`` /
    ``entity`` / ``service`` (a label for logging); ``raw`` is the matched span.
    """

    token: str
    kind: str
    raw: str


@dataclass(frozen=True)
class GroundingVerdict:
    """The outcome of grounding a message's referents.

    ``results`` maps each referent token to ``RESOLVED`` / ``UNRESOLVED``;
    ``unresolved`` is the ordered tuple of unresolved tokens; ``cues`` maps each
    unresolved token to its honest-absence cue.
    """

    results: dict[str, str]
    unresolved: tuple[str, ...]
    cues: dict[str, str]

    @property
    def has_unresolved(self) -> bool:
        """True when at least one referent could not be resolved."""
        return bool(self.unresolved)


def _strip_code_spans(text: str) -> str:
    """Blank out fenced ``` blocks then inline `code` spans (DD-5)."""
    text = _FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    return text


def _is_entity_identifier(token: str) -> bool:
    """Return whether a regex-located entity token is identifier-like.

    Digits, underscores, and hyphens are strong machine-identifier signals.
    Plain alphabetic identifiers remain valid unless they are common grammar
    words that occur naturally after ``node`` / ``record`` / ``entity``.
    """
    if any(char.isdigit() or char in "_-" for char in token):
        return True
    return token.casefold() not in _ENTITY_GRAMMAR_STOP_WORDS


def extract_referents(text: str) -> list[Referent]:
    """Extract candidate referents from ``text`` (pure, no I/O).

    Strips code spans first (DD-5), matches the three referent kinds, orders by
    first appearance, dedupes by token (first-seen wins), and caps at
    ``_MAX_REFERENTS``. Returns ``[]`` for empty / whitespace text.
    """
    if not text:
        return []
    stripped = _strip_code_spans(text)
    # (start, token, kind, raw) so we can order by first appearance across kinds.
    matches: list[tuple[int, str, str, str]] = []
    for m in _HEX_RE.finditer(stripped):
        matches.append((m.start(), m.group(0), "hex", m.group(0)))
    for m in _ENTITY_RE.finditer(stripped):
        token = m.group(1)
        if _is_entity_identifier(token):
            matches.append((m.start(1), token, "entity", m.group(0)))
    for m in _SERVICE_RE.finditer(stripped):
        matches.append((m.start(1), m.group(1), "service", m.group(0)))
    matches.sort(key=lambda t: t[0])
    found: list[Referent] = []
    seen: set[str] = set()
    for _start, token, kind, raw in matches:
        if not token or token in seen:
            continue
        seen.add(token)
        found.append(Referent(token=token, kind=kind, raw=raw))
        if len(found) >= _MAX_REFERENTS:
            break
    return found


class ReferentResolver(Protocol):
    """A ground-truth resolver for a single referent token.

    ``kind`` is a short label for logging. ``resolve`` returns True only when the
    resolver CONFIRMS the token exists; it must honest-degrade to False on any
    operational failure. Task cancellation remains control flow and propagates.
    """

    kind: str

    async def resolve(self, token: str) -> bool:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class _GitProcessResult:
    """Small cross-thread result for one ``git cat-file`` process."""

    returncode: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    start_error: OSError | None = None


class GitObjectResolver:
    """Confirm a token is a real git object via ``git cat-file -e <token>^{object}``.

    ``^{object}`` matches any object type (blob/tree/commit/tag) and resolves
    abbreviations + packed objects, so an 8-char prefix like ``e77acec7`` is
    checked correctly (a raw ``.git/objects/`` filesystem probe could not).
    Honest-degrades to False: a missing git binary / non-repo ``cwd`` / non-zero
    exit / timeout all return False (logged), never a false True. Task
    cancellation kills and reaps the child before propagating.
    """

    kind = "git"
    _POLL_INTERVAL_SECONDS = 0.01

    def __init__(self, *, repo_root: Path | None = None, timeout: float = 5.0) -> None:
        # Default anchors to the repo root (src/probos/cognitive/ -> parents[3]);
        # overridable so a test injects a real tmp_path git repo (DD-2).
        self._repo_root = repo_root or Path(__file__).resolve().parents[3]
        self._timeout = timeout

    async def resolve(self, token: str) -> bool:
        """Return True iff ``token`` resolves to a git object under ``repo_root``."""
        cancel_requested = threading.Event()
        worker = asyncio.get_running_loop().run_in_executor(
            None,
            self._resolve_sync,
            token,
            cancel_requested,
        )
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel_requested.set()
            try:
                await asyncio.shield(worker)
            except Exception:
                logger.warning(
                    "BF-660 GitObjectResolver: cancellation cleanup worker "
                    "failed for token=%r; cancellation will still propagate",
                    token,
                    exc_info=True,
                )
            raise
        except Exception:
            logger.warning(
                "AD-1119 GitObjectResolver: git cat-file failed for token=%r; "
                "treating as unresolved",
                token,
                exc_info=True,
            )
            return False

        if result.start_error is not None:
            logger.debug(
                "AD-1119 GitObjectResolver: git unavailable for token=%r cwd=%s "
                "(%s); treating as unresolved",
                token,
                self._repo_root,
                result.start_error,
            )
            return False
        if result.timed_out:
            logger.warning(
                "AD-1119 GitObjectResolver: git cat-file timed out after %.1fs for "
                "token=%r; treating as unresolved",
                self._timeout,
                token,
            )
            return False
        return result.returncode == 0

    def _resolve_sync(
        self,
        token: str,
        cancel_requested: threading.Event,
    ) -> _GitProcessResult:
        """Run one selector-compatible Git probe in a worker thread."""
        if cancel_requested.is_set():
            return _GitProcessResult(cancelled=True)

        proc: subprocess.Popen[bytes] | None = None
        try:
            try:
                proc = subprocess.Popen(
                    ["git", "cat-file", "-e", "--", f"{token}^{{object}}"],
                    cwd=str(self._repo_root),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
            except (FileNotFoundError, NotADirectoryError, OSError) as exc:
                return _GitProcessResult(start_error=exc)

            deadline = time.monotonic() + max(0.0, self._timeout)
            while True:
                returncode = proc.poll()
                if returncode is not None:
                    return _GitProcessResult(returncode=returncode)
                if cancel_requested.is_set():
                    self._kill_and_reap(proc)
                    return _GitProcessResult(cancelled=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    self._kill_and_reap(proc)
                    return _GitProcessResult(timed_out=True)
                cancel_requested.wait(
                    min(self._POLL_INTERVAL_SECONDS, remaining)
                )
        finally:
            if proc is not None and proc.poll() is None:
                self._kill_and_reap(proc)

    @staticmethod
    def _kill_and_reap(proc: subprocess.Popen[bytes]) -> None:
        """Kill ``proc`` and synchronously reap it before returning."""
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()


class AgentResolver:
    """Confirm a token names a live-or-resting crew member.

    Confirmed if ANY of: the registry knows the agent id, the registry has a
    non-empty pool by that name, or the callsign registry resolves it. Callsign
    existence is LIVENESS-INDEPENDENT (``resolve`` returns a dict even when the
    agent_id is None for a resting crew member), so ``is not None`` is the
    correct existence test. Honest-degrades to False on any failure.
    """

    kind = "agent"

    def __init__(self, registry: Any, callsign_registry: Any) -> None:
        self._registry = registry
        self._callsign_registry = callsign_registry

    async def resolve(self, token: str) -> bool:
        """Return True iff ``token`` is a known agent id / pool / callsign."""
        try:
            if self._registry is not None:
                if self._registry.get(token) is not None:
                    return True
                if self._registry.get_by_pool(token):
                    return True
            if self._callsign_registry is not None:
                if self._callsign_registry.resolve(token) is not None:
                    return True
        except Exception:
            logger.warning(
                "AD-1119 AgentResolver: lookup failed for token=%r; treating as "
                "unresolved",
                token,
                exc_info=True,
            )
            return False
        return False


class WardRoomResolver:
    """Confirm a token names a ward-room channel.

    Guards ``ward_room is None`` (``runtime.ward_room`` is None until ``start()``)
    — None returns False. Honest-degrades to False on any failure.
    """

    kind = "ward_room"

    def __init__(self, ward_room: Any) -> None:
        self._ward_room = ward_room

    async def resolve(self, token: str) -> bool:
        """Return True iff ``token`` names an existing ward-room channel."""
        if self._ward_room is None:
            return False
        try:
            channel = await self._ward_room.get_channel_by_name(token)
        except Exception:
            logger.warning(
                "AD-1119 WardRoomResolver: get_channel_by_name failed for token=%r; "
                "treating as unresolved",
                token,
                exc_info=True,
            )
            return False
        return channel is not None


class ReferentGroundingGate:
    """Resolve a message's referents against ground truth (DIP: injected resolvers).

    Resolution policy (DD-2): for each extracted referent, try ALL resolvers in
    order; the FIRST True marks it RESOLVED; all-False marks it UNRESOLVED (with
    an honest-absence cue). ``evaluate`` NEVER raises — a catastrophic failure
    returns an empty verdict (logged), and each resolver call is individually
    wrapped so one raising resolver is treated as False and the referent falls
    through.
    """

    def __init__(self, resolvers: list[ReferentResolver]) -> None:
        self._resolvers = list(resolvers)

    async def evaluate(self, text: str) -> GroundingVerdict:
        """Ground every referent in ``text`` and return the verdict."""
        try:
            referents = extract_referents(text)
        except Exception:
            logger.warning(
                "AD-1119 ReferentGroundingGate: extraction failed; returning an "
                "empty verdict",
                exc_info=True,
            )
            return GroundingVerdict(results={}, unresolved=(), cues={})
        results: dict[str, str] = {}
        unresolved: list[str] = []
        cues: dict[str, str] = {}
        for ref in referents:
            token = ref.token
            if token in results:
                continue
            if await self._resolve_one(token):
                results[token] = RESOLVED
            else:
                results[token] = UNRESOLVED
                unresolved.append(token)
                cues[token] = self._honest_absence_cue(token)
        return GroundingVerdict(
            results=results,
            unresolved=tuple(unresolved),
            cues=cues,
        )

    async def _resolve_one(self, token: str) -> bool:
        """First resolver that confirms wins; a raising resolver counts as False."""
        for resolver in self._resolvers:
            try:
                if await resolver.resolve(token):
                    return True
            except Exception:
                logger.warning(
                    "AD-1119 ReferentGroundingGate: resolver kind=%s raised for "
                    "token=%r; treating as unresolved by this resolver",
                    getattr(resolver, "kind", "?"),
                    token,
                    exc_info=True,
                )
                continue
        return False

    @staticmethod
    def _honest_absence_cue(token: str) -> str:
        """A gap-regex-safe cue for an unresolved referent (DD-4, reuse AD-981b).

        The wording is checked against the decomposer ``is_capability_gap`` regex
        — it must NOT read as a capability gap (so it avoids "can't"/"cannot"/
        "unable to"/"lack*"/"don't have"/"no <X> capability|ability|support|way|
        mechanism|tool"/"not available|supported|possible"/"outside ... scope").
        "do not" (with a space), "no such referent", "structurally unresolvable",
        and "nothing resolves" are safe.
        """
        return (
            f"No ship referent resolves for '{token}'. Treat it as structurally "
            "unresolvable: do not build an investigation on it, and do not invent "
            "details to make it real. If nothing resolves, the correct finding is "
            "that there is no such referent."
        )


def build_default_resolvers(
    *,
    registry: Any,
    callsign_registry: Any,
    ward_room: Any,
    repo_root: Path | None = None,
) -> list[ReferentResolver]:
    """Build the three default resolvers from narrow deps (DD-3).

    The wiring site passes ``runtime.registry`` / ``runtime.callsign_registry`` /
    ``getattr(runtime, "ward_room", None)`` — the factory itself is runtime-free,
    so the gate stays unit-testable with real fixtures and no runtime mock.
    """
    return [
        GitObjectResolver(repo_root=repo_root),
        AgentResolver(registry, callsign_registry),
        WardRoomResolver(ward_room),
    ]
